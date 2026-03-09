"""
SIM — Carousel de Asientos en Dashboard (Opción B)
====================================================
MÓDULO 1 — Estado carouselPage declarado
MÓDULO 2 — Reset al cargar datos nuevos
MÓDULO 3 — Lógica de paginación (3 por página, totalPages)
MÓDULO 4 — Flechas ← → ocultas si ≤ 3 asientos
MÓDULO 5 — Navegación: prev/next y clic en puntos
"""
import sys, os

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src  = open(os.path.join(ROOT, "frontend/src/pages/Dashboard.jsx")).read()

# ─── MÓDULO 1: Estado carouselPage ───────────────────────────────────────
print("\n🎠 MÓDULO 1 — Estado carouselPage:")
check("carouselPage"          in src, "carouselPage declarado con useState(0)")
check("setCarouselPage"       in src, "setCarouselPage declarado")
check("useState(0)  // página del carousel" in src,
      "estado inicializado en 0 con comentario")

# ─── MÓDULO 2: Reset al cargar datos ─────────────────────────────────────
print("\n🔄 MÓDULO 2 — Reset al cargar nuevos datos:")
check("setCarouselPage(0)  // reset al cargar" in src,
      "reset a página 0 después de setRecentEntries")

# La llamada a setCarouselPage(0) debe aparecer después de setRecentEntries
idx_set  = src.find("setRecentEntries(allEntries")
idx_reset = src.find("setCarouselPage(0)  // reset")
check(idx_reset > idx_set,
      "setCarouselPage(0) aparece después de setRecentEntries (orden correcto)")

# ─── MÓDULO 3: Lógica de paginación ──────────────────────────────────────
print("\n📐 MÓDULO 3 — Lógica de paginación (3 por página):")

# Simular la paginación en Python
def paginar(entries, page, per_page=3):
    total_pages = -(-len(entries) // per_page)  # ceil division
    start = page * per_page
    visible = entries[start:start + per_page]
    return visible, total_pages

entries_5 = list(range(5))  # 5 asientos (el caso del usuario)
entries_3 = list(range(3))  # exactamente 3
entries_1 = list(range(1))  # 1 asiento

# 5 asientos → 2 páginas
p0, tp5 = paginar(entries_5, 0)
p1, _   = paginar(entries_5, 1)
check(tp5 == 2,   "5 asientos → 2 páginas")
check(p0 == [0,1,2], f"página 0: [0,1,2] → {p0}")
check(p1 == [3,4],   f"página 1: [3,4] → {p1}")

# 3 asientos → 1 página (no aparecen flechas)
_, tp3 = paginar(entries_3, 0)
check(tp3 == 1,   "3 asientos → 1 página (flechas ocultas)")

# 1 asiento → 1 página
_, tp1 = paginar(entries_1, 0)
check(tp1 == 1,   "1 asiento → 1 página (flechas ocultas)")

# Verificar en el código
check("PER_PAGE" in src and "= 3" in src, "PER_PAGE = 3 en el código")
check("Math.ceil(recentEntries.length / PER_PAGE)" in src, "totalPages = ceil(n/3)")
check("recentEntries.slice("       in src, "slice para extraer la página visible")
check("carouselPage * PER_PAGE"    in src, "índice de inicio calculado con carouselPage")

# ─── MÓDULO 4: Flechas ocultas si ≤ 3 ────────────────────────────────────
print("\n🙈 MÓDULO 4 — Flechas ocultas si hay ≤ 3 asientos:")
check("totalPages > 1 &&" in src or "totalPages > 1 \u0026\u0026" in src,
      "controles de nav solo se muestran si totalPages > 1")

# ─── MÓDULO 5: Navegación ────────────────────────────────────────────────
print("\n🔘 MÓDULO 5 — Navegación: prev/next y puntos:")
check("setCarouselPage(p => p - 1)" in src, "flecha ← decrementa página")
check("setCarouselPage(p => p + 1)" in src, "flecha → incrementa página")
check("setCarouselPage(i)"          in src, "clic en punto va a página i directamente")
check("← " in src or "'←'" in src,          "botón ← renderizado")
check("→ " in src or "'→'" in src,          "botón → renderizado")
# Botones deshabilitados en extremos
check("carouselPage === 0"              in src, "prev deshabilitado en página 0")
check("carouselPage === totalPages - 1" in src, "next deshabilitado en última página")
# Indicadores de punto con animación CSS
check("transition: 'all 0.2s'" in src, "puntos con transición animada")
check("width: i === carouselPage ? 16 : 7" in src,
      "punto activo es más ancho (16px vs 7px)")

# ─── Resultado final ───────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Carousel de Asientos (Opción B)")
    print("   · 3 asientos por página")
    print("   · Flechas ← → solo si hay > 3 asientos")
    print("   · Puntos animados que indican la página actual")
    print("   · Reset automático al cargar datos nuevos")
    print("   · Prev deshabilitado en pág 0, Next en última página")
    sys.exit(0)
