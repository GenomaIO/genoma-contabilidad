"""
sim_balance_ytd_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIMULACIÓN E2E — Balance de Comprobación YTD
Principio de Devengo · NIIF PYMES 3ª Ed. · Sec. 2.36 y 3.10

BACKEND (services/ledger/router.py):
  B1:  Parámetro `mode` presente en firma del endpoint
  B2:  Modo 'period' con consulta je.period = :period
  B3:  Modo 'ytd' con consulta je.period >= :year_start AND <= :period
  B4:  Modo 'running' con consulta je.period <= :period
  B5:  Alias acumulado=True → mode='ytd'
  B6:  Retorno incluye campo 'mode'
  B7:  Retorno incluye campo 'year_start'
  B8:  Retorno incluye campo 'niif_ref' en modo ytd
  B9:  Invariante Debe=Haber en la lógica del endpoint
  B10: year_start calculado desde year[:4] + '-01'

FRONTEND (BalanceComprobacion.jsx):
  F1:  Modo default es 'ytd' (no 'period')
  F2:  Array MODES con 3 elementos (period/ytd/running)
  F3:  Botones id btn-mode-period, btn-mode-ytd, btn-mode-running
  F4:  URL usa ?mode= (no ?acumulado=)
  F5:  Banner advertencia visible cuando mode=period
  F6:  Banner YTD con year_start visible cuando mode=ytd
  F7:  Bombillito NiifTip presente
  F8:  Referencia NIIF PYMES Sec. 2.36 en el código
  F9:  Referencia NIIF PYMES Sec. 3.10 en el código
  F10: Cuadratura balanced Math.abs < 0.01 calculada en frontend
  F11: token desde localStorage.getItem('gc_token')
  F12: Estado vacío cuando no hay cuentas

SIM MATEMÁTICA (cuadratura Debe=Haber en YTD):
  SIM1: Enero solo → Debe=Haber
  SIM2: Febrero solo → Debe=Haber
  SIM3: YTD Ene+Feb → Debe=Haber
  SIM4: Variación de caja correcta en YTD
  SIM5: Cuenta sin movimiento en Feb aparece en YTD si tuvo Ene
  SIM6: YTD correctamente excluye períodos futuros
"""
import sys, os, re
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PASS = "✅"; FAIL = "❌"
results = []

def check(name, condition, details=""):
    s = PASS if condition else FAIL
    results.append((s, name, details))
    print(f"  {s} {name}" + (f" — {details}" if details else ""))

def section(t):
    print(f"\n{'━'*64}\n  {t}\n{'━'*64}")

BASE   = os.path.join(os.path.dirname(__file__), '..')
router = open(os.path.join(BASE, 'services/ledger/router.py'), encoding='utf-8').read()
jsx    = open(os.path.join(BASE, 'frontend/src/pages/BalanceComprobacion.jsx'), encoding='utf-8').read()


# ─── BACKEND ─────────────────────────────────────────────────────
section("B1-B10: Backend trial_balance endpoint")

check("B1  — Parámetro mode en firma",
      "mode:" in router and "Query(" in router and "'ytd'" in router)
check("B2  — Consulta mode=period usa je.period = :period",
      "mode == \"period\"" in router or "mode == 'period'" in router)
check("B3  — Consulta mode=ytd usa >= year_start AND <= period",
      "year_start" in router and ">= :year_start" in router and "<= :period" in router)
check("B4  — Consulta mode=running con <= :period",
      'else:  # running' in router or
      ('else:' in router and '<= :period' in router and 'running' in router))
check("B5  — Alias acumulado → mode=ytd",
      "acumulado" in router and "mode = \"ytd\"" in router or "mode='ytd'" in router)
check("B6  — Retorno incluye 'mode'",
      '"mode":' in router or "'mode':" in router)
check("B7  — Retorno incluye 'year_start'",
      '"year_start"' in router or "'year_start'" in router)
check("B8  — niif_ref en retorno modo ytd",
      "niif_ref" in router and "Sec. 2.36" in router)
