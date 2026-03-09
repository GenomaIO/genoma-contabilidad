#!/usr/bin/env python3
"""
sim_catalogo_reguladora_e2e.py — SIM + E2E
==========================================
Verifica que la columna es_reguladora está correctamente manejada en:
  1. Modelo SQLAlchemy (catalog/models.py)
  2. Migración en main.py (M_CATALOG_V2)
  3. Schema Pydantic de salida (AccountOut)
  4. Tooltip 💡 en Conciliacion.jsx
"""
import sys, os, pathlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0
FAIL = 0

def check(condition: bool, label: str):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition:
        PASS += 1
    else:
        FAIL += 1

# ─────────────────────────────────────────────────────────────────────────────
print("\n[SIM-1] Modelo SQLAlchemy — Account.es_reguladora")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from services.catalog.models import Account
    col = Account.__table__.columns.get("es_reguladora")
    check(col is not None, "Column 'es_reguladora' existe en Account.__table__")
    if col is not None:
        check(str(col.type).startswith("BOOLEAN"), f"Tipo es BOOLEAN (got: {col.type})")
        check(col.default is not None or col.server_default is not None, "Tiene DEFAULT")
except Exception as ex:
    check(False, f"Import Account falló: {ex}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n[SIM-2] Migración M_CATALOG_V2 en main.py")
# ─────────────────────────────────────────────────────────────────────────────
main_path = ROOT / "services" / "gateway" / "main.py"
main_src = main_path.read_text(encoding="utf-8")
check("M_CATALOG_V2" in main_src, "main.py contiene M_CATALOG_V2")
check("es_reguladora" in main_src, "main.py menciona es_reguladora")
check("ADD COLUMN IF NOT EXISTS es_reguladora" in main_src, "ALTER TABLE usa ADD COLUMN IF NOT EXISTS")

# ─────────────────────────────────────────────────────────────────────────────
print("\n[SIM-3] Schema Pydantic AccountOut — serializa es_reguladora")
# ─────────────────────────────────────────────────────────────────────────────
try:
    from services.catalog.router import AccountOut
    fields = AccountOut.model_fields
    check("es_reguladora" in fields, "AccountOut tiene campo es_reguladora")
except Exception as ex:
    check(False, f"Import AccountOut falló: {ex}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n[SIM-4] Frontend — Tooltip 💡 en Conciliacion.jsx")
# ─────────────────────────────────────────────────────────────────────────────
conc_path = ROOT / "frontend" / "src" / "pages" / "Conciliacion.jsx"
conc_src = conc_path.read_text(encoding="utf-8")
check("diff-tip" in conc_src, "Conciliacion.jsx contiene clase diff-tip (tooltip)")
check("¿Cómo se calcula?" in conc_src, "Tooltip tiene contenido '¿Cómo se calcula?'")
check("Diferencia = Banco" in conc_src, "Tooltip muestra fórmula 'Diferencia = Banco − Libros'")
check("cursor: 'help'" in conc_src, "Ícono 💡 tiene cursor: help")

# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"  Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*50}\n")
sys.exit(0 if FAIL == 0 else 1)
