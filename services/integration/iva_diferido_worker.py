"""
services/integration/iva_diferido_worker.py
═══════════════════════════════════════════════════════════════════
Worker: Vencimiento IVA Diferido (Condición 11, Art.17 Ley IVA 9635)

Responsabilidades:
  1. Detectar registros IvaDiferido con estado='PENDIENTE' y vencimiento <= hoy
  2. Por cada uno: generar JournalEntry DRAFT con DR 2108 → CR 2102
  3. Marcar el registro como EJECUTADO

Diseño sin ORM externo (usa dicts puros + SQLAlchemy text) para
poder correr en SIMs sin la pila completa de FastAPI.

Se puede invocar desde:
  - APScheduler (bgworker existente) → una vez al día
  - Endpoint manual /integration/run-iva-diferido-check (admin)
  - Tests SIM directamente
"""
import uuid
import logging
from datetime import datetime, timezone, date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cuentas hardcoded — solo IVA Diferido involucra estas dos ─────────
CUENTA_IVA_DIFERIDO = "2108"
CUENTA_IVA_DEBITO   = "2102"
DIAS_VENCIMIENTO    = 90


# ──────────────────────────────────────────────────────────────────────
# Capa de tracking: alta y consulta de registros iva_diferidos
# ──────────────────────────────────────────────────────────────────────

def registrar_iva_diferido(
    db,
    tenant_id:   str,
    entry_id:    str,
    source_ref:  str,    # clave Hacienda
    fecha_doc:   str,    # YYYY-MM-DD
    monto_iva:   float,
) -> dict:
    """
    Registra un IVA diferido cuando se importa un doc con condicion=11.
    Retorna el registro creado como dict.
    """
    from datetime import date as _date
    try:
        fecha_d     = _date.fromisoformat(fecha_doc)
    except Exception:
        fecha_d     = _date.today()
    vencimiento = fecha_d + timedelta(days=DIAS_VENCIMIENTO)

    record = {
        "id":             str(uuid.uuid4()),
        "tenant_id":      tenant_id,
        "entry_id":       entry_id,
        "source_ref":     source_ref,
        "fecha_doc":      str(fecha_d),
        "vencimiento":    str(vencimiento),
        "monto_iva":      round(monto_iva, 5),
        "cuenta_origen":  CUENTA_IVA_DIFERIDO,
        "cuenta_destino": CUENTA_IVA_DEBITO,
        "estado":         "PENDIENTE",
        "entry_id_cierre": None,
        "created_at":     datetime.now(timezone.utc).isoformat(),
    }
    logger.info(
        f"📋 IVA Diferido registrado: tenant={tenant_id[:8]} "
        f"ref={source_ref[:12]} monto={monto_iva} vence={vencimiento}"
    )
    return record


