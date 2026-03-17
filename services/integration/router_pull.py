"""
integration/router_pull.py
════════════════════════════════════════════════════════════
APIs Pull — Auto-Importación de Documentos Fiscales

Arquitectura v3 (correcta):
  El gc_token del contador (partner) contiene:
    - facturador_token : token de sesión en el Facturador (X-Partner-Token)
    - tenant_id        : tenant_id DEL CLIENTE (Álvaro) en el Facturador
                         (cuando el contador seleccionó a Álvaro en /select)

  Estos se pasan a genoma_client.py para llamar:
    GET /api/partners/portal/cliente/{tenant_id}/documentos
        ?tipo=enviados|recibidos&period=YYYYMM
    Header: X-Partner-Token: {facturador_token}

Endpoints:
  GET  /integration/pull-enviados     → FE/TE/ND/NC desde Genoma Contable
  GET  /integration/pull-recibidos    → FEC/compras desde Genoma Contable
  POST /integration/import-batch      → Importa lote seleccionado al Diario
  GET  /integration/ping              → Diagnóstico de conectividad

Reglas de Oro:
  - Idempotente: dedup por source_ref (clave Hacienda)
  - Transacción por lote — rollback si falla cualquier doc
  - tenant_id siempre del JWT — nunca del payload
  - TOKEN_EXPIRADO → 401 claro con instrucción de renovación
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional, Callable
import math

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.auth.database import get_session
from services.auth.security import get_current_user
from services.integration.genoma_client import (
    pull_documentos_enviados,
    pull_documentos_recibidos,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integration", tags=["integration-pull"])


# ─────────────────────────────────────────────────────────────────
# Helpers (exportados para SIM tests)
# ─────────────────────────────────────────────────────────────────

def _paginate_result(items: list, page: int, limit: int) -> dict:
    """Pagina una lista de items. Retorna {items, total, page, total_pages}."""
    total = len(items)
    total_pages = math.ceil(total / limit) if limit else 1
    start = (page - 1) * limit
    end   = start + limit
    return {
        "items":       items[start:end],
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
    }


def _is_already_imported(db, tenant_id: str, source_ref: str) -> bool:
    """Verifica si un documento ya fue importado (dedup por clave Hacienda)."""
    row = db.execute(text("""
        SELECT id FROM journal_entries
        WHERE tenant_id  = :tid
          AND source_ref = :ref
        LIMIT 1
    """), {"tid": tenant_id, "ref": source_ref}).fetchone()
    return row is not None


def _validate_tenant_docs(docs: list, tenant_id: str) -> list:
    """
    Filtra documentos cuyo tenant_id no coincida con el del JWT.
    Guard de seguridad cross-tenant.
    """
    return [d for d in docs if d.get("tenant_id", tenant_id) == tenant_id]


def _get_tenant_cedula(db, tenant_id: str) -> str | None:
    """
    Obtiene la cédula fiscal del tenant contable.
    Usada para filtrar docs por receptor_cedula (recibidos) o emisor_cedula (enviados).
    Regla de Oro: cada tenant es una casa aparte — solo ve sus docs.
    """
    try:
        row = db.execute(text("""
            SELECT cedula FROM tenants WHERE id = :tid LIMIT 1
        """), {"tid": tenant_id}).fetchone()
        return row[0] if row else None
    except Exception as ex:
        logger.warning(f"⚠️ _get_tenant_cedula: error para {tenant_id[:8]}: {ex}")
        return None


def _filtrar_docs_por_cedula(
    docs: list,
    tenant_cedula: str,
    campo: str,
) -> list:
    """
    Filtra documentos cuyo campo (receptor_cedula o emisor_cedula)
    coincida con la cédula del tenant contable.
    Guard de aislamiento multi-tenant.
    """
    if not tenant_cedula:
        logger.warning("⚠️ _filtrar_docs: sin cédula del tenant — retornando 0 docs por seguridad")
        return []
    antes = len(docs)
    filtrados = [d for d in docs if d.get(campo) == tenant_cedula]
    if antes != len(filtrados):
        logger.info(
            f"🔒 Aislamiento: {antes} docs del Facturador → {len(filtrados)} pertenecen "
            f"al tenant (cédula={tenant_cedula}, campo={campo})"
        )
    return filtrados


def _process_import_batch(
    db,
    docs: list,
    tenant_id: str,
    mapper_fn: Callable,
) -> dict:
    """
    Importa un lote de documentos al libro diario.
    Transacción única: rollback completo si falla cualquier doc.

    Args:
        db:        Sesión de DB
        docs:      Lista de dicts de documentos
        tenant_id: ID del tenant (del JWT)
        mapper_fn: Función que convierte doc → JournalEntry (inyectable para tests)

    Returns:
        {importados, skipped, errors}
    """
    importados = 0
    skipped    = 0
    errors     = []

    try:
        for doc in docs:
            ref = doc.get("clave", "")

            # Dedup
            if _is_already_imported(db, tenant_id, ref):
                skipped += 1
                continue

            # Mapear doc → entry en DB
            mapper_fn(db, doc, tenant_id)
            importados += 1

        db.commit()
        return {"importados": importados, "skipped": skipped, "errors": errors}

    except Exception as e:
        db.rollback()
        logger.error(f"❌ import_batch: rollback por error: {e}")
        return {
            "importados": 0,
            "skipped":    skipped,
            "error":      str(e),
        }


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/ping")
def get_ping_genoma(
    period:       str    = Query(None, description="Período YYYYMM para verificar documentos"),
    db:           Session = Depends(get_session),
    current_user: dict    = Depends(get_current_user),
):
    """
    Diagnóstico de conectividad con Genoma Contable.
    Informa: token del Facturador, cliente_tenant_id activo, y docs en el período.
    """
    from services.integration.genoma_client import GENOMA_CONTABLE_URL, pull_documentos_enviados

    # v3: facturador_token viene en el gc_token (del handoff de partner)
    # cliente_tenant_id es el tenant_id que se guardó al seleccionar al cliente
    tenant_id         = current_user["tenant_id"]
    facturador_token  = current_user.get("facturador_token", "")
    url_config        = GENOMA_CONTABLE_URL

    diag = {
        "genoma_contable_url":   url_config,
        "url_configurada":       url_config != "https://app.genomaio.com",
        "facturador_token":      "presente" if facturador_token else "AUSENTE",
        "cliente_tenant_id":     tenant_id[:8] + "...",
        "periodo_consultado":    period,
        "enviados_check":        None,
        "error":                 None,
    }

    if period and facturador_token:
        result = pull_documentos_enviados(
            facturador_token=facturador_token,
            cliente_tenant_id=tenant_id,
            period=period,
            page=1,
            limit=5,
        )
        if result["ok"]:
            diag["enviados_check"] = {
                "ok": True,
                "total_disponibles": result.get("total", 0),
                "muestra": [d.get("numero_doc") for d in result.get("items", [])[:5]],
            }
        else:
            diag["enviados_check"] = {"ok": False, "error": result.get("error")}
            diag["error"] = result.get("error")

    if not facturador_token:
        diag["diagnostico"] = (
            "🔴 Token del Facturador ausente. "
            "Volvé al Panel de Partners (app.genomaio.com) y hacé clic en 'Sistema de Contabilidad'."
        )
    elif diag["enviados_check"] and not diag["enviados_check"]["ok"]:
        err = result.get("error", "")
        if err == "TOKEN_EXPIRADO":
            diag["diagnostico"] = "🔴 Sesión expirada. Volvé al Panel de Partners y hacé clic en 'Sistema de Contabilidad'."
        else:
            diag["diagnostico"] = f"🔴 Genoma Contable rechazó la consulta: {diag['error']}"
    else:
        diag["diagnostico"] = "🟢 Conexión OK"

    return diag

@router.get("/pull-enviados")
def get_pull_enviados(
    period:               str           = Query(..., description="Período YYYYMM"),
    page:                 int           = Query(1,   ge=1),
    limit:                int           = Query(10,  ge=1, le=100),
    import_all:           bool          = Query(False),
    facturador_tenant_id: Optional[str] = Query(None, description="tenant_id real del cliente en el Facturador"),
    db:                   Session       = Depends(get_session),
    current_user:         dict          = Depends(get_current_user),
):
    """
    Consulta FE/TE/ND/NC enviados ACEPTADOS por Hacienda del cliente seleccionado.
    Autenticación: X-Partner-Token del Facturador (en gc_token como facturador_token).

    facturador_tenant_id: tenant_id REAL del cliente (Álvaro) en el Facturador.
      - El gc_token tiene tenant_id=GC-RNHJ (código del partner), NO el de Álvaro.
      - El frontend pasa el tenant_id correcto desde state.tenant.tenant_id.
      - Si no se pasa, cae en tenant_id del JWT (solo válido para cuentas standalone).
    """
    jwt_tenant_id    = current_user["tenant_id"]
    facturador_token = current_user.get("facturador_token", "")

    # El tenant_id real del cliente viene del frontend (state.tenant.tenant_id)
    # El gc_token solo tiene el código del partner (GC-RNHJ)
    cliente_tenant_id = facturador_tenant_id or jwt_tenant_id

    if not facturador_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sesión con el Facturador no disponible. "
                "Volvé al Panel de Partners y hacé clic en 'Sistema de Contabilidad'."
            )
        )

    result = pull_documentos_enviados(
        facturador_token=facturador_token,
        cliente_tenant_id=cliente_tenant_id,
        period=period,
        page=1 if import_all else page,
        limit=1000 if import_all else limit,
    )
    if not result["ok"]:
        err = result.get("error", "")
        detail = result.get("error_detail") or f"Genoma Contable no disponible: {err}"
        code   = 401 if err == "TOKEN_EXPIRADO" else 503
        raise HTTPException(status_code=code, detail=detail)

    docs = result.get("items", [])

    # ── Aislamiento multi-tenant: solo docs donde emisor = tenant ──────
    tenant_cedula = _get_tenant_cedula(db, jwt_tenant_id)
    docs = _filtrar_docs_por_cedula(docs, tenant_cedula, "emisor_cedula")

    for doc in docs:
        doc["ya_importado"] = _is_already_imported(db, jwt_tenant_id, doc.get("clave", ""))

    if import_all:
        return {"items": docs, "total": len(docs), "page": 1, "total_pages": 1}

    return _paginate_result(docs, page, limit)


@router.get("/pull-recibidos")
def get_pull_recibidos(
    period:               str           = Query(..., description="Período YYYYMM"),
    page:                 int           = Query(1,   ge=1),
    limit:                int           = Query(10,  ge=1, le=100),
    import_all:           bool          = Query(False),
    facturador_tenant_id: Optional[str] = Query(None, description="tenant_id real del cliente en el Facturador"),
    db:                   Session       = Depends(get_session),
    current_user:         dict          = Depends(get_current_user),
):
    """
    Consulta FEC recibidos ACEPTADOS por Hacienda del cliente seleccionado.
    Retorna condicion_impuesto + iva_acreditado + iva_gasto para el asiento.
    """
    jwt_tenant_id    = current_user["tenant_id"]
    facturador_token = current_user.get("facturador_token", "")
    cliente_tenant_id = facturador_tenant_id or jwt_tenant_id

    if not facturador_token:
        raise HTTPException(
            status_code=401,
            detail=(
                "Sesión con el Facturador no disponible. "
                "Volvé al Panel de Partners y hacé clic en 'Sistema de Contabilidad'."
            )
        )

    result = pull_documentos_recibidos(
        facturador_token=facturador_token,
        cliente_tenant_id=cliente_tenant_id,
        period=period,
        page=1 if import_all else page,
        limit=1000 if import_all else limit,
    )
    if not result["ok"]:
        err = result.get("error", "")
        detail = result.get("error_detail") or f"Genoma Contable no disponible: {err}"
        code   = 401 if err == "TOKEN_EXPIRADO" else 503
        raise HTTPException(status_code=code, detail=detail)

    docs = result.get("items", [])

    # ── Diagnóstico: log de todos los docs que retorna el Facturador ───────────
    logger.info(
        f"📥 pull-recibidos [{period}] tenant={cliente_tenant_id[:8]}... "
        f"→ {len(docs)} docs del Facturador"
    )
    for d in docs:
        logger.info(
            f"   doc: tipo={d.get('tipo_doc','?')} "
            f"emisor={str(d.get('emisor_nombre','?'))[:30]} "
            f"total={d.get('total_doc','?')} "
            f"clave={str(d.get('clave',''))[:20]}..."
        )

    # ── Aislamiento multi-tenant: solo docs donde receptor = tenant ─────
    tenant_cedula = _get_tenant_cedula(db, jwt_tenant_id)
    docs = _filtrar_docs_por_cedula(docs, tenant_cedula, "receptor_cedula")

    for doc in docs:
        doc["ya_importado"] = _is_already_imported(db, jwt_tenant_id, doc.get("clave", ""))

    ya = sum(1 for d in docs if d.get("ya_importado"))
    logger.info(f"   → {ya} ya importados, {len(docs)-ya} nuevos disponibles")

    if import_all:
        return {"items": docs, "total": len(docs), "page": 1, "total_pages": 1}

    return _paginate_result(docs, page, limit)


class ImportBatchRequest(BaseModel):
    doc_ids:    list[str]   # lista de claves Hacienda a importar
    period:     str         # YYYYMM
    docs_data:  list[dict]  # datos completos de los docs (el frontend ya los tiene)
    tipo_batch: str = "enviados"  # 'enviados' | 'recibidos' — define técnica contable


@router.post("/import-batch")
def post_import_batch(
    payload:      ImportBatchRequest,
    db:           Session = Depends(get_session),
    current_user: dict    = Depends(get_current_user),
):
    """
    Importa un lote de documentos al Libro Diario como DRAFT.
    Idempotente: skippea los ya importados.
    Transacción completa: rollback si falla cualquier doc.

    tipo_batch:
      'enviados'  → FE/TE emitidas por la empresa (INGRESO: CxC / 4xxx / IVA Débito)
      'recibidos' → Compras/FEC recibidas de proveedores (EGRESO: 5xxx / IVA Crédito / CxP)
    """
    from services.integration.journal_mapper_v2 import map_document_lines_to_entry

    tenant_id  = current_user["tenant_id"]
    es_recibido = payload.tipo_batch == "recibidos"

    # Guard cross-tenant: solo docs que el frontend seleccionó
    docs_filtrados = [
        d for d in payload.docs_data
        if d.get("clave") in payload.doc_ids
    ]

    # ── Aislamiento multi-tenant: verificar cédula antes de importar ──
    tenant_cedula = _get_tenant_cedula(db, tenant_id)
    campo_cedula = "receptor_cedula" if es_recibido else "emisor_cedula"
    docs_filtrados = _filtrar_docs_por_cedula(docs_filtrados, tenant_cedula, campo_cedula)

    # ── Normalizar tipo para recibidos ─────────────────────────────
    # El Facturador retorna el tipo_doc ORIGINAL de Hacienda (ej: "01").
    # Para recibidos forzamos _es_recibido=True → el mapper usará lógica EGRESO.
    if es_recibido:
        for doc in docs_filtrados:
            doc["_es_recibido"] = True

    def mapper(db, doc, tid):
        map_document_lines_to_entry(db, doc, tid)

    result = _process_import_batch(db, docs_filtrados, tenant_id, mapper)

    # Registrar en import_batchya 
    try:
        db.execute(text("""
            INSERT INTO import_batch (tenant_id, period, tipo, total_docs, importados, skipped, estado)
            VALUES (:tid, :period, :tipo, :total, :imp, :skipped, 'COMPLETO')
        """), {
            "tid":     tenant_id,
            "period":  payload.period,
            "tipo":    "RECIBIDOS" if es_recibido else "ENVIADOS",
            "total":   len(docs_filtrados),
            "imp":     result.get("importados", 0),
            "skipped": result.get("skipped", 0),
        })
        db.commit()
    except Exception:
        pass  # No crítico si el registro de batch falla

    return {
        "ok": "error" not in result,
        **result,
        "message": (
            f"{result.get('importados',0)} importados, "
            f"{result.get('skipped',0)} ya existían"
        ),
    }



# ─────────────────────────────────────────────────────────────────
# POST /integration/purge-bad-drafts
# Borra DRAFTs de FE Recibidas importados con logica vieja (4xxx)
# y libera sus source_ref para re-importacion correcta.
# ─────────────────────────────────────────────────────────────────

class PurgeBadDraftsRequest(BaseModel):
    entry_ids: list[str] = []
    confirm:   bool      = False


@router.post("/purge-bad-drafts")
def purge_bad_drafts(
    payload:      PurgeBadDraftsRequest,
    db:           Session = Depends(get_session),
    current_user: dict    = Depends(get_current_user),
):
    """
    Borra en batch DRAFTs de FE Recibidas importados con la logica vieja
    (cuenta 4xxx = ingreso cuando deben ser egresos).

    Paso 1: Detecta DRAFTs con linea 4xxx + source HACIENDA_PULL/AUTO.
            O recibe entry_ids explicitos desde la UI.
    Paso 2: Hard-delete de lineas + encabezados (solo DRAFT permitido).
    Paso 3: Retorna source_refs liberados para que el usuario re-importe
            desde pull-recibidos con la logica corregida (5xxx/CxP/IVA Credito).

    confirm=True requerido para ejecutar.

    SEGURIDAD: Este endpoint solo funciona si la variable de entorno
    ENABLE_PURGE_UTILITY=1 esta seteada en el servidor. En produccion
    NO debe estar activa de forma permanente — solo habilitarla al momento
    de la migracion puntual y luego retirarla del entorno.
    """
    import os as _os
    if _os.getenv("ENABLE_PURGE_UTILITY", "") != "1":
        raise HTTPException(
            503,
            "Utilidad de purge deshabilitada. "
            "Esta herramienta es de uso excepcional. "
            "El administrador del sistema debe habilitar ENABLE_PURGE_UTILITY=1 "
            "en el entorno del servidor para ejecutarla."
        )

    if current_user["role"] not in ("admin", "contador"):
        raise HTTPException(403, "Solo admin o contador puede ejecutar purge-bad-drafts")

    tenant_id = current_user["tenant_id"]

    if not payload.confirm:
        raise HTTPException(
            400,
            "Agrega confirm=true en el payload para ejecutar el borrado real. "
            "Esto borrara los DRAFTs malos y liberara sus source_ref para re-importar."
        )

    # 1. Identificar candidatos
    if payload.entry_ids:
        candidate_ids = payload.entry_ids
    else:
        rows = db.execute(text("""
            SELECT DISTINCT je.id
            FROM journal_entries je
            JOIN journal_lines  jl ON jl.entry_id = je.id
            WHERE je.tenant_id = :tid
              AND je.status    = 'DRAFT'
              AND je.source    IN ('HACIENDA_PULL', 'hacienda_pull', 'AUTO')
              AND jl.account_code LIKE '4%'
        """), {"tid": tenant_id}).fetchall()
        candidate_ids = [r[0] for r in rows]

    if not candidate_ids:
        return {
            "ok":       True,
            "borrados": 0,
            "liberados": [],
            "mensaje":  "No se encontraron DRAFTs con cuentas 4xxx para borrar.",
        }

    # 2. Verificar estado DRAFT
    placeholders = ",".join([f":id{i}" for i in range(len(candidate_ids))])
    id_params    = {f"id{i}": v for i, v in enumerate(candidate_ids)}
    entries_db   = db.execute(
        text(f"SELECT id, status, source_ref, description "
             f"FROM journal_entries "
             f"WHERE tenant_id = :tid AND id IN ({placeholders})"),
        {"tid": tenant_id, **id_params}
    ).fetchall()

    bad_status    = [e[0] for e in entries_db if e[1] not in ("DRAFT", "draft")]
    draft_entries = [e for e in entries_db if e[1] in ("DRAFT", "draft")]

    if bad_status:
        raise HTTPException(
            400,
            f"Los asientos {bad_status} NO son DRAFT y no se pueden borrar aqui. "
            f"Para POSTED usa PATCH /ledger/entries/{{id}}/void."
        )

    # 3. Hard-delete
    source_refs_liberados = []
    borrados = 0

    for e in draft_entries:
        entry_id   = e[0]
        source_ref = e[2]
        desc       = (e[3] or "")[:60]

        db.execute(text("DELETE FROM journal_lines   WHERE entry_id  = :eid"), {"eid": entry_id})
        db.execute(text("DELETE FROM journal_entries WHERE id = :eid AND tenant_id = :tid"),
                   {"eid": entry_id, "tid": tenant_id})

        if source_ref:
            source_refs_liberados.append(source_ref)

        logger.info(f"purge-bad-drafts: DRAFT {entry_id} borrado (ref={source_ref}, desc={desc})")
        borrados += 1

    db.commit()

    return {
        "ok":       True,
        "borrados": borrados,
        "liberados": source_refs_liberados,
        "mensaje": (
            f"{borrados} asiento(s) DRAFT eliminado(s). "
            f"Podes re-importarlos desde 'FE Recibidas' con la logica corregida "
            f"(Gasto + CxP + IVA Credito). El ICE Telecomunicaciones tambien estara disponible."
        ),
    }

# ─────────────────────────────────────────────────────────────────
# POST /integration/purge-cross-tenant-bleed
# ─────────────────────────────────────────────────────────────────
# INGENIERÍA INVERSA: Detecta y elimina datos de otro tenant que
# "sangraron" dentro del tenant activo por el bug pre-switch-tenant.
#
# CAUSA RAÍZ (documentada):
#   Antes de POST /auth/switch-tenant, el JWT nunca se actualizaba
#   al seleccionar un cliente. Todos los import-batch usaban el
#   tenant_id del partner (GC-RNHJ) o del primer cliente abierto.
#   Resultado: asientos de Álvaro quedaron bajo Angélica/SA/GC-RNHJ.
#
# DETECCIÓN POR CÉDULA (ingeniería inversa):
#   La clave Hacienda (source_ref, 50 dígitos) embebe la cédula del
#   EMISOR en posiciones 3-12 (10 dígitos). Comparando esa cédula
#   contra la cédula del tenant actual detectamos la contaminación.
#
#   Para docs RECIBIDOS (compras), la cédula del receptor está en
#   source_doc_lines JSONB como "receptor_cedula" y se compara también.
#
# MURO POST-PURGE:
#   El guard _filtrar_docs_por_cedula en pull-enviados y pull-recibidos
#   ya impide que futuros import-batch acepten docs de otro tenant.
#   Este endpoint limpia el pasado; ese guard protege el futuro.
#
# SEGURIDAD:
#   - Requiere ENABLE_PURGE_UTILITY=1 en el entorno
#   - confirm=False → dry-run (solo lectura, 100% seguro)
#   - confirm=True  → borrado real irreversible
#   - Solo borra DRAFT — nunca POSTED
#   - tenant_id siempre del JWT, nunca del body
# ─────────────────────────────────────────────────────────────────

import json as _json


def _extract_cedula_from_clave(clave: str) -> str:
    """
    Extrae la cédula del EMISOR embebida en la clave Hacienda.
    Formato Hacienda v4.4 (50 dígitos numéricos):
      [0-2]   : código país (506)
      [3-12]  : cédula emisor (10 dígitos, sin guiones)
      [13-20] : fecha YYYYMMDD
      [21+]   : resto de la clave
    Retorna string vacío si la clave no cumple el formato.
    VALIDACIÓN: debe ser 100% numérica y >= 50 caracteres.
    Strings arbitrarios (source_refs alfanuméricos) retornan vacío,
    dejando la detección a la Estrategia B (JSONB receptor_cedula).
    """
    if not clave or len(clave) < 50 or not clave.isdigit():
        return ""
    return clave[3:13].lstrip("0")  # strip leading zeros para comparación


def _cedulas_coinciden(cedula_a: str, cedula_b: str) -> bool:
    """Compara cédulas normalizando ceros y guiones."""
    def _norm(c: str) -> str:
        return (c or "").replace("-", "").replace(" ", "").lstrip("0")
    return _norm(cedula_a) == _norm(cedula_b)


class PurgeCrossTenantRequest(BaseModel):
    confirm:      bool      = False   # False = dry-run (seguro), True = borrado real
    source_types: list[str] = ["HACIENDA_PULL", "hacienda_pull", "AUTO"]
    entry_ids:    list[str] = []      # vacío = detección automática


@router.post("/purge-cross-tenant-bleed")
def purge_cross_tenant_bleed(
    payload:      PurgeCrossTenantRequest,
    db:           Session = Depends(get_session),
    current_user: dict    = Depends(get_current_user),
):
    """
    Detecta y purga asientos que "sangraron" al tenant activo desde
    otro cliente, por el bug pre-switch-tenant.

    Paso 1 — Detección:
      Para cada DRAFT importado del Facturador, extrae la cédula del
      emisor de la clave Hacienda (source_ref[3:13]) y la compara con
      la cédula del tenant. Para docs recibidos también revisa
      source_doc_lines JSONB → receptor_cedula.
      Si NO coincide → el asiento es contaminación de otro cliente.

    Paso 2 — Dry-run (confirm=False, DEFAULT):
      Retorna la lista de contaminados SIN borrar nada.

    Paso 3 — Borrado real (confirm=True):
      Borra journal_lines + journal_entries contaminados (solo DRAFT).
      Libera sus source_refs para que el tenant correcto los importe.

    Muro post-purge:
      El guard _filtrar_docs_por_cedula ya impide nuevas importaciones
      cruzadas. Este endpoint limpia el PASADO; ese guard protege el FUTURO.

    Requiere ENABLE_PURGE_UTILITY=1 en el entorno del servidor.
    """
    import os as _os
    if _os.getenv("ENABLE_PURGE_UTILITY", "") != "1":
        raise HTTPException(
            503,
            "Utilidad de purge deshabilitada. "
            "El administrador debe habilitar ENABLE_PURGE_UTILITY=1 en el entorno. "
            "Esta herramienta es de uso excepcional — solo durante la migración puntual."
        )

    if current_user.get("role") not in ("admin", "contador"):
        raise HTTPException(403, "Solo admin o contador puede ejecutar purge-cross-tenant-bleed")

    tenant_id = current_user["tenant_id"]

    # 1. Cédula del tenant activo (fuente de verdad)
    tenant_cedula = _get_tenant_cedula(db, tenant_id)
    if not tenant_cedula:
        raise HTTPException(
            400,
            f"No se encontró la cédula fiscal del tenant {tenant_id[:8]}... "
            "El tenant debe tener su cédula configurada para ejecutar el purge."
        )

    logger.info(
        f"purge-bleed: iniciando para tenant={tenant_id[:8]} "
        f"cedula={tenant_cedula} confirm={payload.confirm}"
    )

    # 2. Identificar candidatos a revisar
    if payload.entry_ids:
        # Modo explícito: IDs dados por el operador
        ids_list = list(set(payload.entry_ids))
        placeholders = ",".join([f":id{i}" for i in range(len(ids_list))])
        id_params = {f"id{i}": v for i, v in enumerate(ids_list)}
        candidate_rows = db.execute(
            text(
                f"SELECT je.id, je.status, je.source_ref, je.description, je.source_doc_lines "
                f"FROM journal_entries je "
                f"WHERE je.tenant_id = :tid "
                f"  AND je.status IN ('DRAFT', 'draft') "
                f"  AND je.id IN ({placeholders})"
            ),
            {"tid": tenant_id, **id_params}
        ).fetchall()
    else:
        # Modo automático: todos los DRAFTs importados del Facturador
        sources = list(set(payload.source_types))
        src_ph  = ",".join([f":s{i}" for i in range(len(sources))])
        src_p   = {f"s{i}": v for i, v in enumerate(sources)}
        candidate_rows = db.execute(
            text(
                f"SELECT je.id, je.status, je.source_ref, je.description, je.source_doc_lines "
                f"FROM journal_entries je "
                f"WHERE je.tenant_id = :tid "
                f"  AND je.status IN ('DRAFT', 'draft') "
                f"  AND je.source IN ({src_ph})"
            ),
            {"tid": tenant_id, **src_p}
        ).fetchall()

    if not candidate_rows:
        return {
            "ok":                    True,
            "tenant_id":             tenant_id,
            "cedula_tenant":         tenant_cedula,
            "confirmado":            payload.confirm,
            "contaminados":          [],
            "borrados":              0,
            "source_refs_liberados": [],
            "mensaje":               "✅ No se encontraron DRAFTs importados — tenant limpio.",
        }

    # 3. Detectar contaminación por cédula
    contaminados = []

    for row in candidate_rows:
        entry_id, status, source_ref, description, source_doc_lines_raw = row

        cedula_detectada = None
        motivo_deteccion = None

        # ── Estrategia A: cédula del EMISOR en la clave Hacienda (source_ref) ──
        if source_ref:
            cedula_en_clave = _extract_cedula_from_clave(source_ref)
            if cedula_en_clave and not _cedulas_coinciden(cedula_en_clave, tenant_cedula):
                cedula_detectada = cedula_en_clave
                motivo_deteccion = "emisor_en_clave_hacienda"

        # ── Estrategia B: receptor_cedula en source_doc_lines JSONB (recibidos) ──
        if not cedula_detectada and source_doc_lines_raw:
            try:
                sdl = (
                    _json.loads(source_doc_lines_raw)
                    if isinstance(source_doc_lines_raw, str)
                    else source_doc_lines_raw
                )
                items = sdl if isinstance(sdl, list) else [sdl]
                for item in items:
                    receptor = item.get("receptor_cedula", "")
                    if receptor and not _cedulas_coinciden(receptor, tenant_cedula):
                        cedula_detectada = receptor
                        motivo_deteccion = "receptor_cedula_en_source_doc_lines"
                        break
            except Exception as ex:
                logger.warning(f"⚠️ purge-bleed: error parseando source_doc_lines {entry_id[:8]}: {ex}")

        if cedula_detectada:
            contaminados.append({
                "entry_id":         entry_id,
                "description":      (description or "")[:80],
                "source_ref":       source_ref,
                "cedula_detectada": cedula_detectada,
                "cedula_tenant":    tenant_cedula,
                "motivo":           motivo_deteccion,
            })
            logger.warning(
                f"🩸 purge-bleed: contaminación — entry={entry_id[:8]} "
                f"cedula_doc={cedula_detectada} != cedula_tenant={tenant_cedula} "
                f"motivo={motivo_deteccion}"
            )

    # 4. DRY-RUN — solo diagnóstico, sin borrar
    if not payload.confirm:
        return {
            "ok":                  True,
            "tenant_id":           tenant_id,
            "cedula_tenant":       tenant_cedula,
            "confirmado":          False,
            "modo":                "DRY_RUN",
            "total_revisados":     len(candidate_rows),
            "total_contaminados":  len(contaminados),
            "contaminados":        contaminados,
            "borrados":            0,
            "source_refs_liberados": [],
            "mensaje": (
                f"🔍 DRY-RUN: {len(contaminados)} asiento(s) contaminado(s) de {len(candidate_rows)} revisados. "
                f"Llamá con confirm=true para borrar."
                if contaminados
                else f"✅ DRY-RUN: {len(candidate_rows)} asiento(s) revisados — tenant limpio."
            ),
        }

    # 5. BORRADO REAL (confirm=True)
    if not contaminados:
        return {
            "ok":                    True,
            "tenant_id":             tenant_id,
            "cedula_tenant":         tenant_cedula,
            "confirmado":            True,
            "modo":                  "PURGE_REAL",
            "contaminados":          [],
            "borrados":              0,
            "source_refs_liberados": [],
            "mensaje":               "✅ Tenant limpio — no había asientos contaminados.",
        }

    # Sanity check: solo borrar DRAFTs
    ids_a_borrar  = [c["entry_id"] for c in contaminados]
    ph2           = ",".join([f":bid{i}" for i in range(len(ids_a_borrar))])
    bp2           = {f"bid{i}": v for i, v in enumerate(ids_a_borrar)}
    verificadas   = db.execute(
        text(f"SELECT id, status FROM journal_entries WHERE tenant_id = :tid AND id IN ({ph2})"),
        {"tid": tenant_id, **bp2}
    ).fetchall()

    no_draft = [e[0] for e in verificadas if e[1] not in ("DRAFT", "draft")]
    if no_draft:
        raise HTTPException(
            400,
            f"Los asientos {no_draft} NO son DRAFT — no se pueden borrar aquí. "
            "Para POSTED usá PATCH /ledger/entries/{id}/void."
        )

    source_refs_liberados = []
    borrados = 0

    for contam in contaminados:
        eid        = contam["entry_id"]
        source_ref = contam.get("source_ref")

        db.execute(text("DELETE FROM journal_lines WHERE entry_id = :eid"), {"eid": eid})
        db.execute(
            text("DELETE FROM journal_entries WHERE id = :eid AND tenant_id = :tid"),
            {"eid": eid, "tid": tenant_id}
        )
        if source_ref:
            source_refs_liberados.append(source_ref)

        logger.info(
            f"purge-bleed: BORRADO entry={eid[:8]} "
            f"cedula_doc={contam['cedula_detectada']} source_ref={source_ref}"
        )
        borrados += 1

    db.commit()

    return {
        "ok":                    True,
        "tenant_id":             tenant_id,
        "cedula_tenant":         tenant_cedula,
        "confirmado":            True,
        "modo":                  "PURGE_REAL",
        "contaminados":          contaminados,
        "borrados":              borrados,
        "source_refs_liberados": source_refs_liberados,
        "mensaje": (
            f"✅ Purge completado: {borrados} asiento(s) eliminado(s) de otro tenant. "
            f"El tenant {tenant_id[:8]}... ahora solo tiene sus propios datos. "
            f"🧱 El muro anti-bleed (filtro de cédula en import-batch) impide que esto vuelva a ocurrir."
        ),
    }
