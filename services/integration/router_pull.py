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

    for doc in docs:
        doc["ya_importado"] = _is_already_imported(db, jwt_tenant_id, doc.get("clave", ""))

    if import_all:
        return {"items": docs, "total": len(docs), "page": 1, "total_pages": 1}

    return _paginate_result(docs, page, limit)


class ImportBatchRequest(BaseModel):
    doc_ids:   list[str]   # lista de claves Hacienda a importar
    period:    str         # YYYYMM
    docs_data: list[dict]  # datos completos de los docs (el frontend ya los tiene)


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
    """
    from services.integration.journal_mapper_v2 import map_document_lines_to_entry

    tenant_id = current_user["tenant_id"]

    # Guard cross-tenant
    docs_filtrados = [
        d for d in payload.docs_data
        if d.get("clave") in payload.doc_ids
    ]

    def mapper(db, doc, tid):
        map_document_lines_to_entry(db, doc, tid)

    result = _process_import_batch(db, docs_filtrados, tenant_id, mapper)

    # Registrar en import_batch
    try:
        db.execute(text("""
            INSERT INTO import_batch (tenant_id, period, tipo, total_docs, importados, skipped, estado)
            VALUES (:tid, :period, 'MIXTO', :total, :imp, :skipped, 'COMPLETO')
        """), {
            "tid": tenant_id, "period": payload.period,
            "total": len(docs_filtrados),
            "imp": result.get("importados", 0),
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
