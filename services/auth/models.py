"""
Modelos de Base de Datos — Genoma Contabilidad
Principios:
  - Sin hardcoded tenant IDs
  - Multi-tenant via tenant_id en cada tabla
  - tenant_type distingue partner_linked vs standalone
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Boolean, DateTime, Enum, Text,
    ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────────────────────────────────────────────
# Enums
# ───────────────────────────────────────────────────────────────

class TenantType(str, enum.Enum):
    """
    partner_linked : Contador que es Partner en Genoma Facturador.
                     Sus clientes se importan automáticamente.
    standalone     : Contador o empresa sin vínculo con Facturador.
                     Ingresa datos manualmente o importa XMLs.
    """
    partner_linked = "partner_linked"
    standalone = "standalone"


class UserRole(str, enum.Enum):
    admin     = "admin"      # Dueño de la cuenta / administrador
    contador  = "contador"   # Contador con acceso completo
    lectura   = "lectura"    # Solo lectura (para clientes del contador)


class TenantStatus(str, enum.Enum):
    active    = "active"
    suspended = "suspended"
    trial     = "trial"


# ───────────────────────────────────────────────────────────────
# Tenant (empresa / despacho contable)
# ───────────────────────────────────────────────────────────────

class Tenant(Base):
    """
    Un Tenant = una empresa o despacho contable.
    Para partner_linked: el partner_id conecta con Genoma Facturador.
    Para standalone: partner_id es NULL.
    """
    __tablename__ = "tenants"

    id             = Column(String(36), primary_key=True, default=gen_uuid)
    nombre         = Column(String(200), nullable=False)
    cedula         = Column(String(20), nullable=False, unique=True)  # cédula jurídica o física
    email_contacto = Column(String(200), nullable=True)

    tenant_type    = Column(
        Enum(TenantType), nullable=False,
        default=TenantType.standalone
    )

    # Solo para partner_linked — ID del partner en Genoma Facturador
    partner_id     = Column(String(100), nullable=True)
    # API key del Facturador (encriptado en producción)
    facturador_api_key = Column(Text, nullable=True)

    status         = Column(Enum(TenantStatus), nullable=False, default=TenantStatus.trial)
    created_at     = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at     = Column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    # Relaciones
    users          = relationship("User", back_populates="tenant",
                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Tenant {self.cedula} [{self.tenant_type}]>"


# ───────────────────────────────────────────────────────────────
# User (usuario dentro de un tenant)
# ───────────────────────────────────────────────────────────────

class User(Base):
    """
    Un usuario pertenece a UN único tenant.
    El email + tenant_id es la clave única (un email puede existir en varios tenants).
    """
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", "tenant_id", name="uq_user_email_tenant"),
    )

    id          = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id   = Column(String(36), ForeignKey("tenants.id", ondelete="CASCADE"),
                         nullable=False, index=True)
    nombre      = Column(String(200), nullable=False)
    email       = Column(String(200), nullable=False, index=True)
    password_hash = Column(Text, nullable=False)
    role        = Column(Enum(UserRole), nullable=False, default=UserRole.admin)
    is_active   = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    last_login  = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    tenant      = relationship("Tenant", back_populates="users")

    def __repr__(self):
        return f"<User {self.email} [{self.role}] tenant={self.tenant_id}>"
