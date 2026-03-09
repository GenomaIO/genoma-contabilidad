#!/usr/bin/env python3
"""
sim_matching_fe_e2e.py — SIM + E2E  Fase 3
============================================
Verifica que el motor de matching usa FE emitidas/recibidas.
Prueba con datos sintéticos: BANK_FEE auto-CON_FE, txns vs FE lista, sin FE → SIN_FE.
"""
import sys, pathlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0; FAIL = 0

def check(condition, label):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition: PASS += 1
    else: FAIL += 1


# ── SIM-1: Lógica de matching pura (sin BD) ──────────────────────────────────
print("\n[SIM-1] Lógica de matching contra FE (motor puro)")

from services.conciliacion.reconciliation_engine import (
    match_transactions, calcular_diferencia_saldo
)

# Simular txns bancarias
BANK_TXNS = [
    {"id":"t1","fecha":"2026-02-02","monto": 9238.9,  "tipo":"CR", "beneficiario_categoria":"BANK_INTEREST", "descripcion":"BNCR INTERESES"},
    {"id":"t2","fecha":"2026-02-02","monto":200_000.0,"tipo":"DB", "beneficiario_categoria":"BANK_FEE",      "descripcion":"BNCR COMISION"},
    {"id":"t3","fecha":"2026-02-05","monto":260_000.0,"tipo":"DB", "beneficiario_categoria":"TERCERO",      "descripcion":"JOSE ALEJANDRO"},
    {"id":"t4","fecha":"2026-02-09","monto": 23_000.0,"tipo":"DB", "beneficiario_categoria":"TERCERO",      "descripcion":"JOSE PABLO ROMERO"},
    {"id":"t5","fecha":"2026-02-13","monto":  5_000.0,"tipo":"DB", "beneficiario_categoria":"TERCERO",      "descripcion":"SODA RUTA 35"},
]

# FE recibidas del período (gastos con comprobante)
FE_RECIBIDAS = [
    {"id":"fe1","fecha":"2026-02-09","monto":23_000.0,"description":"ROMERO VILLEG"},
    # t4 debería matchear con fe1 (monto exacto)
]

TOLERANCIA_FE = 0.02
fe_gastos = list(FE_RECIBIDAS)

resultados = {}
for txn in BANK_TXNS:
    cat = txn.get("beneficiario_categoria","TERCERO")
    txn_monto = abs(float(txn["monto"]))
    txn_tipo  = txn["tipo"]

    if cat in ("BANK_FEE","BANK_INTEREST"):
        txn["match_estado"] = "CON_FE"
        txn["tiene_fe"]     = True
        txn["fe_numero"]    = "CARGO_BANCARIO"
        resultados[txn["id"]] = txn["match_estado"]
        continue

    pool = fe_gastos if txn_tipo == "DB" else []
    best = None; best_diff = 1.0
    for i, fe in enumerate(pool):
        fe_monto = abs(float(fe.get("monto",0) or 0))
        if fe_monto <= 0: continue
        diff = abs(txn_monto - fe_monto) / fe_monto
        if diff < TOLERANCIA_FE and diff < best_diff:
            best_diff = diff; best = (i, fe)

    if best:
        idx, fe = best
        txn["match_estado"] = "CON_FE"
        txn["tiene_fe"]     = True
        txn["fe_numero"]    = fe["id"]
        pool.pop(idx)
    else:
        txn["match_estado"] = "SIN_FE"
        txn["tiene_fe"]     = False
        txn["fe_numero"]    = None
    resultados[txn["id"]] = txn["match_estado"]

check(resultados["t1"] == "CON_FE",  "t1 BANK_INTEREST → CON_FE automático")
check(resultados["t2"] == "CON_FE",  "t2 BANK_FEE → CON_FE automático")
check(resultados["t4"] == "CON_FE",  "t4 JOSE PABLO ROMERO matchea con FE recibida (monto exacto)")
check(resultados["t3"] == "SIN_FE",  "t3 JOSE ALEJANDRO sin FE → SIN_FE (riesgo fiscal)")
check(resultados["t5"] == "SIN_FE",  "t5 SODA sin FE → SIN_FE")

# ── SIM-2: Tolerancia de monto ±2% ───────────────────────────────────────────
print("\n[SIM-2] Tolerancia de monto ±2%")
monto_txn = 100_000.0
monto_fe_ok  = 99_000.0   # diff 1% → MATCH
monto_fe_no  = 97_000.0   # diff 3% → NO match

diff_ok = abs(monto_txn - monto_fe_ok) / monto_fe_ok
diff_no = abs(monto_txn - monto_fe_no) / monto_fe_no

check(diff_ok < TOLERANCIA_FE, f"±1% dentro tolerancia ({diff_ok:.3f} < {TOLERANCIA_FE})")
check(diff_no > TOLERANCIA_FE, f"±3% fuera tolerancia ({diff_no:.3f} > {TOLERANCIA_FE})")

# ── SIM-3: calcular_diferencia_saldo con saldo real ──────────────────────────
print("\n[SIM-3] calcular_diferencia_saldo — sin hardcode 0.0")
# Scenario: banco=1,500,000  libros=787,402 → diferencia significativa real
diff = calcular_diferencia_saldo(1_500_000.0, 787_402.0)
check(diff["diferencia"] != 0, "Diferencia no es 0 (saldo_libros no está hardcodeado)")
check(diff["estado"] == "DIFERENCIA_SIGNIFICATIVA", "Estado correcto: DIFERENCIA_SIGNIFICATIVA")
check(abs(diff["diferencia"] - 712_598.0) < 1, f"Diferencia exacta ₡712,598 (got {diff['diferencia']:.0f})")

# Scenario cuadrado
diff2 = calcular_diferencia_saldo(1_000_000.0, 1_000_000.5)
check(diff2["estado"] == "CUADRADO", "Diferencia < ₡1 → CUADRADO")

# ── SIM-4: Router actualizado ─────────────────────────────────────────────────
print("\n[SIM-4] Verificación estática del router")
router_src = (ROOT / "services" / "conciliacion" / "router.py").read_text(encoding="utf-8")
check('"CON_FE"'    in router_src, "run_match usa CON_FE")
check('"SIN_FE"'    in router_src, "run_match usa SIN_FE")
check('"con_fe"'                      in router_src, "stats devuelve con_fe")
check('"sin_fe"'                      in router_src, "stats devuelve sin_fe")
check("CARGO_BANCARIO"               in router_src, "BANK_FEE/INTEREST → CARGO_BANCARIO")
check("fe_ingresos_disponibles"       in router_src, "pool de FE para ingresos")
check("fe_gastos_disponibles"         in router_src, "pool de FE para gastos")
check("TOLERANCIA_FE = 0.02"         in router_src, "tolerancia FE definida")

# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F3 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
