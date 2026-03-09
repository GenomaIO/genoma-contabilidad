"""
Catálogo de Cuentas — Modelo SQLAlchemy
Genoma Contabilidad · Plan de Cuentas NIIF CR

Reglas de Oro:
- tenant_id en TODA tabla (jamás hardcodeado)
- DECIMAL(18,5) para montos, nunca FLOAT
- No DELETE — solo is_active=False
- allow_entries=False en cuentas-grupo (solo agrupan, no reciben asientos)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Boolean, DateTime, Enum, Text,
    ForeignKeyConstraint, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base
import enum

from services.auth.models import Base   # Comparte la misma Base para create_all


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class AccountType(str, enum.Enum):
    """Tipo raíz del plan de cuentas CR (1xxx-5xxx)."""
    ACTIVO     = "ACTIVO"      # 1xxx
    PASIVO     = "PASIVO"      # 2xxx
    PATRIMONIO = "PATRIMONIO"  # 3xxx
    INGRESO    = "INGRESO"     # 4xxx
    GASTO      = "GASTO"       # 5xxx


class AccountSubType(str, enum.Enum):
    """Sub-clasificación para reportes NIIF."""
    CIRCULANTE      = "CIRCULANTE"
    NO_CIRCULANTE   = "NO_CIRCULANTE"
    OPERATIVO       = "OPERATIVO"
    NO_OPERATIVO    = "NO_OPERATIVO"
    FINANCIERO      = "FINANCIERO"
    CAPITAL         = "CAPITAL"
    RESERVAS        = "RESERVAS"
    RESULTADOS      = "RESULTADOS"
    COSTO           = "COSTO"
    IMPUESTO        = "IMPUESTO"
    OTRO            = "OTRO"


# ─────────────────────────────────────────────────────────────────
# Modelo Account
# ─────────────────────────────────────────────────────────────────

class Account(Base):
    """
    Cuenta contable dentro de un catálogo de tenant.

    Regla: la unicidad es (tenant_id, code) — distintos tenants
    pueden tener el mismo código sin colisión.

    allow_entries: False en cuentas-grupo (ej: 1100 Activo Circulante).
                   Solo las hojas de la jerarquía aceptan asientos.

    parent_code:   Permite construir el árbol jerárquico sin JOINs
                   costosos (tenant_id + parent_code).
    """
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_account_tenant_code"),
        Index("idx_accounts_tenant", "tenant_id"),
        Index("idx_accounts_type",   "tenant_id", "account_type"),
    )

    id            = Column(String(36),  primary_key=True, default=gen_uuid)
    tenant_id     = Column(String(36),  nullable=False, index=True)

    code          = Column(String(20),  nullable=False)   # "1101", "2101.03"
    name          = Column(String(200), nullable=False)
    description   = Column(Text,        nullable=True)

    account_type  = Column(Enum(AccountType),    nullable=False)
    account_sub_type = Column(Enum(AccountSubType), nullable=True)

    parent_code   = Column(String(20),  nullable=True)    # NULL = raíz
    allow_entries = Column(Boolean,     nullable=False, default=True)
    is_active     = Column(Boolean,     nullable=False, default=True)

    # Modo NONE: cuentas genéricas precargadas por el sistema
    is_generic    = Column(Boolean,     nullable=False, default=False)

    # Cuenta reguladora (contra-account): su naturaleza es OPUESTA al tipo.
    # Ej: Dep. Acumulada (ACTIVO) → naturaleza HABER → es_reguladora=True
    # Ej: Devoluciones s/Ventas (INGRESO) → naturaleza DEBE → es_reguladora=True
    # Cuando es True, la Balanza no emite alarma_naturaleza aunque el saldo
    # esté en la columna "contraria" al tipo ORM.
    es_reguladora = Column(Boolean,     nullable=False, default=False)

    created_at    = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at    = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    def __repr__(self):
        return f"<Account {self.code} [{self.account_type}] tenant={self.tenant_id}>"
