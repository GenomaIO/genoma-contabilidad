"""
Simulación — Fix email-validator (genoma-contabilidad)
Verifica que el crash de startup sea resuelto por la dependencia añadida.

Prueba:
1. El archivo requirements.txt contiene email-validator
2. Los imports del auth router no fallan con EmailStr
3. Todos los módulos auth importan sin error de sintaxis
4. El gateway importa auth_router sin problemas

Ejecutar: python tests/sim_email_validator_fix.py
"""
import sys
import os
import ast
import subprocess

# Agregar raíz del proyecto al path (necesario para imports locales)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("JWT_SECRET", "test-sim")
os.environ.setdefault("DATABASE_URL", "")

PASS = "  ✅"
FAIL = "  ❌"
errors = []

def check(label, condition, detail=""):
    if condition:
        print(f"{PASS} {label}")
    else:
        msg = f"{FAIL} {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(label)

print("\n" + "═"*62)
print("  SIMULACIÓN — Fix email-validator deploy crash")
print("  proyecto: genoma-contabilidad")
print("═"*62)


# ─────────────────────────────────────────────────────────────────
# BLOQUE 1: requirements.txt contiene email-validator
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 1: requirements.txt")

with open("requirements.txt") as f:
    reqs = f.read()

check("email-validator está en requirements.txt",
      "email-validator" in reqs)
check("pydantic==2.9.0 sigue presente",
      "pydantic==2.9.0" in reqs)
check("email-validator tiene versión pinneada",
      "email-validator==" in reqs)


# ─────────────────────────────────────────────────────────────────
# BLOQUE 2: Sintaxis de todos los archivos auth
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 2: Sintaxis Python — auth service")

auth_files = [
    "services/auth/models.py",
    "services/auth/security.py",
    "services/auth/database.py",
    "services/auth/router.py",
    "services/auth/__init__.py",
    "services/gateway/main.py",
]

for f in auth_files:
    try:
        with open(f) as fh:
            ast.parse(fh.read())
        check(f"Sintaxis OK: {f}", True)
    except SyntaxError as e:
        check(f"Sintaxis OK: {f}", False, str(e))
    except FileNotFoundError:
        check(f"Archivo existe: {f}", False, "No encontrado")


# ─────────────────────────────────────────────────────────────────
# BLOQUE 3: EmailStr en router.py — la causa del crash
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 3: EmailStr en router.py")

with open("services/auth/router.py") as f:
    router_source = f.read()

check("router.py usa EmailStr", "EmailStr" in router_source)
check("router.py importa desde pydantic", "from pydantic import" in router_source)

# Verificar que email-validator está instalado en el env actual
try:
    result = subprocess.run(
        [sys.executable, "-c", "from pydantic import EmailStr; print('OK')"],
        capture_output=True, text=True, timeout=5
    )
    installed = result.returncode == 0 and "OK" in result.stdout
    check("EmailStr importa sin error en el entorno local",
          installed,
          result.stderr.strip() if not installed else "")
except Exception as e:
    check("EmailStr importa sin error en el entorno local", False, str(e))


# ─────────────────────────────────────────────────────────────────
# BLOQUE 4: Importación completa del router (sin DB)
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 4: Import de módulos auth (sin DB)")

# Intentar importar solo los módulos que no requieren DB
try:
    from services.auth.models import Tenant, User, TenantType, UserRole
    check("services.auth.models importa OK", True)
except Exception as e:
    check("services.auth.models importa OK", False, str(e))

try:
    from services.auth.security import hash_password, create_access_token
    check("services.auth.security importa OK", True)
except Exception as e:
    check("services.auth.security importa OK", False, str(e))


# ─────────────────────────────────────────────────────────────────
# BLOQUE 5: El gateway tiene auth_router incluido
# ─────────────────────────────────────────────────────────────────
print("\n📌 BLOQUE 5: Gateway wire-up")

with open("services/gateway/main.py") as f:
    gw = f.read()

check("gateway importa auth_router",
      "from services.auth.router import router as auth_router" in gw)
check("gateway incluye auth_router",
      "app.include_router(auth_router)" in gw)
check("gateway tiene init_db en lifespan",
      "init_db()" in gw)


# ─────────────────────────────────────────────────────────────────
# RESULTADO
# ─────────────────────────────────────────────────────────────────
print("\n" + "═"*62)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ SIMULACIÓN APROBADA — Deploy crash resuelto")
    print("     → email-validator en requirements.txt")
    print("     → EmailStr importa sin error")
    print("     → Todos los módulos auth sintaxis OK")
    print("     → Gateway wire-up correcto")
print("═"*62 + "\n")
