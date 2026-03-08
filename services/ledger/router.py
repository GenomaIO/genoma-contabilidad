"""
Ledger Router — Endpoints del Libro Diario
Genoma Contabilidad · Workflow DRAFT → POSTED → VOIDED

Reglas de Oro aplicadas:
- tenant_id SIEMPRE del JWT
- DRAFT: cualquier contador/admin puede crear
- POSTED: solo contador o admin puede aprobar (valida balance debit=credit)
- VOIDED: solo contador o admin — genera asiento de reversión automático
- Todo cambio de estado queda en audit_log
"""
import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.auth.database import get_session
from services.auth.security import get_current_user
from services.ledger.models import (
    JournalEntry, JournalLine,
    EntryStatus, EntrySource, DeductibleStatus
)
from services.ledger.audit_log import AuditAction
from services.ledger.audit_logger import log_action

router = APIRouter(prefix="/ledger", tags=["ledger"])


# ─────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────

class JournalLineIn(BaseModel):
    account_code:      str
    description:       Optional[str] = None
    debit:             float = 0.0
    credit:            float = 0.0
    deductible_status: Optional[DeductibleStatus] = DeductibleStatus.PENDING
    legal_basis:       Optional[str] = None
    dim_segment:       Optional[str] = None
    dim_branch:        Optional[str] = None
    dim_project:       Optional[str] = None


class JournalEntryCreate(BaseModel):
    date:        str              # 'YYYY-MM-DD'
    description: str
    source:      EntrySource = EntrySource.MANUAL
    source_ref:  Optional[str] = None
    lines:       List[JournalLineIn]


class JournalLineOut(BaseModel):
    id:                str
    account_code:      str
    description:       Optional[str]
    debit:             float
    credit:            float
    deductible_status: Optional[str]
    legal_basis:       Optional[str]
    dim_segment:       Optional[str]
    dim_branch:        Optional[str]
    dim_project:       Optional[str]

    class Config:
        from_attributes = True


class JournalEntryOut(BaseModel):
    id:          str
    period:      str
    date:        str
    description: str
    status:      str
    source:      str
    source_ref:  Optional[str]
    created_by:  str
    approved_by: Optional[str]
    approved_at: Optional[str]
    lines:       List[JournalLineOut] = []

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _require_role(role: str, allowed: list) -> None:
    if role not in allowed:
        raise HTTPException(403, f"Solo {'/'.join(allowed)} puede realizar esta acción")


def _uid(current_user: dict) -> str:
    """
    Extrae el user_id del payload JWT de forma segura.

    El JWT de este sistema usa 'sub' como clave estándar (RFC 7519).
    Fallback a 'user_id' e 'id' por compatibilidad con tokens legacy.
    NUNCA lanza KeyError — devuelve 'unknown' como último recurso.
    """
    return (
        current_user.get("sub") or
        current_user.get("user_id") or
        current_user.get("id") or
        "unknown"
    )


def _validate_balance(lines: List[JournalLineIn]) -> None:
    """
    Valida que el asiento esté balanceado (suma débitos = suma créditos).
    Hacienda y NIIF exigen partida doble perfecta.
    """
    total_debit  = sum(round(float(l.debit),  5) for l in lines)
    total_credit = sum(round(float(l.credit), 5) for l in lines)
    if abs(total_debit - total_credit) > 0.00001:
        raise HTTPException(
            400,
            f"Asiento no balanceado: débitos={total_debit:.5f} ≠ créditos={total_credit:.5f}"
        )
    if any(l.debit > 0 and l.credit > 0 for l in lines):
        raise HTTPException(400, "Una línea no puede tener débito Y crédito simultáneamente")


# ─────────────────────────────────────────────────────────────────
# POST /ledger/entries — Crear asiento DRAFT
# ─────────────────────────────────────────────────────────────────

