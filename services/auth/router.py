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
from .models import Tenant, User, TenantType, UserRole, TenantStatus, CatalogMode
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

    # Notificar al Facturador para que aparezca en Mission Control → Partners
    # Solo para cuentas standalone (Contadores Independientes)
    if req.tenant_type == TenantType.standalone:
        facturador_base = os.getenv("FACTURADOR_BASE_URL", "https://app.genomaio.com")
        try:
            httpx.post(
                f"{facturador_base}/api/partners/portal/auto-register-independiente",
                json={
                    "email":                 req.email,
                    "nombre_despacho":       req.nombre_empresa,
                    "contabilidad_tenant_id": tenant.id,
                },
                timeout=5.0
            )
        except Exception:
            # Fire-and-forget: si falla no bloquea el registro
            pass

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
def me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    Retorna la identidad del usuario autenticado.
    Combina JWT (identidad) + DB (catalog_mode real del tenant).
    El JWT no incluye catalog_mode por diseño (TTL corto), pero la DB siempre
    tiene el valor actualizado → RO#227 (State Hydration Guard).
    """
    tenant_id = current_user.get("tenant_id")

    # Obtener catalog_mode actualizado desde la DB
    catalog_mode = None
    if tenant_id:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if tenant and tenant.catalog_mode:
            catalog_mode = (
                tenant.catalog_mode.value
                if hasattr(tenant.catalog_mode, "value")
                else str(tenant.catalog_mode)
            )

    return {
        "user_id":      current_user.get("sub"),
        "nombre":       current_user.get("nombre"),
        "tenant_id":    tenant_id,
        "tenant_type":  current_user.get("tenant_type"),
        "role":         current_user.get("role"),
        "partner_id":   current_user.get("partner_id"),
        "catalog_mode": catalog_mode,   # RO#227: fuente de verdad = DB, no JWT
    }


@router.get("/clients")
def get_clients(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session)
):
    """
    Lista las empresas disponibles para el usuario autenticado.
    - partner_linked : consulta federada al Facturador (fuente de verdad)
    - standalone     : tenants en la DB local de contabilidad
    """
    tenant_type       = current_user.get("tenant_type")
    facturador_token  = current_user.get("facturador_token")  # solo en gc_token de partner
    user_id           = current_user.get("sub")

    # ── PARTNER: fuente de verdad = Facturador ───────────────────────
    if tenant_type == TenantType.partner_linked.value and facturador_token:
        facturador_base = os.getenv("FACTURADOR_BASE_URL", "https://app.genomaio.com")
        try:
            resp = httpx.get(
                f"{facturador_base}/api/partners/portal/me/clientes",
                headers={"X-Partner-Token": facturador_token},
                timeout=15.0
            )
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="No se pudo contactar al Facturador")

        if resp.status_code == 401:
            raise HTTPException(status_code=401, detail="Token del Facturador expirado")
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Error obteniendo clientes del Facturador")

        data = resp.json()
        clientes_raw = data.get("clientes", [])

        return {
            "clients": [
                {
                    "tenant_id":   c.get("tenant_id"),
                    "emisor_id":   c.get("emisor_id"),    # puerta a documentos fiscales
                    "nombre":      c.get("nombre") or "Sin nombre",
                    "estado":      c.get("estado", "ACTIVO"),
                    "numero":      c.get("numero_cliente"),
                    "genera_comision": c.get("genera_comision", False),
                    "origen":      "facturador",
                }
                for c in clientes_raw
            ]
        }

    # ── STANDALONE: fuente de verdad = BD local contabilidad ──────────
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {"clients": []}
    tenants = db.query(Tenant).filter(Tenant.id == user.tenant_id).all()

    return {
        "clients": [
            {
                "tenant_id":   t.id,
                "nombre":      t.nombre,
                "cedula":      t.cedula,
                "tenant_type": t.tenant_type.value,
                "status":      t.status.value,
                "origen":      "contabilidad",
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

    El gc_token incluye:
      - partner_uuid     : UUID del partner en la BD del Facturador
      - facturador_token : token opaco original (para llamadas server-to-server)
      - partner_id       : codigo_referido (GC-XXXX)
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
    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail="No se pudo contactar al Facturador para validar el token"
        )

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Token de partner inválido o expirado")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Error al validar token con el Facturador")

    partner_data = resp.json()

    partner_uuid     = str(partner_data.get("id") or "")
    codigo_referido  = partner_data.get("codigo_referido") or ""
    nombre_despacho  = partner_data.get("nombre_despacho") or partner_data.get("email", "")

    gc_token = create_access_token(
        user_id      = partner_uuid or partner_data.get("email", ""),
        tenant_id    = codigo_referido,
        tenant_type  = TenantType.partner_linked.value,
        role         = UserRole.admin.value,
        nombre       = nombre_despacho,
        partner_id   = codigo_referido,
        extra_claims = {
            "partner_uuid":     partner_uuid,
            "facturador_token": req.partner_token,  # token opaco para llamadas futuras
        }
    )

    return {"gc_token": gc_token}


# ─────────────────────────────────────────────────────────────────
# Onboarding: elegir modo de catálogo de cuentas
# ─────────────────────────────────────────────────────────────────

class CatalogModeRequest(BaseModel):
    mode: CatalogMode   # NONE | STANDARD | CUSTOM


@router.patch("/catalog-mode")
def set_catalog_mode(
    req: CatalogModeRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Guarda la elección del modo de catálogo para el tenant del usuario.
    Regla de Oro: tenant_id SIEMPRE del JWT, nunca del body.
    Solo lo puede cambiar admin o contador — lectura queda bloqueado.
    """
    role = current_user.get("role")
    if role not in ("admin", "contador"):
        raise HTTPException(
            status_code=403,
            detail="Solo admin o contador puede configurar el modo de catálogo"
        )

    tenant_id = current_user.get("tenant_id")
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant no encontrado")

    old_mode = tenant.catalog_mode.value if tenant.catalog_mode else None
    tenant.catalog_mode = req.mode
    db.commit()

    return {
        "ok": True,
        "tenant_id": tenant_id,
        "catalog_mode": req.mode.value,
        "previous_mode": old_mode,
    }


