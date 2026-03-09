#!/usr/bin/env python3
"""
sim_tarifa_iva_e2e.py — SIM + E2E  Fase 4
==========================================
Verifica que estimar_tarifa() clasifica correctamente 12+ casos
según Ley 9635 CR, y que calcular_iva_incluido() usa la tarifa variable.
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


# ── Importar ──────────────────────────────────────────────────────────────────
print("\n[SIM-0] Importación")
try:
    from services.conciliacion.fiscal_engine import (
        estimar_tarifa, calcular_iva_incluido, IVA_RATE
    )
    check(True, "fiscal_engine importado OK")
    check(IVA_RATE == 0.13, f"IVA_RATE = {IVA_RATE} (esperado 0.13)")
except Exception as ex:
    check(False, f"Import falló: {ex}")
    sys.exit(1)


# ── SIM-1: Tabla de tarifas por semántica (Ley 9635) ─────────────────────────
CASOS_TARIFA = [
    # (descripcion, categoria, tarifa_esperada, label)
    ("BNCR INTERESES GANADOS",      "BANK_INTEREST", 0.00, "BANK_INTEREST → 0% (exento art.8)"),
    ("BNCR COMISION TRANSFERENCIA", "BANK_FEE",      0.00, "BANK_FEE → 0%"),
    ("ZUNIGA PEREZ / COMBUSTIBLE",  "TERCERO",       0.00, "COMBUSTIBLE → 0%"),
    ("FARMACIA SUCURSAL CENTRO",    "TERCERO",       0.00, "FARMACIA → 0%"),
    ("CLINICA DR MORA",             "TERCERO",       0.00, "CLINICA → 0% (salud)"),
    ("INS SEGURO VEHICULO",         "TERCERO",       0.02, "INS/SEGURO → 2% (Ley 9635 art.11)"),
    ("PAGO HONORARIO ABOGADO",      "TERCERO",       0.04, "HONORARIO/ABOGADO → 4% (transitorio V)"),
    ("CONSULTOR SISTEMAS S.A.",     "TERCERO",       0.04, "CONSULTOR → 4%"),
    ("UNIVERSIDAD LATINA",          "TERCERO",       0.04, "UNIVERSIDAD → 4%"),
    ("SODA RUTA 35 ALAJUELA",       "TERCERO",       0.13, "SODA → 13% (general)"),
    ("MARCOS VINICIO JIMENEZ",      "TERCERO",       0.13, "Persona sin keyword → 13%"),
    ("TRANSFERENCIA SINPE MOVIL",   "SINPE",         0.13, "SINPE ingreso → 13%"),
]

print(f"\n[SIM-1] {len(CASOS_TARIFA)} casos de tarifa (Ley 9635)")
for desc, cat, tarifa_esp, label in CASOS_TARIFA:
    t = estimar_tarifa(desc, cat)
    check(t == tarifa_esp, f"{label} → {int(t*100)}% (esperado {int(tarifa_esp*100)}%)")


# ── SIM-2: calcular_iva_incluido con tarifa variable ─────────────────────────
print("\n[SIM-2] calcular_iva_incluido con tarifa variable")

# ₡130,000 con 13% → base ₡115,044.25, IVA ₡14,955.75
r1 = calcular_iva_incluido(130_000.0, 0.13)
check(abs(r1["base"] - 115044.25) < 0.5,  f"13%: base={r1['base']} ≈ 115,044.25")
check(abs(r1["iva"]  -  14955.75) < 0.5,  f"13%: IVA={r1['iva']} ≈ 14,955.75")
check(r1["tarifa_pct"] == 13,              "tarifa_pct = 13")

# ₡104,000 con 4% → base ₡100,000, IVA ₡4,000
r2 = calcular_iva_incluido(104_000.0, 0.04)
check(abs(r2["base"] - 100_000.0) < 0.5,  f"4%: base={r2['base']} ≈ 100,000")
check(abs(r2["iva"]  -   4_000.0) < 0.5,  f"4%: IVA={r2['iva']} ≈ 4,000")
check(r2["tarifa_pct"] == 4,               "tarifa_pct = 4")

# ₡40,000 con 0% → base=40,000, IVA=0
r3 = calcular_iva_incluido(40_000.0, 0.00)
check(r3["base"] == 40_000.0, f"0%: base={r3['base']} = 40,000 (exento)")
check(r3["iva"]  == 0.0,      f"0%: IVA={r3['iva']} = 0")


# ── SIM-3: Fórmula base = monto/1.13 (estándar CR) ───────────────────────────
print("\n[SIM-3] Fórmula base = bruto ÷ 1.13")
bruto = 200_000.0
esperada_base = round(bruto / 1.13, 2)
r4 = calcular_iva_incluido(bruto, 0.13)
check(abs(r4["base"] - esperada_base) < 0.5,
      f"₡{bruto:,.0f} / 1.13 = ₡{r4['base']:,.2f} (esperado ₡{esperada_base:,.2f})")


# ── SIM-4: No duplicado IVA_RATE ─────────────────────────────────────────────
print("\n[SIM-4] Sin duplicados en fiscal_engine.py")
src = (ROOT / "services" / "conciliacion" / "fiscal_engine.py").read_text(encoding="utf-8")
count_iva_rate = src.count("IVA_RATE = 0.13")
check(count_iva_rate == 1, f"IVA_RATE definido exactamente 1 vez (got {count_iva_rate})")
check("estimar_tarifa"     in src, "estimar_tarifa() existe en fiscal_engine.py")
check("_TARIFA_SEMANTICA"  in src, "_TARIFA_SEMANTICA definida")
check("0.04"               in src, "tarifa 4% existe (servicios profesionales)")
check("GASOLINA"           in src, "GASOLINA → 0%")


# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F4 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
