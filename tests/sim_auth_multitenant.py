"""
Simulación E2E — Paso 2c: Auth Service
Multi-tenant: partner_linked y standalone

Prueba los modelos y la lógica de seguridad sin necesitar DB real.
Ejecutar con: python -m pytest tests/sim_auth_multitenant.py -v
              o: python tests/sim_auth_multitenant.py
"""
import os
import sys
import json

# Configurar JWT_SECRET para el test (nunca hardcodeado en producción)
os.environ["JWT_SECRET"] = "test-secret-para-simulacion-no-usar-en-prod"

# Agregar path del proyecto
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.auth.security import (
    hash_password, verify_password,
    create_access_token, decode_token, extract_tenant_id
)
from services.auth.models import Tenant, User, TenantType, UserRole, TenantStatus

PASS_MARK = "  ✅"
FAIL_MARK = "  ❌"
errors = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"{PASS_MARK} {label}")
    else:
        print(f"{FAIL_MARK} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)


print("\n" + "═"*60)
print("  SIMULACIÓN E2E — Paso 2: Auth Multi-tenant")
print("═"*60)


# ─────────────────────────────────────────────────────────────────
# BLOQUE 1: Password hashing
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 1: Password Hashing")

plain = "MiPassword123!"
hashed = hash_password(plain)

check("Hash no es texto plano", hashed != plain)
check("Hash empieza con $2b$ (bcrypt)", hashed.startswith("$2b$"))
check("Verificación correcta pasa", verify_password(plain, hashed))
check("Verificación incorrecta falla", not verify_password("WrongPass", hashed))
check("Dos hashes del mismo password son distintos",
      hash_password(plain) != hash_password(plain))  # salt aleatorio


# ─────────────────────────────────────────────────────────────────
# BLOQUE 2: JWT para Contador STANDALONE
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 2: JWT — Contador Standalone")

tenant_id_standalone = "ten-standalone-001"
user_id_standalone   = "usr-001"

token_standalone = create_access_token(
    user_id=user_id_standalone,
    tenant_id=tenant_id_standalone,
    tenant_type=TenantType.standalone,
    role=UserRole.admin,
    nombre="Diego Standalone",
)

payload = decode_token(token_standalone)
check("JWT generado y decodificado", bool(payload))
check("sub contiene user_id", payload["sub"] == user_id_standalone)
check("tenant_id en JWT", payload["tenant_id"] == tenant_id_standalone)
check("tenant_type = standalone", payload["tenant_type"] == TenantType.standalone)
check("role = admin", payload["role"] == UserRole.admin)
check("NO hay partner_id en token standalone", "partner_id" not in payload)
check("extract_tenant_id funciona", extract_tenant_id(token_standalone) == tenant_id_standalone)


# ─────────────────────────────────────────────────────────────────
# BLOQUE 3: JWT para Contador PARTNER_LINKED
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 3: JWT — Contador Partner Linked")

tenant_id_partner = "ten-partner-002"
partner_id        = "ptr-genoma-facturador-456"
user_id_partner   = "usr-002"

token_partner = create_access_token(
    user_id=user_id_partner,
    tenant_id=tenant_id_partner,
    tenant_type=TenantType.partner_linked,
    role=UserRole.contador,
    nombre="Ana Partner",
    partner_id=partner_id,
)

payload_p = decode_token(token_partner)
check("JWT partner generado", bool(payload_p))
check("tenant_type = partner_linked", payload_p["tenant_type"] == TenantType.partner_linked)
check("partner_id presente en token", payload_p.get("partner_id") == partner_id)


# ─────────────────────────────────────────────────────────────────
# BLOQUE 4: Aislamiento Multi-tenant
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 4: Aislamiento Multi-tenant")

tid_a = extract_tenant_id(token_standalone)
tid_b = extract_tenant_id(token_partner)
check("Tenant A ≠ Tenant B", tid_a != tid_b)
check("Token A no filtra datos de B",
      tid_a == tenant_id_standalone and tid_b == tenant_id_partner)

# Simular que un query usa el tenant_id del JWT (nunca del body)
def simular_query_tenant(token: str, dato: str) -> bool:
    """El dato pertenece al tenant del token — simula WHERE tenant_id = X"""
    tid = extract_tenant_id(token)
    # En producción: SELECT ... WHERE tenant_id = tid
    # Aquí solo verificamos que el tenant_id se usa correctamente
    return tid in dato

dato_tenant_a = f"asiento-{tenant_id_standalone}-001"
dato_tenant_b = f"asiento-{tenant_id_partner}-001"

check("Token A solo ve datos de A", simular_query_tenant(token_standalone, dato_tenant_a))
check("Token A NO ve datos de B",  not simular_query_tenant(token_standalone, dato_tenant_b))
check("Token B solo ve datos de B", simular_query_tenant(token_partner, dato_tenant_b))


# ─────────────────────────────────────────────────────────────────
# BLOQUE 5: Modelos SQLAlchemy (sin DB)
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 5: Modelos SQLAlchemy (estructura)")

# Verificar que los modelos tienen los campos correctos
tenant_cols = {c.name for c in Tenant.__table__.columns}
user_cols   = {c.name for c in User.__table__.columns}

check("Tenant tiene id", "id" in tenant_cols)
check("Tenant tiene cedula", "cedula" in tenant_cols)
check("Tenant tiene tenant_type", "tenant_type" in tenant_cols)
check("Tenant tiene partner_id", "partner_id" in tenant_cols)
check("Tenant tiene facturador_api_key", "facturador_api_key" in tenant_cols)
check("User tiene tenant_id (FK)", "tenant_id" in user_cols)
check("User tiene role", "role" in user_cols)
check("User tiene is_active", "is_active" in user_cols)
check("Constraint email+tenant_id existe",
      any(getattr(c, 'name', '') == "uq_user_email_tenant"
          for c in User.__table__.constraints))


# ─────────────────────────────────────────────────────────────────
# BLOQUE 6: Token inválido es rechazado
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 6: Tokens inválidos")
from jose import JWTError

try:
    decode_token("este.token.es.falso")
    check("Token falso es rechazado", False, "Debió lanzar JWTError")
except JWTError:
    check("Token falso lanza JWTError", True)

try:
    # Token firmado con otro secret
    import os as _os
    _os.environ["JWT_SECRET"] = "otro-secret-diferente"
    from services.auth import security as _sec
    _sec.JWT_SECRET = "otro-secret-diferente"
    wrong_token = _sec.create_access_token("u", "t", "standalone", "admin", "Test")
    _sec.JWT_SECRET = "test-secret-para-simulacion-no-usar-en-prod"
    _os.environ["JWT_SECRET"] = "test-secret-para-simulacion-no-usar-en-prod"
    decode_token(wrong_token)
    check("Token de otro secret es rechazado", False, "Debió lanzar JWTError")
except JWTError:
    check("Token de otro secret lanza JWTError", True)


# ─────────────────────────────────────────────────────────────────
# RESULTADO FINAL
# ─────────────────────────────────────────────────────────────────
print("\n" + "═"*60)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — Paso 2c APROBADO")
    print("     → Modelos correctos")
    print("     → JWT multi-tenant con tenant_id embebido")
    print("     → Aislamiento partner_linked vs standalone verificado")
    print("     → Tokens inválidos son rechazados")
print("═"*60 + "\n")
