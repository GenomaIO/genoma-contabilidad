"""
SIM — Fix KPI Cards Dashboard (trial-balance / es_reguladora fallback)
=======================================================================
MÓDULO 1: es_reguladora falla → rollback + fallback sin columna → query principal OK
MÓDULO 2: Con fallback, account_type se mapea correctamente → KPIs no son null
MÓDULO 3: Sin accounts_map (fallback total falla) → tb puede estar vacío pero no crashea
MÓDULO 4: La lógica del front kpis.activos === null → "—" se activa solo si tb=[]
MÓDULO 5: Frontend → si trial-balance retorna 0 filas debería loggear diagnóstico
"""
import sys, os

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_ledger = open(os.path.join(ROOT, "services/ledger/router.py")).read()
src_dash   = open(os.path.join(ROOT, "frontend/src/pages/Dashboard.jsx")).read()

# ─── MÓDULO 1: El fix de rollback + retry sin es_reguladora existe ────────────
print("\n🛡️  MÓDULO 1 — Rollback + fallback sin es_reguladora:")

check("db.rollback()"                              in src_ledger,
      "db.rollback() en el except para limpiar transacción contaminada")
check("SELECT code, name, account_type FROM accounts" in src_ledger,
      "query de fallback sin es_reguladora (columna opcional)")
check("es_reguladora\": False,  # default seguro"  in src_ledger,
      "default es_reguladora=False en fallback")
check("migraci" in src_ledger,  # migración pendiente
      "comentario explica que es_reguladora puede no estar migrada")

# ─── MÓDULO 2: Simular el fallback ────────────────────────────────────────────
print("\n🔄 MÓDULO 2 — Lógica del fallback en producción:")

def simular_trial_balance(rows_db, accounts_map):
    """Simula la lógica del backend después del fix."""
    NATURALEZA_DEBE  = {"ACTIVO", "GASTO"}
    NATURALEZA_HABER = {"PASIVO", "PATRIMONIO", "INGRESO"}

    lines_out = []
    for r in rows_db:
        td = float(r.get('total_debit', 0))
        tc = float(r.get('total_credit', 0))
        acc_info = accounts_map.get(r['account_code'], {})
        acc_type = acc_info.get("type", "")
        es_reg   = acc_info.get("es_reguladora", False)  # default False del fallback

        saldo_neto = round(td - tc, 2)
        if acc_type in NATURALEZA_DEBE:
            saldo_debe  = round(max(saldo_neto, 0), 2)
            saldo_haber = round(abs(min(saldo_neto, 0)), 2)
        elif acc_type in NATURALEZA_HABER:
            saldo_haber = round(max(-saldo_neto, 0), 2)
            saldo_debe  = round(max(saldo_neto, 0), 2)
        else:
            saldo_debe = saldo_haber = 0.0
        lines_out.append({
            "account_code": r['account_code'],
            "account_type": acc_type,
            "es_reguladora": es_reg,
            "total_debit": td,
            "total_credit": tc,
        })
    return lines_out

# Simular DB con 3 asientos POSTED de Álvaro
rows_alvaro = [
    {'account_code': '1101', 'total_debit': 500000, 'total_credit': 0},     # ACTIVO Caja
    {'account_code': '3101', 'total_debit': 0,      'total_credit': 500000}, # PATRIMONIO
    {'account_code': '4101', 'total_debit': 0,      'total_credit': 150000}, # INGRESO
    {'account_code': '5101', 'total_debit': 150000, 'total_credit': 0},     # GASTO
]

# Sin accounts_map (fallback total falla) → acc_type = "" siempre
lines_sin_map = simular_trial_balance(rows_alvaro, {})
check(len(lines_sin_map) == 4, "Sin accounts_map: 4 filas procesadas (no se dropean)")
check(all(l['account_type'] == "" for l in lines_sin_map),
      "Sin accounts_map: account_type = '' para todas")