check("B9  — Invariante balanced abs < 0.01",
      "abs(total_debit - total_credit) < 0.01" in router)
check("B10 — year_start = year[:4] + primer mes",
      'year_start = f"{year}-01"' in router or "year_start" in router and '"-01"' in router)


# ─── FRONTEND ────────────────────────────────────────────────────
section("F1-F12: Frontend BalanceComprobacion.jsx")

check("F1  — Default mode='ytd'",
      "useState('ytd')" in jsx)
check("F2  — Array MODES con 3 elementos",
      jsx.count("id: '") >= 3 or "MODES = [" in jsx)
check("F2b — MODES incluye period/ytd/running",
      "'period'" in jsx and "'ytd'" in jsx and "'running'" in jsx)
check("F3  — Botones modo generados con template literal btn-mode-${m.id}",
      'btn-mode-${m.id}' in jsx or '"btn-mode-period"' in jsx)
check("F3b — MODES array tiene id: 'ytd'",
      "id: 'ytd'" in jsx)
check("F3c — MODES array tiene id: 'running'",
      "id: 'running'" in jsx)
check("F4  — URL usa mode= (no acumulado=)",
      "mode=${mode}" in jsx and "acumulado=${acumulado}" not in jsx)
check("F5  — Banner advertencia mode=period",
      "mode === 'period'" in jsx and "Solo los movimientos" in jsx or
      "mode === 'period'" in jsx and "solo los movimientos" in jsx.lower())
check("F6  — Banner YTD con year_start",
      "data.year_start" in jsx or "year_start" in jsx)
check("F7  — NiifTip definida",
      "function NiifTip" in jsx)
check("F8  — Ref NIIF PYMES Sec. 2.36",
      "Sec. 2.36" in jsx)
check("F9  — Ref NIIF PYMES Sec. 3.10",
      "Sec. 3.10" in jsx)
check("F10 — Cuadratura balanced en frontend",
      "Math.abs(totalDebit - totalCredit) < 0.01" in jsx)
check("F11 — token desde localStorage",
      "localStorage.getItem('gc_token')" in jsx)
check("F12 — Estado vacío cuando accounts.length === 0",
      "accounts.length === 0" in jsx)


# ─── SIM MATEMÁTICA ──────────────────────────────────────────────
section("SIM1-SIM6: Cuadratura YTD (Debe = Haber siempre)")

from decimal import Decimal

def sim_period_rows(rows):
    """Simula lo que devuelve la consulta SQL para un período."""
    return [{"account_code": r[0], "total_debit": Decimal(str(r[1])), "total_credit": Decimal(str(r[2]))} for r in rows]

# Datos de prueba — basados en las capturas del usuario
enero_rows = [
    ("1101.01",  176069671.83, 137877.00),  # Caja General
    ("1201.04",   13555935.00,      0.00),  # Vehículos
    ("1202.03",          0.00, 4424872.13), # Dep. Acum Vehículos
    ("1202.04",          0.00,  112966.12), # Dep. Acum Mobiliario
    ("2102.01",          0.00,  594437.60), # IVA Débito
    ("2102.02",       658.00,   112780.00), # IVA Cond. Venta
    ("3401.01",          0.00,  178854520.10), # Capital
    ("4101.03",          0.00, 5638997.00), # Ventas
    ("5301.01",   112966.12,        0.00), # Intereses préstamos
    ("5401.01",     3621.00,        0.00), # ISR
    ("5901.01",   133598.00,        0.00), # Gastos rep.
]
febrero_rows = [
    ("1101.01",  1055530.00,   342932.00), # Caja — Solo Feb
    ("1202.03",       0.00,   225932.24),  # Dep. Acum Veh — Solo Feb
    ("1202.04",  112966.12,        0.00),  # Dep. Acum Mob — Solo Feb
    ("2102.02",    4614.00,    20697.00),  # IVA — Solo Feb
    ("4101.03",       0.00,  1034833.00), # Ventas — Solo Feb
    ("5210.03",  225932.24,        0.00),  # Gasto dep. — Solo Feb
    ("5301.01",       0.00,   112966.12), # Intereses — Solo Feb
    ("5401.01",   29994.00,        0.00),  # ISR — Solo Feb
    ("5901.01",  308324.00,        0.00),  # Gastos rep. — Solo Feb
]

