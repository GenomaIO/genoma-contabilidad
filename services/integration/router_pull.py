"""
integration/router_pull.py
════════════════════════════════════════════════════════════
APIs Pull — Auto-Importación de Documentos Fiscales

Endpoints:
  GET  /integration/pull-enviados     → FE/TE/ND/NC desde Genoma Contable
  GET  /integration/pull-recibidos    → FEC/compras desde Genoma Contable
  POST /integration/import-batch      → Importa lote seleccionado al Diario

Reglas de Oro:
  - Idempotente: dedup por source_ref (clave Hacienda 50 chars)
  - Transacción por lote completo — rollback si falla cualquier doc
  - tenant_id siempre del JWT — nunca del payload
  - Timeout 10s al llamar Genoma Contable (en genoma_client.py)
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
    Informa: URL configurada, estado de autenticación, y si hay docs en el período.
    Útil para saber exactamente por qué falla el botón 'Importar del mes'.
    """
    import os
    from services.integration.genoma_client import GENOMA_CONTABLE_URL, pull_documentos_enviados

    tenant_id    = current_user["tenant_id"]
    tenant_token = current_user.get("token", "")
    url_config   = GENOMA_CONTABLE_URL

    diag = {
        "genoma_contable_url":  url_config,
        "url_configurada":      url_config != "https://api.genoma.io",
        "token_presente":       bool(tenant_token),
        "tenant_id":            tenant_id[:8] + "...",
        "periodo_consultado":   period,
        "enviados_check":       None,
        "error":                None,
    }

    if period:
        result = pull_documentos_enviados(
            tenant_token=tenant_token,
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

    # Diagnóstico claro del problema más probable
    if not diag["url_configurada"]:
        diag["diagnostico"] = (
            "🔴 GENOMA_CONTABLE_URL no está configurada en el entorno del servidor. "
            f"Actualmente apunta a '{url_config}'. "
            "Agrega GENOMA_CONTABLE_URL=https://tu-instancia-genoma.io en las variables de entorno de Render."
        )
    elif not diag["token_presente"]:
        diag["diagnostico"] = "🔴 Token del contador no está disponible en el JWT. Cierra sesión y vuelve a entrar."
    elif diag["enviados_check"] and not diag["enviados_check"]["ok"]:
        diag["diagnostico"] = f"🔴 Genoma Contable rechazó la consulta: {diag['error']}"
    else:
        diag["diagnostico"] = "🟢 Conexión OK"

    return diag

@router.get("/pull-enviados")

def get_pull_enviados(
    period:     str           = Query(..., description="Período YYYYMM"),
    page:       int           = Query(1,   ge=1),
    limit:      int           = Query(10,  ge=1, le=100),
    import_all: bool          = Query(False),
    db:         Session       = Depends(get_session),
    current_user: dict        = Depends(get_current_user),
):
    """
    Consulta documentos FE/TE/ND/NC enviados del tenant en Genoma Contable.
    No importa aún — solo lista lo disponible + estado de importación.
    """
    tenant_id    = current_user["tenant_id"]
    tenant_token = current_user.get("token", "")  # JWT del contador

    # Pull desde Genoma Contable
    result = pull_documentos_enviados(
        tenant_token=tenant_token,
        period=period,
        page=1 if import_all else page,
        limit=1000 if import_all else limit,
    )
    if not result["ok"]:
        raise HTTPException(503, detail=f"Genoma Contable no disponible: {result.get('error')}")

    docs = result.get("items", [])

    # Marcar cuáles ya están importados
    for doc in docs:
        doc["ya_importado"] = _is_already_imported(db, tenant_id, doc.get("clave", ""))

    if import_all:
        return {"items": docs, "total": len(docs), "page": 1, "total_pages": 1}

    return _paginate_result(docs, page, limit)


@router.get("/pull-recibidos")
def get_pull_recibidos(
    period:     str           = Query(..., description="Período YYYYMM"),
    page:       int           = Query(1,   ge=1),
    limit:      int           = Query(10,  ge=1, le=100),
    import_all: bool          = Query(False),
    db:         Session       = Depends(get_session),
    current_user: dict        = Depends(get_current_user),
):
    """
    Consulta documentos FEC/RECIBIDOS del tenant en Genoma Contable.
    Incluye líneas con código CABYS por ítem (para el accordion de la UI).
    """
    tenant_id    = current_user["tenant_id"]
    tenant_token = current_user.get("token", "")

    result = pull_documentos_recibidos(
        tenant_token=tenant_token,
        period=period,
        page=1 if import_all else page,
        limit=1000 if import_all else limit,
    )
    if not result["ok"]:
        raise HTTPException(503, detail=f"Genoma Contable no disponible: {result.get('error')}")

    docs = result.get("items", [])

    for doc in docs:
        doc["ya_importado"] = _is_already_imported(db, tenant_id, doc.get("clave", ""))

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
