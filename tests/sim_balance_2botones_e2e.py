"""
sim_balance_2botones_e2e.py — E2E Balance 2 Botones (Mes / Acumulado)
"""
import sys, os, ast
from decimal import Decimal, ROUND_HALF_UP

PASS = "✅"; FAIL = "❌"
results = []

def check(name, cond, details=""):
    s = PASS if cond else FAIL
    results.append((s, name, details))
    print(f"  {s} {name}" + (f" — {details}" if details else ""))

def section(t):
    print(f"\n{'━'*60}\n  {t}\n{'━'*60}")

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
jsx  = open(os.path.join(BASE, 'frontend/src/pages/BalanceComprobacion.jsx'), encoding='utf-8').read()
rtr  = open(os.path.join(BASE, 'services/ledger/router.py'), encoding='utf-8').read()

# ── JSX STRUCTURE ─────────────────────────────────────────────
section("JSX — Estructura 2 botones simplificada")
check("J1  — Default mode='ytd'",             "useState('ytd')" in jsx)
check("J2  — Botón Mes id=btn-mode-period",   "btn-mode-period" in jsx)
check("J3  — Botón Acumulado id=btn-mode-ytd","btn-mode-ytd" in jsx)
check("J4  — Solo 2 botones de modo (no 3)",  jsx.count("btn-mode-") == 2)
check("J5  — Sin NiifTip",                    "function NiifTip" not in jsx)
check("J6  — Sin array MODES",                "const MODES" not in jsx)
check("J7  — Sin banner advertencia",         "Estás viendo" not in jsx)
check("J8  — Sin indicador rango year_start", "year_start" not in jsx)
check("J9  — URL usa mode= not acumulado=",   "mode=${mode}" in jsx and "acumulado=" not in jsx)
check("J10 — Fix r2() redondeo",              "function r2(" in jsx and "Math.round" in jsx)
check("J11 — Roll-up usa r2() en acumulación","r2(acc[target].d" in jsx or "r2(s + a.total_debit)" in jsx)
check("J12 — totalDebit/Credit con r2",       "r2(accounts.reduce" in jsx)
check("J13 — token desde localStorage",        "localStorage.getItem('gc_token')" in jsx)
check("J14 — Cuadratura balanceado < 0.02",   "< 0.02" in jsx)
check("J15 — Estado vacío accounts.length===0","accounts.length === 0" in jsx)
check("J16 — Click fila → /mayor?code=",      "/mayor?code=" in jsx)
check("J17 — Selector periodo N=24",           "i < 24" in jsx)
check("J18 — Botones N4/N5 con template id",  "`btn-nivel-${lvl}`" in jsx or "'btn-nivel-4'" in jsx)

# ── BACKEND ────────────────────────────────────────────────────
section("BACKEND — Modos period/ytd presentes")
check("B1  — mode=period en router",       "mode == \"period\"" in rtr)
check("B2  — mode=ytd con >= year_start",  ">= :year_start" in rtr and "<= :period" in rtr)
check("B3  — Imports auth correctos",      "from services.auth.security import" in rtr)

# ── MATH: cuadratura con r2() ──────────────────────────────────
section("MATH — Fix ¢0.01 con r2()")

def r2(n):
    return float(Decimal(str(n or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

raw_ytd = [
    ("1101.01", 177125201.83, 480809.00),
    ("1201.04",  13555935.00,      0.00),
    ("1202.03",       0.00,  4650804.38),
    ("1202.04",  112966.12,   112966.12),
    ("2102.01",       0.00,   594437.60),
    ("2102.02",    5272.00,   133477.00),
    ("3401.01",       0.00, 178854520.10),
    ("4101.03",       0.00,  6673830.00),
    ("5210.03",  225932.24,       0.00),
    ("5301.01",  112966.12,  112966.12),
    ("5401.01",   33615.00,      0.00),
    ("5901.01",  441922.00,      0.00),
]

total_d = 0.0; total_c = 0.0
for _, d, c in raw_ytd:
    total_d = r2(total_d + r2(d))
    total_c = r2(total_c + r2(c))

diff = abs(total_d - total_c)
check("MATH1 — YTD cuadra con r2() (diff < 0.02)",
      diff < 0.02, f"D={total_d:,.2f} H={total_c:,.2f} diff={diff:.4f}")
check("MATH2 — Total ≈ 191,613,810",
      abs(total_d - 191613810.31) < 1.0, f"total_d={total_d:,.2f}")

# ── AUDIT IMPORTS ──────────────────────────────────────────────
section("AUDIT — Imports Python (prevenir errores deploy)")
for rel in ['services/ledger/router.py']:
    src = open(os.path.join(BASE, rel), encoding='utf-8').read()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('services.auth.'):
            submod = node.module.replace('services.auth.', '')
            target = os.path.join(BASE, 'services/auth', submod + '.py')
            names_list = [a.name for a in node.names]
            if os.path.exists(target):
                content = open(target).read()
                missing = [n for n in names_list if n not in content]
                if missing:
                    check(f"IMPORT {node.module}", False, f"NO EXPORTADO: {missing}")
                else:
                    check(f"IMPORT from {node.module} import {names_list}", True)
            else:
                check(f"IMPORT {node.module}", False, "MÓDULO NO EXISTE")

# ── RESUMEN ────────────────────────────────────────────────────
print(f"\n{'═'*60}")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"  RESULTADO: {passed}/{len(results)} pasados")
if failed:
    print(f"\n  FALLOS ({failed}):")
    for r in results:
        if r[0] == FAIL:
            print(f"    ❌  {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print(f"  ✅✅✅ TODO VERDE — Listo para push")
    print(f"{'═'*60}")
