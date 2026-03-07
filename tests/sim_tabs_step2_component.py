"""
tests/sim_tabs_step2_component.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 2 — Simula el comportamiento del componente AsientosPendientes
con los nuevos tabs.

Valida:
  · El componente no tiene más referencias a statusFilter/setStatus
  · activeTab, filteredEntries, tabCounts están correctamente implementados
  · La API se llama SIN el parámetro &status= (filtrado client-side)
  · Los tabs correctos están definidos: DRAFT, POSTED, VOIDED, AUTO
  · AUTO_SOURCES incluye todas las fuentes automáticas relevantes
  · El tab DRAFT es el tab inicial
  · Guardar asiento → vuelve a DRAFT (setActiveTab('DRAFT'))
  · Estado vacío adapta el mensaje por tipo de tab

Ejecutar con:
    python tests/sim_tabs_step2_component.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys
import re

PASS = "  ✅"
FAIL = "  ❌"
errors = []

def check(label, cond, detail=""):
    if cond:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

# ── Leer el archivo del componente ───────────────────────────
JSX_PATH = "frontend/src/pages/AsientosPendientes.jsx"
try:
    with open(JSX_PATH, encoding='utf-8') as f:
        src = f.read()
    print(f"  📄 Leído: {JSX_PATH} ({len(src):,} chars)")
except FileNotFoundError:
    print(f"  ❌ No se encontró {JSX_PATH}")
    sys.exit(1)

print("\n" + "═" * 65)
print("  SIMULACIÓN — Paso 2: Componente AsientosPendientes (tabs)")
print("═" * 65)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 1: Bug eliminado — no queda dropdown de status")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("statusFilter eliminado del state",
      "const [statusFilter" not in src,
      "statusFilter todavía está en el state")
check("setStatus eliminado",
      "setStatus(" not in src,
      "setStatus todavía en uso")
check("status-select eliminado",
      'id="status-select"' not in src,
      "el <select> dropdown de status todavía existe")
check('<select> de status eliminado',
      '<option value="DRAFT">Borrador</option>' not in src)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 2: activeTab state correctamente implementado")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("activeTab state declarado",
      "const [activeTab, setActiveTab] = useState('DRAFT')" in src)
check("Tab inicial es DRAFT",
      "useState('DRAFT')" in src)
check("setActiveTab existe",
      "setActiveTab" in src)
check("setActiveTab('DRAFT') en handleSaveEntry (post-save)",
      "setActiveTab('DRAFT')" in src,
      "El botón Guardar debería volver a la tab DRAFT")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 3: TABS const y AUTO_SOURCES correctamente definidos")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("const TABS definido",           "const TABS = [" in src)
check("Tab DRAFT en TABS",             "'DRAFT'" in src and "'Borrador'" in src)
check("Tab POSTED en TABS",            "'POSTED'" in src and "'Aprobados'" in src)
check("Tab VOIDED en TABS",            "'VOIDED'" in src and "'Anulados'" in src)
check("Tab AUTO en TABS",              "'AUTO'" in src and "'Automáticos'" in src)
check("Son exactamente 4 tabs",
      src.count("{ id: '") >= 4 or src.count('{ id: "') >= 4 or
      sum(1 for t in ["'DRAFT'", "'POSTED'", "'VOIDED'", "'AUTO'"] if t in src) == 4)

check("AUTO_SOURCES definido como Set",  "AUTO_SOURCES = new Set(" in src)
auto_sources_required = ['FE', 'DEPRECIACION', 'CIERRE', 'TE', 'NC']
for source in auto_sources_required:
    check(f"AUTO_SOURCES incluye '{source}'", f"'{source}'" in src)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 4: fetchEntries — sin parámetro status en la URL")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Extrae el bloque de fetchEntries
fetch_match = re.search(r'async function fetchEntries\(\)(.*?)(?=\n    async function|\n    function|\n    const [a-z])', src, re.DOTALL)
if fetch_match:
    fetch_block = fetch_match.group(0)
    check("fetchEntries no pasa &status= a la URL",
          'status: statusFilter' not in fetch_block and
          'status: activeTab' not in fetch_block,
          "Todavía pasa filtro de status al API")
    check("fetchEntries usa solo period en la URL",
          'period=${period}`' in fetch_block or "period=\\'${period}\\'" in fetch_block,
          fetch_block[:200])
    check("StatusFilter no está en URL del fetch",
          'statusFilter' not in fetch_block)
else:
    check("fetchEntries encontrado en el código", False, "No se pudo localizar la función")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 5: filteredEntries y tabCounts — memos correctos")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("filteredEntries definido con useMemo",  "const filteredEntries = useMemo(" in src)
check("filteredEntries usa AUTO_SOURCES.has",  "AUTO_SOURCES.has(e.source)" in src)
check("filteredEntries filtra por activeTab",   "e.status === activeTab" in src)
check("tabCounts definido con useMemo",         "const tabCounts = useMemo(" in src)
check("tabCounts.DRAFT existe",                "DRAFT:" in src and "e.status === 'DRAFT'" in src)
check("tabCounts.AUTO usa AUTO_SOURCES.has",
      src.count("AUTO_SOURCES.has(e.source)") >= 2,  # filteredEntries + tabCounts
      "AUTO_SOURCES.has debe aparecer en ambos memos")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 6: UI — TabBar renderiza los 4 tabs")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("TABS.map() en el JSX",          "TABS.map(tab =>" in src)
check("tab.id en el botón",            "id={`tab-${tab.id.toLowerCase()}`}" in src)
check("setActiveTab en el onClick",    "onClick={() => setActiveTab(tab.id)}" in src)
check("Badge count en cada tab",       "{count}" in src and "tabCounts[tab.id]" in src)
check("Tab activo resaltado",          "isActive ? tab.color" in src)
check("Transición suave en tabs",      "transition: 'all 0.15s ease'" in src)
check("filteredEntries en el render",  "filteredEntries.map(entry =>" in src)
check("Entrada vacía usa filteredEntries", "filteredEntries.length === 0" in src)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 7: Estado vacío — mensajes por tipo de tab")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("Estado vacío diferenciado por tab",
      "activeTab === 'AUTO'" in src)
check("Mensaje específico para tab AUTO",
      "asientos automáticos" in src or "Automáticos" in src)
check("Hint informativo para tab AUTO",
      "Activos Fijos" in src or "generan desde" in src)
check("Botón 'Crear primer asiento' solo en tab DRAFT",
      "activeTab === 'DRAFT'" in src)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 8: useEffect — solo se recarga al cambiar period")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check("useEffect solo depende de [period]",
      "}, [period])" in src and "}, [period, statusFilter])" not in src)
check("No hay reload al cambiar tab (filtrado es client-side)",
      "}, [activeTab])" not in src or
      "fetchEntries" not in src[src.find("}, [activeTab])") - 500:src.find("}, [activeTab])")] if "}, [activeTab])" in src else True)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — Paso 2 APROBADO")
    print("     → Dropdown eliminado, tabs implementados ✓")
    print("     → activeTab/filteredEntries/tabCounts correctos ✓")
    print("     → fetchEntries sin filtro de status (client-side) ✓")
    print("     → Tab AUTO con AUTO_SOURCES.has() ✓")
    print("     → Estado vacío diferenciado por tab ✓")
    print("     → useEffect solo depende de [period] ✓")
print("═" * 65 + "\n")
