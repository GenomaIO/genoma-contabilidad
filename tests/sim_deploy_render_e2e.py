"""
SIM E2E Deploy-Ready — Verifica que el proyecto está listo para Render:
  1. requirements.txt tiene pdfplumber + xlrd
  2. main.py tiene migración idempotente de 4 tablas bancarias
  3. render.yaml tiene el servicio y la DB configurados
  4. El router de conciliación está incluido en main.py
  5. Frontend dist existe (build previo)
"""
import os, sys

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else: print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def read(rel):
    with open(os.path.join(ROOT, rel)) as f: return f.read()

# ── requirements.txt ─────────────────────────────────────────────────────────
print("\n📦 Dependencias Python (requirements.txt):")
req = read("requirements.txt")
check("fastapi"       in req, "fastapi presente")
check("sqlalchemy"    in req, "sqlalchemy presente")
check("openpyxl"      in req, "openpyxl (Excel XLSX)")
check("pdfplumber"    in req, "pdfplumber (PDF bancario)")
check("xlrd"          in req, "xlrd (Excel XLS legacy)")
check("psycopg2"      in req, "psycopg2 (PostgreSQL)")
check("httpx"         in req, "httpx (TC BCCR)")

# ── main.py — migración + router ─────────────────────────────────────────────
print("\n🚀 gateway/main.py:")
main = read("services/gateway/main.py")
check("bank_reconciliation"  in main, "CREATE TABLE bank_reconciliation")
check("bank_transactions"    in main, "CREATE TABLE bank_transactions")
check("bank_rules"           in main, "CREATE TABLE bank_rules")
check("centinela_score"      in main, "CREATE TABLE centinela_score")
check("CREATE TABLE IF NOT EXISTS" in main, "Migración idempotente (IF NOT EXISTS)")
check("conciliacion_router"  in main, "/conciliacion router incluido")
check("CENTINELA" in main or "centinela" in main, "CENTINELA referenciado")
check("_bank_err"            in main, "Bloque try/except de migración bancaria")

# ── render.yaml ──────────────────────────────────────────────────────────────
print("\n☁️  render.yaml:")
ry = read("render.yaml")
check("genoma-contabilidad-api" in ry, "Nombre del servicio")
check("healthCheckPath" in ry, "healthCheckPath configurado")
check("DATABASE_URL"    in ry, "DATABASE_URL desde managed DB")
check("genoma-contabilidad-db" in ry, "Base de datos gestionada")
check("branch: main"    in ry, "Branch main configurado")

# ── Módulos de conciliación ───────────────────────────────────────────────────
print("\n🏦 Módulos backend:")
check(os.path.exists(os.path.join(ROOT, "services/conciliacion/router.py")),             "router.py")
check(os.path.exists(os.path.join(ROOT, "services/conciliacion/file_parser.py")),         "file_parser.py")
check(os.path.exists(os.path.join(ROOT, "services/conciliacion/reconciliation_engine.py")), "reconciliation_engine.py")
check(os.path.exists(os.path.join(ROOT, "services/conciliacion/fiscal_engine.py")),       "fiscal_engine.py (CENTINELA)")
check(os.path.exists(os.path.join(ROOT, "services/conciliacion/bccr_exchange.py")),       "bccr_exchange.py (TC USD)")

# ── Frontend ──────────────────────────────────────────────────────────────────
print("\n🖥️  Frontend:")
check(os.path.exists(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")), "Conciliacion.jsx")
check(os.path.exists(os.path.join(ROOT, "frontend/src/pages/Centinela.jsx")),    "Centinela.jsx")
dist = os.path.join(ROOT, "frontend/dist/index.html")
check(os.path.exists(dist), "frontend/dist/index.html (build previo)")

print("\n" + "="*60)
if errors:
    print(f"{FAIL} DEPLOY-SIM FALLIDO — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print(f"{OK} DEPLOY-SIM VERDE — Proyecto listo para Render")
    sys.exit(0)