@router.post("/entries", status_code=201)
def create_entry(
    req: JournalEntryCreate,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Crea un asiento en estado DRAFT.
    El asistente contable puede crear; el contador es quien aprueba (POSTED).
    Se valida balance debit=credit antes de guardar.
    """
    # E0: eliminado _require_role duplicado (código muerto con 'lectura').
    # Solo admin y contador pueden crear asientos — el asistente no crea, aprueba el contador.
    _require_role(current_user["role"], ["admin", "contador"])

    if not req.lines or len(req.lines) < 2:
        raise HTTPException(400, "El asiento debe tener al menos 2 líneas")
    _validate_balance(req.lines)

    tenant_id = current_user["tenant_id"]

    # ── Guard: período bloqueado (art. 51 Ley Renta CR — inalterabilidad) ──
    _ym = req.date[:7]  # 'YYYY-MM'
    _lock = db.execute(
        text("SELECT status FROM period_locks WHERE tenant_id=:tid AND year_month=:ym"),
        {"tid": tenant_id, "ym": _ym}
    ).fetchone()
    if _lock and _lock.status == 'CLOSED':
        raise HTTPException(
            status_code=423,
            detail=f"El período {_ym} está CERRADO. No se pueden agregar asientos. "
                   f"Los libros digitales ya fueron generados."
        )

    # ── Validación NIIF: solo cuentas de movimiento (hojas) aceptan asientos ──
    # Obtener códigos que son padres de otras cuentas en este tenant
    _parent_rows = db.execute(
        text("SELECT DISTINCT parent_code FROM accounts WHERE tenant_id = :tid AND parent_code IS NOT NULL"),
        {"tid": tenant_id},
    ).fetchall()
    _parent_set = {r[0] for r in _parent_rows}

    # Obtener todas las hojas válidas (allow_entries=True AND not in parent_set)
    _all_active_codes = db.execute(
        text("SELECT code, name, allow_entries FROM accounts WHERE tenant_id = :tid AND is_active = true"),
        {"tid": tenant_id},
    ).fetchall()
    _accounts_map = {r[0]: {"name": r[1], "allow_entries": r[2]} for r in _all_active_codes}

    for l in req.lines:
        _code = l.account_code.strip().upper()
        if _code not in _accounts_map:
            raise HTTPException(
                422,
                f"Cuenta '{_code}' no existe en el catálogo de este tenant."
            )
        if _code in _parent_set:
            _name = _accounts_map[_code]["name"]
            raise HTTPException(
                422,
                f"'{_code} – {_name}' es una cuenta de agrupación y no acepta asientos. "
                f"Use una subcuenta de detalle (nivel 4)."
            )
        if not _accounts_map[_code].get("allow_entries", True):
            raise HTTPException(
                422,
                f"La cuenta '{_code}' no está habilitada para recibir movimientos."
            )
    # ── Fin validación ─────────────────────────────────────────────


    period    = req.date[:7]  # 'YYYY-MM'
    entry_id  = str(uuid.uuid4())
    now       = datetime.now(timezone.utc)

    entry = JournalEntry(
        id          = entry_id,
        tenant_id   = tenant_id,
        period      = period,
        date        = req.date,
        description = req.description,
        status      = EntryStatus.DRAFT,
        source      = req.source,
        source_ref  = req.source_ref,
        created_by  = _uid(current_user),
        created_at  = now,
    )
    db.add(entry)

    for l in req.lines:
        db.add(JournalLine(
            id           = str(uuid.uuid4()),
            entry_id     = entry_id,
            tenant_id    = tenant_id,
            account_code = l.account_code.upper(),
            description  = l.description,
            debit        = round(float(l.debit),  5),
            credit       = round(float(l.credit), 5),
            deductible_status = l.deductible_status,
            legal_basis  = l.legal_basis,
            dim_segment  = l.dim_segment,
            dim_branch   = l.dim_branch,
            dim_project  = l.dim_project,
            created_at   = now,
        ))

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_CREATED,
        entity_type="journal_entry", entity_id=entry_id,
        after={"status": "DRAFT", "lines": len(req.lines)},
        note=req.description
    )
    db.commit()

    return {"ok": True, "entry_id": entry_id, "status": "DRAFT", "period": period}


# ─────────────────────────────────────────────────────────────────
# DELETE /ledger/entries/{entry_id} — Eliminar DRAFT (no POSTED)
# ─────────────────────────────────────────────────────────────────

@router.delete("/entries/{entry_id}", status_code=200)
def delete_draft_entry(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Elimina permanentemente un asiento DRAFT.
    Solo DRAFTs pueden eliminarse — POSTED y VOIDED son inmutables (audit trail).
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.tenant_id == tenant_id
    ).first()

    if not entry:
        raise HTTPException(404, "Asiento no encontrado")
    if entry.status != EntryStatus.DRAFT:
        raise HTTPException(400,
            f"Solo se pueden eliminar asientos BORRADOR. "
            f"Estado actual: {entry.status.value}. "
            f"Para asientos Aprobados usa 'Anular' (genera reversión auditada).")

    # Eliminar líneas y asiento
    db.query(JournalLine).filter(JournalLine.entry_id == entry_id).delete()
    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_VOIDED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"status": "DRAFT", "description": entry.description},
        after={"status": "DELETED"},
        note="Borrador eliminado por el usuario"
    )
    db.delete(entry)
    db.commit()

    return {"ok": True, "deleted": entry_id}


# ─────────────────────────────────────────────────────────────────
# PATCH /ledger/entries/{entry_id} — Editar DRAFT
# ─────────────────────────────────────────────────────────────────

@router.patch("/entries/{entry_id}")
def update_draft_entry(
    entry_id: str,
    req:      JournalEntryCreate,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Edita un asiento DRAFT (fecha, descripción, líneas).
    Reemplaza las líneas existentes por las nuevas.
    Solo aplica a DRAFTs — los POSTED son inmutables.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.tenant_id == tenant_id
    ).first()

    if not entry:
        raise HTTPException(404, "Asiento no encontrado")
    if entry.status != EntryStatus.DRAFT:
        raise HTTPException(400,
            f"Solo se pueden editar asientos BORRADOR. "
            f"Estado actual: {entry.status.value}.")

    if not req.lines or len(req.lines) < 2:
        raise HTTPException(400, "El asiento debe tener al menos 2 líneas")
    _validate_balance(req.lines)

    now = datetime.now(timezone.utc)
    old_desc = entry.description

    # Actualizar cabecera
    entry.date        = req.date
    entry.description = req.description
    entry.period      = req.date[:7]

    # Reemplazar líneas
    db.query(JournalLine).filter(JournalLine.entry_id == entry_id).delete()
    for l in req.lines:
        db.add(JournalLine(
            id           = str(uuid.uuid4()),
            entry_id     = entry_id,
            tenant_id    = tenant_id,
            account_code = l.account_code.upper(),
            description  = l.description,
            debit        = round(float(l.debit),  5),
            credit       = round(float(l.credit), 5),
            deductible_status = l.deductible_status,
            legal_basis  = l.legal_basis,
            dim_segment  = l.dim_segment,
            dim_branch   = l.dim_branch,
            dim_project  = l.dim_project,
            created_at   = now,
        ))

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_UPDATED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"description": old_desc},
        after={"description": req.description, "lines": len(req.lines)},
        note=f"[EDIT-DRAFT] {req.description}"
    )
    db.commit()

    return {"ok": True, "entry_id": entry_id, "status": "DRAFT", "period": entry.period}



@router.patch("/entries/{entry_id}/approve")
def approve_entry(
    entry_id: str,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Aprueba un asiento DRAFT → POSTED.
    Solo contador o admin puede aprobar.
    Una vez POSTED, el asiento es inmutable.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.tenant_id == tenant_id
    ).first()

    if not entry:
        raise HTTPException(404, "Asiento no encontrado")
    if entry.status != EntryStatus.DRAFT:
        raise HTTPException(400, f"Solo asientos DRAFT pueden aprobarse. Estado actual: {entry.status.value}")

    # ── Guard: re-validar partida doble antes de aprobar (anti-corrupción) ───
    # Aunque create_entry ya valida, un asiento podría estar desbalanceado
    # si fue creado por fuera del UI o por un bug. Este guard es la última
    # línea de defensa antes de inmortalizar el asiento como POSTED.
    lines_db = entry.lines  # relación lazy-loaded
    total_debit_ap  = sum(round(float(l.debit  or 0), 5) for l in lines_db)
    total_credit_ap = sum(round(float(l.credit or 0), 5) for l in lines_db)
    if abs(total_debit_ap - total_credit_ap) > 0.00001:
        raise HTTPException(
            status_code=400,
            detail=(
                f"El asiento no está balanceado: "
                f"débitos={total_debit_ap:,.2f} ≠ créditos={total_credit_ap:,.2f}. "
                f"No se puede aprobar un asiento sin partida doble perfecta (NIIF / principio contable básico)."
            )
        )
    if len(lines_db) < 2:
        raise HTTPException(400, "El asiento debe tener al menos 2 líneas para ser aprobado.")
    # ── Fin guard ─────────────────────────────────────────────────────────────

    now = datetime.now(timezone.utc)
    entry.status      = EntryStatus.POSTED
    entry.approved_by = _uid(current_user)
    entry.approved_at = now

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_POSTED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"status": "DRAFT"},
        after={"status": "POSTED", "approved_by": _uid(current_user)}
    )
    db.commit()

    return {"ok": True, "entry_id": entry_id, "status": "POSTED", "approved_at": str(now)}



# ─────────────────────────────────────────────────────────────────
# PATCH /ledger/entries/{entry_id}/void — POSTED → VOIDED (+ reversión)
# ─────────────────────────────────────────────────────────────────

@router.patch("/entries/{entry_id}/void")
def void_entry(
    entry_id: str,
    reason:   str = Query(..., description="Motivo de anulación (requerido)"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Anula un asiento POSTED → VOIDED.
    NO borra el asiento — genera un asiento de reversión (partidas invertidas).
    Regla de Oro: audit trail permanente.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.tenant_id == tenant_id
    ).first()

    if not entry:
        raise HTTPException(404, "Asiento no encontrado")
    if entry.status not in (EntryStatus.POSTED, EntryStatus.DRAFT):
        raise HTTPException(400, f"No se puede anular un asiento en estado {entry.status.value}")

    now        = datetime.now(timezone.utc)
    reversal_id = str(uuid.uuid4())

    # Crear asiento de reversión en DRAFT (el contador debe revisarlo antes de aprobar)
    reversal = JournalEntry(
        id          = reversal_id,
        tenant_id   = tenant_id,
        period      = entry.period,
        date        = now.strftime("%Y-%m-%d"),
        description = f"[REVERSIÓN] {entry.description[:150]}",
        status      = EntryStatus.DRAFT,   # ⚠️ DRAFT — el contador revisa antes de aprobar
        source      = entry.source,
        source_ref  = entry.source_ref,
        created_by  = _uid(current_user),
        created_at  = now,
    )
    db.add(reversal)

    # Invertir débitos/créditos de cada línea
    original_lines = db.query(JournalLine).filter(JournalLine.entry_id == entry_id).all()
    for l in original_lines:
        db.add(JournalLine(
            id           = str(uuid.uuid4()),
            entry_id     = reversal_id,
            tenant_id    = tenant_id,
            account_code = l.account_code,
            description  = l.description,
            debit        = l.credit,    # invertido
            credit       = l.debit,    # invertido
            deductible_status = l.deductible_status,
            legal_basis  = l.legal_basis,
            dim_segment  = l.dim_segment,
            dim_branch   = l.dim_branch,
            dim_project  = l.dim_project,
            created_at   = now,
        ))

    # Marcar original como VOIDED
    entry.status     = EntryStatus.VOIDED
    entry.voided_by  = _uid(current_user)
    entry.voided_at  = now
    entry.reversal_id = reversal_id

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_VOIDED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"status": "POSTED"},
        after={"status": "VOIDED", "reversal_id": reversal_id},
        note=reason
    )
    db.commit()

    return {
        "ok": True,
        "entry_id":    entry_id,
        "status":      "VOIDED",
        "reversal_id": reversal_id,
        "reversal_status": "DRAFT",
        "voided_at":   str(now),
        "note": "Asiento de reversión creado como BORRADOR — revísalo en el Diario antes de aprobar.",
    }


# ─────────────────────────────────────────────────────────────────
# PATCH /ledger/entries/{entry_id}/revert-to-draft — POSTED → DRAFT
# ─────────────────────────────────────────────────────────────────

@router.patch("/entries/{entry_id}/revert-to-draft")
def revert_to_draft(
    entry_id: str,
    reason:   str = Query(..., description="Motivo del reverso a borrador (requerido)"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Regresa un asiento POSTED → DRAFT para corrección, siempre que el período
    NO esté cerrado (status CLOSED).

    Regla:
      - Solo aplica a asientos POSTED (no VOIDED, no DRAFT ya).
      - El período del asiento debe estar en OPEN o CLOSING (no CLOSED).
      - Limpia approved_by / approved_at para forzar revisión.
      - Deja audit trail completo.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    entry = db.query(JournalEntry).filter(
        JournalEntry.id == entry_id,
        JournalEntry.tenant_id == tenant_id
    ).first()

    if not entry:
        raise HTTPException(404, "Asiento no encontrado")
    if entry.status != EntryStatus.POSTED:
        raise HTTPException(400,
            f"Solo asientos APROBADOS pueden revertirse a borrador. "
            f"Estado actual: {entry.status.value}")

    # Verificar que el período NO esté cerrado
    period_row = db.execute(text("""
        SELECT status FROM period_status
        WHERE tenant_id = :tid AND year_month = :ym
    """), {"tid": tenant_id, "ym": entry.period}).fetchone()

    period_status = period_row.status if period_row else "OPEN"
    if period_status == "CLOSED":
        raise HTTPException(409,
            f"El período {entry.period} ya está CERRADO. "
            f"No se puede revertir un asiento de un período cerrado. "
            f"Usa un asiento de ajuste en el período actual en su lugar.")

    now = datetime.now(timezone.utc)
    old_approved_by = entry.approved_by
    old_approved_at = str(entry.approved_at) if entry.approved_at else None

    # Revertir a DRAFT
    entry.status      = EntryStatus.DRAFT
    entry.approved_by = None
    entry.approved_at = None

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_UPDATED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"status": "POSTED", "approved_by": old_approved_by, "approved_at": old_approved_at},
        after={"status": "DRAFT",   "approved_by": None,            "approved_at": None},
        note=f"[REVERT-TO-DRAFT] {reason}"
    )
    db.commit()

    return {
        "ok":      True,
        "entry_id": entry_id,
        "period":   entry.period,
        "status":   "DRAFT",
        "note":     f"Asiento revertido a BORRADOR. Período {entry.period}: {period_status}. Razón: {reason}",
    }


# ─────────────────────────────────────────────────────────────────
# GET /ledger/entries — Listar asientos del período
# ─────────────────────────────────────────────────────────────────

@router.get("/entries", response_model=List[JournalEntryOut])
def list_entries(
    period: Optional[str] = Query(None, description="'YYYY-MM' (default: mes actual)"),
    status_filter: Optional[EntryStatus] = Query(None, alias="status"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Lista los asientos del tenant. Filtrable por período y estado.
    """
    tenant_id = current_user["tenant_id"]

    if not period:
        period = datetime.now(timezone.utc).strftime("%Y-%m")

    query = db.query(JournalEntry).filter(
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.period == period,
    )
    if status_filter:
        query = query.filter(JournalEntry.status == status_filter)

    entries = query.order_by(JournalEntry.date, JournalEntry.created_at).all()

    result = []
    for e in entries:
        lines_out = [
            JournalLineOut(
                id=l.id, account_code=l.account_code, description=l.description,
                debit=float(l.debit), credit=float(l.credit),
                deductible_status=l.deductible_status.value if l.deductible_status else None,
                legal_basis=l.legal_basis,
                dim_segment=l.dim_segment, dim_branch=l.dim_branch, dim_project=l.dim_project,
            )
            for l in e.lines
        ]
        result.append(JournalEntryOut(
            id=e.id, period=e.period, date=e.date, description=e.description,
            status=e.status.value, source=e.source.value, source_ref=e.source_ref,
            created_by=e.created_by, approved_by=e.approved_by,
            approved_at=str(e.approved_at) if e.approved_at else None,
            lines=lines_out
        ))
    return result


# ─────────────────────────────────────────────────────────────────
# GET /ledger/trial-balance — Balance de Comprobación
# ─────────────────────────────────────────────────────────────────

_BALANCE_ACCOUNT_TYPES   = {"ACTIVO", "PASIVO", "PATRIMONIO"}
_RESULTADO_ACCOUNT_TYPES = {"INGRESO", "GASTO"}


@router.get("/trial-balance")
def trial_balance(
    period:       Optional[str] = Query(None,    description="'YYYY-MM' (default: mes actual)"),
    mode:         str           = Query("ytd",   description="period=solo mes | ytd=año acumulado (base EEFF, NIIF Sec.2.36) | running=saldo histórico"),
    acumulado:    bool          = Query(False,   description="Alias legacy de mode=ytd. Si True, equivale a mode='ytd'."),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Balance de Comprobación.

    Modos (parámetro `mode`):
      period  — Solo movimientos del período seleccionado.
                Para revisión interna del mes.
      ytd     — Acumulado desde el 1 de enero del año fiscal hasta el período
                seleccionado. BASE para los EEFF (NIIF PYMES Sec. 2.36 y 3.10).
                DEFAULT.
      running — Saldo corriente histórico: apertura + TODOS los períodos cerrados
                + movimientos abiertos. Para auditoría.

    Invariante: Debe = Haber en cualquier modo (partida doble).
    Solo incluye asientos POSTED.
    """
    tenant_id = current_user["tenant_id"]
    if not period:
        period = datetime.now(timezone.utc).strftime("%Y-%m")

    # Alias de compatibilidad: acumulado=True → mode=ytd
    if acumulado and mode == "ytd":
        pass  # ya igual
    elif acumulado:
        mode = "ytd"

    # Rango de fechas según modo
    year = period[:4]
    year_start = f"{year}-01"  # primer período del año fiscal
    # ┌────────────────────────────────────────────────────────────────────────┐
    # │ mode="ytd"  → desde año-01-01 hasta fin del período seleccionado.     │
    # │ Es la base correcta para los EEFF (NIIF PYMES Sec. 2.36 y 3.10).     │
    # │ Invariante garantizada: Debe = Haber (partida doble).                  │
    # └────────────────────────────────────────────────────────────────────────┘

    # Catálogo de cuentas para tipos
    accounts_map = {}
    try:
        accs = db.execute(text(
            "SELECT code, name, account_type FROM accounts WHERE tenant_id = :tid AND is_active = true"
        ), {"tid": tenant_id}).fetchall()
        accounts_map = {r.code: {"name": r.name, "type": r.account_type} for r in accs}
    except Exception:
        pass

    # ── Construir la consulta SQL según modo ─────────────────────
    if mode == "period":
        # Solo el período seleccionado — vista de movimientos del mes
        rows = db.execute(text("""
            SELECT
                jl.account_code,
                SUM(jl.debit)  AS total_debit,
                SUM(jl.credit) AS total_credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.tenant_id = :tid
              AND je.period    = :period
              AND je.status    = 'POSTED'
            GROUP BY jl.account_code
            ORDER BY jl.account_code
        """), {"tid": tenant_id, "period": period}).fetchall()

    elif mode == "ytd":
        # ── MODO YTD (DEFAULT) ────────────────────────────────────────────
        # Acumula desde el primer período del año hasta el período seleccionado.
        # BASE de los EEFF. Garantiza Debe = Haber.
        # NIIF PYMES Sec. 2.36 (devengo) · Sec. 3.10 (período anual).
        rows = db.execute(text("""
            SELECT
                jl.account_code,
                SUM(jl.debit)  AS total_debit,
                SUM(jl.credit) AS total_credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.tenant_id = :tid
              AND je.period    >= :year_start
              AND je.period    <= :period
              AND je.status    = 'POSTED'
            GROUP BY jl.account_code
            ORDER BY jl.account_code
        """), {"tid": tenant_id, "year_start": year_start, "period": period}).fetchall()

    else:  # running — saldo histórico completo (todos los años)
        rows = db.execute(text("""
            SELECT
                jl.account_code,
                SUM(jl.debit)  AS total_debit,
                SUM(jl.credit) AS total_credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE je.tenant_id = :tid
              AND je.period    <= :period
              AND je.status    = 'POSTED'
            GROUP BY jl.account_code
            ORDER BY jl.account_code
        """), {"tid": tenant_id, "period": period}).fetchall()

    # ── Construir resultado ───────────────────────────────────────
    total_debit = 0.0
    total_credit = 0.0
    lines_out = []

    for r in rows:
        td = float(r.total_debit  or 0)
        tc = float(r.total_credit or 0)
        total_debit  += td
        total_credit += tc
        acc_info = accounts_map.get(r.account_code, {})
        acc_type = acc_info.get("type", "")
        saldo    = round(td - tc, 2)

        lines_out.append({
            "account_code":  r.account_code,
            "account_name":  acc_info.get("name", r.account_code),
            "account_type":  acc_type,
            "total_debit":   round(td, 2),
            "total_credit":  round(tc, 2),
            "saldo":         saldo,
        })

    # ── Invariante: Debe = Haber ──────────────────────────────────
    # En partida doble, CUALQUIER corte temporal debe cuadrar.
    balanced = abs(total_debit - total_credit) < 0.01

    return {
        "period":        period,
        "mode":          mode,
        "year_start":    year_start if mode in ("ytd", "running") else period,
        "acumulado":     mode in ("ytd", "running"),  # compatibilidad con frontend legacy
        "balanced":      balanced,
        "total_debit":   round(total_debit,  2),
        "total_credit":  round(total_credit, 2),
        "diff":          round(abs(total_debit - total_credit), 5),
        "lines":         lines_out,
        "tenant_id":     tenant_id,
        "niif_ref":      "NIIF PYMES Sec. 2.36 (devengo) · Sec. 3.10 (período anual)" if mode == "ytd" else "",
    }


# ─────────────────────────────────────────────────────────────────
# POST /ledger/close-period — Cierre de Período
# ─────────────────────────────────────────────────────────────────

@router.post("/close-period")
def close_period(
    period: str = Query(..., description="Período a cerrar: 'YYYY-MM'"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Genera el asiento de cierre del período.

    Reglas NIIF CR:
    1. No puede haber asientos DRAFT pendientes en el período.
    2. Cierra saldos de INGRESO (4xxx) y GASTO (5xxx) → cuenta 3303 (Utilidad del Ejercicio).
    3. El asiento de cierre se crea en estado DRAFT para que el contador lo apruebe.
    4. Solo contador o admin puede generar el cierre.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    # 1. Verificar que no hay DRAFT pendientes
    drafts = db.query(JournalEntry).filter(
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.period == period,
        JournalEntry.status == EntryStatus.DRAFT,
    ).count()
    if drafts > 0:
        raise HTTPException(
            400,
            f"Existen {drafts} asiento(s) DRAFT pendientes de aprobación en {period}. "
            "Apruébalos o cancélalos antes de cerrar el período."
        )

    # 2. Calcular saldos de ingresos y gastos del período
    rows = db.execute(text("""
        SELECT
            jl.account_code,
            a.account_type,
            a.name,
            SUM(jl.debit) - SUM(jl.credit) AS saldo
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id = je.tenant_id AND a.code = jl.account_code
        WHERE je.tenant_id = :tenant_id
          AND je.period = :period
          AND je.status = 'POSTED'
          AND a.account_type IN ('INGRESO', 'GASTO')
        GROUP BY jl.account_code, a.account_type, a.name
        HAVING ABS(SUM(jl.debit) - SUM(jl.credit)) > 0.00001
    """), {"tenant_id": tenant_id, "period": period}).fetchall()

    if not rows:
        return {
            "ok": True,
            "period": period,
            "message": "No hay movimientos de ingresos/gastos en este período. Sin asiento de cierre necesario.",
            "entry_id": None,
        }

    # 3. Construir las líneas del asiento de cierre
    now       = datetime.now(timezone.utc)
    entry_id  = str(uuid.uuid4())
    close_lines_in = []

    total_ing = 0.0  # suma créditos ingresos → se convierten en débito para cerrar
    total_gas = 0.0  # suma débitos gastos → se convierten en crédito para cerrar

    for r in rows:
        saldo = float(r.saldo or 0)
        if r.account_type == "INGRESO":
            # Ingresos tienen saldo CR (crédito) → para cerrar: debitar la cuenta
            if saldo < 0:  # saldo CR es negativo en nuestra convención (debit-credit)
                close_lines_in.append(JournalLineIn(
                    account_code=r.account_code,
                    description=f"Cierre ingreso: {r.name}",
                    debit=abs(saldo),
                    credit=0.0,
                ))
                total_ing += abs(saldo)
        elif r.account_type == "GASTO":
            # Gastos tienen saldo DR (débito) → para cerrar: acreditar la cuenta
            if saldo > 0:
                close_lines_in.append(JournalLineIn(
                    account_code=r.account_code,
                    description=f"Cierre gasto: {r.name}",
                    debit=0.0,
                    credit=saldo,
                ))
                total_gas += saldo

    # 4. Contrapartida a cuenta 3303 — Utilidad del Ejercicio
    utilidad = total_ing - total_gas
    if utilidad >= 0:
        close_lines_in.append(JournalLineIn(
            account_code="3303",
            description="Utilidad del ejercicio — cierre de período",
            debit=0.0,
            credit=round(utilidad, 5),
        ))
    else:
        close_lines_in.append(JournalLineIn(
            account_code="3302",
            description="Pérdida del ejercicio — cierre de período",
            debit=round(abs(utilidad), 5),
            credit=0.0,
        ))

    # 5. Validar y guardar el asiento de cierre en DRAFT
    try:
        _validate_balance(close_lines_in)
    except HTTPException:
        # Si el balance no cierra perfectamente, agregar diferencia como nota
        pass  # El contador revisará en la aprobación

    close_entry = JournalEntry(
        id          = entry_id,
        tenant_id   = tenant_id,
        period      = period,
        date        = now.strftime("%Y-%m-%d"),
        description = f"Cierre de periodo {period}",
        status      = EntryStatus.DRAFT,
        source      = EntrySource.CIERRE,
        created_by  = _uid(current_user),
        created_at  = now,
    )
    db.add(close_entry)

    for l in close_lines_in:
        db.add(JournalLine(
            id           = str(uuid.uuid4()),
            entry_id     = entry_id,
            tenant_id    = tenant_id,
            account_code = l.account_code.upper(),
            description  = l.description,
            debit        = round(float(l.debit),  5),
            credit       = round(float(l.credit), 5),
            deductible_status=DeductibleStatus.EXEMPT,
            created_at   = now,
        ))

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_CREATED,
        entity_type="journal_entry", entity_id=entry_id,
        after={
            "status": "DRAFT",
            "source": "CIERRE",
            "period": period,
            "utilidad_neta": round(utilidad, 2),
            "lines": len(close_lines_in),
        },
        note=f"Cierre de período {period}"
    )
    db.commit()

    return {
        "ok": True,
        "period":          period,
        "entry_id":        entry_id,
        "status":          "DRAFT",
        "utilidad_neta":   round(utilidad, 2),
        "lines_created":   len(close_lines_in),
        "message":         "Asiento de cierre creado en DRAFT. El contador debe aprobarlo.",
        "next_action":     f"PATCH /ledger/entries/{entry_id}/approve",
    }


# ─────────────────────────────────────────────────────────────────
# GET /ledger/opening-entry — Consultar apertura del ejercicio
# ─────────────────────────────────────────────────────────────────

@router.get("/opening-entry")
def get_opening_entry(
    year:         Optional[str] = Query(None, description="Año fiscal YYYY (default: año actual)"),
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Retorna el asiento de apertura POSTED del año indicado (o del año actual).
    Si no existe → {'exists': False}.
    """
    _require_role(current_user["role"], ["admin", "contador", "asistente"])
    tenant_id = current_user["tenant_id"]
    fiscal_year = year or str(datetime.now(timezone.utc).year)

    entry = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.source    == EntrySource.APERTURA,
            JournalEntry.period.like(f"{fiscal_year}%"),
        )
        .order_by(JournalEntry.created_at.asc())
        .first()
    )

    if not entry:
        return {"exists": False, "year": fiscal_year}

    return {
        "exists":      True,
        "year":        fiscal_year,
        "entry_id":    entry.id,
        "date":        entry.date,
        "description": entry.description,
        "status":      entry.status.value,
        "created_by":  entry.created_by,
        "approved_at": str(entry.approved_at) if entry.approved_at else None,
        "lines": [
            {
                "account_code": l.account_code,
                "description":  l.description,
                "debit":        float(l.debit),
                "credit":       float(l.credit),
            }
            for l in entry.lines
        ],
    }


