"""
sim_switch_tenant.py — SIM Test: POST /auth/switch-tenant
══════════════════════════════════════════════════════════
Verifica que al cambiar de tenant el sistema emite un nuevo JWT
con el tenant_id correcto.

Patrón Genoma: llamada directa a la función del endpoint,
inyectando current_user y db como dicts/mocks de Python puro.
Sin TestClient, sin servidor HTTP, sin DB real.

Escenarios:
  SC-1 · partner_linked → JWT con tenant_id del cliente seleccionado
  SC-2 · El JWT nuevo tiene tenant_id DIFERENTE al original
  SC-3 · standalone no puede hacer switch a tenant ajeno (404)
  SC-4 · El facturador_token se preserva en el nuevo JWT
  SC-5 · El tenant_id del nuevo JWT se puede decodificar y verificar
"""

import os
import sys

os.environ.setdefault("JWT_SECRET", "test-secret-sim-switch-tenant")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock
from fastapi import HTTPException
from jose import jwt as jose_jwt

from services.auth.security import (
    create_access_token, JWT_SECRET, JWT_ALGORITHM
)
from services.auth.models import TenantType, UserRole, TenantStatus
from services.auth.router import switch_tenant, SwitchTenantRequest

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS_MARK = "  ✅"
FAIL_MARK = "  ❌"
errors = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"{PASS_MARK} {label}")
    else:
        msg = f"{FAIL_MARK} {label}" + (f" — {detail}" if detail else "")
        print(msg)
        errors.append(label)


def _decode(token: str) -> dict:
    return jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _partner_current_user(tenant_id: str = "GC-0001", sub: str = "partner-uuid-001") -> dict:
    """Simula current_user de un partner_linked (ya autenticado)."""
    return {
        "sub":              sub,
        "tenant_id":        tenant_id,
        "tenant_type":      TenantType.partner_linked.value,
        "role":             UserRole.admin.value,
        "nombre":           "Despacho Demo",
        "partner_id":       "GC-0001",
        "partner_uuid":     sub,
        "facturador_token": "tok_facturador_opaco_xyz",
    }


def _standalone_current_user(tenant_id: str, sub: str) -> dict:
    """Simula current_user de un standalone (ya autenticado)."""
    return {
        "sub":         sub,
        "tenant_id":   tenant_id,
        "tenant_type": TenantType.standalone.value,
        "role":        UserRole.admin.value,
        "nombre":      "Usuario Demo",
    }


