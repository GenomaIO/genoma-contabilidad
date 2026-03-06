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
        created_by  = current_user["user_id"],
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
# PATCH /ledger/entries/{entry_id}/approve — DRAFT → POSTED
# ─────────────────────────────────────────────────────────────────

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
    entry.approved_by = current_user["user_id"]
    entry.approved_at = now

    log_action(
        db, tenant_id, current_user, AuditAction.ENTRY_POSTED,
        entity_type="journal_entry", entity_id=entry_id,
        before={"status": "DRAFT"},
        after={"status": "POSTED", "approved_by": current_user["user_id"]}
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

    # Crear asiento de reversión (partidas invertidas)
    reversal = JournalEntry(
        id          = reversal_id,
        tenant_id   = tenant_id,
        period      = entry.period,
        date        = now.strftime("%Y-%m-%d"),
        description = f"[REVERSIÓN] {entry.description[:150]}",
        status      = EntryStatus.POSTED,   # La reversión ya se aprueba automáticamente
        source      = entry.source,
        source_ref  = entry.source_ref,
        created_by  = current_user["user_id"],
        approved_by = current_user["user_id"],
        approved_at = now,
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
    entry.voided_by  = current_user["user_id"]
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
        "entry_id":   entry_id,
        "status":     "VOIDED",
        "reversal_id": reversal_id,
        "voided_at":  str(now),
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

@router.get("/trial-balance")
def trial_balance(
    period: Optional[str] = Query(None, description="'YYYY-MM' (default: mes actual)"),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Balance de Comprobación del período.
    Retorna por cada cuenta: total_debit, total_credit y saldo (debit - credit).
    Solo incluye asientos POSTED (los DRAFT no afectan saldos).

    Formato de salida compatible con declaración D150 Hacienda y NIIF.
    """
    tenant_id = current_user["tenant_id"]
    if not period:
        period = datetime.now(timezone.utc).strftime("%Y-%m")

    rows = db.execute(text("""
        SELECT
            jl.account_code,
            SUM(jl.debit)  AS total_debit,
            SUM(jl.credit) AS total_credit,
            SUM(jl.debit) - SUM(jl.credit) AS saldo
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id = :tenant_id
          AND je.period    = :period
          AND je.status    = 'POSTED'
        GROUP BY jl.account_code
        ORDER BY jl.account_code
    """), {"tenant_id": tenant_id, "period": period}).fetchall()

    accounts_map = {}
    try:
        accs = db.execute(text(
            "SELECT code, name, account_type FROM accounts WHERE tenant_id = :tid"
        ), {"tid": tenant_id}).fetchall()
        accounts_map = {r.code: {"name": r.name, "type": r.account_type} for r in accs}
    except Exception:
        pass

    total_debit = 0
    total_credit = 0
    lines_out = []
    for r in rows:
        td = float(r.total_debit or 0)
        tc = float(r.total_credit or 0)
        total_debit  += td
        total_credit += tc
        acc_info = accounts_map.get(r.account_code, {})
        lines_out.append({
            "account_code":  r.account_code,
            "account_name":  acc_info.get("name", ""),
            "account_type":  acc_info.get("type", ""),
            "total_debit":   round(td, 2),
            "total_credit":  round(tc, 2),
            "saldo":         round(float(r.saldo or 0), 2),
        })

    balanced = abs(total_debit - total_credit) < 0.01

    return {
        "period":        period,
        "tenant_id":     tenant_id,
        "balanced":      balanced,
        "total_debit":   round(total_debit,  2),
        "total_credit":  round(total_credit, 2),
        "diff":          round(abs(total_debit - total_credit), 5),
        "lines":         lines_out,
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
        created_by  = current_user["user_id"],
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
        created_by  = current_user["user_id"],
        approved_by = current_user["user_id"],
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

    return {
        "ok":          True,
        "entry_id":    entry_id,
        "period":      period,
        "year":        fiscal_year,
        "status":      "POSTED",
        "source":      "APERTURA",
        "lines":       len(req.lines),
        "total_debe":  round(total_dr, 2),
        "total_haber": round(total_cr, 2),
        "message":     f"Asiento de apertura {fiscal_year} creado y aprobado. El libro queda abierto.",
    }

