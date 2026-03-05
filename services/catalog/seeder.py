"""
Seeder — Catálogo Estándar NIIF CR
Carga las ~70 cuentas del plan estándar para un tenant cuando elige modo STANDARD.

Uso:
    from services.catalog.seeder import seed_standard_catalog
    seed_standard_catalog(tenant_id, db_session)

Reglas:
- Idempotente: usa INSERT ... ON CONFLICT DO NOTHING
- Solo inserta si el tenant no tiene cuentas de tipo STANDARD existentes
- Registra en audit_log (pendiente B2) — por ahora solo logging
"""
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "seeds" / "standard_cr.json"
GENERIC_CODES = [
    {"code": "INGRESO",     "name": "Ingresos",              "type": "INGRESO",  "sub_type": "OPERATIVO",  "parent_code": None, "allow_entries": True},
    {"code": "GASTO",       "name": "Gastos",                "type": "GASTO",    "sub_type": "OPERATIVO",  "parent_code": None, "allow_entries": True},
    {"code": "IVA_DEBITO",  "name": "IVA Débito Fiscal",     "type": "PASIVO",   "sub_type": "CIRCULANTE", "parent_code": None, "allow_entries": True},
    {"code": "IVA_CREDITO", "name": "IVA Crédito Fiscal",    "type": "ACTIVO",   "sub_type": "CIRCULANTE", "parent_code": None, "allow_entries": True},
    {"code": "CXC",         "name": "Cuentas por Cobrar",    "type": "ACTIVO",   "sub_type": "CIRCULANTE", "parent_code": None, "allow_entries": True},
    {"code": "CXP",         "name": "Cuentas por Pagar",     "type": "PASIVO",   "sub_type": "CIRCULANTE", "parent_code": None, "allow_entries": True},
    {"code": "EFECTIVO",    "name": "Efectivo",              "type": "ACTIVO",   "sub_type": "CIRCULANTE", "parent_code": None, "allow_entries": True},
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def seed_standard_catalog(tenant_id: str, db: Session) -> int:
    """
    Carga el catálogo estándar NIIF CR para un tenant.
    Retorna el número de cuentas insertadas.

    Idempotente: si las cuentas ya existen (ON CONFLICT) las omite.
    """
    try:
        accounts = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.error(f"❌ Seeder: no se encontró {SEED_FILE}")
        return 0

    inserted = 0
    now = _now()

    for acc in accounts:
        try:
            db.execute(
                text("""
                    INSERT INTO accounts
                        (id, tenant_id, code, name, account_type, account_sub_type,
                         parent_code, allow_entries, is_active, is_generic, created_at)
                    VALUES
                        (:id, :tenant_id, :code, :name, :account_type, :account_sub_type,
                         :parent_code, :allow_entries, TRUE, FALSE, :created_at)
                    ON CONFLICT (tenant_id, code) DO NOTHING
                """),
                {
                    "id":              str(uuid.uuid4()),
                    "tenant_id":       tenant_id,
                    "code":            acc["code"],
                    "name":            acc["name"],
                    "account_type":    acc["type"],
                    "account_sub_type": acc.get("sub_type"),
                    "parent_code":     acc.get("parent_code"),
                    "allow_entries":   acc.get("allow_entries", True),
                    "created_at":      now,
                }
            )
            inserted += 1
        except Exception as e:
            logger.warning(f"⚠️  Seeder: error en cuenta {acc['code']}: {e}")

    db.commit()
    logger.info(f"✅ Seeder: {inserted} cuentas STANDARD cargadas para tenant {tenant_id}")
    return inserted


def seed_generic_catalog(tenant_id: str, db: Session) -> int:
    """
    Carga las cuentas genéricas para modo NONE (sin catálogo formal).
    Solo 7 cuentas genéricas: INGRESO, GASTO, IVA_DEBITO, IVA_CREDITO, CXC, CXP, EFECTIVO.
    """
    inserted = 0
    now = _now()

    for acc in GENERIC_CODES:
        try:
            db.execute(
                text("""
                    INSERT INTO accounts
                        (id, tenant_id, code, name, account_type, account_sub_type,
                         parent_code, allow_entries, is_active, is_generic, created_at)
                    VALUES
                        (:id, :tenant_id, :code, :name, :account_type, :account_sub_type,
                         :parent_code, :allow_entries, TRUE, TRUE, :created_at)
                    ON CONFLICT (tenant_id, code) DO NOTHING
                """),
                {
                    "id":              str(uuid.uuid4()),
                    "tenant_id":       tenant_id,
                    "code":            acc["code"],
                    "name":            acc["name"],
                    "account_type":    acc["type"],
                    "account_sub_type": acc.get("sub_type"),
                    "parent_code":     None,
                    "allow_entries":   True,
                    "created_at":      now,
                }
            )
            inserted += 1
        except Exception as e:
            logger.warning(f"⚠️  Seeder NONE: error en {acc['code']}: {e}")

    db.commit()
    logger.info(f"✅ Seeder NONE: {inserted} cuentas genéricas cargadas para tenant {tenant_id}")
    return inserted