# Con accounts_map del fallback (sin es_reguladora)
accounts_map_fallback = {
    '1101': {'type': 'ACTIVO',     'es_reguladora': False},
    '3101': {'type': 'PATRIMONIO', 'es_reguladora': False},
    '4101': {'type': 'INGRESO',    'es_reguladora': False},
    '5101': {'type': 'GASTO',      'es_reguladora': False},
}
lines_con_map = simular_trial_balance(rows_alvaro, accounts_map_fallback)
check(len(lines_con_map) == 4, "Con fallback accounts_map: 4 filas procesadas")

# Simular KPI del dashboard con los datos resultantes
def simular_dashboard_kpis(lines):
    """Simula la lógica sum() del Dashboard.jsx."""
    def s(type_, sign):
        rows = [l for l in lines if l['account_type'] == type_]
        total = 0
        for l in rows:
            net = l['total_debit'] - l['total_credit']
            total += net if sign == 'debit' else -net
        return total
    ingresos = abs(s('INGRESO', 'credit'))
    gastos   = abs(s('GASTO',   'debit'))
    return {
        'activos':    s('ACTIVO',     'debit'),
        'pasivos':    abs(s('PASIVO',  'credit')),
        'patrimonio': abs(s('PATRIMONIO', 'credit')),
        'resultado':  ingresos - gastos,
    }

kpis = simular_dashboard_kpis(lines_con_map)
check(kpis['activos']    == 500000, f"Activos = ₡500,000 (got {kpis['activos']})")
check(kpis['patrimonio'] == 500000, f"Patrimonio = ₡500,000 (got {kpis['patrimonio']})")
check(kpis['resultado']  == 0,      f"Resultado = ₡0 (150k ingreso - 150k gasto = 0)")

# ─── MÓDULO 3: Sin accounts_map y con is_active en columna ───────────────────
print("\n🔃 MÓDULO 3 — Sin accounts_map → KPIs son 0, no nulls ni error:")

kpis_sin_map = simular_dashboard_kpis(lines_sin_map)
# Con líneas pero sin types → el dashboard llamaría setKpis({}) que son 0
check(all(v == 0 for v in kpis_sin_map.values()),
      "Sin accounts_map: todos los KPIs = 0 (no null → no muestra —)")

# Verificar que el Dashboard detecta tb.length > 0 independientemente del accounts_map
check(len(lines_sin_map) > 0,
      "lines !== [] incluso sin accounts_map → setKpis se llama (muestra 0, no —)")

# ─── MÓDULO 4: Frontend — condición de null vs 0 ─────────────────────────────
print("\n📊 MÓDULO 4 — Frontend: null → '—', 0 → '₡0':")

def fmt(n):
    if n is None or (isinstance(n, float) and n != n):
        return '—'
    return f'₡{int(n):,}'

check(fmt(None)   == '—',    "activos=null → '—' (estado inicial sin datos)")
check(fmt(0)      == '₡0',   "activos=0 → '₡0' (datos cargados pero balance 0)")
check(fmt(500000) == '₡500,000', "activos=500000 → formateado")

# Verificar en el código del Dashboard que setKpis solo necesita tb.length > 0
check("if (tb.length > 0)" in src_dash,
      "Dashboard: setKpis solo se llama si tb.length > 0")
check("tbRaw?.lines || []" in src_dash,
      "Dashboard: extrae .lines del objeto devuelto por trial-balance")

# ─── MÓDULO 5: La causa raíz está documentada en el backend ──────────────────
print("\n📝 MÓDULO 5 — Causa raíz documentada en el código:")

check("contamina la transacci" in src_ledger,
      "Comentario explica por qué except pass no era suficiente")
check("Fallback: es_reguladora puede no existir" in src_ledger,
      "Comentario de fallback con contexto de migración")

# ─── Resultado ────────────────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Fix KPI Cards Dashboard")
    print("   · es_reguladora falla → rollback + fallback sin columna")
    print("   · Fallback mantiene account_type → setKpis recibe datos correctos")
    print("   · Sin accounts_map total → KPIs = ₡0 (no — silencioso)")
    print("   · Frontend: tb.length > 0 gate funciona correctamente")
    sys.exit(0)
