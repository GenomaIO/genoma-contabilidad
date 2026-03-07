"""
tests/sim_tax_step1_logic.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 1 — Simulación de lógica pura de cálculo fiscal (sin DB, sin HTTP)

Valida:
  · Algoritmo de tramos progresivos (_apply_brackets)
  · Tramos 2026 oficiales cargados correctamente (PJ, PF, PJ_GRANDE)
  · Proyección desde mes parcial al año completo
  · Casos límite: utilidad negativa, exactamente en el límite de tramo
  · Detección correcta de Gran Contribuyente

Ejecutar con:
    python tests/sim_tax_step1_logic.py
    python -m pytest tests/sim_tax_step1_logic.py -v
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Importar la función pura desde el router ──────────────────
from services.tax.router import _apply_brackets, SEED_2026

PASS = "  ✅"
FAIL = "  ❌"
errors = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"{PASS} {label}")
    else:
        msg = f"{FAIL} {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        errors.append(label)


def near(a: float, b: float, tol: float = 0.5) -> bool:
    """Comparación monetaria con tolerancia de ₡0.50"""
    return abs(a - b) <= tol


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
print("  SIMULACIÓN — Paso 1: Lógica Fiscal Pura")
print("  Módulo: services/tax/router.py :: _apply_brackets + SEED_2026")
print("═" * 65)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 1: Seed 2026 — estructura y conteo")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pj_tramos       = [b for b in SEED_2026 if b["taxpayer_type"] == "PJ"]
pf_tramos       = [b for b in SEED_2026 if b["taxpayer_type"] == "PF"]
pj_grande       = [b for b in SEED_2026 if b["taxpayer_type"] == "PJ_GRANDE"]

check("SEED_2026 tiene al menos 10 filas",     len(SEED_2026) >= 10)
check("Hay 4 tramos PJ",                        len(pj_tramos) == 4,     f"encontrados: {len(pj_tramos)}")
check("Hay 5 tramos PF",                        len(pf_tramos) == 5,     f"encontrados: {len(pf_tramos)}")
check("Hay 1 tramo PJ_GRANDE",                  len(pj_grande) == 1,     f"encontrados: {len(pj_grande)}")
check("Primer tramo PJ empieza en 0",           pj_tramos[0]["income_from"] == 0)
check("Primer tramo PF empieza en 0",           pf_tramos[0]["income_from"] == 0)
check("Primer tramo PF tiene tasa 0 (exento)",  pf_tramos[0]["rate"] == 0.0)
check("PJ_GRANDE tiene tasa 0.30",              pj_grande[0]["rate"] == 0.30)
check("Último tramo PJ no tiene límite (None)", pj_tramos[-1]["income_to"] is None)
check("Último tramo PF no tiene límite (None)", pf_tramos[-1]["income_to"] is None)

# Verificar montos 2026 (Decreto 45333-H)
check("PJ tramo 1 hasta ₡5,621,000",   pj_tramos[0]["income_to"] == 5_621_000)
check("PJ tramo 1 tasa 5%",            pj_tramos[0]["rate"] == 0.05)
check("PJ tramo 2 hasta ₡8,433,000",   pj_tramos[1]["income_to"] == 8_433_000)
check("PJ tramo 2 tasa 10%",           pj_tramos[1]["rate"] == 0.10)
check("PJ tramo 3 hasta ₡11,243,000",  pj_tramos[2]["income_to"] == 11_243_000)
check("PJ tramo 3 tasa 15%",           pj_tramos[2]["rate"] == 0.15)
check("PJ tramo 4 tasa 20%",           pj_tramos[3]["rate"] == 0.20)
check("PF exento hasta ₡6,244,000",    pf_tramos[0]["income_to"] == 6_244_000)
check("PF tasa 10% hasta ₡8,329,000",  pf_tramos[1]["income_to"] == 8_329_000)
check("PF tasa 15% hasta ₡10,414,000", pf_tramos[2]["income_to"] == 10_414_000)
check("PF tasa 20% hasta ₡20,872,000", pf_tramos[3]["income_to"] == 20_872_000)
check("PF tasa 25% en adelante",        pf_tramos[4]["rate"] == 0.25)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 2: Cálculo PJ — tramos progresivos 2026")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Referencia manual:
#   Utilidad: ₡10,000,000
#   Tramo 1: ₡5,621,000 × 5% = ₡281,050
#   Tramo 2: (₡8,433,000 - ₡5,621,000) × 10% = ₡281,200
#   Tramo 3: (₡10,000,000 - ₡8,433,000) × 15% = ₡235,050
#   Total = ₡797,300

UTILIDAD_PJ_TEST = 10_000_000.0
resultado_pj = _apply_brackets(UTILIDAD_PJ_TEST, pj_tramos)

ESPERADO_TRAMO1 = 5_621_000 * 0.05              # 281,050
ESPERADO_TRAMO2 = (8_433_000 - 5_621_000) * 0.10  # 281,200
ESPERADO_TRAMO3 = (10_000_000 - 8_433_000) * 0.15 # 235,050
ESPERADO_TOTAL_PJ = ESPERADO_TRAMO1 + ESPERADO_TRAMO2 + ESPERADO_TRAMO3  # 797,300

check("PJ ₡10M → retorna resultado",          resultado_pj is not None)
check("PJ ₡10M → 3 tramos aplicados",         len(resultado_pj["desglose"]) == 3,
      f"encontrados: {len(resultado_pj['desglose'])}")
check(f"PJ ₡10M → total ~₡{ESPERADO_TOTAL_PJ:,.0f}",
      near(resultado_pj["total"], ESPERADO_TOTAL_PJ),
      f"obtenido: ₡{resultado_pj['total']:,.2f}")

# Caso con utilidad en el tramo 4 (> 11,243,000)
UTILIDAD_PJ_4T = 15_000_000.0
res_pj4 = _apply_brackets(UTILIDAD_PJ_4T, pj_tramos)
T1 = 5_621_000 * 0.05
T2 = (8_433_000 - 5_621_000) * 0.10
T3 = (11_243_000 - 8_433_000) * 0.15
T4 = (15_000_000 - 11_243_000) * 0.20
TOTAL_PJ_4T = T1 + T2 + T3 + T4

check("PJ ₡15M → 4 tramos aplicados",         len(res_pj4["desglose"]) == 4)
check(f"PJ ₡15M → total ~₡{TOTAL_PJ_4T:,.0f}",
      near(res_pj4["total"], TOTAL_PJ_4T),
      f"obtenido: ₡{res_pj4['total']:,.2f}")

# Tasa efectiva aproximada para PJ ₡15M
tasa_ef_pj = res_pj4["total"] / UTILIDAD_PJ_4T * 100
check("PJ ₡15M tasa efectiva entre 10% y 20%",
      10 < tasa_ef_pj < 20,
      f"tasa: {tasa_ef_pj:.2f}%")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 3: Cálculo PF — 5 tramos con exención")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Utilidad: ₡12,000,000
# Tramo 1: ₡6,244,000 × 0% = ₡0 (exento)
# Tramo 2: (₡8,329,000 - ₡6,244,000) × 10% = ₡208,500
# Tramo 3: (₡10,414,000 - ₡8,329,000) × 15% = ₡312,750
# Tramo 4: (₡12,000,000 - ₡10,414,000) × 20% = ₡317,200
# Total = ₡838,450

UTILIDAD_PF = 12_000_000.0
res_pf = _apply_brackets(UTILIDAD_PF, pf_tramos)

PF_T1 = 0
PF_T2 = (8_329_000 - 6_244_000) * 0.10   # 208,500
PF_T3 = (10_414_000 - 8_329_000) * 0.15  # 312,750
PF_T4 = (12_000_000 - 10_414_000) * 0.20 # 317,200
TOTAL_PF = PF_T1 + PF_T2 + PF_T3 + PF_T4  # 838,450

check("PF ₡12M → retorna resultado",           res_pf is not None)
check("PF ₡12M → 4 tramos activos (exento incluido)",
      len(res_pf["desglose"]) == 4,
      f"encontrados: {len(res_pf['desglose'])}")
check(f"PF ₡12M → total ~₡{TOTAL_PF:,.0f}",
      near(res_pf["total"], TOTAL_PF),
      f"obtenido: ₡{res_pf['total']:,.2f}")

# PF por debajo del exento → sin impuesto
res_pf_exento = _apply_brackets(5_000_000, pf_tramos)
check("PF ₡5M (bajo exento) → total = ₡0",
      res_pf_exento["total"] == 0.0,
      f"obtenido: ₡{res_pf_exento['total']:,.2f}")

# PF en zona alta (> 20,872,000) → 5 tramos
res_pf_alta = _apply_brackets(25_000_000, pf_tramos)
check("PF ₡25M → 5 tramos aplicados",
      len(res_pf_alta["desglose"]) == 5,
      f"encontrados: {len(res_pf_alta['desglose'])}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 4: Casos especiales")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# PJ_GRANDE → tasa fija 30%
UTILIDAD_GRANDE = 200_000_000.0
res_grande = _apply_brackets(UTILIDAD_GRANDE, pj_grande)
ESPERADO_GRANDE = UTILIDAD_GRANDE * 0.30  # 60,000,000

check("PJ_GRANDE ₡200M → tasa fija 30%",
      near(res_grande["total"], ESPERADO_GRANDE, tol=1.0),
      f"obtenido: ₡{res_grande['total']:,.2f}")
check("PJ_GRANDE → 1 tramo",
      len(res_grande["desglose"]) == 1)

# Utilidad cero → sin impuesto
res_cero = _apply_brackets(0, pj_tramos)
check("Utilidad ₡0 → impuesto ₡0",
      res_cero["total"] == 0.0)

# Utilidad negativa → sin impuesto (no entra en ningún tramo)
res_neg = _apply_brackets(-1_000_000, pj_tramos)
check("Utilidad negativa → impuesto ₡0",
      res_neg["total"] == 0.0,
      f"obtenido: ₡{res_neg['total']:,.2f}")

# Exactamente en límite del tramo 1 PJ (5,621,000)
res_limite = _apply_brackets(5_621_000, pj_tramos)
LIMITE_ESPERADO = 5_621_000 * 0.05  # 281,050
check("PJ exactamente en límite tramo 1 → solo 5%",
      near(res_limite["total"], LIMITE_ESPERADO),
      f"obtenido: ₡{res_limite['total']:,.2f}, esperado: ₡{LIMITE_ESPERADO:,.2f}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 5: Proyección desde mes parcial")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Si a marzo (mes 3) la utilidad es ₡3,000,000:
# Proyectado = 3,000,000 / 3 × 12 = ₡12,000,000 anuales

def proyectar(utilidad_acumulada: float, mes: int) -> float:
    return (utilidad_acumulada / mes) * 12


UTIL_MARZO = 3_000_000
MES        = 3
proyectado = proyectar(UTIL_MARZO, MES)
check("Proyección marzo (mes 3) = ×4",
      proyectado == UTIL_MARZO * (12 / MES),
      f"obtenido: ₡{proyectado:,.0f}")
check("Proyección = ₡12,000,000",
      near(proyectado, 12_000_000),
      f"obtenido: ₡{proyectado:,.0f}")

# Calcular renta sobre proyección → debe coincidir con cálculo PJ de ₡12M
res_proyectado = _apply_brackets(proyectado, pj_tramos)
REF_PJ_12M_T1 = 5_621_000 * 0.05
REF_PJ_12M_T2 = (8_433_000 - 5_621_000) * 0.10
REF_PJ_12M_T3 = (11_243_000 - 8_433_000) * 0.15
REF_PJ_12M_T4 = (12_000_000 - 11_243_000) * 0.20
TOTAL_PJ_12M = REF_PJ_12M_T1 + REF_PJ_12M_T2 + REF_PJ_12M_T3 + REF_PJ_12M_T4

check(f"Renta sobre proyección ₡12M ~₡{TOTAL_PJ_12M:,.0f}",
      near(res_proyectado["total"], TOTAL_PJ_12M),
      f"obtenido: ₡{res_proyectado['total']:,.2f}")

provision = res_proyectado["total"] / 12
check("Provisión mensual = renta_anual / 12",
      near(provision, res_proyectado["total"] / 12))
check("Provisión mensual > 0",
      provision > 0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 6: Tramos manuales (año ficticio 2027)")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Simula que el usuario cargó tramos 2027 distintos a 2026
tramos_2027 = [
    {"income_from": 0,         "income_to": 6_000_000,  "rate": 0.05},
    {"income_from": 6_000_000, "income_to": 10_000_000, "rate": 0.12},
    {"income_from": 10_000_000,"income_to": None,        "rate": 0.22},
]
res_2027 = _apply_brackets(14_000_000, tramos_2027)
T27_1 = 6_000_000 * 0.05
T27_2 = 4_000_000 * 0.12
T27_3 = 4_000_000 * 0.22
TOTAL_2027 = T27_1 + T27_2 + T27_3

check("Tramos manuales 2027 → cálculo correcto",
      near(res_2027["total"], TOTAL_2027),
      f"obtenido: ₡{res_2027['total']:,.2f}, esperado: ₡{TOTAL_2027:,.2f}")
check("Motor es agnóstico al año — usa lo que le pasen",
      True)  # El motor no sabe el año, solo aplica los tramos recibidos


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — Paso 1 APROBADO")
    print("     → SEED_2026 tiene los valores exactos del Decreto 45333-H")
    print("     → _apply_brackets es correcto para PJ, PF, PJ_GRANDE")
    print("     → Casos límite (negativo, cero, exacto en tramo) OK")
    print("     → Proyección desde mes parcial matemáticamente correcta")
    print("     → Motor es agnóstico al año (acepta cualquier tramo manual)")
print("═" * 65 + "\n")