# ─────────────────────────────────────────────────────────────────
# POST /auth/switch-tenant — Re-emitir JWT con tenant_id correcto
# ─────────────────────────────────────────────────────────────────

class SwitchTenantRequest(BaseModel):
    tenant_id: str  # UUID del tenant seleccionado


@router.post("/switch-tenant")
def switch_tenant(
    req: SwitchTenantRequest,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Re-emite un JWT con el tenant_id del tenant seleccionado.

    Fix crítico para aislamiento multi-tenant:
    El ClientSelector cambiaba el nombre visual pero nunca cambiaba el JWT.
    Ahora genera un JWT nuevo con el tenant_id real de la empresa elegida.

    Seguridad:
    - partner_linked: verifica que el tenant existe y está activo
    - standalone: verifica que el tenant pertenece al usuario
    - El JWT nuevo hereda user_id, role, nombre del JWT original
    """
    target_tenant_id = req.tenant_id
    user_tenant_type = current_user.get("tenant_type", "")
    user_id = current_user.get("sub", "")

    # ── Buscar el tenant destino en la DB ────────────────────────
    target_tenant = db.query(Tenant).filter(Tenant.id == target_tenant_id).first()

    if not target_tenant:
        raise HTTPException(404, "Tenant no encontrado")

    if target_tenant.status == TenantStatus.suspended:
        raise HTTPException(403, "Cuenta suspendida")

    # ── Verificación de permisos ─────────────────────────────────
    if user_tenant_type == TenantType.standalone.value:
        # Standalone: solo puede switch a su propio tenant
        user = db.query(User).filter(User.id == user_id).first()
        if not user or user.tenant_id != target_tenant_id:
            raise HTTPException(403, "No tenés acceso a este tenant")

    # partner_linked: confiamos en que el tenant existe y es accesible
    # (la lista de clientes viene del Facturador, que ya validó permisos)

    # ── Generar nuevo JWT con el tenant_id correcto ──────────────
    new_token = create_access_token(
        user_id=user_id,
        tenant_id=target_tenant.id,     # ← ESTE ES EL FIX
        tenant_type=user_tenant_type,
        role=current_user.get("role", "admin"),
        nombre=current_user.get("nombre", ""),
        partner_id=current_user.get("partner_id"),
        extra_claims={
            k: v for k, v in current_user.items()
            if k in ("partner_uuid", "facturador_token")
        } if user_tenant_type == TenantType.partner_linked.value else None,
    )

    return {
        "access_token": new_token,
        "token_type": "bearer",
        "tenant_id": target_tenant.id,
        "nombre": target_tenant.nombre,
        "cedula": target_tenant.cedula,
    }

