"""
services/assets/depreciation.py
═══════════════════════════════════════════════════════════════════════
Auto-Depreciación Mensual — Startup Recovery Pattern
═══════════════════════════════════════════════════════════════════════

Lógica pura sin JWT ni FastAPI deps. Se invoca desde:
  1. Lifespan de main.py al arrancar (startup recovery)
  2. Endpoint POST /jobs/monthly-depreciation (trigger manual/Render Cron)

Técnica contable (NIIF):
  DR  Gasto Depreciación   (dep_gasto_code)   cuota_mensual
  CR  Dep. Acumulada        (dep_acum_code)    cuota_mensual

Fecha del asiento = ÚLTIMO día del mes (art. 55 NIIF para PYMES).
El asiento siempre se crea como DRAFT para revisión del contador.
"""

import logging
import calendar
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("genoma.depreciation")


# ── helpers ──────────────────────────────────────────────────────────

def _last_day_of_month(period: str) -> str:
    """'2026-01' → '2026-01-31'  (último día real del mes)."""
    y, m = map(int, period.split("-"))
    last = calendar.monthrange(y, m)[1]
    return f"{y}-{m:02d}-{last}"


def _gen_uuid_sql() -> str:
    """Genera un UUID v4 en Python (no requiere gen_random_uuid de Postgres)."""
    import uuid
    return str(uuid.uuid4())


def _months_range(start: str, end_excl: str):
    """
    Genera lista de períodos ['2026-01', '2026-02', ...] desde start
    hasta end_excl (exclusivo).

    start, end_excl → formato 'YYYY-MM'
    """
    sy, sm = map(int, start.split("-"))
    ey, em = map(int, end_excl.split("-"))
    periods = []
    y, m = sy, sm
    while (y, m) < (ey, em):
        periods.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return periods


# ── core: depreciar UN activo en UN período ──────────────────────────

def _depreciate_asset(db: Session, asset_row: dict, period: str) -> Optional[dict]:
    """
    Genera el asiento DRAFT de depreciación para un activo en un período.
    Devuelve dict con info o None si ya existe / no aplica.

    asset_row: dict con keys {id, tenant_id, nombre, cuota_mensual,
                               dep_gasto_code, dep_acum_code}
    """
    tid           = asset_row["tenant_id"]
    asset_id      = asset_row["id"]
    nombre        = asset_row["nombre"]
    cuota         = float(asset_row["cuota_mensual"] or 0)
    gasto_code    = asset_row["dep_gasto_code"]
    acum_code     = asset_row["dep_acum_code"]

    if cuota <= 0:
        logger.debug(f"Activo {nombre} [{asset_id}] cuota=0 — omitido")
        return None

    # Idempotencia: ¿ya existe un asiento DEPRECIACION para este activo/período?
    existing = db.execute(text("""
        SELECT je.id FROM journal_entries je
        WHERE je.tenant_id = :tid
          AND je.period     = :period
          AND je.source     = 'DEPRECIACION'
          AND je.status    != 'VOIDED'
          AND EXISTS (
              SELECT 1 FROM journal_lines jl
              WHERE jl.entry_id     = je.id
                AND jl.tenant_id   = :tid
                AND jl.account_code = :gasto_code
          )
        LIMIT 1
    """), {"tid": tid, "period": period, "gasto_code": gasto_code}).first()

    if existing:
        logger.debug(f"Dep {nombre} {period} ya existe — omitido")
        return None

    # Último día del mes para cumplir NIIF para PYMES
    entry_date = _last_day_of_month(period)
    entry_id   = _gen_uuid_sql()
    line1_id   = _gen_uuid_sql()
    line2_id   = _gen_uuid_sql()
    desc       = f"Depreciación {nombre} — {period}"
    system_uid = "SYSTEM_AUTODEP"

    # Insertar asiento
    db.execute(text("""
        INSERT INTO journal_entries
            (id, tenant_id, period, date, description, status, source, created_by, created_at)
        VALUES
            (:id, :tid, :period, :date, :desc, 'DRAFT', 'DEPRECIACION', :uid, NOW())
    """), {
        "id": entry_id, "tid": tid, "period": period,
        "date": entry_date, "desc": desc, "uid": system_uid,
    })

    # DR  Gasto Depreciación
    db.execute(text("""
        INSERT INTO journal_lines
            (id, entry_id, tenant_id, account_code, description, debit, credit, created_at)
        VALUES (:id, :eid, :tid, :code, :desc, :amt, 0, NOW())
    """), {
        "id": line1_id, "eid": entry_id, "tid": tid,
        "code": gasto_code, "desc": desc, "amt": cuota,
    })

    # CR  Depreciación Acumulada
    db.execute(text("""
        INSERT INTO journal_lines
            (id, entry_id, tenant_id, account_code, description, debit, credit, created_at)
        VALUES (:id, :eid, :tid, :code, :desc, 0, :amt, NOW())
    """), {
        "id": line2_id, "eid": entry_id, "tid": tid,
        "code": acum_code, "desc": desc, "amt": cuota,
    })

    logger.info(
        f"✅ Dep AUTO {nombre} [{tid[:8]}] {period} "
        f"DR {gasto_code} CR {acum_code} ¢{cuota:,.0f}"
    )
    return {
        "entry_id": entry_id,
        "asset_id": asset_id,
        "tenant_id": tid,
        "period": period,
        "nombre": nombre,
        "cuota": cuota,
    }