def _get_vencidos(db, today: Optional[date] = None) -> list:
    """
    Consulta la tabla iva_diferidos para obtener registros vencidos.
    En SIMs, `db` puede ser una lista de dicts (no DB real).
    """
    if today is None:
        today = date.today()

    # SIM/test: db es lista de dicts
    if isinstance(db, list):
        return [
            r for r in db
            if r.get("estado") == "PENDIENTE"
            and date.fromisoformat(r["vencimiento"]) <= today
        ]

    # Producción: SQLAlchemy
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT id, tenant_id, entry_id, source_ref, fecha_doc,
               vencimiento, monto_iva, cuenta_origen, cuenta_destino
        FROM iva_diferidos
        WHERE estado = 'PENDIENTE'
          AND vencimiento <= :today
        ORDER BY vencimiento ASC
    """), {"today": str(today)}).fetchall()
    return [dict(r._mapping) for r in rows]


def _marcar_ejecutado(db, record_id: str, entry_id_cierre: str):
    """Actualiza el estado del registro a EJECUTADO."""
    if isinstance(db, list):
        for r in db:
            if r["id"] == record_id:
                r["estado"] = "EJECUTADO"
                r["entry_id_cierre"] = entry_id_cierre
        return

    from sqlalchemy import text
    db.execute(text("""
        UPDATE iva_diferidos
        SET estado='EJECUTADO', entry_id_cierre=:eid
        WHERE id=:rid
    """), {"eid": entry_id_cierre, "rid": record_id})
    db.commit()


# ──────────────────────────────────────────────────────────────────────
# Motor principal del worker
# ──────────────────────────────────────────────────────────────────────

def run_iva_diferido_check(
    db,
    today: Optional[date] = None,
    auto_post: bool = False,   # False=DRAFT (contador aprueba), True=auto-posteado
) -> dict:
    """
    Punto de entrada del worker.

    Detecta IVA Diferidos vencidos y genera los asientos de cierre.
    Retorna un dict con estadísticas del run.

    Args:
        db:        Session de SQLAlchemy o lista de dicts (para SIMs).
        today:     Fecha de referencia (default=hoy). Inyectable en tests.
        auto_post: Si True, el entry generado queda POSTED (sin revisión).
                   Default False → DRAFT (contador aprueba).

    Asiento generado por cada vencido:
        DR 2108  IVA Diferido   (reversa del diferido original)
        CR 2102  IVA por Pagar  (lo que ahora se le debe a Hacienda)
    """
    if today is None:
        today = date.today()

    vencidos = _get_vencidos(db, today)
    generados = []
    errores   = []

    for rec in vencidos:
        try:
            entry_id_cierre = str(uuid.uuid4())
            monto_iva       = float(rec["monto_iva"])
            tenant_id       = rec["tenant_id"]
            source_ref      = rec.get("source_ref", "?")

            # Armar las líneas del asiento de cierre
            linea_dr = {
                "id":           str(uuid.uuid4()),
                "entry_id":     entry_id_cierre,
                "tenant_id":    tenant_id,
                "account_code": CUENTA_IVA_DIFERIDO,  # 2108
                "description":  f"IVA Diferido → Exigible · {source_ref[:20]}",
                "debit":        round(monto_iva, 5),
                "credit":       0.0,
                "deductible_status": "EXEMPT",
                "legal_basis":  "Art. 17 Ley IVA 9635 — 90 días vencidos",
                "account_role": "IVA_DIFERIDO_REV",
                "created_at":   datetime.now(timezone.utc),
            }
            linea_cr = {
                "id":           str(uuid.uuid4()),
                "entry_id":     entry_id_cierre,
                "tenant_id":    tenant_id,
                "account_code": CUENTA_IVA_DEBITO,    # 2102
                "description":  f"IVA Exigible (90d) · {source_ref[:20]}",
                "debit":        0.0,
                "credit":       round(monto_iva, 5),
                "deductible_status": "EXEMPT",
                "legal_basis":  "Art. 17 Ley IVA 9635 — 90 días vencidos",
                "account_role": "IVA_DEBITO",
                "created_at":   datetime.now(timezone.utc),
            }

            entry_cierre = {
                "id":          entry_id_cierre,
                "tenant_id":   tenant_id,
                "date":        str(today),
                "description": f"Vencimiento IVA Diferido 90d · {source_ref[:30]}",
                "status":      "POSTED" if auto_post else "DRAFT",
                "source":      "SISTEMA_IVA_DIFERIDO",
                "source_ref":  f"IVA90D-{source_ref[:20]}",
                "lines":       [linea_dr, linea_cr],
            }

            _marcar_ejecutado(db, rec["id"], entry_id_cierre)

            generados.append({
                "record_id":       rec["id"],
                "entry_id_cierre": entry_id_cierre,
                "tenant_id":       tenant_id,
                "source_ref":      source_ref,
                "monto_iva":       monto_iva,
                "entry":           entry_cierre,
            })
            logger.info(
                f"✅ IVA Diferido cerrado: {source_ref[:15]} "
                f"→ entry {entry_id_cierre[:8]} (monto={monto_iva})"
            )

        except Exception as ex:
            errores.append({"record_id": rec.get("id"), "error": str(ex)})
            logger.error(f"❌ Error cerrando IVA diferido {rec.get('id')}: {ex}")

    return {
        "run_date":  str(today),
        "vencidos":  len(vencidos),
        "generados": len(generados),
        "errores":   len(errores),
        "detalle":   generados,
        "errores_detalle": errores,
    }
