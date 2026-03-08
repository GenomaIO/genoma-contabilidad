"""
services/reporting/models.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Motor de Mapeo NIIF — Estados Financieros (EEFF)
NIIF PYMES 3ª Edición · Febrero 2025 · IASB

Tablas:
  niif_line_defs   → Catálogo de partidas NIIF estándar (global, sin tenant)
  niif_mappings    → Mapeo por tenant: account_code → niif_line_code
  eeff_snapshots   → EEFF generados (inmutables una vez guardados)

Reglas de Oro aplicadas:
  - DECIMAL(18,5) para montos
  - tenant_id en cada tabla multitenancy
  - NIIF PYMES 3ª Ed. 2025 como referencia normativa
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Boolean, DateTime, Enum, Text,
    Integer, Index, Numeric, JSON, UniqueConstraint
)
from sqlalchemy.orm import declarative_base

from services.auth.models import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class NiifStatement(str, enum.Enum):
    """Los 5 estados financieros requeridos por NIIF PYMES Sec. 3.17"""
    ESF  = "ESF"   # Estado de Situación Financiera (Balance General)
    ERI  = "ERI"   # Estado de Resultado Integral
    ECP  = "ECP"   # Estado de Cambios en el Patrimonio
    EFE  = "EFE"   # Estado de Flujos de Efectivo
    NOTA = "NOTA"  # Notas a los EEFF


class EfeActivity(str, enum.Enum):
    """Clasificación de flujos para el EFE (Sección 7 NIIF PYMES 3ª Ed.)"""
    OPERACION    = "OPERACION"    # Actividades de operación
    INVERSION    = "INVERSION"    # Actividades de inversión
    FINANCIACION = "FINANCIACION" # Actividades de financiación
    NO_APLICA    = "NO_APLICA"    # Para cuentas que no van al EFE directamente


class EsfSection(str, enum.Enum):
    """Secciones del ESF — Sec. 4 NIIF PYMES"""
    ACTIVO_CORRIENTE    = "ACTIVO_CORRIENTE"
    ACTIVO_NO_CORRIENTE = "ACTIVO_NO_CORRIENTE"
    PASIVO_CORRIENTE    = "PASIVO_CORRIENTE"
    PASIVO_NO_CORRIENTE = "PASIVO_NO_CORRIENTE"
    PATRIMONIO          = "PATRIMONIO"
    # Para el ERI
    INGRESO             = "INGRESO"
    COSTO               = "COSTO"
    GASTO_OPERATIVO     = "GASTO_OPERATIVO"
    GASTO_FINANCIERO    = "GASTO_FINANCIERO"
    IMPUESTO_RENTA      = "IMPUESTO_RENTA"
    OTRO_RESULTADO      = "OTRO_RESULTADO"   # ORI — 3ª Ed.


# ─────────────────────────────────────────────────────────────────
# NiifLineDef — Catálogo de partidas NIIF (global, sin tenant)
# ─────────────────────────────────────────────────────────────────

class NiifLineDef(Base):
    """
    Catálogo global de partidas NIIF.
    Ejemplo: ESF.AC.01 = 'Efectivo y equivalentes al efectivo' (Sec. 4)
    No es por tenant — es la norma universal.
    """
    __tablename__ = "niif_line_defs"

    id            = Column(String, primary_key=True, default=gen_uuid)
    code          = Column(String(30), unique=True, nullable=False)   # ESF.AC.01
    label         = Column(String(200), nullable=False)                # 'Efectivo y equivalentes'
    statement     = Column(Enum(NiifStatement), nullable=False)        # ESF | ERI | EFE ...
    section       = Column(Enum(EsfSection), nullable=False)           # ACTIVO_CORRIENTE ...
    order         = Column(Integer, nullable=False)                    # Orden de presentación
    is_subtotal   = Column(Boolean, default=False)                     # Total Activo Corriente etc.
    is_calculated = Column(Boolean, default=False)                     # Se calcula (vs. suma de cuentas)
    efe_activity  = Column(Enum(EfeActivity), default=EfeActivity.NO_APLICA)
    niif_section_ref = Column(String(20), nullable=True)              # Ref. ej. "Sec.4" "Sec.7"
    created_at    = Column(DateTime(timezone=True), default=now_utc)


# ─────────────────────────────────────────────────────────────────
# NiifMapping — Mapeo por tenant: account_code → niif_line_code
# ─────────────────────────────────────────────────────────────────

class NiifMapping(Base):
    """
    Mapeo de cada cuenta del catálogo del tenant a una partida NIIF.
    Este es el corazón del motor de EEFF.

    Regla: TODA cuenta activa debe tener un mapping para poder generar EEFF.
    Si no → el sistema bloquea la generación con alerta.
    """
    __tablename__ = "niif_mappings"

    id              = Column(String, primary_key=True, default=gen_uuid)
    tenant_id       = Column(String, nullable=False, index=True)
    account_code    = Column(String(30), nullable=False)   # Código del catálogo del tenant
    niif_line_code  = Column(String(30), nullable=False)   # ESF.AC.01, ERI.ING.01, etc.
    is_contra       = Column(Boolean, default=False)        # Cta. complementaria (Dep. Acumulada)
    efe_override    = Column(Enum(EfeActivity), nullable=True)  # Override actividad EFE
    notes           = Column(Text, nullable=True)           # Notas del contador
    created_at      = Column(DateTime(timezone=True), default=now_utc)
    updated_at      = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    __table_args__ = (
        UniqueConstraint("tenant_id", "account_code", name="uq_niif_mapping_tenant_account"),
        Index("ix_niif_mapping_tenant", "tenant_id"),
    )


# ─────────────────────────────────────────────────────────────────
# EeffSnapshot — EEFF generados (inmutables)
# ─────────────────────────────────────────────────────────────────

class EeffSnapshot(Base):
    """
    Snapshot de los EEFF de un año fiscal.
    Una vez generado y 'locked', no se modifica (Sec. 3.14 NIIF PYMES).
    Permite comparativo N vs N-1 leyendo el snapshot anterior.
    """
    __tablename__ = "eeff_snapshots"

    id                  = Column(String, primary_key=True, default=gen_uuid)
    tenant_id           = Column(String, nullable=False, index=True)
    year                = Column(String(4), nullable=False)                # "2026"
    period_label        = Column(String(100), nullable=True)               # "Año terminado 31 dic 2026"
    comparative_year    = Column(String(4), nullable=True)                 # "2025"
    # Datos de cada estado (JSON)
    esf_data            = Column(JSON, nullable=True)
    eri_data            = Column(JSON, nullable=True)
    ecp_data            = Column(JSON, nullable=True)
    efe_data            = Column(JSON, nullable=True)
    notes_data          = Column(JSON, nullable=True)
    # Sumas de control
    total_activo        = Column(Numeric(18, 5), nullable=True)
    total_pasivo_pat    = Column(Numeric(18, 5), nullable=True)
    net_income          = Column(Numeric(18, 5), nullable=True)
    esf_balanced        = Column(Boolean, default=False)                   # Activo == Pasivo+Pat
    efe_cash_matches    = Column(Boolean, default=False)                   # EFE final == ESF.AC.01
    # Metadatos
    generated_at        = Column(DateTime(timezone=True), default=now_utc)
    is_locked           = Column(Boolean, default=False)
    signed_by           = Column(String(200), nullable=True)
    version             = Column(Integer, default=1)
    niif_edition        = Column(String(10), default="3rd_2025")           # Edición NIIF usada

    __table_args__ = (
        Index("ix_eeff_snapshot_tenant_year", "tenant_id", "year"),
    )
