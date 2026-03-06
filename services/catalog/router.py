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
# GET /catalog/accounts/posteable
# Devuelve SOLO cuentas de movimiento (hojas del árbol) con display_code.
# Principio NIIF/SAP: solo la cuenta más detallada sin hijos acepta asientos.
# ──────────────────────────────────────────────────────────────────

def _get_display_code(code: str) -> str:
    """Convierte código interno (1101.01) a display DGCN (1.1.1.01)."""
    if '.' in code:
        base, sub = code.split('.', 1)
        return f'{_get_display_code(base)}.{sub}'
    if len(code) != 4:
        return code
    g1, g2, g3, g4 = code
    if g2 == '0' and g3 == '0' and g4 == '0':
        return g1
    if g3 == '0' and g4 == '0':
        return f'{g1}.{g2}'
    return f'{g1}.{g2}.{str(int(g3 + g4))}'


@router.get("/accounts/posteable")
def list_posteable_accounts(
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Cuentas de movimiento del tenant: solo hojas (sin hijos) con allow_entries=True.
    Incluye display_code (notación DGCN/NIIF) para uso en formularios de asientos.
    Usadas por el AccountPicker y validadas en create_entry().
    """
    tenant_id = current_user["tenant_id"]

    # Códigos que son padres de otras cuentas en este tenant
    parent_codes_raw = db.execute(
        text("SELECT DISTINCT parent_code FROM accounts WHERE tenant_id = :tid AND parent_code IS NOT NULL"),
        {"tid": tenant_id},
    ).fetchall()
    parent_set = {r[0] for r in parent_codes_raw}

    # Cuentas activas de movimiento: allow_entries=True Y no son padre de nadie
    all_active = db.query(Account).filter(
        Account.tenant_id == tenant_id,
        Account.is_active == True,        # noqa: E712
        Account.allow_entries == True,    # noqa: E712
    ).order_by(Account.code).all()

    result = []
    for a in all_active:
        if a.code not in parent_set:          # es hoja real
            result.append({
                "code":         a.code,
                "display_code": _get_display_code(a.code),
                "name":         a.name,
                "account_type": a.account_type.value if hasattr(a.account_type, 'value') else str(a.account_type),
                "sub_type":     a.account_sub_type.value if a.account_sub_type and hasattr(a.account_sub_type, 'value') else None,
                "allow_entries": a.allow_entries,
            })

    return result


# ──────────────────────────────────────────────────────────────────
# GET /catalog/health
# Diagnostica si el catálogo tiene ramas con mezcla de profundidad.
# Si un hijo de un rubro fue expandido a N5 pero sus hermanas siguen
# en N4, la rama queda "mixta" y los EEFF podrían tener doble conteo.
# Principio SAP FI / Oracle GL: toda la rama debe estar al mismo nivel.
# ──────────────────────────────────────────────────────────────────

@router.get("/health")
def catalog_health(
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Devuelve el estado de salud del catálogo del tenant.
    - status: 'OK' | 'WARNING'
    - mix_level_branches: ramas donde hay hijos en niveles distintos
    - total_posteable: qty de cuentas que actualmente aceptan asientos
    """
    tenant_id = current_user["tenant_id"]

    rows = db.execute(
        text("""
            SELECT code, name, parent_code, allow_entries, is_active
            FROM accounts
            WHERE tenant_id = :tid AND is_active = true
            ORDER BY code
        """),
        {"tid": tenant_id},
    ).fetchall()

    # Construir índices
    code_map      = {r[0]: {"name": r[1], "allow_entries": r[3]} for r in rows}
    parent_set    = {r[2] for r in rows if r[2] is not None}  # códigos que son padres

    # Agrupar hijos por padre
    from collections import defaultdict
    siblings: dict = defaultdict(list)
    for r in rows:
        if r[2]:  # tiene parent_code
            siblings[r[2]].append(r[0])

    mix_level_branches = []
    for parent_code, children in siblings.items():
        leaves   = [c for c in children if c not in parent_set]   # hojas reales
        promoted = [c for c in children if c in parent_set]        # ya tienen hijos propios
        if leaves and promoted:  # mezcla: algunos hijos son hojas, otros son padres
            mix_level_branches.append({
                "parent":      parent_code,
                "parent_name": code_map.get(parent_code, {}).get("name", "?"),
                "leaves_at_current_level": leaves,     # hermanas sin expandir
                "promoted_to_parent":      promoted,   # hermanas ya expandidas a N+1
                "recommendation": (
                    f"Las cuentas {promoted} tienen sub-cuentas (nivel superior). "
                    f"Se recomienda también expandir {leaves} al mismo nivel "
                    f"para evitar inconsistencias en estados financieros."
                ),
            })

    total_posteable = sum(
        1 for r in rows
        if r[0] not in parent_set and r[3]  # not in parent_set AND allow_entries
    )

    return {
        "status":              "WARNING" if mix_level_branches else "OK",
        "total_posteable":     total_posteable,
        "mix_level_count":     len(mix_level_branches),
        "mix_level_branches":  mix_level_branches,
    }


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
# Dispara el seeder para el modo elegido (llamado desde el onboarding
# o desde el Catálogo en estado vacío).
# ──────────────────────────────────────────────────────────────────

class SeedRequest(BaseModel):
    """
    mode es opcional.
    - Si el tenant ya tiene catalog_mode en BD: se usa ese (se ignora mode del body).
    - Si catalog_mode = NULL (tenant creado antes del onboarding) y viene mode:
        → se guarda mode en BD y luego se seedea.
    - Si ambos son null: default STANDARD (el más común bajo NIIF PYMES CR).
    """
    mode: Optional[str] = None


@router.post("/seed")
def trigger_seed(
    req:          SeedRequest = SeedRequest(),
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Dispara el seeder del catálogo según el catalog_mode del tenant.
    - Si el tenant tiene catalog_mode en BD: usa ese.
    - Si no tiene (tenant pre-onboarding): usa el mode del body y lo guarda.
    Idempotente — ON CONFLICT DO NOTHING.
    """
    from services.auth.models import Tenant, CatalogMode

    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    # Si el tenant no tiene registro en BD (partner_linked sin onboarding en contabilidad),
    # usamos el mode del body. El tenant_id del JWT es suficiente para insertar cuentas.
    # RO#6 (Safe Fallback): no bloquear la operacion por ausencia de registro ORM.

    # Obtener el modo efectivo
    db_mode = None
    if tenant and tenant.catalog_mode:
        db_mode = tenant.catalog_mode.value if hasattr(tenant.catalog_mode, "value") else str(tenant.catalog_mode)

    effective_mode = db_mode or req.mode or "STANDARD"

    # Si el tenant tiene registro en BD pero no tenía mode → guardarlo
    if tenant and not db_mode and req.mode:
        try:
            tenant.catalog_mode = CatalogMode(req.mode)
            db.commit()
        except (ValueError, KeyError):
            pass  # modo desconocido → continuar con effective_mode de todas formas

    # Ejecutar el seeder usando tenant_id del JWT (funciona con o sin registro ORM)
    if effective_mode == "STANDARD":
        count = seed_standard_catalog(tenant_id, db)
    elif effective_mode == "NONE":
        count = seed_generic_catalog(tenant_id, db)
    else:
        # CUSTOM — el seeder no aplica, el contador construye su catálogo
        count = 0

    return {
        "ok": True,
        "catalog_mode": effective_mode,
        "accounts_seeded": count,
        "message": f"Catálogo '{effective_mode}' listo con {count} cuentas" if count else "Modo CUSTOM — construí tu catálogo en /catalog/accounts"
    }

# ──────────────────────────────────────────────────────────────────
# POST /catalog/reseed-missing
# Inserta SOLO las cuentas del seed estándar ausentes en el tenant.
# Nunca modifica ni elimina cuentas existentes.
# ──────────────────────────────────────────────────────────────────

@router.post("/reseed-missing")
def reseed_missing(
    current_user: dict = Depends(get_current_user),
    db:           Session = Depends(get_session),
):
    """
    Detecta y agrega cuentas del catálogo estándar que faltan en el tenant.
    Caso de uso: tenants existentes que no tienen sub-cuentas nuevas (PPE lvl4).
    Idempotente — si se ejecuta 2 veces, la 2da inserta 0.
    """
    import json, uuid
    from pathlib import Path

    _require_write_role(current_user["role"])
    tenant_id = current_user["tenant_id"]

    seed_path = Path(__file__).parent / "seeds" / "standard_cr.json"
    if not seed_path.exists():
        raise HTTPException(status_code=500, detail="Seed estándar no encontrado")

    with open(seed_path, "r", encoding="utf-8") as f:
        seed_accounts = json.load(f)

    existing = db.query(Account.code).filter(Account.tenant_id == tenant_id).all()
    existing_codes = {row[0] for row in existing}

    inserted = 0
    for acc_data in seed_accounts:
        code = acc_data["code"].strip().upper()
        if code in existing_codes:
            continue
        try:
            new_acc = Account(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                code=code,
                name=acc_data["name"].strip(),
                description=acc_data.get("description"),
                account_type=acc_data["type"],
                account_sub_type=acc_data.get("sub_type"),
                parent_code=acc_data.get("parent_code") or None,
                allow_entries=acc_data.get("allow_entries", True),
                is_generic=False,
            )
            db.add(new_acc)
            db.flush()
            inserted += 1
            existing_codes.add(code)
        except Exception:
            db.rollback()
            continue

    db.commit()

    return {
        "ok": True,
        "inserted": inserted,
        "skipped": len(seed_accounts) - inserted,
        "message": (
            f"{inserted} cuentas nuevas agregadas al catálogo"
            if inserted > 0
            else "El catálogo ya estaba completo — no se insertó nada"
        )
    }
