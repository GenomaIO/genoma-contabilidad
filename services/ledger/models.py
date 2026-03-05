"""
Ledger — Libro Diario (Models)
Genoma Contabilidad · Motor Contable NIIF

Reglas de Oro aplicadas:
- DECIMAL(18,5) para montos — nunca FLOAT (Regla de Oro #3)
- Tabla append-only: NUNCA UPDATE/DELETE en journal_entries ni journal_lines
- tenant_id en cada tabla (Regla de Oro #1)
- VOIDED genera asiento de reversión, no borra el original
- fiscal_tag en cada línea para rastreabilidad Hacienda (Art. 8/9 Ley Renta)
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Boolean, DateTime, Enum, Text,
    ForeignKey, Index, Numeric, CheckConstraint
)
from sqlalchemy.orm import declarative_base, relationship

from services.auth.models import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class EntryStatus(str, enum.Enum):
    """
    Estado de un asiento contable.
    DRAFT  : Generado (auto o manual) — pendiente de aprobación del contador.
    POSTED : Aprobado por contador/admin — definitivo e inmutable.
    VOIDED : Anulado — se genera asiento de reversión automático.
    """
    DRAFT  = "DRAFT"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class EntrySource(str, enum.Enum):
    """
    Origen del asiento — trazabilidad para auditoría Hacienda.
    """
    MANUAL   = "MANUAL"    # Ingresado a mano por el contador/asistente
    FE       = "FE"        # Factura Electrónica (tipo 01)
    TE       = "TE"        # Tiquete Electrónico (tipo 04)
    NC       = "NC"        # Nota de Crédito (tipo 03)
    ND       = "ND"        # Nota de Débito (tipo 02)
    REP      = "REP"       # Recibo de Pago (tipo 08)
    FEC      = "FEC"       # Factura Electrónica de Compra (tipo 08 compra)
    RECIBIDO = "RECIBIDO"  # Documento recibido (lado comprador)
    CIERRE   = "CIERRE"    # Asiento de cierre de período


class DeductibleStatus(str, enum.Enum):
    """
    Status fiscal de deducibilidad (Art. 8 Ley Renta CR).
    PENDING       : sin clasificar todavía (default para MANUAL)
    DEDUCTIBLE    : deducible al 100% (Art. 8)
    PARTIAL       : deducible parcial / prorrata (Art. 29/34)
    NON_DEDUCTIBLE: no deducible (Art. 9 — multas, recargos, etc.)
    EXEMPT        : exento / no aplica IVA
    """
    PENDING        = "PENDING"
    DEDUCTIBLE     = "DEDUCTIBLE"
    PARTIAL        = "PARTIAL"
    NON_DEDUCTIBLE = "NON_DEDUCTIBLE"
    EXEMPT         = "EXEMPT"


# ─────────────────────────────────────────────────────────────────
# JournalEntry — Cabecera del Asiento
# ─────────────────────────────────────────────────────────────────

class JournalEntry(Base):
    """
    Asiento contable (cabecera).

    APPEND-ONLY: una vez creado, solo puede cambiar de DRAFT → POSTED → VOIDED.
    VOIDED no borra — genera un asiento de reversión que también pasa por DRAFT.

    period: 'YYYY-MM' — para filtros y cierre de período.
    source_ref: clave Hacienda (50 chars) si viene del Facturador.
    voided_by_id: UUID del asiento de reversión (si aplica).
    """
    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("idx_je_tenant_period", "tenant_id", "period"),
        Index("idx_je_tenant_status", "tenant_id", "status"),
        Index("idx_je_source_ref",    "source_ref"),
    )

    id          = Column(String(36),  primary_key=True, default=gen_uuid)
    tenant_id   = Column(String(36),  nullable=False, index=True)

    period      = Column(String(7),   nullable=False)         # '2026-03'
    date        = Column(String(10),  nullable=False)         # '2026-03-05' (ISO)
    description = Column(Text,        nullable=False)
    status      = Column(Enum(EntryStatus),  nullable=False, default=EntryStatus.DRAFT)
    source      = Column(Enum(EntrySource),  nullable=False, default=EntrySource.MANUAL)
    source_ref  = Column(String(100), nullable=True)          # clave Hacienda

    # Trazabilidad de auditoría
    created_by  = Column(String(36),  nullable=False)         # user_id
    approved_by = Column(String(36),  nullable=True)          # user_id del contador
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Anulación
    voided_by   = Column(String(36),  nullable=True)          # user_id que anuló
    voided_at   = Column(DateTime(timezone=True), nullable=True)
    reversal_id = Column(String(36),  nullable=True)          # ID del asiento de reversión

    created_at  = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    # NO updated_at — append-only, el estado se actualiza con POSTED/VOIDED solamente

    lines       = relationship("JournalLine", back_populates="entry",
                               cascade="all, delete-orphan", lazy="select")

    def __repr__(self):
        return f"<JournalEntry {self.id[:8]} [{self.status}] {self.period} tenant={self.tenant_id}>"


# ─────────────────────────────────────────────────────────────────
# JournalLine — Línea del Asiento (partida doble)
# ─────────────────────────────────────────────────────────────────

class JournalLine(Base):
    """
    Línea de asiento contable (partida doble).

    DECIMAL(18,5): máxima precisión para montos fiscales en CRC y USD.
    Regla: debit XOR credit — una línea no puede tener ambos > 0.

    fiscal_tag: capa de metadata para declaraciones Hacienda.
    dimension_*: etiquetas para segmentación sin explosión de cuentas.
    """
    __tablename__ = "journal_lines"
    __table_args__ = (
        Index("idx_jl_entry_id",     "entry_id"),
        Index("idx_jl_tenant_code",  "tenant_id", "account_code"),
        # Constraint: debit o credit puede ser 0, pero no ambos pueden ser > 0
        CheckConstraint(
            "(debit = 0 OR credit = 0)",
            name="chk_debit_or_credit"
        ),
    )

    id           = Column(String(36),  primary_key=True, default=gen_uuid)
    entry_id     = Column(String(36),  ForeignKey("journal_entries.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    tenant_id    = Column(String(36),  nullable=False, index=True)  # redundante para queries

    account_code = Column(String(20),  nullable=False)
    description  = Column(Text,        nullable=True)

    # DECIMAL(18,5) — Regla de Oro #3: nunca FLOAT para montos
    debit        = Column(Numeric(18, 5), nullable=False, default=0)
    credit       = Column(Numeric(18, 5), nullable=False, default=0)

    # ── Capa Fiscal (Hacienda / Ley Renta) ──────────────────────
    deductible_status = Column(Enum(DeductibleStatus), nullable=True,
                                default=DeductibleStatus.PENDING)
    legal_basis       = Column(String(100), nullable=True)   # 'Art. 8 Ley Renta'

    # ── Dimensiones (segmentación sin explosión de cuentas) ──────
    dim_segment  = Column(String(50),  nullable=True)   # 'Hotel', 'Restaurant'
    dim_branch   = Column(String(50),  nullable=True)   # 'Escazú', 'Heredia'
    dim_project  = Column(String(50),  nullable=True)   # 'Evento X'

    created_at   = Column(DateTime(timezone=True), default=now_utc, nullable=False)

    entry = relationship("JournalEntry", back_populates="lines")

    def __repr__(self):
        side = f"DR {self.debit}" if self.debit else f"CR {self.credit}"
        return f"<JournalLine {self.account_code} {side} tenant={self.tenant_id}>"