# ── auto_depreciate_period: todos los tenants / UN período ───────────

def auto_depreciate_period(db: Session, period: str) -> dict:
    """
    Genera los asientos de depreciación para TODOS los tenants y activos
    activos en el período dado.

    Idempotente: seguros de llamar múltiples veces.
    Devuelve resumen {created, skipped, errors}.
    """
    logger.info(f"🔄 Auto-Depreciación periodo {period}...")

    # Activos ACTIVOS con cuota > 0 de todos los tenants
    rows = db.execute(text("""
        SELECT
            id, tenant_id, nombre,
            dep_gasto_code, dep_acum_code,
            cuota_mensual
        FROM fixed_assets
        WHERE estado = 'ACTIVO'
          AND cuota_mensual > 0
        ORDER BY tenant_id, nombre
    """)).fetchall()

    created = 0
    skipped = 0
    errors  = []

    for row in rows:
        asset = dict(row._mapping)
        try:
            result = _depreciate_asset(db, asset, period)
            if result:
                created += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"asset": asset.get("nombre"), "error": str(exc)})
            logger.error(f"❌ Dep {asset.get('nombre')} {period}: {exc}")

    if created > 0:
        db.commit()

    logger.info(
        f"📊 Dep {period}: {created} creados, {skipped} omitidos, {len(errors)} errores"
    )
    return {"period": period, "created": created, "skipped": skipped, "errors": errors}


# ── startup_recovery: detecta meses sin cobertura ────────────────────

def startup_depreciation_recovery(db: Session) -> list[dict]:
    """
    Llamar al arrancar el servidor.

    Convención:
      - Busca el asiento de Apertura para conocer el primer período
      - Genera depreciación para todos los meses desde apertura
        hasta el mes ANTERIOR AL ACTUAL (inclusive)
      - Idempotente: omite los que ya existen

    Con esto, entrando en Marzo 2026 se garantiza que
    Enero 2026 y Febrero 2026 tienen sus asientos de depreciación.
    """
    from datetime import date

    today = date.today()
    current_ym = f"{today.year}-{today.month:02d}"

    # ── Encontrar el primer período (Apertura o primer journal_entry) ─
    opening = db.execute(text("""
        SELECT MIN(period) AS first_period
        FROM journal_entries
        WHERE source = 'APERTURA'
          AND status  = 'POSTED'
    """)).first()

    if not opening or not opening.first_period:
        # Fallback: primer asiento de cualquier tipo
        any_entry = db.execute(text("""
            SELECT MIN(period) AS first_period FROM journal_entries
        """)).first()
        if not any_entry or not any_entry.first_period:
            logger.info("Startup DEP: sin asientos previos — nada que recuperar")
            return []

    first_period = (opening.first_period
                    if (opening and opening.first_period)
                    else any_entry.first_period)

    # Genera lista de meses a cubrir (excluye mes actual — aún no terminó)
    periods = _months_range(first_period, current_ym)

    if not periods:
        logger.info("Startup DEP: ningún período de recuperación")
        return []

    logger.info(
        f"🔄 Startup DEP Recovery: {first_period} → {periods[-1]} "
        f"({len(periods)} períodos)"
    )

    results = []
    for p in periods:
        try:
            r = auto_depreciate_period(db, p)
            if r["created"] > 0:
                results.append(r)
        except Exception as exc:
            logger.error(f"Startup DEP {p}: {exc}")

    return results