def _mock_db_no_tenant() -> MagicMock:
    """Mock DB donde NO existe el tenant objetivo → simula tenant ajeno."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    return db


def _mock_db_with_tenant(tenant_id: str, user_id: str, same_tenant: bool = True) -> MagicMock:
    """
    Mock DB donde sí existe el tenant objetivo.
    Si same_tenant=True: el usuario pertenece a ese tenant (acceso OK).
    Si same_tenant=False: el usuario pertenece a OTRO tenant (acceso denegado).
    """
    db = MagicMock()

    mock_tenant = MagicMock()
    mock_tenant.id     = tenant_id
    mock_tenant.nombre = "Empresa Test"
    mock_tenant.cedula = "3101000001"
    mock_tenant.status = TenantStatus.trial

    mock_user = MagicMock()
    mock_user.id        = user_id
    mock_user.tenant_id = tenant_id if same_tenant else "otro-tenant-uuid"

    # Primera llamada → Tenant; segunda → User
    db.query.return_value.filter.return_value.first.side_effect = [
        mock_tenant,
        mock_user,
    ]
    return db


# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
print("   SIM TEST — POST /auth/switch-tenant")
print("═" * 60)

# ─────────────────────────────────────────────────────────────────────────────
# SC-1 · partner_linked → JWT con tenant_id del cliente seleccionado
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-1  partner_linked → JWT con tenant_id del cliente")

TARGET_TENANT_1 = "cliente-uuid-alvaro"
current_user_1  = _partner_current_user(tenant_id="GC-0001")
req_1           = SwitchTenantRequest(tenant_id=TARGET_TENANT_1, nombre="Álvaro López")
db_1            = MagicMock()  # partner_linked no consulta la DB

try:
    resp_1 = switch_tenant(req_1, current_user_1, db_1)
    new_payload_1 = _decode(resp_1["access_token"])
    check("Retorna access_token", "access_token" in resp_1)
    check(
        f"JWT.tenant_id = {TARGET_TENANT_1}",
        new_payload_1["tenant_id"] == TARGET_TENANT_1,
        f"got: {new_payload_1['tenant_id']!r}"
    )
    check("tenant_type preservado (partner_linked)", new_payload_1["tenant_type"] == TenantType.partner_linked.value)
except Exception as e:
    check("SC-1 sin excepción", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SC-2 · El JWT nuevo tiene tenant_id DIFERENTE al original
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-2  JWT nuevo ≠ JWT original")

ORIGINAL_TENANT_2 = "GC-0001"
TARGET_TENANT_2   = "cliente-uuid-angelica"
current_user_2    = _partner_current_user(tenant_id=ORIGINAL_TENANT_2)
req_2             = SwitchTenantRequest(tenant_id=TARGET_TENANT_2, nombre="Angélica Méndez")
db_2              = MagicMock()

try:
    resp_2      = switch_tenant(req_2, current_user_2, db_2)
    new_payload_2 = _decode(resp_2["access_token"])
    check(
        "JWT nuevo != tenant original",
        new_payload_2["tenant_id"] != ORIGINAL_TENANT_2,
        f"Ambos tienen tenant_id={ORIGINAL_TENANT_2}"
    )
    check(
        f"JWT nuevo tiene tenant correcto ({TARGET_TENANT_2})",
        new_payload_2["tenant_id"] == TARGET_TENANT_2,
        f"got: {new_payload_2['tenant_id']!r}"
    )
except Exception as e:
    check("SC-2 sin excepción", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SC-3 · standalone no puede hacer switch a tenant ajeno → 404
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-3  standalone no puede hacer switch a tenant ajeno")

MY_TENANT_3    = "tenant-standalone-a"
OTHER_TENANT_3 = "tenant-standalone-b"
MY_USER_3      = "user-uuid-standalone-001"

current_user_3 = _standalone_current_user(tenant_id=MY_TENANT_3, sub=MY_USER_3)
req_3          = SwitchTenantRequest(tenant_id=OTHER_TENANT_3)
db_3           = _mock_db_no_tenant()

try:
    switch_tenant(req_3, current_user_3, db_3)
    check("SC-3 lanza HTTPException", False, "Se esperaba 404 o 403, pero el endpoint tuvo éxito")
except HTTPException as exc:
    check(
        f"Switch a tenant ajeno retorna HTTP {exc.status_code} (403/404)",
        exc.status_code in (403, 404),
        f"got HTTP {exc.status_code}"
    )
except Exception as e:
    check("SC-3 lanza HTTPException correcta", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SC-4 · facturador_token se preserva en el nuevo JWT
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-4  facturador_token preservado en el nuevo JWT")

FACTURADOR_TOKEN = "tok_facturador_opaco_xyz"
current_user_4   = _partner_current_user(tenant_id="GC-0001")
req_4            = SwitchTenantRequest(tenant_id="cliente-uuid-sa", nombre="SA Corp")
db_4             = MagicMock()

try:
    resp_4      = switch_tenant(req_4, current_user_4, db_4)
    new_payload_4 = _decode(resp_4["access_token"])
    check(
        "facturador_token en JWT nuevo",
        new_payload_4.get("facturador_token") == FACTURADOR_TOKEN,
        f"got: {new_payload_4.get('facturador_token')!r}"
    )
    check(
        "partner_uuid preservado",
        new_payload_4.get("partner_uuid") == "partner-uuid-001",
        f"got: {new_payload_4.get('partner_uuid')!r}"
    )
except Exception as e:
    check("SC-4 sin excepción", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# SC-5 · Aislamiento: Álvaro (A) y Angélica (B) tienen JWTs distintos
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-5  Aislamiento completo: tenant A vs tenant B")

current_user_5 = _partner_current_user(tenant_id="GC-0001")
db_5           = MagicMock()

req_a = SwitchTenantRequest(tenant_id="cliente-uuid-alvaro",   nombre="Álvaro")
req_b = SwitchTenantRequest(tenant_id="cliente-uuid-angelica", nombre="Angélica")

try:
    jwt_a = switch_tenant(req_a, current_user_5, db_5)["access_token"]
    jwt_b = switch_tenant(req_b, current_user_5, db_5)["access_token"]

    payload_a = _decode(jwt_a)
    payload_b = _decode(jwt_b)

    check("JWT de Álvaro ≠ JWT de Angélica (tokens distintos)", jwt_a != jwt_b)
    check("Álvaro.tenant_id = cliente-uuid-alvaro",   payload_a["tenant_id"] == "cliente-uuid-alvaro")
    check("Angélica.tenant_id = cliente-uuid-angelica", payload_b["tenant_id"] == "cliente-uuid-angelica")
    check("tenant_ids son distintos entre sí",        payload_a["tenant_id"] != payload_b["tenant_id"])
except Exception as e:
    check("SC-5 sin excepción", False, str(e))

# ─────────────────────────────────────────────────────────────────────────────
# RESULTADO FINAL
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    print("═" * 60 + "\n")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — switch-tenant VERIFICADO")
    print("     → JWT nuevo contiene tenant_id del cliente seleccionado")
    print("     → JWT nuevo ≠ JWT original (aislamiento real)")
    print("     → standalone rechaza switch a tenant ajeno (403/404)")
    print("     → facturador_token preservado en el nuevo JWT")
    print("     → Álvaro y Angélica obtienen JWTs completamente distintos")
    print("═" * 60 + "\n")
