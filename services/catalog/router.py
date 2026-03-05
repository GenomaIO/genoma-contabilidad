"""
Catálogo de Cuentas — Router
Genoma Contabilidad · Endpoints CRUD del plan de cuentas

Reglas de Oro aplicadas:
- tenant_id SIEMPRE del JWT, nunca del body (multi-tenant absoluto)
- No DELETE — solo is_active toggle
- Todo cambio queda en audit_log (paso B2)
- Control de rol: lectura no puede crear/modificar cuentas
"""
from typing import Optional, List
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.auth.database import get_session
from services.auth.security import get_current_user
from services.catalog.models import Account, AccountType, AccountSubType
from services.catalog.seeder import seed_standard_catalog, seed_generic_catalog

router = APIRouter(prefix="/catalog", tags=["catalogo"])


# ──────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ──────────────────────────────────────────────────────────────────

class AccountOut(BaseModel):
    id:              str
    code:            str
    name:            str
    description:     Optional[str] = None
    account_type:    str
    account_sub_type: Optional[str] = None
    parent_code:     Optional[str] = None
    allow_entries:   bool
    is_active:       bool
    is_generic:      bool

    class Config:
        from_attributes = True


class AccountCreate(BaseModel):
    code:            str
    name:            str
    description:     Optional[str] = None
    account_type:    AccountType
    account_sub_type: Optional[AccountSubType] = None
    parent_code:     Optional[str] = None
    allow_entries:   bool = True

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip().upper()
        if len(v) < 2 or len(v) > 20:
            raise ValueError("El código debe tener entre 2 y 20 caracteres")
        return v

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("El nombre debe tener al menos 2 caracteres")
        return v


class AccountUpdate(BaseModel):
    name:            Optional[str] = None
    description:     Optional[str] = None
    account_sub_type: Optional[AccountSubType] = None


# ──────────────────────────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────────────────────────

def _require_write_role(role: str) -> None:
    """Valida que el rol puede escribir. Lectura es solo consulta."""
    if role == "lectura":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Rol 'lectura' no puede crear ni modificar cuentas"
        )


# ──────────────────────────────────────────────────────────────────
# GET /catalog/accounts
# ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=List[AccountOut])
def list_accounts(
    q:           Optional[str] = Query(None, description="Buscar por nombre o código"),
    type_filter: Optional[AccountType] = Query(None, alias="type"),
    only_active: bool = Query(True),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Lista las cuentas del catálogo del tenant autenticado.
    Soporta búsqueda por nombre/código y filtro por tipo.
    """
    tenant_id = current_user["tenant_id"]

    query = db.query(Account).filter(Account.tenant_id == tenant_id)

    if only_active:
        query = query.filter(Account.is_active == True)  # noqa: E712

    if type_filter:
        query = query.filter(Account.account_type == type_filter)

    if q:
        like = f"%{q.upper()}%"
        query = query.filter(
            (Account.code.like(like)) | (Account.name.ilike(f"%{q}%"))
        )

    accounts = query.order_by(Account.code).all()
    return accounts


# ──────────────────────────────────────────────────────────────────
# POST /catalog/accounts
# ──────────────────────────────────────────────────────────────────

@router.post("/accounts", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    req: AccountCreate,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Crea una nueva cuenta en el catálogo del tenant.
    Solo admin y contador pueden crear cuentas.
    """
    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    # Verificar duplicado
    existing = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        Account.code == req.code.strip().upper()
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Ya existe una cuenta con código '{req.code}'"
        )

    # Verificar que parent_code existe si se proporcionó
    if req.parent_code:
        parent = db.query(Account).filter(
            Account.tenant_id == tenant_id,
            Account.code == req.parent_code
        ).first()
        if not parent:
            raise HTTPException(
                status_code=404,
                detail=f"Cuenta padre '{req.parent_code}' no encontrada"
            )

    import uuid
    account = Account(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        code=req.code.strip().upper(),
        name=req.name.strip(),
        description=req.description,
        account_type=req.account_type,
        account_sub_type=req.account_sub_type,
        parent_code=req.parent_code,
        allow_entries=req.allow_entries,
        is_generic=False,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


# ──────────────────────────────────────────────────────────────────
# PATCH /catalog/accounts/{code}
# ──────────────────────────────────────────────────────────────────

@router.patch("/accounts/{code}", response_model=AccountOut)
def update_account(
    code: str,
    req: AccountUpdate,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Edita nombre, descripción o sub-tipo de una cuenta.
    No permite cambiar code ni account_type.
    """
    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    account = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        Account.code == code.upper()
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    if req.name is not None:
        account.name = req.name.strip()
    if req.description is not None:
        account.description = req.description
    if req.account_sub_type is not None:
        account.account_sub_type = req.account_sub_type

    account.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    return account


# ──────────────────────────────────────────────────────────────────
# PATCH /catalog/accounts/{code}/toggle
# (Desactivar/Reactivar — nunca eliminar)
# ──────────────────────────────────────────────────────────────────

@router.patch("/accounts/{code}/toggle", response_model=AccountOut)
def toggle_account(
    code: str,
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Activa o desactiva una cuenta.
    Regla de Oro: NO DELETE — audit trail permanente.
    Nota: no se puede desactivar una cuenta con is_generic=True.
    """
    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    account = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        Account.code == code.upper()
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    if account.is_generic:
        raise HTTPException(
            status_code=400,
            detail="Las cuentas genéricas del sistema no se pueden desactivar"
        )

    account.is_active = not account.is_active
    account.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    return account


# ──────────────────────────────────────────────────────────────────
# POST /catalog/seed
# Dispara el seeder para el modo elegido (llamado desde el onboarding)
# ──────────────────────────────────────────────────────────────────

@router.post("/seed")
def trigger_seed(
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Dispara el seeder del catálogo según el catalog_mode del tenant.
    Se llama automáticamente después de PATCH /auth/catalog-mode.
    Idempotente — ON CONFLICT DO NOTHING.
    """
    from services.auth.models import Tenant

    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant or not tenant.catalog_mode:
        raise HTTPException(
            status_code=400,
            detail="El tenant no tiene un catalog_mode definido"
        )

    mode = tenant.catalog_mode.value if hasattr(tenant.catalog_mode, "value") else tenant.catalog_mode

    if mode == "STANDARD":
        count = seed_standard_catalog(tenant_id, db)
    elif mode == "NONE":
        count = seed_generic_catalog(tenant_id, db)
    else:
        # CUSTOM — el seeder no aplica, el contador construye su catálogo
        count = 0

    return {
        "ok": True,
        "catalog_mode": mode,
        "accounts_seeded": count,
        "message": f"Catálogo '{mode}' listo con {count} cuentas" if count else "Modo CUSTOM — construí tu catálogo en /catalog/accounts"
    }
