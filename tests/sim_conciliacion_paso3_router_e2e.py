"""
SIM E2E PASO 3 — Router REST + Sidebar + Registro en main.py
Verifica estáticamente que el router esté registrado y el sidebar actualizado.
"""
import os, sys, ast

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond:
        print(f"  {OK} {msg}")
    else:
        print(f"  {FAIL} {msg}")
        errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "services", "gateway", "main.py")
SIDEBAR = os.path.join(ROOT, "frontend", "src", "components", "Sidebar.jsx")
ROUTER = os.path.join(ROOT, "services", "conciliacion", "router.py")

# ── 1. router.py existe y tiene los endpoints clave ────────────────────────
print("\n📡 PASO 3A — router.py:")
check(os.path.exists(ROUTER), "services/conciliacion/router.py existe")
with open(ROUTER) as f:
    rsrc = f.read()

ENDPOINTS = [
    "/conciliacion/entidades",
    "/conciliacion/parse",
    "/conciliacion/sesion",
    "/conciliacion/match/",
    "/centinela/analyze/",
    "/centinela/score/",
    "/centinela/d270/",
    "/conciliacion/rule",
    "/conciliacion/rules",
]
for ep in ENDPOINTS:
    check(ep in rsrc, f"  Endpoint '{ep}'")

PYDANTIC = ["ParseRequest", "UploadSession", "BankRule"]
for m in PYDANTIC:
    check(m in rsrc, f"  Modelo Pydantic '{m}'")

# ── 2. main.py importa y registra el router ─────────────────────────────────
print("\n🔗 PASO 3B — Registro en gateway/main.py:")
with open(MAIN) as f:
    msrc = f.read()

check("from services.conciliacion.router import router as conciliacion_router" in msrc,
      "Import conciliacion_router")
check("app.include_router(conciliacion_router)" in msrc,
      "app.include_router(conciliacion_router)")

# ── 3. Sidebar.jsx tiene los 2 nuevos ítems en Generadores ─────────────────
print("\n🗂️  PASO 3C — Sidebar.jsx:")
with open(SIDEBAR) as f:
    ssrc = f.read()

check("Conciliación Bancaria" in ssrc, "Item 'Conciliación Bancaria' en sidebar")
check("/conciliacion"         in ssrc, "Path /conciliacion en sidebar")
check("CENTINELA Fiscal"      in ssrc, "Item 'CENTINELA Fiscal' en sidebar")
check("/centinela"            in ssrc, "Path /centinela en sidebar")
check("🏦"                   in ssrc, "Emoji 🏦 para conciliación")
check("🛡️"                  in ssrc, "Emoji 🛡️ para CENTINELA")

# Verificar que los nuevos ítems están en la sección correcta (Generadores)
gen_start = ssrc.find("'Generadores'")
gen_end   = ssrc.find("section:", gen_start + 1)
gen_block = ssrc[gen_start:gen_end] if gen_start > 0 and gen_end > gen_start else ""
check("Conciliación Bancaria" in gen_block, "Conciliación está en sección Generadores")
check("CENTINELA"             in gen_block, "CENTINELA está en sección Generadores")
check("Registros Contables" not in gen_block, "Registros Contables NO modificado")

# Verificar que Registros Contables sigue igual (solo sus 5 ítems originales)
reg_start = ssrc.find("'Registros Contables'")
reg_end   = ssrc.find("section:", reg_start + 1)
reg_block = ssrc[reg_start:reg_end] if reg_start > 0 and reg_end > reg_start else ""
check("/diario"        in reg_block, "Diario sigue en Registros Contables")
check("/cierre-anual"  in reg_block, "Cierre Anual sigue en Registros Contables")
check("/conciliacion" not in reg_block, "/conciliacion NO está en Registros Contables")

# ── 4. Sintaxis Python básica del router ────────────────────────────────────
print("\n🐍 PASO 3D — Sintaxis Python:")
try:
    compile(rsrc, ROUTER, "exec")
    check(True, "router.py tiene sintaxis Python válida")
except SyntaxError as e:
    check(False, f"Error de sintaxis en router.py: {e}")

# ── Resultado ───────────────────────────────────────────────────────────────
print("\n" + "="*60)
if errors:
    print(f"{FAIL} PASO 3 FALLIDO — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print(f"{OK} PASO 3 VERDE — Router + Sidebar verificados")
    sys.exit(0)
