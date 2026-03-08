"""
tests/sim_annual_close_step2_entries.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 2 — Simula la lógica de generación de los 3 asientos de
cierre anual y el asiento de apertura del año siguiente.

Valida:
  · Asiento A: cada cuenta INGRESO tiene saldo CR → se debita para cerrar
  · Asiento B: cada cuenta GASTO tiene saldo DR → se acredita para cerrar
  · Asiento C: net_income > 0 → CR 3303 Utilidad; < 0 → DR 3302 Pérdida
  · Partida doble: cada asiento está balanceado (DR = CR)
  · Saldo 3304 Resumen de Resultado = 0 después de A+B+C
  · Asiento de apertura: solo cuentas ACTIVO/PASIVO/PATRIMONIO
  · Apertura balanceada: DR = CR

Ejecutar con:
    python tests/sim_annual_close_step2_entries.py
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

def is_balanced(lines, tol=0.001):
    total_dr = sum(l.get("debit",0) for l in lines)
    total_cr = sum(l.get("credit",0) for l in lines)
    return abs(total_dr - total_cr) < tol, total_dr, total_cr

# ── Datos de prueba — ejercicio fiscal 2026 ──────────────────
ACCOUNTS = {
    # Cuentas nominales (ingresos/gastos = se cierran)
    "4101": {"name": "Ingresos por Ventas",    "type": "INGRESO"},
    "4102": {"name": "Otros Ingresos",          "type": "INGRESO"},
    "5101": {"name": "Costo de Ventas",         "type": "GASTO"},
    "5201": {"name": "Gastos de Administración","type": "GASTO"},
    "5301": {"name": "Gastos de Ventas",        "type": "GASTO"},
    # Cuentas reales (Balance = se trasladan en la apertura)
    "1101": {"name": "Caja y Bancos",           "type": "ACTIVO"},
    "1201": {"name": "Cuentas por Cobrar",      "type": "ACTIVO"},
    "2101": {"name": "Cuentas por Pagar",       "type": "PASIVO"},
    "3101": {"name": "Capital Social",          "type": "PATRIMONIO"},
    "3303": {"name": "Utilidad del Ejercicio",  "type": "PATRIMONIO"},
    "3304": {"name": "Resumen de Resultado",    "type": "PATRIMONIO"},
    "1301": {"name": "Inventarios",              "type": "ACTIVO"},
}

# Saldos acumulados al 31-dic-2026 (debit - credit = saldo neto)
# Ingresos: saldo CR (negativo en convencion debit-credit)
# Gastos: saldo DR (positivo)
SALDOS_NOMINALES = {
    "4101": -5_000_000.0,   # CR 5M (ingreso)
    "4102":   -500_000.0,   # CR 500K (ingreso)
    "5101":  2_000_000.0,   # DR 2M (costo)
    "5201":  1_200_000.0,   # DR 1.2M (gasto)
    "5301":    300_000.0,   # DR 300K (gasto ventas)
}
SALDOS_BALANCE = {
    # Total Activos = Total Pasivos+Patrimonio (ecuacion contable cuadrada)
    "1101":  3_500_000.0,   # DR: Caja
    "1201":  1_500_000.0,   # DR: CxC
    "1301":  2_000_000.0,   # DR: Inventarios
    "2101": -1_800_000.0,   # CR: CxP
    "3101": -3_200_000.0,   # CR: Capital Social
    # Total DR=7M, CR=7M -> Balance cuadrado ANTES de la utilidad
}

# ── Replica de la lógica del endpoint annual_close ───────────

def build_closing_entries(saldos_nominales, accounts):
    """
    Construye los 3 asientos de cierre anual.
    Devuelve: (asiento_a, asiento_b, asiento_c, net_income)
    """
    lines_ing, lines_gas = [], []
    total_ing = total_gas = 0.0

    for code, saldo in saldos_nominales.items():
        acc_type = accounts.get(code, {}).get("type")
        acc_name = accounts.get(code, {}).get("name", code)
        if acc_type == "INGRESO" and saldo < 0:  # CR → DR para cerrar
            lines_ing.append({"account_code": code, "debit": abs(saldo), "credit": 0.0,
                               "description": f"Cierre ingreso: {acc_name}"})
            total_ing += abs(saldo)
        elif acc_type == "GASTO" and saldo > 0:  # DR → CR para cerrar
            lines_gas.append({"account_code": code, "debit": 0.0, "credit": saldo,
                               "description": f"Cierre gasto: {acc_name}"})
            total_gas += saldo

    net_income = round(total_ing - total_gas, 2)

    # Asiento A: Ingresos → 3304
    asiento_a = lines_ing + [{"account_code": "3304",
                               "debit": 0.0, "credit": round(total_ing, 5),
                               "description": "Resumen de Resultado — Ingresos"}]

    # Asiento B: Gastos → 3304
    asiento_b = lines_gas + [{"account_code": "3304",
                               "debit": round(total_gas, 5), "credit": 0.0,
                               "description": "Resumen de Resultado — Gastos"}]

    # Asiento C: 3304 → Patrimonio
    if net_income > 0:
        asiento_c = [
            {"account_code": "3304", "debit": round(net_income, 5), "credit": 0.0,
             "description": "Cancelar Resumen de Resultado"},
            {"account_code": "3303", "debit": 0.0, "credit": round(net_income, 5),
             "description": "Utilidad del Ejercicio 2026"},
        ]
    elif net_income < 0:
        loss = abs(net_income)
        asiento_c = [
            {"account_code": "3302", "debit": round(loss, 5), "credit": 0.0,
             "description": "Pérdida del Ejercicio 2026"},
            {"account_code": "3304", "debit": 0.0, "credit": round(loss, 5),
             "description": "Cancelar Resumen de Resultado"},
        ]
    else:
        asiento_c = []  # net_income == 0 → sin asiento C

    return asiento_a, asiento_b, asiento_c, net_income


def build_opening_entry(saldos_balance, next_year):
    """Genera el asiento de apertura del año siguiente."""
    lines = []
    for code, saldo in saldos_balance.items():
        if abs(saldo) < 0.001: continue
        lines.append({
            "account_code": code,
            "debit":  saldo if saldo > 0 else 0.0,
            "credit": abs(saldo) if saldo < 0 else 0.0,
            "description": f"Apertura {next_year}: {code}",
        })
    return lines

print("\n" + "═" * 65)
print("  SIMULACIÓN — Paso 2: Asientos de Cierre Anual 2026")
print("═" * 65)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 1: Construcción de los 3 asientos de cierre")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

a, b, c, net = build_closing_entries(SALDOS_NOMINALES, ACCOUNTS)

# Utilidad esperada: 5.5M (ingresos) - 3.5M (gastos) = 2M
expected_net = 2_000_000.0
check(f"Net income calculado correctamente = {net:,.0f}",
      abs(net - expected_net) < 0.01, f"got {net}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 2: Asiento A — Cierre de Ingresos")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ok_a, dr_a, cr_a = is_balanced(a)
check("Asiento A balanceado (DR = CR)",      ok_a, f"DR={dr_a:,.0f} CR={cr_a:,.0f}")
check("Asiento A tiene líneas de ingresos",  any(l["account_code"] in ["4101","4102"] for l in a))
check("Asiento A tiene contrapartida 3304",  any(l["account_code"] == "3304" for l in a))
check("Asiento A: todas las cuentas de ingreso son DR",
      all(l["debit"] > 0 for l in a if l["account_code"] != "3304"))
check("Asiento A: 3304 es CR",
      all(l["credit"] > 0 for l in a if l["account_code"] == "3304"))
check("CR de 3304 en Asiento A = total_ingresos (5.5M)",
      abs(sum(l["credit"] for l in a if l["account_code"] == "3304") - 5_500_000) < 0.01)
print(f"     → Asiento A: DR={dr_a:,.0f} CR={cr_a:,.0f} ({len(a)} líneas)")
for l in a:
    side = f"DR {l['debit']:>12,.0f}" if l['debit'] else f"CR {l['credit']:>12,.0f}"
    print(f"       {l['account_code']} {side}  {l['description'][:35]}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 3: Asiento B — Cierre de Gastos")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ok_b, dr_b, cr_b = is_balanced(b)
check("Asiento B balanceado (DR = CR)",      ok_b, f"DR={dr_b:,.0f} CR={cr_b:,.0f}")
check("Asiento B tiene líneas de gastos",    any(l["account_code"] in ["5101","5201","5301"] for l in b))
check("Asiento B tiene contrapartida 3304",  any(l["account_code"] == "3304" for l in b))
check("Asiento B: todas las cuentas de gasto son CR",
      all(l["credit"] > 0 for l in b if l["account_code"] != "3304"))
check("Asiento B: 3304 es DR",
      all(l["debit"] > 0 for l in b if l["account_code"] == "3304"))
check("DR de 3304 en Asiento B = total_gastos (3.5M)",
      abs(sum(l["debit"] for l in b if l["account_code"] == "3304") - 3_500_000) < 0.01)
print(f"     → Asiento B: DR={dr_b:,.0f} CR={cr_b:,.0f} ({len(b)} líneas)")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 4: Asiento C — Traspaso al Patrimonio")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ok_c, dr_c, cr_c = is_balanced(c)
check("Asiento C balanceado (DR = CR)",      ok_c, f"DR={dr_c:,.0f} CR={cr_c:,.0f}")
check("Asiento C tiene 3304 y 3303",
      any(l["account_code"] == "3304" for l in c) and
      any(l["account_code"] == "3303" for l in c))
check("Asiento C: 3304 → DR (cierra saldo CR neto de A-B)",
      any(l["account_code"] == "3304" and l["debit"] > 0 for l in c))
check("Asiento C: 3303 → CR (Utilidad del Ejercicio)",
      any(l["account_code"] == "3303" and l["credit"] > 0 for l in c))
utilidad_en_c = sum(l["credit"] for l in c if l["account_code"] == "3303")
check(f"Asiento C: 3303 CR = 2M (utilidad neta)",
      abs(utilidad_en_c - 2_000_000) < 0.01, f"got {utilidad_en_c:,.0f}")
print(f"     → Asiento C: DR={dr_c:,.0f} CR={cr_c:,.0f}")
for l in c:
    side = f"DR {l['debit']:>12,.0f}" if l['debit'] else f"CR {l['credit']:>12,.0f}"
    print(f"       {l['account_code']} {side}  {l['description'][:35]}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 5: Saldo final de 3304 después de A+B+C = 0")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

saldo_3304 = 0.0
for ent in [a, b, c]:
    for l in ent:
        if l["account_code"] == "3304":
            saldo_3304 += l["debit"] - l["credit"]
check("Saldo 3304 = 0 después de los 3 asientos (cuenta transitoria se cancela)",
      abs(saldo_3304) < 0.01, f"saldo_3304 = {saldo_3304:,.2f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 6: Escenario de pérdida")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SALDOS_PERDIDA = {
    "4101": -1_000_000.0,   # CR 1M (ingreso bajo)
    "5101":  2_000_000.0,   # DR 2M (costos altos)
}
a2, b2, c2, net2 = build_closing_entries(SALDOS_PERDIDA, ACCOUNTS)
check("Pérdida del ejercicio: net_income < 0",   net2 < 0, f"net={net2}")
check("Pérdida: Asiento C tiene 3302 (no 3303)",
      any(l["account_code"] == "3302" for l in c2) and
      not any(l["account_code"] == "3303" for l in c2))
ok_c2, dr_c2, cr_c2 = is_balanced(c2)
check("Asiento C (pérdida) balanceado", ok_c2, f"DR={dr_c2} CR={cr_c2}")
print(f"     → Pérdida neta: {net2:,.0f}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 7: Asiento de Apertura 2027")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Saldos del Balance al cierre de 2026 (después de incluir utilidad en patrimonio)
saldos_balance_2026 = dict(SALDOS_BALANCE)
saldos_balance_2026["3303"] = -2_000_000.0  # CR: Utilidad 2026 acumulada en patrimonio

apertura = build_opening_entry(saldos_balance_2026, 2027)
ok_ap, dr_ap, cr_ap = is_balanced(apertura)
check("Asiento de Apertura 2027 balanceado",     ok_ap, f"DR={dr_ap:,.0f} CR={cr_ap:,.0f}")
check("Apertura solo tiene cuentas de Balance",
      all(ACCOUNTS.get(l["account_code"], {}).get("type") in
          ["ACTIVO","PASIVO","PATRIMONIO",None] for l in apertura))
check("Apertura NO tiene cuentas nominales",
      not any(ACCOUNTS.get(l["account_code"], {}).get("type") in
              ["INGRESO","GASTO"] for l in apertura))
check("Apertura incluye cuentas ACTIVO (DR)",
      any(l["debit"] > 0 and ACCOUNTS.get(l["account_code"],{}).get("type") == "ACTIVO"
          for l in apertura))
check("Apertura incluye Cuentas por Pagar (CR)",
      any(l["credit"] > 0 and l["account_code"] == "2101" for l in apertura))
check("Apertura incluye Utilidad 2026 en Patrimonio",
      any(l["account_code"] == "3303" for l in apertura))
print(f"     → Apertura 2027: {len(apertura)} cuentas, DR={dr_ap:,.0f} CR={cr_ap:,.0f}")
for l in apertura:
    t = ACCOUNTS.get(l["account_code"], {}).get("type", "?")
    side = f"DR {l['debit']:>12,.0f}" if l['debit'] else f"CR {l['credit']:>12,.0f}"
    print(f"       [{t:9}] {l['account_code']} {side}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — Paso 2 APROBADO")
    print("     → Asiento A (cierre ingresos → 3304): balanceado ✓")
    print("     → Asiento B (cierre gastos → 3304): balanceado ✓")
    print("     → Asiento C (3304 → patrimonio): balanceado ✓")
    print("     → Saldo 3304 = 0 después de los 3 asientos ✓")
    print("     → Escenario pérdida usa 3302 (no 3303) ✓")
    print("     → Apertura 2027: solo Balance, balanceada ✓")
print("═" * 65 + "\n")
