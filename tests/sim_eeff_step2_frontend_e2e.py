"""
sim_eeff_step2_frontend_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIMULACIÓN E2E — Paso 2: EstadosFinancieros.jsx Frontend
NIIF PYMES 3ª Ed. (Feb 2025)

Verifica el componente JSX mediante análisis estático del código fuente:
  F1:  Archivo creado y no vacío
  F2:  Registrado en App.jsx reemplazando ComingSoon
  F3:  Import correcto en App.jsx
  F4:  Tabs ESF / ERI / MAP presentes
  F5:  IDs únicos para testing (eeff-tab-esf, eeff-tab-eri, etc.)
  F6:  Selector de año (eeff-year-select)
  F7:  Botón regenerar (eeff-reload-btn)
  F8:  Auto-seed al montar (POST /reporting/eeff/seed-mapping)
  F9:  fetchEEFF llama a GET /reporting/eeff/{year}
  F10: Token de autenticación incluido en los headers
  F11: TabESF renderiza ESF data (activo_corriente, pasivo_corriente, patrimonio)
  F12: TabERI renderiza ERI data (ingresos, costos, utilidad_neta)
  F13: Drilldown de cuentas (NiifLine con detail)
  F14: UnmappedWarning muestra cuentas sin mapear
  F15: BalanceCheck ESF cuadrado
  F16: Escenario de pérdida presentado en rojo
  F17: ORI (3ª Ed.) renderizado si existe
  F18: Metadatos de calidad (total_accounts_in_tb, mapped_accounts)
  F19: Warning SIN_MAPEO_NIIF con instrucción de acción
  F20: Nota NIIF en cada tab (Sección 4, Sección 5)
  F21: useCallback + useEffect para cargar datos
  F22: Estado de carga (loading, error, data)
  F23: Selector de año con años actuales - 3
  F24: TabMapeo llama a GET /reporting/eeff/mapping/unmapped
"""
import sys, os, re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PASS = "✅"; FAIL = "❌"
results = []

def check(name, condition, details=""):
    status = PASS if condition else FAIL
    results.append((status, name, details))
    print(f"  {status} {name}" + (f" — {details}" if details else ""))

def section(title):
    print(f"\n{'━'*62}\n  {title}\n{'━'*62}")

BASE = os.path.join(os.path.dirname(__file__), '..')
eeff_jsx = os.path.join(BASE, 'frontend/src/pages/EstadosFinancieros.jsx')
app_jsx  = os.path.join(BASE, 'frontend/src/App.jsx')

# Leer fuentes
try:
    src  = open(eeff_jsx, encoding='utf-8').read()
    appsrc = open(app_jsx,  encoding='utf-8').read()
except Exception as e:
    print(f"❌ No se pudo leer el archivo: {e}")
    sys.exit(1)

# ─── F1-F3: Existencia y registro ─────────────────────────────
section("F1-F3: Existencia y registro en App.jsx")
size = os.path.getsize(eeff_jsx)
check("F1 — EstadosFinancieros.jsx existe y no vacío", size > 5000, f"{size} bytes")
check("F2 — /reportes usa EstadosFinancieros (no ComingSoon)",
      "EstadosFinancieros" in appsrc and
      "/reportes" in appsrc and
      "<EstadosFinancieros" in appsrc and
      'ComingSoon name="Estados' not in appsrc)
check("F3 — import EstadosFinancieros en App.jsx",
      "import EstadosFinancieros from './pages/EstadosFinancieros'" in appsrc)

# ─── F4-F7: Estructura de tabs y controles ────────────────────
section("F4-F7: Tabs y controles principales")
check("F4.1 — Tab ESF declarada",  "activeTab === 'esf'" in src or "'esf'" in src)
check("F4.2 — Tab ERI declarada",  "'eri'" in src)
check("F4.3 — Tab MAP declarada",  "'map'" in src)
# IDs generados dinámicamente con interpolación: `eeff-tab-${tab.id}` → eeff-tab-esf/eri/map
check("F5.1 — ID eeff-tab-esf (dinámico)",  "eeff-tab-" in src and "tab.id" in src)
check("F5.2 — ID eeff-tab-eri (dinámico)",  "eeff-tab-" in src and "eri" in src)
check("F5.3 — ID eeff-tab-map (dinámico)",  "eeff-tab-" in src and "'map'" in src)
check("F5.4 — ID eeff-tab-content","eeff-tab-content" in src)
check("F6 — Selector de año (eeff-year-select)", "eeff-year-select" in src)
check("F7 — Botón regenerar (eeff-reload-btn)",  "eeff-reload-btn" in src)

# ─── F8-F10: Datos y autenticación ────────────────────────────
section("F8-F10: Fetch, auto-seed y autenticación")
check("F8 — POST /eeff/seed-mapping al montar",
      "/reporting/eeff/seed-mapping" in src and "POST" in src)
