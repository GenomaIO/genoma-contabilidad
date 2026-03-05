"""
AuditLog — Registro Inmutable de Acciones
Genoma Contabilidad · Trazabilidad y Cumplimiento

Reglas de Oro:
- APPEND-ONLY: nunca DELETE ni UPDATE en este modelo
- user_id + role en cada registro (multi-perfil trazable)
- before/after en JSON para cambios de estado
- Cobertura: cambios de catálogo, aprobaciones, anulaciones, onboarding
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, DateTime, Enum, Text, Index
)

from services.auth.models import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AuditAction(str, enum.Enum):
    """
    Acción auditada. Cubre todo lo que exige trazabilidad contable/fiscal.
    """
    # ── Catálogo ──────────────────────────────────────────────────
    CATALOG_MODE_SET      = "CATALOG_MODE_SET"      # Onboarding: eligió modo
    ACCOUNT_CREATED       = "ACCOUNT_CREATED"       # Nueva cuenta creada
    ACCOUNT_UPDATED       = "ACCOUNT_UPDATED"       # Cuenta modificada
    ACCOUNT_TOGGLED       = "ACCOUNT_TOGGLED"       # Cuenta activada/desactivada
    CATALOG_SEEDED        = "CATALOG_SEEDED"        # Seeder ejecutado

    # ── Asientos ─────────────────────────────────────────────────
    ENTRY_CREATED         = "ENTRY_CREATED"         # Asiento DRAFT creado
    ENTRY_POSTED          = "ENTRY_POSTED"          # Aprobado → POSTED
    ENTRY_VOIDED          = "ENTRY_VOIDED"          # Anulado → VOIDED + reversal

    # ── Acceso / Sesión ───────────────────────────────────────────
    USER_LOGIN            = "USER_LOGIN"
    USER_LOGOUT           = "USER_LOGOUT"
    CATALOG_MODE_CHANGED  = "CATALOG_MODE_CHANGED"  # Migración de modo posterior

    # ── Integración ───────────────────────────────────────────────
    WEBHOOK_RECEIVED      = "WEBHOOK_RECEIVED"      # Documento desde Facturador
    AUTO_ENTRY_GENERATED  = "AUTO_ENTRY_GENERATED"  # Asiento auto-generado


class AuditLog(Base):
    """
    Registro inmutable de cada acción relevante en el sistema.

    APPEND-ONLY: nunca se modifica ni elimina un registro de audit_log.
    La clave de búsqueda principal es (tenant_id, created_at).

    action     : tipo de acción (AuditAction enum)
    entity_type: tabla afectada ('journal_entry', 'account', 'tenant'...)
    entity_id  : UUID del objeto afectado
    before_json: snapshot JSON del estado previo (si aplica)
    after_json : snapshot JSON del estado nuevo (si aplica)
    ip          : IP del cliente si está disponible en la capa HTTP
    note        : texto libre para contexto adicional
    """
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_tenant_date",   "tenant_id", "created_at"),
        Index("idx_audit_entity",        "entity_type", "entity_id"),
        Index("idx_audit_user",          "user_id"),
        Index("idx_audit_action",        "action"),
    )

    id          = Column(String(36),  primary_key=True, default=gen_uuid)
    tenant_id   = Column(String(36),  nullable=False, index=True)

    user_id     = Column(String(36),  nullable=False)   # quién realizó la acción
    user_role   = Column(String(20),  nullable=False)   # rol en el momento de la acción
    user_email  = Column(String(200), nullable=True)    # referencia legible (no FK)

    action      = Column(Enum(AuditAction), nullable=False)
    entity_type = Column(String(50),  nullable=True)    # 'journal_entry', 'account'...
    entity_id   = Column(String(36),  nullable=True)    # UUID del recurso afectado

    before_json = Column(Text,        nullable=True)    # JSON: estado previo
    after_json  = Column(Text,        nullable=True)    # JSON: estado posterior
    note        = Column(Text,        nullable=True)    # contexto libre

    ip          = Column(String(45),  nullable=True)    # IPv4/IPv6 del cliente
    created_at  = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    # NO updated_at — APPEND-ONLY

    def __repr__(self):
        return f"<AuditLog {self.action} by {self.user_id[:8]} @ {self.created_at}>"