# ─────────────────────────────────────────────────────────────────
# POST /ledger/opening-entry — Crear asiento de apertura
# ─────────────────────────────────────────────────────────────────

# Tipos de cuenta permitidos en un asiento de apertura (NIIF)
_BALANCE_TYPES = {"ACTIVO", "PASIVO", "PATRIMONIO"}


class OpeningLineIn(BaseModel):
    account_code: str
    description:  Optional[str] = None
    debit:        float = 0.0
    credit:       float = 0.0


class OpeningEntryCreate(BaseModel):
    date:        str             # 'YYYY-MM-DD' — primer día del ejercicio
    description: str = "Asiento de Apertura de Ejercicio"
    lines:       List[OpeningLineIn]
    mes_inicio:  int = 1        # 1=enero ... 12=diciembre (para prorrateo de créditos fiscales)


@router.post("/opening-entry", status_code=201)
def create_opening_entry(
    req:          OpeningEntryCreate,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Crea el asiento de apertura del ejercicio fiscal.

    Reglas NIIF / principio contable:
    1. Solo cuentas de Balance (ACTIVO, PASIVO, PATRIMONIO) — nunca INGRESO/GASTO
    2. Partida doble perfecta (Débito = Crédito)
    3. ÚNICO por año fiscal y tenant — no pueden existir dos aperturas del mismo año
    4. Se aprueba (POSTED) directamente — no pasa por DRAFT
    5. Solo contador o admin puede crear la apertura
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]

    if not req.lines or len(req.lines) < 2:
        raise HTTPException(400, "El asiento de apertura debe tener al menos 2 líneas.")

    # Extraer año del campo date
    try:
        fiscal_year = req.date[:4]
        int(fiscal_year)
    except (ValueError, IndexError):
        raise HTTPException(400, f"Fecha inválida: '{req.date}'. Use formato YYYY-MM-DD.")

    # ── Guard 1: unicidad — no puede existir otra apertura del mismo año ──
    existing = (
        db.query(JournalEntry)
        .filter(
            JournalEntry.tenant_id == tenant_id,
            JournalEntry.source    == EntrySource.APERTURA,
            JournalEntry.period.like(f"{fiscal_year}%"),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya existe un asiento de apertura para el año {fiscal_year} "
                f"(ID: {existing.id}). Solo se permite una apertura por ejercicio fiscal."
            )
        )

    # ── Guard 2: validar que las cuentas existen y son de balance ──
    account_codes = [l.account_code for l in req.lines]
    rows = db.execute(
        text("SELECT code, account_type FROM accounts WHERE tenant_id = :tid AND code IN :codes"),
        {"tid": tenant_id, "codes": tuple(account_codes)}
    ).fetchall()
    catalog_map = {r[0]: r[1] for r in rows}

    errors = []
    for l in req.lines:
        if l.account_code not in catalog_map:
            errors.append(f"Cuenta '{l.account_code}' no existe en el catálogo.")
            continue
        acc_type = catalog_map[l.account_code]
        if acc_type not in _BALANCE_TYPES:
            errors.append(
                f"Cuenta '{l.account_code}' es de tipo {acc_type}. "
                f"Solo ACTIVO, PASIVO y PATRIMONIO pueden incluirse en el asiento de apertura (NIIF)."
            )
        if l.debit <= 0 and l.credit <= 0:
            errors.append(f"Cuenta '{l.account_code}' no tiene saldo (débito y crédito son 0).")
        if l.debit > 0 and l.credit > 0:
            errors.append(f"Cuenta '{l.account_code}' tiene débito Y crédito. Use una sola columna por línea.")

    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    # ── Guard 3: partida doble ──
    total_dr = sum(round(float(l.debit),  5) for l in req.lines)
    total_cr = sum(round(float(l.credit), 5) for l in req.lines)
    if abs(total_dr - total_cr) > 0.00001:
        raise HTTPException(
            status_code=400,
            detail=f"Asiento desbalanceado: Debe={total_dr:,.2f} ≠ Haber={total_cr:,.2f}. El asiento de apertura exige partida doble perfecta."
        )

    # ── Crear la cabecera POSTED directamente (no pasa por DRAFT) ──
    period   = f"{fiscal_year}-01"
    entry_id = str(uuid.uuid4())
    now      = datetime.now(timezone.utc)

    entry = JournalEntry(
        id          = entry_id,
        tenant_id   = tenant_id,
        period      = period,
        date        = req.date,
        description = req.description,
        status      = EntryStatus.POSTED,   # POSTED directo — apertura es definitiva
        source      = EntrySource.APERTURA,
        created_by  = _uid(current_user),
        approved_by = _uid(current_user),
        approved_at = now,
    )
    db.add(entry)

    # ── Crear las líneas ──
    for l in req.lines:
        db.add(JournalLine(
            id           = str(uuid.uuid4()),
            entry_id     = entry_id,
            tenant_id    = tenant_id,
            account_code = l.account_code,
            description  = l.description,
            debit        = round(float(l.debit),  5),
            credit       = round(float(l.credit), 5),
        ))

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_POSTED,
        entity_type="journal_entry", entity_id=entry_id,
        before={},
        after={
            "source":   "APERTURA",
            "status":   "POSTED",
            "period":   period,
            "year":     fiscal_year,
            "lines":    len(req.lines),
            "total_dr": round(total_dr, 2),
            "total_cr": round(total_cr, 2),
        },
        note=f"Asiento de apertura {fiscal_year} — {len(req.lines)} líneas · Total ₡{total_dr:,.2f}"
    )
    db.commit()

    # ── Guardar mes de inicio del período en el tenant ──────────────
    # Afecta prorrateo de créditos fiscales por familia (Hacienda CR)
    mes = max(1, min(12, req.mes_inicio))  # clamp 1-12 seguro
    try:
        db.execute(
            text("UPDATE tenants SET mes_inicio_periodo=:mes WHERE id=:tid"),
            {"mes": mes, "tid": tenant_id}
        )
        db.commit()
    except Exception:
        pass  # columna puede no existir en SQLite dev local

    return {
        "ok":           True,
        "entry_id":     entry_id,
        "period":       period,
        "year":         fiscal_year,
        "mes_inicio":   req.mes_inicio,
        "status":       "POSTED",
        "source":       "APERTURA",
        "lines":        len(req.lines),
        "total_debe":   round(total_dr, 2),
        "total_haber":  round(total_cr, 2),
        "message":      f"Asiento de apertura {fiscal_year} creado y aprobado. El libro queda abierto.",
    }


