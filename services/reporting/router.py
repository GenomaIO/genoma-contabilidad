"""
services/reporting/router.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API de Estados Financieros — NIIF PYMES 3ª Ed.
Prefijo: /reporting

Endpoints:
  GET  /reporting/eeff/{year}           → Genera ESF + ERI
  GET  /reporting/eeff/lines            → Catálogo de partidas NIIF
  GET  /reporting/eeff/mapping          → Mapeo actual del tenant
  POST /reporting/eeff/mapping          → Crear/actualizar un mapeo
  GET  /reporting/eeff/mapping/unmapped → Cuentas activas sin mapear
  POST /reporting/eeff/seed-mapping     → Auto-mapear catálogo estándar
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from services.auth.security import get_current_user
from services.auth.database import get_session
from .models import NiifLineDef, NiifMapping, EeffSnapshot
from .niif_lines import (
    seed_niif_lines, seed_standard_mapping,
    get_unmapped_accounts, STANDARD_AUTO_MAPPING
)
from .eeff_engine import EeffEngine
import uuid
from datetime import datetime, timezone

router = APIRouter(prefix="/reporting", tags=["EEFF"])


# ─────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────

class MappingIn(BaseModel):
    account_code:   str
    niif_line_code: str
    is_contra:      bool = False
    notes:          Optional[str] = None


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def now_utc():
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/eeff/lines")
def get_niif_lines(db: Session = Depends(get_session), user=Depends(get_current_user)):
    """
    Retorna el catálogo global de partidas NIIF.
    Si la tabla está vacía, la siembra automáticamente.
    """
    count = db.query(NiifLineDef).count()
    if count == 0:
        seeded = seed_niif_lines(db)
        return {"seeded": seeded, "lines": []}

    lines = db.query(NiifLineDef).order_by(
        NiifLineDef.statement, NiifLineDef.order
    ).all()
    return {
        "total": len(lines),
        "lines": [
            {
                "code":         l.code,
                "label":        l.label,
                "statement":    l.statement,
                "section":      l.section,
                "order":        l.order,
                "is_subtotal":  l.is_subtotal,
                "efe_activity": l.efe_activity,
                "niif_ref":     l.niif_section_ref,
            }
            for l in lines
        ]
    }


@router.get("/eeff/mapping")
def get_mapping(db: Session = Depends(get_session), user=Depends(get_current_user)):
    """Retorna todos los mapeos NIIF del tenant actual."""
    tenant_id = user["tenant_id"]
    mappings = db.query(NiifMapping).filter_by(tenant_id=tenant_id).all()
    return {
        "tenant_id": tenant_id,
        "total":     len(mappings),
        "mappings":  [
            {
                "account_code":   m.account_code,
                "niif_line_code": m.niif_line_code,
                "is_contra":      m.is_contra,
                "notes":          m.notes,
            }
            for m in mappings
        ]
    }


@router.post("/eeff/mapping")
def upsert_mapping(
    body: MappingIn,
    db: Session = Depends(get_session),
    user=Depends(get_current_user)
):
    """
    Crea o actualiza el mapeo de una cuenta a una partida NIIF.
    Usado por el wizard del contador.
    """
    tenant_id = user["tenant_id"]
    existing = db.query(NiifMapping).filter_by(
        tenant_id=tenant_id, account_code=body.account_code
    ).first()

    if existing:
        existing.niif_line_code = body.niif_line_code
        existing.is_contra      = body.is_contra
        existing.notes          = body.notes
        existing.updated_at     = now_utc()
        db.commit()
        return {"status": "updated", "account_code": body.account_code}
    else:
        m = NiifMapping(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            account_code=body.account_code,
            niif_line_code=body.niif_line_code,
            is_contra=body.is_contra,
            notes=body.notes,
        )
        db.add(m)
        db.commit()
        return {"status": "created", "account_code": body.account_code}


@router.get("/eeff/mapping/unmapped")
def get_unmapped(db: Session = Depends(get_session), user=Depends(get_current_user)):
    """
    Cuentas activas del tenant que NO tienen mapeo NIIF.
    Si hay cuentas aquí, los EEFF pueden estar incompletos.
    """
    tenant_id = user["tenant_id"]
    unmapped = get_unmapped_accounts(tenant_id, db)
    return {
        "tenant_id":      tenant_id,
        "unmapped_count": len(unmapped),
        "has_unmapped":   len(unmapped) > 0,
        "accounts":       unmapped,
        "warning":        "⚠️ Estas cuentas no se refleja en los EEFF" if unmapped else None,
    }


@router.post("/eeff/seed-mapping")
def seed_mapping(db: Session = Depends(get_session), user=Depends(get_current_user)):
    """
    Aplica el mapeo automático del catálogo estándar Genoma.
    Solo inserta si no existe — idempotente.
    """
    tenant_id = user["tenant_id"]
    # Asegurarse que las partidas NIIF estén sembradas primero
    count = db.query(NiifLineDef).count()
    if count == 0:
        seed_niif_lines(db)
    inserted = seed_standard_mapping(tenant_id, db)
    return {
        "status":   "ok",
        "inserted": inserted,
        "message":  f"{inserted} mapeos creados para tenant {tenant_id}",
    }


@router.get("/eeff/{year}")
def get_eeff(
    year: str,
    from_date: Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    to_date:   Optional[str] = Query(None, description="Fecha fin YYYY-MM-DD"),
    db: Session = Depends(get_session),
    user=Depends(get_current_user)
):
    """
    Genera el ESF + ERI para el año indicado.
    Fuente de datos: Balance de Comprobación de asientos POSTED.

    Prerrequisito: tenant debe tener mapeos NIIF configurados.
    Si no los tiene, retorna 400 con instrucciones.
    """
    from sqlalchemy import text as _text
    tenant_id = user["tenant_id"]

    # Verificar que existan mapeos
    mapping_count = db.query(NiifMapping).filter_by(tenant_id=tenant_id).count()
    if mapping_count == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "SIN_MAPEO_NIIF",
                "message": "El tenant no tiene mapeos NIIF configurados.",
                "action": "Ejecutar POST /reporting/eeff/seed-mapping primero.",
            }
        )

    # Asegurar partidas NIIF sembradas
    if db.query(NiifLineDef).count() == 0:
        seed_niif_lines(db)

    # ── Leer entity_type del tenant (PERSONA_JURIDICA / PERSONA_FISICA) ──
    # Fallback a PERSONA_JURIDICA para tenants existentes sin el campo.
    try:
        row = db.execute(
            _text("SELECT entity_type FROM tenants WHERE id = :tid"),
            {"tid": tenant_id}
        ).fetchone()
        entity_type = (row[0] if row and row[0] else "PERSONA_JURIDICA")
    except Exception:
        entity_type = "PERSONA_JURIDICA"

    # Calcular EEFF
    engine = EeffEngine(
        tenant_id=tenant_id,
        year=year,
        db=db,
        from_date=from_date,
        to_date=to_date,
        entity_type=entity_type,
    )
    result = engine.compute()

    # Agregar metadatos de mapping
    result["mapping_stats"] = {
        "total_mappings":  mapping_count,
        "unmapped_by_engine": result["warnings"]["unmapped_accounts"],
    }

    return result
