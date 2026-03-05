"""
Auth Router — Endpoints de autenticación
Genoma Contabilidad — Multi-tenant

Reglas de Oro aplicadas:
  - tenant_id NUNCA en el body del request (viene del JWT)
  - password NUNCA en logs ni en responses
  - Todos los errores con mensaje genérico (no revelar info interna)
"""
from datetime import datetime, timezone
from typing import Optional
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from .database import get_session
from .models import Tenant, User, TenantType, UserRole, TenantStatus
from .security import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


# ─────────────────────────────────────────────────────────────────
# Schemas (Pydantic)
# ─────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """
    Registro de nuevo tenant + usuario admin.
    Para partner_linked: incluir partner_id y facturador_api_key.
    Para standalone: omitir esos campos.
    """
    nombre_empresa: str
    cedula: str              # Cédula jurídica o física
    email: str
    password: str
    nombre_usuario: str
    tenant_type: TenantType = TenantType.standalone

    # Solo para partner_linked
    partner_id: Optional[str] = None
    facturador_api_key: Optional[str] = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("El password debe tener al menos 8 caracteres")
        return v

    @field_validator("cedula")
    @classmethod
    def cedula_format(cls, v: str) -> str:
        # Limpiar guiones y espacios
        clean = v.replace("-", "").replace(" ", "")
        if len(clean) < 9 or len(clean) > 12:
            raise ValueError("Cédula inválida (9-12 dígitos)")
        return clean


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_type: str
    role: str
    nombre: str
    tenant_id: str


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_session)):
    """
    Registro de nueva empresa/despacho contable.
    Crea el Tenant y el primer User (rol: admin).
    """
    # Validar: partner_linked requiere partner_id
    if req.tenant_type == TenantType.partner_linked and not req.partner_id:
        raise HTTPException(
            status_code=400,
            detail="partner_id es requerido para cuentas de tipo partner_linked"
        )

    # Verificar que la cédula no está registrada
    existing_tenant = db.query(Tenant).filter(Tenant.cedula == req.cedula).first()
    if existing_tenant:
        raise HTTPException(
            status_code=409,
            detail="Ya existe una cuenta registrada con esa cédula"
        )

    # Crear Tenant
    tenant = Tenant(
        nombre=req.nombre_empresa,
        cedula=req.cedula,
        email_contacto=req.email,
        tenant_type=req.tenant_type,
        partner_id=req.partner_id,
        facturador_api_key=req.facturador_api_key,  # Encriptar en prod con KMS
        status=TenantStatus.trial,
    )
    db.add(tenant)
    db.flush()  # Para obtener tenant.id antes del commit

    # Crear User admin
    user = User(
        tenant_id=tenant.id,
        nombre=req.nombre_usuario,
        email=req.email.lower().strip(),
        password_hash=hash_password(req.password),
        role=UserRole.admin,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.refresh(tenant)

    # Generar JWT
    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_type=tenant.tenant_type.value,
        role=user.role.value,
        nombre=user.nombre,
        partner_id=tenant.partner_id,
    )

    return AuthResponse(
        access_token=token,
        tenant_type=tenant.tenant_type.value,
        role=user.role.value,
        nombre=user.nombre,
        tenant_id=tenant.id,
    )


@router.post("/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_session)):
    """
    Login con email + password.
    Mensaje de error genérico para no revelar si el email existe.
    """
    email = req.email.lower().strip()

    user = db.query(User).filter(User.email == email).first()

    # Mensaje genérico — no revelar si el email existe o no
    credentials_error = HTTPException(
        status_code=401,
        detail="Credenciales incorrectas"
    )

    if not user:
        raise credentials_error

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Cuenta desactivada")

    if not verify_password(req.password, user.password_hash):
        raise credentials_error

    # Actualizar last_login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    tenant = db.query(Tenant).filter(Tenant.id == user.tenant_id).first()

    if not tenant or tenant.status == TenantStatus.suspended:
        raise HTTPException(status_code=403, detail="Cuenta suspendida")

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant.id,
        tenant_type=tenant.tenant_type.value,
        role=user.role.value,
        nombre=user.nombre,
        partner_id=tenant.partner_id,
    )

    return AuthResponse(
        access_token=token,
        tenant_type=tenant.tenant_type.value,
        role=user.role.value,
        nombre=user.nombre,
        tenant_id=tenant.id,
    )


@router.get("/me")
def me(current_user: dict = Depends(get_current_user)):
    """
    Retorna la identidad del usuario autenticado desde el JWT.
    No requiere DB — todo viene del token.
    """
    return {
        "user_id":     current_user.get("sub"),
        "nombre":      current_user.get("nombre"),
        "tenant_id":   current_user.get("tenant_id"),
        "tenant_type": current_user.get("tenant_type"),
        "role":        current_user.get("role"),
        "partner_id":  current_user.get("partner_id"),
    }


@router.get("/clients")
def get_clients(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    Lista las empresas disponibles para el usuario autenticado.
    - partner_linked : empresas cuyos tenants tengan el mismo partner_id
    - standalone     : tenants registrados bajo el user_id
    """
    tenant_type = current_user.get("tenant_type")
    partner_id  = current_user.get("partner_id")
    user_id     = current_user.get("sub")

    if tenant_type == TenantType.partner_linked and partner_id:
        tenants = db.query(Tenant).filter(
            Tenant.partner_id == partner_id
        ).all()
    else:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return {"clients": []}
        tenants = db.query(Tenant).filter(
            Tenant.id == user.tenant_id
        ).all()

    return {
        "clients": [
            {
                "tenant_id":   t.id,
                "nombre":      t.nombre,
                "cedula":      t.cedula,
                "tenant_type": t.tenant_type.value,
                "status":      t.status.value,
            }
            for t in tenants
        ]
    }


# ─────────────────────────────────────────────────────────────────
# Bridge: intercambio partner_token → gc_token (Opción A mejorada)
# ─────────────────────────────────────────────────────────────────

class PartnerHandoffRequest(BaseModel):
    partner_token: str


@router.post("/partner-handoff")
def partner_handoff(req: PartnerHandoffRequest):
    """
    Intercambia un partner_token opaco del Facturador por un gc_token JWT
    válido para el sistema contable.

    Flujo:
      1. Valida partner_token llamando a app.genomaio.com/api/partners/portal/me
      2. Si válido, emite gc_token JWT con identidad del partner
      3. El frontend redirige a /select?token=gc_token
    """
    facturador_base = os.getenv(
        "FACTURADOR_BASE_URL",
        "https://app.genomaio.com"
    )

    try:
        resp = httpx.get(
            f"{facturador_base}/api/partners/portal/me",
            headers={"X-Partner-Token": req.partner_token},
            timeout=15.0
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail="No se pudo contactar al Facturador para validar el token"
        )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Token de partner inválido o expirado")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Error al validar token con el Facturador")

    partner_data = resp.json()

    # Emitir gc_token JWT con identidad del partner
    gc_token = create_access_token(
        user_id=str(partner_data.get("id", "") or partner_data.get("email", "")),
        tenant_id=partner_data.get("codigo_referido", ""),
        tenant_type=TenantType.partner_linked.value,
        role=UserRole.admin.value,
        nombre=partner_data.get("nombre_despacho") or partner_data.get("email", ""),
        partner_id=partner_data.get("codigo_referido"),
    )

    return {"gc_token": gc_token}