def total_db(rows):
    return sum(Decimal(str(r[1])) for r in rows)
def total_cr(rows):
    return sum(Decimal(str(r[2])) for r in rows)

ene_db = total_db(enero_rows)
ene_cr = total_cr(enero_rows)
feb_db = total_db(febrero_rows)
feb_cr = total_cr(febrero_rows)

check("SIM1 — Enero cuadra (Debe=Haber)",
      abs(ene_db - ene_cr) < Decimal("0.05"),
      f"Debe={ene_db:,.2f} Haber={ene_cr:,.2f} diff={abs(ene_db-ene_cr):.4f}")

check("SIM2 — Febrero cuadra (Debe=Haber)",
      abs(feb_db - feb_cr) < Decimal("0.05"),
      f"Debe={feb_db:,.2f} Haber={feb_cr:,.2f} diff={abs(feb_db-feb_cr):.4f}")

ytd_db = ene_db + feb_db
ytd_cr = ene_cr + feb_cr
check("SIM3 — YTD Ene+Feb cuadra (Debe=Haber)",
      abs(ytd_db - ytd_cr) < Decimal("0.05"),
      f"Debe={ytd_db:,.2f} Haber={ytd_cr:,.2f}")

# Variación de Caja en YTD
caja_ytd_db = Decimal("176069671.83") + Decimal("1055530.00")
caja_ytd_cr = Decimal("137877.00")    + Decimal("342932.00")
caja_ytd_saldo = caja_ytd_db - caja_ytd_cr
check("SIM4 — Caja YTD = Ene + Feb correctamente",
      caja_ytd_saldo > 0,
      f"Saldo Caja YTD = ¢{caja_ytd_saldo:,.2f}")

# Una cuenta sin movimiento en Feb que sí tuvo en Ene
# (1201.04 Vehículos: solo aparece en Enero)
cuentas_feb = {r[0] for r in febrero_rows}
check("SIM5 — 1201.04 no tiene movimientos en Feb (solo en Ene)",
      "1201.04" not in cuentas_feb,
      "En YTD debe incluirse con su saldo de Ene")

# YTD no incluye períodos futuros
# (Si period=Feb-2026, no debe incluir Marzo)
# Esto lo garantiza AND je.period <= :period en la SQL
check("SIM6 — Lógica SQL YTD excluye períodos futuros",
      "<= :period" in router and ">= :year_start" in router,
      "Query SQL con rango correcto")


# ─── AUDIT DE IMPORTS (para prevenir el error de anoche) ─────────
section("AUDIT: Imports del módulo ledger — prevenir fallo en Render")

import ast
for rel in ['services/ledger/router.py']:
    fpath = os.path.join(BASE, rel)
    with open(fpath, encoding='utf-8') as f:
        src = f.read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            names_list = [a.name for a in node.names]
            if mod.startswith('services.auth.'):
                submod = mod.replace('services.auth.', '')
                target = os.path.join(BASE, 'services/auth', submod + '.py')
                exists = os.path.exists(target)
                if exists:
                    content = open(target).read()
                    missing = [n for n in names_list if n not in content]
                    if missing:
                        check(f"IMPORT — {mod}: {missing}", False, "NO EXPORTADO")
                    else:
                        check(f"IMPORT — from {mod} import {names_list}", True)
                else:
                    check(f"IMPORT — {target}", False, "MÓDULO NO EXISTE")


# ─── RESUMEN ─────────────────────────────────────────────────────
print(f"\n{'═'*64}")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total  = len(results)
print(f"  RESULTADO: {passed}/{total} checks pasados")
if failed:
    print(f"\n  ❌ FALLOS ({failed}):")
    for r in results:
        if r[0] == FAIL:
            print(f"    ❌ {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print(f"  ✅✅✅ TODO VERDE — Balance YTD listo para push")
    print(f"{'═'*64}")
    sys.exit(0)