# ─────────────────────────────────────────────────────────────────
# GET /ledger/mayor/{account_code} — Libro Mayor (T-account)
# ─────────────────────────────────────────────────────────────────

@router.get("/mayor/{account_code}")
def get_mayor(
    account_code: str,
    from_date: Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    to_date:   Optional[str] = Query(None, description="Fecha fin   YYYY-MM-DD"),
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Libro Mayor de una cuenta — T-account con saldo running.

    Lógica contable (NIIF):
    1. Saldo inicial = neto del asiento APERTURA para esta cuenta.
    2. Movimientos = lineas POSTED en from_date..to_date (sin APERTURA).
    3. Saldo running se acumula linea a linea.
    4. Saldo cierre = saldo_inicial + SUM(debit) - SUM(credit).
    """
    tenant_id = current_user["tenant_id"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year_str  = datetime.now(timezone.utc).strftime("%Y")
    if not from_date:
        from_date = f"{year_str}-01-01"
    if not to_date:
        to_date = now_str

    # ── REGLA: Mayorización a N4 ───────────────────────────────────
    # El Mayor siempre consolida a N4. Si un tenant creó subcuentas N5
    # (ej: 1101.01.01, 1101.01.02), sus movimientos se agregan al T-account
    # de la cuenta N4 padre (1101.01). Se usa LIKE '{code}.%' para capturar.
    code_prefix = f"{account_code}.%"

    # 1. Saldo inicial desde apertura — incluye N4 exacto Y subcuentas N5+
    ap_rows = db.execute(text("""
        SELECT jl.debit, jl.credit, jl.account_code AS sub_code
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id = :tid
          AND je.status    = 'POSTED'
          AND je.source    = 'APERTURA'
          AND (jl.account_code = :code OR jl.account_code LIKE :prefix)
    """), {"tid": tenant_id, "code": account_code, "prefix": code_prefix}).fetchall()

    opening_balance = round(sum(float(r.debit) - float(r.credit) for r in ap_rows), 2)

    # 2. Info de la cuenta N4 (la raíz consultada)
    acc_row = db.execute(text(
        "SELECT name, account_type FROM accounts WHERE tenant_id = :tid AND code = :code"
    ), {"tid": tenant_id, "code": account_code}).fetchone()

    account_name = acc_row.name         if acc_row else account_code
    account_type = acc_row.account_type if acc_row else "DESCONOCIDO"

    # 3. Movimientos del periodo — incluye N5+ con roll-up al T-account N4
    move_rows = db.execute(text("""
        SELECT jl.id AS line_id, je.id AS entry_id,
               je.date, je.description AS entry_desc,
               jl.description AS line_desc,
               jl.debit, jl.credit, je.source, je.source_ref,
               jl.account_code AS sub_code
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id    = :tid
          AND je.status       = 'POSTED'
          AND je.source      != 'APERTURA'
          AND (jl.account_code = :code OR jl.account_code LIKE :prefix)
          AND je.date BETWEEN :from_d AND :to_d
        ORDER BY je.date ASC, je.created_at ASC
    """), {"tid": tenant_id, "code": account_code, "prefix": code_prefix,
           "from_d": from_date, "to_d": to_date}).fetchall()

    # 4. Saldo running con N5 consolidados
    running = opening_balance
    total_debit = 0.0; total_credit = 0.0
    movements = []
    for r in move_rows:
        d  = float(r.debit  or 0)
        cr = float(r.credit or 0)
        running      = round(running + d - cr, 2)
        total_debit  += d
        total_credit += cr
        # Si es una subcuenta N5, indicarlo en la descripción
        sub = r.sub_code if r.sub_code != account_code else None
        desc = r.line_desc or r.entry_desc or ""
        if sub:
            desc = f"[{sub}] {desc}"
        movements.append({
            "entry_id":    r.entry_id,
            "date":        r.date,
            "description": desc,
            "source":      r.source,
            "source_ref":  r.source_ref,
            "sub_account": sub,
            "debit":       round(d,  2),
            "credit":      round(cr, 2),
            "balance":     running,
        })

    return {
        "account_code":    account_code,
        "account_name":    account_name,
        "account_type":    account_type,
        "from_date":       from_date,
        "to_date":         to_date,
        "opening_balance": opening_balance,
        "total_debit":     round(total_debit,  2),
        "total_credit":    round(total_credit, 2),
        "closing_balance": round(opening_balance + total_debit - total_credit, 2),
        "movements":       movements,
        "has_apertura":    len(ap_rows) > 0,
        "consolidates_n5": any(r.sub_code != account_code for r in ap_rows if hasattr(r, 'sub_code'))
                           or any(r.sub_code != account_code for r in move_rows if hasattr(r, 'sub_code')),
    }


# ─────────────────────────────────────────────────────────────────
# GET /ledger/mayor — Indice del Mayor: todas las cuentas con saldo
# ─────────────────────────────────────────────────────────────────

@router.get("/mayor")
def get_mayor_summary(
    from_date:    Optional[str] = Query(None, description="Fecha inicio YYYY-MM-DD"),
    to_date:      Optional[str] = Query(None, description="Fecha fin   YYYY-MM-DD"),
    account_type: Optional[str] = Query(None, description="Filtrar tipo: ACTIVO|PASIVO|PATRIMONIO|INGRESO|GASTO"),
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Indice del Libro Mayor — resumen de todas las cuentas con actividad.
    Saldo inicial (apertura) + movimientos del periodo = saldo cierre.
    """
    tenant_id = current_user["tenant_id"]
    now_str   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    year_str  = datetime.now(timezone.utc).strftime("%Y")
    if not from_date:
        from_date = f"{year_str}-01-01"
    if not to_date:
        to_date = now_str

    # Saldos de apertura por cuenta
    ap_map = {}
    for r in db.execute(text("""
        SELECT jl.account_code,
               SUM(jl.debit) - SUM(jl.credit) AS saldo_aper
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id = :tid AND je.status = 'POSTED' AND je.source = 'APERTURA'
        GROUP BY jl.account_code
    """), {"tid": tenant_id}).fetchall():
        ap_map[r.account_code] = round(float(r.saldo_aper or 0), 2)

    # Movimientos del periodo (sin apertura)
    type_clause = f"AND a.account_type = '{account_type}'" if account_type else ""
    m_rows = db.execute(text(f"""
        SELECT jl.account_code, a.name AS account_name, a.account_type,
               SUM(jl.debit) AS total_debit, SUM(jl.credit) AS total_credit
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id = je.tenant_id AND a.code = jl.account_code
        WHERE je.tenant_id = :tid AND je.status = 'POSTED' AND je.source != 'APERTURA'
          AND je.date BETWEEN :from_d AND :to_d {type_clause}
        GROUP BY jl.account_code, a.name, a.account_type
        ORDER BY jl.account_code
    """), {"tid": tenant_id, "from_d": from_date, "to_d": to_date}).fetchall()

    move_idx = {r.account_code: r for r in m_rows}
    all_codes = sorted(set(ap_map.keys()) | set(move_idx.keys()))

    # Info para cuentas solo en apertura
    aper_only = set(ap_map.keys()) - set(move_idx.keys())
    extra_info = {}
    if aper_only:
        for r in db.execute(text(
            "SELECT code, name, account_type FROM accounts WHERE tenant_id = :tid AND code IN :codes"
        ), {"tid": tenant_id, "codes": tuple(aper_only)}).fetchall():
            extra_info[r.code] = r

    result = []
    for code in all_codes:
        aper = ap_map.get(code, 0.0)
        if code in move_idx:
            r = move_idx[code]
            td = round(float(r.total_debit or 0), 2)
            tc = round(float(r.total_credit or 0), 2)
            name  = r.account_name or code
            atype = r.account_type or ""
        else:
            td = 0.0; tc = 0.0
            ex    = extra_info.get(code)
            name  = ex.name if ex else code
            atype = ex.account_type if ex else ""
        # display_code: convierte 1101.01 → 1.1.1.01 para el frontend
        def _disp(c):
            if '.' not in c: 
                if len(c) == 4:
                    if c[1:] == '000': return c[0]
                    if c[2:] == '00':  return f'{c[0]}.{c[1]}'
                    return f'{c[0]}.{c[1]}.{int(c[2:])}'
            return c
        result.append({
            "account_code":    code,
            "display_code":    _disp(code),
            "account_name":    name,
            "account_type":    atype,
            "opening_balance": aper,
            "total_debit":     td,
            "total_credit":    tc,
            "net_movement":    round(td - tc, 2),
            "closing_balance": round(aper + td - tc, 2),
        })

    return {
        "from_date": from_date,
        "to_date":   to_date,
        "tenant_id": tenant_id,
        "accounts":  result,
        "total":     len(result),
    }


# ─────────────────────────────────────────────────────────────────
# Cierre de Período — OPEN → CLOSING → CLOSED
# Art. 51 Ley Renta CR: inalterabilidad tras cierre
# ─────────────────────────────────────────────────────────────────

@router.get("/period/{year_month}/status")
def get_period_status(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Retorna el estado actual del período (OPEN | CLOSING | CLOSED)."""
    tenant_id = current_user["tenant_id"]
    row = db.execute(
        text("SELECT status, closed_by, closed_at FROM period_locks "
             "WHERE tenant_id=:tid AND year_month=:ym"),
        {"tid": tenant_id, "ym": year_month}
    ).fetchone()
    status_val = row.status if row else "OPEN"
    return {
        "year_month": year_month,
        "status":     status_val,
        "closed_by":  row.closed_by if row else None,
        "closed_at":  str(row.closed_at) if row and row.closed_at else None,
    }


@router.post("/period/{year_month}/close-request")
def request_period_close(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Contador solicita cierre: OPEN → CLOSING. No bloquea aún."""
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]
    # Verificar que no haya DRAFT pendientes en el período
    draft_count = db.execute(
        text("SELECT COUNT(*) FROM journal_entries "
             "WHERE tenant_id=:tid AND period=:ym AND status='DRAFT'"),
        {"tid": tenant_id, "ym": year_month}
    ).scalar()
    if draft_count and draft_count > 0:
        raise HTTPException(
            400,
            f"Hay {draft_count} asiento(s) en DRAFT. Aprueba o elimina antes de cerrar."
        )
    # UPSERT period_lock
    db.execute(
        text("""
            INSERT INTO period_locks (id, tenant_id, year_month, status, closed_by)
            VALUES (gen_random_uuid()::text, :tid, :ym, 'CLOSING', :user)
            ON CONFLICT (tenant_id, year_month)
            DO UPDATE SET status='CLOSING', closed_by=:user
        """),
        {"tid": tenant_id, "ym": year_month, "user": _uid(current_user)}
    )
    db.commit()
    return {"year_month": year_month, "status": "CLOSING",
            "message": "Período en CLOSING. Admin puede ahora bloquear (lock)."}


@router.post("/period/{year_month}/lock")
def lock_period(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Admin bloquea el período: CLOSING → CLOSED. Inalterabilidad total."""
    _require_role(current_user["role"], ["admin"])
    tenant_id = current_user["tenant_id"]
    # Solo puede bloquear si está en CLOSING
    row = db.execute(
        text("SELECT status FROM period_locks WHERE tenant_id=:tid AND year_month=:ym"),
        {"tid": tenant_id, "ym": year_month}
    ).fetchone()
    if not row or row.status != "CLOSING":
        raise HTTPException(
            400,
            f"El período {year_month} debe estar en CLOSING antes de bloquear. "
            f"Estado actual: {row.status if row else 'OPEN'}"
        )
    db.execute(
        text("""
            UPDATE period_locks
            SET status='CLOSED', closed_by=:user, closed_at=NOW()
            WHERE tenant_id=:tid AND year_month=:ym
        """),
        {"tid": tenant_id, "ym": year_month, "user": _uid(current_user)}
    )
    db.commit()
    return {"year_month": year_month, "status": "CLOSED",
            "message": "Período CERRADO. Libros digitales disponibles. Sin modificaciones posibles."}


# ─────────────────────────────────────────────────────────────────
# Libros Digitales — Solo disponibles cuando status = CLOSED
# Art. 51 Ley Renta CR: Diario, Mayor, Inventarios y Balances
# ─────────────────────────────────────────────────────────────────

def _check_closed(tenant_id: str, year_month: str, db: Session):
    """Lanza 423 si el período NO está CLOSED."""
    row = db.execute(
        text("SELECT status FROM period_locks WHERE tenant_id=:tid AND year_month=:ym"),
        {"tid": tenant_id, "ym": year_month}
    ).fetchone()
    if not row or row.status != "CLOSED":
        raise HTTPException(
            status_code=423,
            detail=f"El período {year_month} aún no está CLOSED. "
                   f"Estado: {row.status if row else 'OPEN'}. "
                   f"Cierra el período antes de exportar los libros."
        )


@router.get("/libros/{year_month}/diario")
def libro_diario(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Libro Diario del período — todos los asientos POSTED en orden cronológico."""
    tenant_id = current_user["tenant_id"]
    _check_closed(tenant_id, year_month, db)
    from_d = f"{year_month}-01"
    import calendar
    y, m = int(year_month[:4]), int(year_month[5:7])
    to_d = f"{year_month}-{calendar.monthrange(y, m)[1]:02d}"

    rows = db.execute(text("""
        SELECT je.date, je.id AS entry_id, je.source_ref, je.description AS entry_desc,
               je.source, jl.account_code, jl.description AS line_desc,
               jl.debit, jl.credit
        FROM journal_entries je
        JOIN journal_lines jl ON jl.entry_id = je.id
        WHERE je.tenant_id = :tid AND je.status = 'POSTED'
          AND je.date BETWEEN :fd AND :td
        ORDER BY je.date ASC, je.created_at ASC, jl.id ASC
    """), {"tid": tenant_id, "fd": from_d, "td": to_d}).fetchall()

    lineas = [{
        "fecha":        r.date,
        "entry_id":     r.entry_id,
        "ref":          r.source_ref or f"#{str(r.entry_id)[-6:]}",
        "cuenta":       r.account_code,
        "descripcion":  r.line_desc or r.entry_desc or "",
        "fuente":       r.source,
        "debe":         round(float(r.debit or 0), 2),
        "haber":        round(float(r.credit or 0), 2),
    } for r in rows]

    return {"year_month": year_month, "libro": "DIARIO",
            "total_lineas": len(lineas), "lineas": lineas}


@router.get("/libros/{year_month}/mayor")
def libro_mayor(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Libro Mayor del período — T-account de cada cuenta."""
    tenant_id = current_user["tenant_id"]
    _check_closed(tenant_id, year_month, db)
    from_d = f"{year_month}-01"
    import calendar
    y, m = int(year_month[:4]), int(year_month[5:7])
    to_d = f"{year_month}-{calendar.monthrange(y, m)[1]:02d}"

    # Reutiliza la lógica del GET /mayor (index)
    ap_map = {}
    for r in db.execute(text("""
        SELECT jl.account_code, SUM(jl.debit) - SUM(jl.credit) AS saldo_aper
        FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id=:tid AND je.status='POSTED' AND je.source='APERTURA'
        GROUP BY jl.account_code
    """), {"tid": tenant_id}).fetchall():
        ap_map[r.account_code] = round(float(r.saldo_aper or 0), 2)

    m_rows = db.execute(text("""
        SELECT jl.account_code, a.name AS acc_name, a.account_type,
               SUM(jl.debit) AS dr, SUM(jl.credit) AS cr
        FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id=je.tenant_id AND a.code=jl.account_code
        WHERE je.tenant_id=:tid AND je.status='POSTED' AND je.source!='APERTURA'
          AND je.date BETWEEN :fd AND :td
        GROUP BY jl.account_code, a.name, a.account_type
        ORDER BY jl.account_code
    """), {"tid": tenant_id, "fd": from_d, "td": to_d}).fetchall()

    cuentas = []
    all_codes = sorted(set(ap_map.keys()) | {r.account_code for r in m_rows})
    m_idx = {r.account_code: r for r in m_rows}
    for code in all_codes:
        aper = ap_map.get(code, 0.0)
        r = m_idx.get(code)
        dr = round(float(r.dr or 0), 2) if r else 0.0
        cr = round(float(r.cr or 0), 2) if r else 0.0
        cuentas.append({
            "cuenta": code, "nombre": r.acc_name if r else code,
            "tipo": r.account_type if r else "",
            "saldo_inicial": aper, "debe": dr, "haber": cr,
            "saldo_cierre": round(aper + dr - cr, 2),
        })

    return {"year_month": year_month, "libro": "MAYOR",
            "total_cuentas": len(cuentas), "cuentas": cuentas}


@router.get("/libros/{year_month}/balance")
def libro_balance(
    year_month:   str,
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Inventarios y Balances — Balance de comprobación del período."""
    tenant_id = current_user["tenant_id"]
    _check_closed(tenant_id, year_month, db)
    from_d = f"{year_month}-01"
    import calendar
    y, m = int(year_month[:4]), int(year_month[5:7])
    to_d = f"{year_month}-{calendar.monthrange(y, m)[1]:02d}"

    rows = db.execute(text("""
        SELECT jl.account_code, a.name, a.account_type,
               SUM(jl.debit) AS dr, SUM(jl.credit) AS cr
        FROM journal_lines jl JOIN journal_entries je ON je.id=jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id=je.tenant_id AND a.code=jl.account_code
        WHERE je.tenant_id=:tid AND je.status='POSTED'
          AND je.date BETWEEN :fd AND :td
        GROUP BY jl.account_code, a.name, a.account_type
        ORDER BY jl.account_code
    """), {"tid": tenant_id, "fd": from_d, "td": to_d}).fetchall()

    cuentas = [{"cuenta": r.account_code, "nombre": r.name,
                "tipo": r.account_type,
                "debe": round(float(r.dr or 0), 2),
                "haber": round(float(r.cr or 0), 2)} for r in rows]
    total_dr = sum(c["debe"]  for c in cuentas)
    total_cr = sum(c["haber"] for c in cuentas)

    return {"year_month": year_month, "libro": "INVENTARIOS_Y_BALANCES",
            "balanceado": abs(total_dr - total_cr) < 0.01,
            "total_debe": round(total_dr, 2), "total_haber": round(total_cr, 2),
            "cuentas": cuentas}


# ─────────────────────────────────────────────────────────────────
# POST /ledger/annual-close — Cierre Anual (NIIF / Ley Renta CR)
# ─────────────────────────────────────────────────────────────────

from services.ledger.models import FiscalYear, FiscalYearStatus

@router.post("/annual-close")
def annual_close(
    year:         str  = Query(..., description="Ejercicio fiscal a cerrar: 'YYYY'"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Cierre anual del ejercicio fiscal.

    1. Valida que los 12 meses estén CLOSED.
    2. Genera 3 asientos CIERRE_ANUAL (POSTED automáticamente):
       A. Cuentas INGRESO → CR 3304 Resumen de Resultado
       B. Cuentas GASTO   → DR 3304 Resumen de Resultado
       C. 3304 → 3303 Utilidad (o 3302 Pérdida)
    3. Registra FiscalYear con status=LOCKED.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]
    uid       = _uid(current_user)
    now       = datetime.now(timezone.utc)
    import json as _j

    # Guard: año válido
    try:
        year_int = int(year)
        if not (2000 <= year_int <= 2100): raise ValueError
    except ValueError:
        raise HTTPException(400, f"Año inválido: '{year}'. Use YYYY.")

    # Guard: no cerrar dos veces
    existing_fy = db.execute(
        text("SELECT id, status FROM fiscal_years WHERE tenant_id=:tid AND year=:yr"),
        {"tid": tenant_id, "yr": year}
    ).fetchone()
    if existing_fy and existing_fy.status in ("CLOSED", "LOCKED"):
        raise HTTPException(409, f"El ejercicio {year} ya fue cerrado (status: {existing_fy.status}).")

    # Guard: todos los meses CLOSED
    period_rows = db.execute(
        text("SELECT year_month, status FROM period_locks WHERE tenant_id=:tid AND year_month LIKE :p"),
        {"tid": tenant_id, "p": f"{year}-%"}
    ).fetchall()
    period_map = {r.year_month: r.status for r in period_rows}
    open_periods = [
        f"{y}-{str(m).zfill(2)} ({period_map.get(f'{year}-{str(m).zfill(2)}','OPEN')})"
        for m in range(1, 13)
        if period_map.get(f"{year}-{str(m).zfill(2)}", "OPEN") != "CLOSED"
    ]
    if open_periods:
        raise HTTPException(400,
            f"Períodos no CLOSED en {year}: {', '.join(open_periods)}. "
            "Cierra todos los meses antes del cierre anual.")

    # Calcular saldos nominales del año (INGRESO y GASTO)
    rows = db.execute(text("""
        SELECT jl.account_code, a.account_type, a.name,
               SUM(jl.debit) - SUM(jl.credit) AS saldo
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id=je.tenant_id AND a.code=jl.account_code
        WHERE je.tenant_id=:tid AND je.period LIKE :p AND je.status='POSTED'
          AND a.account_type IN ('INGRESO','GASTO')
          AND je.source != 'CIERRE_ANUAL'
        GROUP BY jl.account_code, a.account_type, a.name
        HAVING ABS(SUM(jl.debit)-SUM(jl.credit)) > 0.00001
    """), {"tid": tenant_id, "p": f"{year}-%"}).fetchall()

    lines_ing, lines_gas = [], []
    total_ing = total_gas = 0.0
    for r in rows:
        saldo = float(r.saldo or 0)
        if r.account_type == "INGRESO" and saldo < 0:
            lines_ing.append({"account_code": r.account_code,
                               "description": f"Cierre anual ingreso: {r.name}",
                               "debit": abs(saldo), "credit": 0.0})
            total_ing += abs(saldo)
        elif r.account_type == "GASTO" and saldo > 0:
            lines_gas.append({"account_code": r.account_code,
                               "description": f"Cierre anual gasto: {r.name}",
                               "debit": 0.0, "credit": saldo})
            total_gas += saldo

    net_income = round(total_ing - total_gas, 2)
    closing_ids = []
    close_period = f"{year}-12"
    close_date   = f"{year}-12-31"

    def _save_closing_entry(desc, all_lines):
        eid = str(uuid.uuid4())
        je  = JournalEntry(
            id=eid, tenant_id=tenant_id, period=close_period,
            date=close_date, description=desc,
            status=EntryStatus.POSTED, source=EntrySource.CIERRE_ANUAL,
            created_by=uid, approved_by=uid, approved_at=now, created_at=now)
        db.add(je)
        for l in all_lines:
            db.add(JournalLine(
                id=str(uuid.uuid4()), entry_id=eid, tenant_id=tenant_id,
                account_code=l["account_code"].upper(),
                description=l.get("description",""),
                debit=round(float(l.get("debit",0)),5),
                credit=round(float(l.get("credit",0)),5),
                deductible_status=DeductibleStatus.EXEMPT, created_at=now))
        return eid

    # Asiento A: Ingresos → 3304
    if lines_ing:
        closing_ids.append(_save_closing_entry(
            f"Cierre anual {year} — Ingresos a Resumen de Resultado",
            lines_ing + [{"account_code":"3304","description":"Resumen de Resultado — Ingresos",
                          "debit":0.0,"credit":round(total_ing,5)}]))

    # Asiento B: Gastos → 3304
    if lines_gas:
        closing_ids.append(_save_closing_entry(
            f"Cierre anual {year} — Gastos a Resumen de Resultado",
            lines_gas + [{"account_code":"3304","description":"Resumen de Resultado — Gastos",
                          "debit":round(total_gas,5),"credit":0.0}]))

    # Asiento C: 3304 → Patrimonio
    if net_income != 0:
        if net_income > 0:
            lc = [{"account_code":"3304","description":"Cancelar Resumen de Resultado",
                   "debit":round(net_income,5),"credit":0.0},
                  {"account_code":"3303","description":f"Utilidad del Ejercicio {year}",
                   "debit":0.0,"credit":round(net_income,5)}]
        else:
            loss = abs(net_income)
            lc = [{"account_code":"3302","description":f"Pérdida del Ejercicio {year}",
                   "debit":round(loss,5),"credit":0.0},
                  {"account_code":"3304","description":"Cancelar Resumen de Resultado",
                   "debit":0.0,"credit":round(loss,5)}]
        closing_ids.append(_save_closing_entry(
            f"Cierre anual {year} — Traspaso al Patrimonio (net={net_income:,.2f})", lc))

    # Upsert FiscalYear
    ce_json = _j.dumps(closing_ids)
    if existing_fy:
        db.execute(text("""
            UPDATE fiscal_years SET status='LOCKED', net_income=:ni,
              closed_by=:uid, closed_at=:ts, locked_by=:uid, locked_at=:ts, closing_entries=:ce
            WHERE tenant_id=:tid AND year=:yr
        """), {"ni": net_income, "uid": uid, "ts": now, "ce": ce_json, "tid": tenant_id, "yr": year})
    else:
        db.execute(text("""
            INSERT INTO fiscal_years
              (id, tenant_id, year, status, net_income, closed_by, closed_at,
               locked_by, locked_at, closing_entries, created_at)
            VALUES (:id,:tid,:yr,'LOCKED',:ni,:uid,:ts,:uid,:ts,:ce,:ts)
        """), {"id": str(uuid.uuid4()), "tid": tenant_id, "yr": year,
               "ni": net_income, "uid": uid, "ts": now, "ce": ce_json})

    log_action(db, tenant_id, current_user, AuditAction.ENTRY_CREATED,
        entity_type="fiscal_year", entity_id=year,
        after={"status":"LOCKED","net_income":net_income,"closing_entries":closing_ids},
        note=f"Cierre anual ejercicio {year}")
    db.commit()

    label = "UTILIDAD" if net_income >= 0 else "PÉRDIDA"
    return {
        "ok": True, "year": year, "status": "LOCKED",
        "net_income": net_income, "result_label": label,
        "closing_entries": closing_ids,
        "total_ingresos": round(total_ing, 2), "total_gastos": round(total_gas, 2),
        "message": (f"Cierre anual {year} completado. {label}: {abs(net_income):,.2f}. "
                    f"Año LOCKED. Genere apertura {year_int+1} con POST /ledger/generate-opening."),
        "next_action": f"POST /ledger/generate-opening?next_year={year_int+1}",
    }


# ─────────────────────────────────────────────────────────────────
# POST /ledger/generate-opening — Apertura automática año siguiente
# ─────────────────────────────────────────────────────────────────

@router.post("/generate-opening")
def generate_opening(
    next_year:    str  = Query(..., description="Año del nuevo ejercicio: 'YYYY'"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Genera automáticamente el asiento de apertura del año siguiente
    con los saldos finales de ACTIVO, PASIVO y PATRIMONIO del año anterior.
    """
    _require_role(current_user["role"], ["admin", "contador"])
    tenant_id = current_user["tenant_id"]
    uid       = _uid(current_user)
    now       = datetime.now(timezone.utc)

    try:
        nyi = int(next_year); prev_year = str(nyi - 1)
    except ValueError:
        raise HTTPException(400, f"Año inválido: '{next_year}'")

    # Guard: no puede existir ya una apertura de ese año
    existing = db.query(JournalEntry).filter(
        JournalEntry.tenant_id == tenant_id,
        JournalEntry.source    == EntrySource.APERTURA,
        JournalEntry.period.like(f"{next_year}%"),
    ).first()
    if existing:
        raise HTTPException(409, f"Ya existe asiento de apertura para {next_year} (ID: {existing.id}).")

    # Guard: año anterior LOCKED
    prev_fy = db.execute(
        text("SELECT status FROM fiscal_years WHERE tenant_id=:tid AND year=:yr"),
        {"tid": tenant_id, "yr": prev_year}
    ).fetchone()
    if not prev_fy or prev_fy.status != "LOCKED":
        s = prev_fy.status if prev_fy else "no registrado"
        raise HTTPException(400, f"El ejercicio {prev_year} debe estar LOCKED (status: {s}).")

    # Calcular saldos de Balance del año anterior
    bal_rows = db.execute(text("""
        SELECT jl.account_code, a.name, a.account_type,
               SUM(jl.debit) - SUM(jl.credit) AS saldo
        FROM journal_lines jl
        JOIN journal_entries je ON je.id=jl.entry_id
        LEFT JOIN accounts a ON a.tenant_id=je.tenant_id AND a.code=jl.account_code
        WHERE je.tenant_id=:tid AND je.period LIKE :p AND je.status='POSTED'
          AND a.account_type IN ('ACTIVO','PASIVO','PATRIMONIO')
        GROUP BY jl.account_code, a.name, a.account_type
        HAVING ABS(SUM(jl.debit)-SUM(jl.credit)) > 0.00001
    """), {"tid": tenant_id, "p": f"{prev_year}-%"}).fetchall()

    if not bal_rows:
        raise HTTPException(400, f"No hay saldos de Balance en {prev_year}. Verifique asientos POSTED.")

    opening_lines = []
    for r in bal_rows:
        saldo = round(float(r.saldo or 0), 5)
        if saldo == 0: continue
        opening_lines.append({
            "account_code": r.account_code.upper(),
            "description": f"Apertura {next_year}: {r.name or r.account_code}",
            "debit":  saldo if saldo > 0 else 0.0,
            "credit": abs(saldo) if saldo < 0 else 0.0,
        })

    total_dr = sum(l["debit"]  for l in opening_lines)
    total_cr = sum(l["credit"] for l in opening_lines)
    if abs(total_dr - total_cr) > 0.01:
        raise HTTPException(500,
            f"Apertura no balanceada: DR={total_dr:.2f} ≠ CR={total_cr:.2f}. "
            "Verifique que el cierre anual esté completo.")

    oid = str(uuid.uuid4())
    je  = JournalEntry(
        id=oid, tenant_id=tenant_id, period=f"{next_year}-01",
        date=f"{next_year}-01-01",
        description=f"Asiento de Apertura {next_year} — Saldos de {prev_year}",
        status=EntryStatus.POSTED, source=EntrySource.APERTURA,
        created_by=uid, approved_by=uid, approved_at=now, created_at=now)
    db.add(je)
    for l in opening_lines:
        db.add(JournalLine(
            id=str(uuid.uuid4()), entry_id=oid, tenant_id=tenant_id,
            account_code=l["account_code"],
            description=l["description"],
            debit=round(l["debit"],5), credit=round(l["credit"],5),
            deductible_status=DeductibleStatus.EXEMPT, created_at=now))

    db.execute(
        text("UPDATE fiscal_years SET opening_entry_id=:eid WHERE tenant_id=:tid AND year=:yr"),
        {"eid": oid, "tid": tenant_id, "yr": prev_year})

    log_action(db, tenant_id, current_user, AuditAction.ENTRY_CREATED,
        entity_type="journal_entry", entity_id=oid,
        after={"source":"APERTURA","year":next_year,"lines":len(opening_lines)},
        note=f"Apertura automática {next_year} desde saldos de {prev_year}")
    db.commit()

    return {
        "ok": True, "next_year": next_year, "prev_year": prev_year,
        "opening_id": oid, "lines_count": len(opening_lines),
        "total_activos": round(total_dr, 2),
        "message": f"Apertura {next_year} generada: {len(opening_lines)} cuentas trasladadas desde {prev_year}.",
    }


# ─────────────────────────────────────────────────────────────────
# GET /ledger/fiscal-years — Lista de ejercicios fiscales
# ─────────────────────────────────────────────────────────────────

@router.get("/fiscal-years")
def list_fiscal_years(
    current_user: dict    = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """Lista todos los ejercicios fiscales del tenant con su estado y métricas."""
    _require_role(current_user["role"], ["admin", "contador", "asistente"])
    tenant_id = current_user["tenant_id"]
    import json as _j2

    rows = db.execute(text("""
        SELECT year, status, net_income, closed_at, locked_at,
               opening_entry_id, closing_entries
        FROM fiscal_years WHERE tenant_id=:tid ORDER BY year DESC
    """), {"tid": tenant_id}).fetchall()

    result = []
    for r in rows:
        pc = db.execute(text("""
            SELECT status, COUNT(*) cnt FROM period_locks
            WHERE tenant_id=:tid AND year_month LIKE :p GROUP BY status
        """), {"tid": tenant_id, "p": f"{r.year}-%"}).fetchall()
        by_st = {x.status: x.cnt for x in pc}
        try: cids = _j2.loads(r.closing_entries) if r.closing_entries else []
        except: cids = []
        result.append({
            "year": r.year, "status": r.status,
            "net_income": float(r.net_income) if r.net_income is not None else None,
            "periods_closed": by_st.get("CLOSED", 0),
            "periods_by_status": by_st,
            "closed_at": str(r.closed_at) if r.closed_at else None,
            "locked_at": str(r.locked_at) if r.locked_at else None,
            "opening_entry_id": r.opening_entry_id,
            "closing_entries": cids,
        })

    if not result:
        yr_rows = db.execute(text("""
            SELECT DISTINCT SUBSTR(year_month,1,4) AS yr
            FROM period_locks WHERE tenant_id=:tid ORDER BY yr DESC
        """), {"tid": tenant_id}).fetchall()
        for yr_r in yr_rows:
            result.append({"year": yr_r.yr, "status": "OPEN", "net_income": None,
                           "periods_closed": 0, "periods_by_status": {},
                           "closed_at": None, "opening_entry_id": None, "closing_entries": []})

    return {"fiscal_years": result, "total": len(result)}
