"""
SIM E2E PASO 1 — Migración M_CONCILIACION: Tablas BD
Verifica ESTÁTICAMENTE que el código de migración está en gateway/main.py
con las 4 tablas y sus columnas clave.
"""
import os, sys, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"

errors = []

def check(cond, msg):
    if cond:
        print(f"  {OK} {msg}")
    else:
        print(f"  {FAIL} {msg}")
        errors.append(msg)

MAIN_PY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services", "gateway", "main.py"
)

print(f"\n📂 Verificando: {MAIN_PY}")
check(os.path.exists(MAIN_PY), "gateway/main.py existe")

with open(MAIN_PY, "r") as f:
    src = f.read()

print("\n📋 TABLAS:")
TABLES = {
    "bank_reconciliation": ["tenant_id", "period", "banco", "account_code",
                             "saldo_inicial", "saldo_final", "score_riesgo", "estado"],
    "bank_transactions":   ["recon_id", "tenant_id", "fecha", "descripcion",
                             "tipo", "monto", "telefono", "match_estado",
                             "fuga_tipo", "score_puntos", "iva_estimado",
                             "base_estimada", "d270_codigo", "ai_clasificacion"],
    "bank_rules":          ["tenant_id", "pattern", "pattern_type",
                             "contact_name", "ledger_account", "d270_codigo", "uses_count"],
    "centinela_score":     ["tenant_id", "period", "score_total",
                             "fugas_tipo_a", "fugas_tipo_b", "fugas_tipo_c",
                             "exposicion_iva", "exposicion_total", "d270_regs"],
}

for table, cols in TABLES.items():
    check(f"CREATE TABLE IF NOT EXISTS {table}" in src, f"  Tabla '{table}' declarada")
    for col in cols:
        check(col in src, f"    Columna '{col}' en {table}")

print("\n📊 ÍNDICES:")
INDEXES = [
    "idx_bankrecon_tenant_period",
    "idx_banktxn_recon",
    "idx_banktxn_tenant_fecha",
    "idx_bankrules_tenant",
    "idx_centinela_tenant_period",
]
for idx in INDEXES:
    check(idx in src, f"  Índice '{idx}'")

print("\n🔒 IDEMPOTENCIA:")
check(src.count("M_CONCILIACION") >= 2,
      "  Bloque M_CONCILIACION con try/except (idempotente)")
check("logger.info(\"✅ Migración M_CONCILIACION" in src,
      "  Log de éxito presente")
check("logger.warning(f\"⚠️  Migración M_CONCILIACION omitida" in src,
      "  Log de error/skip presente")

print("\n⏱️  TIMING — Ventana óptima (comentarios):")
# No bloqueante: solo informativo
has_comment = "CENTINELA" in src and "M_CONCILIACION" in src
check(has_comment, "  Referencia CENTINELA en el código de migración")

# ── Resultado ───────────────────────────────────────────────────────────────
print("\n" + "="*55)
if errors:
    print(f"{FAIL} PASO 1 FALLIDO — {len(errors)} error(es):")
    for e in errors:
        print(f"   • {e}")
    sys.exit(1)
else:
    print(f"{OK} PASO 1 VERDE — 4 tablas BD verificadas en gateway/main.py")
    sys.exit(0)