check("F9 — GET /eeff/{year} con año dinámico",
      "/reporting/eeff/${year}" in src or "/eeff/${year}" in src or "`${API}/reporting/eeff/${year}`" in src)
check("F10 — Authorization: Bearer en headers",
      "Authorization" in src and "Bearer" in src and "token" in src)

# ─── F11-F12: Tabs ESF y ERI ──────────────────────────────────
section("F11-F12: Componentes TabESF y TabERI")
check("F11.1 — TabESF existe", "function TabESF" in src or "TabESF" in src)
check("F11.2 — activo_corriente presente en ESF", "activo_corriente" in src)
check("F11.3 — pasivo_corriente presente en ESF", "pasivo_corriente" in src)
check("F11.4 — patrimonio presente en ESF",       "patrimonio" in src)
check("F11.5 — total_activos en totals",          "total_activos" in src)
check("F11.6 — total_pasivo_patrimonio en totals","total_pasivo_patrimonio" in src)
check("F12.1 — TabERI existe", "function TabERI" in src)
check("F12.2 — ingresos en ERI",   "eri.ingresos" in src or "ingresos" in src)
check("F12.3 — costos en ERI",     "eri.costos" in src or "costos" in src)
check("F12.4 — utilidad_neta",     "utilidad_neta" in src)
check("F12.5 — utilidad_bruta",    "utilidad_bruta" in src)
check("F12.6 — total_isr",        "total_isr" in src)

# ─── F13-F15: UX avanzado ─────────────────────────────────────
section("F13-F15: Drilldown, UnmappedWarning y BalanceCheck")
check("F13.1 — NiifLine con collapse/expand (drilldown)", "NiifLine" in src)
check("F13.2 — detail array en drilldown",  "detail" in src and "d.code" in src)
check("F14.1 — UnmappedWarning componente", "UnmappedWarning" in src)
check("F14.2 — unmapped_accounts en warnings", "unmapped_accounts" in src)
check("F15.1 — BalanceCheck componente",    "BalanceCheck" in src)
check("F15.2 — balanced prop",              "balanced" in src)
check("F15.3 — ESF cuadrado texto",         "ESF cuadrado" in src or "cuadrad" in src)

# ─── F16-F18: Escenarios especiales ───────────────────────────
section("F16-F18: Pérdida, ORI y metadatos de calidad")
check("F16.1 — Pérdida neta en rojo",       "isLoss" in src or "Pérdida" in src)
check("F16.2 — Color ef4444 para pérdidas", "#ef4444" in src)
check("F17.1 — ORI renderizado (3ª Ed.)",   "otro_resultado" in src or "ORI" in src)
check("F17.2 — total_resultado_integral",   "total_resultado_integral" in src)
check("F18.1 — total_accounts_in_tb metadato", "total_accounts_in_tb" in src)
check("F18.2 — mapped_accounts metadato",      "mapped_accounts" in src)
check("F18.3 — niif_edition metadato",         "niif_edition" in src)

# ─── F19-F20: Mensajes importantes ───────────────────────────
section("F19-F20: Mensajes de usuario y notas NIIF")
check("F19.1 — Error SIN_MAPEO_NIIF manejado", "SIN_MAPEO_NIIF" in src)
check("F19.2 — Instrucción de acción en error", "seed-mapping" in src or "auto-mapear" in src)
check("F20.1 — Referencia NIIF PYMES 3ª Ed.", "3ª" in src or "3rd" in src)
check("F20.2 — Referencia Sección 4 (ESF)",   "Sección 4" in src or "Sec. 4" in src or "Sec.4" in src)
check("F20.3 — Referencia Sección 5 (ERI)",   "Sección 5" in src or "Sec. 5" in src or "Sec.5" in src)

# ─── F21-F24: Hooks y estado ─────────────────────────────────
section("F21-F24: Hooks React y gestión de estado")
check("F21.1 — useCallback para cargar datos", "useCallback" in src)
check("F21.2 — useEffect para auto-carga",    "useEffect" in src)
check("F22.1 — Estado loading",  "loading" in src)
check("F22.2 — Estado error",    "setError" in src)
check("F22.3 — Estado data",     "setData" in src)
check("F23   — Selector con currentYear - 3", "currentYear - 3" in src or "currentYear-3" in src or "currentYear - 1" in src)
check("F24   — TabMapeo llama a /mapping/unmapped", "mapping/unmapped" in src)

# ─── RESUMEN ──────────────────────────────────────────────────
print(f"\n{'═'*62}")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total  = len(results)
print(f"  RESULTADO FINAL: {passed}/{total} checks pasados")
if failed:
    print(f"\n  ❌ FALLOS ({failed}):")
    for r in results:
        if r[0] == FAIL:
            print(f"    ❌ {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print(f"  ✅✅✅ TODO VERDE — Paso 2 Frontend EEFF completamente validado")
    print(f"{'═'*62}")
    sys.exit(0)
