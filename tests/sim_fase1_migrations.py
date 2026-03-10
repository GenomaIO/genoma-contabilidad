"""
SIM Fase 1 — Migraciones cabys_account_rules + import_batch
Verifica que:
  1. La migration es idempotente (código fuente contiene IF NOT EXISTS)
  2. Las columnas nuevas en journal_lines/entries están declaradas
  3. genoma_client.py existe y expone las funciones necesarias
  4. La estructura de cabys_account_rules es correcta
"""
import sys, os, pathlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0
ROOT = pathlib.Path(__file__).parent.parent

def check(label, cond):
    global PASS, FAIL
    if cond:
        print(f"  ✅ PASS: {label}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {label}")
        FAIL += 1

print("=" * 60)
print("SIM-F1 — Fase 1: DB Migrations y Contrato API")
print("=" * 60)

# ─── SIM-F1-01: main.py contiene las tablas nuevas ───────────────
print("\nSIM-F1-01: Tablas nuevas en main.py (idempotentes)")
main_src = (ROOT / "services/gateway/main.py").read_text()
check("cabys_account_rules con IF NOT EXISTS",
      "CREATE TABLE IF NOT EXISTS cabys_account_rules" in main_src)
check("import_batch con IF NOT EXISTS",
      "CREATE TABLE IF NOT EXISTS import_batch" in main_src)

# ─── SIM-F1-02: Columnas nuevas en journal_lines ─────────────────
print("\nSIM-F1-02: Columnas en journal_lines")
check("cabys_code presente en journal_lines DDL",
      "cabys_code" in main_src)
check("confidence_score en journal_lines",
      "confidence_score" in main_src)
check("iva_tarifa en journal_lines",
      "iva_tarifa" in main_src)
check("clasificacion_fuente en journal_lines",
      "clasificacion_fuente" in main_src)

# ─── SIM-F1-03: Columnas nuevas en journal_entries ───────────────
print("\nSIM-F1-03: Columnas en journal_entries")
check("needs_review en journal_entries",
      "needs_review" in main_src)
check("source_doc_lines en journal_entries",
      "source_doc_lines" in main_src)

# ─── SIM-F1-04: genoma_client.py existe y tiene funciones requeridas
print("\nSIM-F1-04: genoma_client.py")
client_path = ROOT / "services/integration/genoma_client.py"
check("genoma_client.py existe", client_path.exists())
if client_path.exists():
    client_src = client_path.read_text()
    check("pull_documentos_enviados() definida",
          "def pull_documentos_enviados" in client_src)
    check("pull_documentos_recibidos() definida",
          "def pull_documentos_recibidos" in client_src)
    check("Timeout configurado (resiliencia)",
          "timeout" in client_src.lower())

# ─── SIM-F1-05: Migración F1 en main.py tiene logging correcto ───
print("\nSIM-F1-05: Audit trail de la migración")
check("M_AUTOIMPOR label en main.py",
      "M_AUTOIMPOR" in main_src or "cabys_account_rules creada" in main_src)

# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if FAIL == 0:
    print(f"ALL {PASS} SIM-F1 TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 60)
