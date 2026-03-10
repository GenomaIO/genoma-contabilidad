"""
tests/sim_fase5_genoma_client_v2.py  (v3 update)
════════════════════════════════════════════════════════════
SIM pre-push para genoma_client.py v3 (Arquitectura Correcta).
Verifica:
  1. Sintaxis Python válida
  2. Funciones clave definidas
  3. URLs correctas (nuevo endpoint partner portal del Facturador)
  4. _period_to_dates — conversión YYYYMM correcta
  5. pull_documentos_enviados acepta facturador_token + cliente_tenant_id
  6. pull_documentos_recibidos acepta facturador_token + cliente_tenant_id
  7. Manejo de TOKEN_EXPIRADO sin crash
  8. Período inválido retorna error limpio
"""
import sys, os, ast, inspect

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  ✅ PASS: {name}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {name}" + (f" → {detail}" if detail else ""))
        FAIL += 1

print("\n════════════════════════════════════════")
print("SIM-F5 genoma_client.py v3 (Arquitectura Correcta)")
print("════════════════════════════════════════\n")

# ─── TEST 1: Sintaxis válida ─────────────────────────────
print("⟹ T1: Sintaxis Python")
path = os.path.join(os.path.dirname(__file__), "..", "services", "integration", "genoma_client.py")
with open(path) as f:
    src = f.read()
try:
    ast.parse(src)
    check("Sintaxis Python válida", True)
except SyntaxError as e:
    check("Sintaxis Python válida", False, str(e))

# ─── TEST 2: Funciones clave presentes ───────────────────
print("\n⟹ T2: Funciones clave definidas")
check("pull_documentos_enviados definida",  "def pull_documentos_enviados" in src)
check("pull_documentos_recibidos definida", "def pull_documentos_recibidos" in src)
check("_period_to_dates definida",          "def _period_to_dates" in src)

# ─── TEST 3: URLs correctas ──────────────────────────────
print("\n⟹ T3: URL apunta al endpoint correcto del partner portal")
check("Usa /api/partners/portal/cliente/",    "/api/partners/portal/cliente/" in src)
check("NO usa /invoices/list (endpoint antiguo)",          "/invoices/list" not in src)
check("NO usa /api/reception/list (endpoint antiguo)",     "/api/reception/list" not in src)
check("Usa X-Partner-Token como header",    "X-Partner-Token" in src)

# ─── TEST 4: _period_to_dates ────────────────────────────
print("\n⟹ T4: _period_to_dates — conversión de período")
from services.integration.genoma_client import _period_to_dates

d1, d2 = _period_to_dates("202603")
check("Desde = 2026-03-01",     d1 == "2026-03-01", f"obtuvo: {d1}")
check("Hasta = 2026-03-31",     d2 == "2026-03-31", f"obtuvo: {d2}")
d3, d4 = _period_to_dates("202602")
check("Feb 2026 hasta = 2026-02-28", d4 == "2026-02-28", f"obtuvo: {d4}")
d5, d6 = _period_to_dates("INVALIDO")
check("Período inválido → (None, None)", d5 is None and d6 is None)

# ─── TEST 5: Firma de pull_documentos_enviados ───────────
print("\n⟹ T5: Firma de pull_documentos_enviados — v3 correcta")
from services.integration.genoma_client import pull_documentos_enviados
sig = inspect.signature(pull_documentos_enviados)
params = list(sig.parameters.keys())
check("Acepta facturador_token",   "facturador_token"  in params, f"params={params}")
check("Acepta cliente_tenant_id",  "cliente_tenant_id" in params, f"params={params}")
check("NO acepta tenant_token (v1/v2)", "tenant_token" not in params, f"params={params}")

# ─── TEST 6: Firma de pull_documentos_recibidos ──────────
print("\n⟹ T6: Firma de pull_documentos_recibidos — v3 correcta")
from services.integration.genoma_client import pull_documentos_recibidos
sig2 = inspect.signature(pull_documentos_recibidos)
params2 = list(sig2.parameters.keys())
check("Acepta facturador_token",   "facturador_token"  in params2)
check("Acepta cliente_tenant_id",  "cliente_tenant_id" in params2)

# ─── TEST 7: Manejo de token vacío ──────────────────────
print("\n⟹ T7: Token vacío retorna TOKEN_EXPIRADO sin crash")
result_vacio = pull_documentos_enviados(
    facturador_token="",
    cliente_tenant_id="some-tenant",
    period="202603"
)
check("ok=False cuando token vacío",      result_vacio["ok"] is False)
check("error=TOKEN_EXPIRADO",             result_vacio.get("error") == "TOKEN_EXPIRADO")
check("error_detail presente",            bool(result_vacio.get("error_detail")))

result_none = pull_documentos_enviados(
    facturador_token=None,
    cliente_tenant_id="some-tenant",
    period="202603"
)
check("ok=False cuando token None",       result_none["ok"] is False)

# ─── TEST 8: Período inválido no crashea ────────────────
print("\n⟹ T8: Período inválido retorna error limpio")
result_inv = pull_documentos_enviados(
    facturador_token="tok123",
    cliente_tenant_id="tenant-abc",
    period="INVALIDO"
)
check("ok=False con período inválido",   result_inv["ok"] is False)
check("items=[] con período inválido",   result_inv.get("items") == [])

# ─── RESUMEN ─────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'='*60}")
if FAIL == 0:
    print(f"ALL {total} SIM-F5 TESTS PASSED ✅")
    print("🟢 genoma_client v3 lista — arquitectura correcta con X-Partner-Token")
else:
    print(f"{PASS}/{total} passed — {FAIL} FAILED ❌ — revisar antes de push")
print(f"{'='*60}\n")

sys.exit(1 if FAIL > 0 else 0)
