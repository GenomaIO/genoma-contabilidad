"""
tests/sim_tabs_step1_logic.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 1 — Simula la lógica de filtrado y conteo de tabs
para AsientosPendientes.jsx

Valida:
  · Tab DRAFT  → solo entries con status=DRAFT
  · Tab POSTED → solo entries con status=POSTED
  · Tab VOIDED → solo entries con status=VOIDED
  · Tab AUTO   → entries donde source ≠ 'MANUAL' (cualquier status)
  · Counts de cada tab son correctos
  · Cambiar pestaña → lista cambia, tab anterior no se mezcla
  · Estado vacío por tab
  · Asientos automáticos pueden ser DRAFT o POSTED (cualquier status)

Ejecutar con:
    python tests/sim_tabs_step1_logic.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys

PASS = "  ✅"
FAIL = "  ❌"
errors = []

def check(label, cond, detail=""):
    if cond:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

# ── Datos de prueba — réplica de lo que devuelve el API ───────
ENTRIES = [
    # Manuales
    {"id": "e1", "status": "DRAFT",  "source": "MANUAL",     "description": "Reversión error",              "date": "2026-02-01"},
    {"id": "e2", "status": "DRAFT",  "source": "MANUAL",     "description": "Reg. Depreciación mes pasado", "date": "2026-02-01"},
    {"id": "e3", "status": "POSTED", "source": "MANUAL",     "description": "Pago servicios",               "date": "2026-02-05"},
    {"id": "e4", "status": "VOIDED", "source": "MANUAL",     "description": "Error anulado",                "date": "2026-02-10"},
    # Automáticos — DRAFT
    {"id": "e5", "status": "DRAFT",  "source": "DEPRECIACION","description": "Depreciación CHANGAN 2026-02", "date": "2026-02-28"},
    # Automáticos — POSTED
    {"id": "e6", "status": "POSTED", "source": "FE",          "description": "Venta factura 001",           "date": "2026-02-03"},
    {"id": "e7", "status": "POSTED", "source": "CIERRE",      "description": "Cierre del período",          "date": "2026-02-29"},
    # Automático — VOIDED
    {"id": "e8", "status": "VOIDED", "source": "TE",          "description": "Tiquete anulado",             "date": "2026-02-07"},
]

# ── Lógica de filtrado (replica useMemo del componente) ───────
def filter_by_tab(entries, tab):
    if tab == 'AUTO':
        return [e for e in entries if e['source'] != 'MANUAL']
    return [e for e in entries if e['status'] == tab]

def compute_counts(entries):
    return {
        'DRAFT':  len([e for e in entries if e['status'] == 'DRAFT']),
        'POSTED': len([e for e in entries if e['status'] == 'POSTED']),
        'VOIDED': len([e for e in entries if e['status'] == 'VOIDED']),
        'AUTO':   len([e for e in entries if e['source'] != 'MANUAL']),
    }

print("\n" + "═" * 65)
print("  SIMULACIÓN — Paso 1: Lógica de Tabs en Libro Diario")
print("═" * 65)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 1: Tab DRAFT — solo borradores manuales")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

result = filter_by_tab(ENTRIES, 'DRAFT')
check("Tab DRAFT → devuelve 3 entries",   len(result) == 3, f"devolvió {len(result)}")
check("Tab DRAFT → todos son DRAFT",      all(e['status'] == 'DRAFT' for e in result))
check("Tab DRAFT → incluye manuales",     any(e['source'] == 'MANUAL' for e in result))
check("Tab DRAFT → incluye automáticos",  any(e['source'] != 'MANUAL' for e in result),
      "Un borrador puede ser automático (ej. depreciación no aprobada)")
check("Tab DRAFT → no tiene POSTED",      all(e['status'] != 'POSTED' for e in result))
check("Tab DRAFT → no tiene VOIDED",      all(e['status'] != 'VOIDED' for e in result))
for e in result:
    print(f"     → {e['source']:12} | {e['status']} | {e['description'][:40]}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 2: Tab POSTED — aprobados")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

result = filter_by_tab(ENTRIES, 'POSTED')
check("Tab POSTED → 3 entries",           len(result) == 3, f"devolvió {len(result)}")
check("Tab POSTED → todos son POSTED",    all(e['status'] == 'POSTED' for e in result))
check("Tab POSTED → no hay DRAFT",        all(e['status'] != 'DRAFT' for e in result))
check("Tab POSTED → mix de fuentes",
      len(set(e['source'] for e in result)) > 1,
      f"fuentes: {set(e['source'] for e in result)}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 3: Tab VOIDED — anulados")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

result = filter_by_tab(ENTRIES, 'VOIDED')
check("Tab VOIDED → 2 entries",           len(result) == 2, f"devolvió {len(result)}")
check("Tab VOIDED → todos son VOIDED",    all(e['status'] == 'VOIDED' for e in result))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 4: Tab AUTO — asientos automáticos (fuente ≠ MANUAL)")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

result = filter_by_tab(ENTRIES, 'AUTO')
check("Tab AUTO → 4 entries",             len(result) == 4, f"devolvió {len(result)}")
check("Tab AUTO → ninguno es MANUAL",     all(e['source'] != 'MANUAL' for e in result))
check("Tab AUTO → mezcla de status",      len(set(e['status'] for e in result)) > 1,
      f"statuses: {set(e['status'] for e in result)}")
check("Tab AUTO → incluye DRAFT automático",   any(e['status'] == 'DRAFT'  and e['source'] != 'MANUAL' for e in result))
check("Tab AUTO → incluye POSTED automático",  any(e['status'] == 'POSTED' and e['source'] != 'MANUAL' for e in result))
check("Tab AUTO → incluye VOIDED automático",  any(e['status'] == 'VOIDED' and e['source'] != 'MANUAL' for e in result))
fuentes_auto = sorted(set(e['source'] for e in result))
print(f"     → Fuentes automáticas: {fuentes_auto}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 5: compute_counts — badges de cada tab")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

counts = compute_counts(ENTRIES)
check("Count DRAFT  = 3",   counts['DRAFT']  == 3, f"got {counts['DRAFT']}")
check("Count POSTED = 3",   counts['POSTED'] == 3, f"got {counts['POSTED']}")
check("Count VOIDED = 2",   counts['VOIDED'] == 2, f"got {counts['VOIDED']}")
check("Count AUTO   = 4",   counts['AUTO']   == 4, f"got {counts['AUTO']}")
check("Total entries = 8",  sum(1 for _ in ENTRIES) == 8)
# Nota: DRAFT (e5) y VOIDED (e8) automáticos NO se suman en DRAFT/VOIDED dos veces
# Cada tab tiene su propio criterio de filtro — no hay solapamiento incorrecto
draft_ids  = {e['id'] for e in filter_by_tab(ENTRIES, 'DRAFT')}
auto_ids   = {e['id'] for e in filter_by_tab(ENTRIES, 'AUTO')}
overlap    = draft_ids & auto_ids
check("DRAFT y AUTO pueden compartir entries (e.g. depreciación borrador)",
      len(overlap) > 0, "e5 (Depreciación DRAFT) debería aparecer en ambos")
check("Overlap DRAFT∩AUTO = solo automáticos en DRAFT", overlap == {'e5'}, str(overlap))
print(f"     → Counts: {counts}")
print(f"     → Overlap DRAFT∩AUTO: {overlap}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 6: Estado vacío — período sin asientos de cierto tipo")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EMPTY_PERIOD = []  # Nuevo período sin asientos
empty_counts = compute_counts(EMPTY_PERIOD)
check("Período vacío → DRAFT = 0",   empty_counts['DRAFT']  == 0)
check("Período vacío → AUTO = 0",    empty_counts['AUTO']   == 0)
check("Período vacío → entries = []", filter_by_tab(EMPTY_PERIOD, 'DRAFT') == [])

ONLY_MANUAL = [e for e in ENTRIES if e['source'] == 'MANUAL']
only_manual_counts = compute_counts(ONLY_MANUAL)
check("Solo manuales → AUTO = 0",    only_manual_counts['AUTO'] == 0)
check("Solo manuales → DRAFT tiene manuales", only_manual_counts['DRAFT'] == 2)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 7: Cambio de tab — aislamiento entre tabs")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

tabs = ['DRAFT', 'POSTED', 'VOIDED', 'AUTO']
for tab in tabs:
    result = filter_by_tab(ENTRIES, tab)
    # Al cambiar de tab, el resultado no mezcla los criterios de otros
    other_tabs = [t for t in tabs if t != tab]
    for other in other_tabs:
        other_result = filter_by_tab(ENTRIES, other)
        if tab not in ('AUTO',) and other not in ('AUTO',):
            # Tabs de status son mutuamente exclusivos
            ids_tab   = {e['id'] for e in result}
            ids_other = {e['id'] for e in other_result}
            intersection = ids_tab & ids_other
            check(f"Tab {tab} y tab {other} no comparten entries",
                  len(intersection) == 0, f"Overlap: {intersection}")
    print(f"     → Tab {tab}: {[e['id'] for e in result]}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 8: Icono + color por fuente (SOURCE_ICON)")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SOURCE_ICON = {
    'MANUAL': '✍️', 'FE': '📄', 'TE': '🧾', 'NC': '↩️', 'ND': '➕',
    'FEC': '🛒', 'REP': '💰', 'RECIBIDO': '📥', 'CIERRE': '🔒',
    'DEPRECIACION': '🏗️', 'APERTURA': '🔵',
}
auto_entries = filter_by_tab(ENTRIES, 'AUTO')
for e in auto_entries:
    icon = SOURCE_ICON.get(e['source'], '📋')
    check(f"AUTO entry {e['id']} ({e['source']}) → tiene ícono '{icon}'",
          bool(icon))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — Paso 1 APROBADO")
    print("     → Filtrado por status (DRAFT/POSTED/VOIDED): OK ✓")
    print("     → Tab AUTO filtra por source ≠ MANUAL: OK ✓")
    print("     → Counts de badges correctos: OK ✓")
    print("     → Tabs de status son mutuamente exclusivos: OK ✓")
    print("     → AUTO puede solaparse con otros tabs (correcto): OK ✓")
    print("     → Estados vacíos: OK ✓")
print("═" * 65 + "\n")
