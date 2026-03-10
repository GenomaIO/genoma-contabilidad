"""
SIM — Fórmulas fiscales Hacienda CR en calcular_score_v2
=========================================================
Valida que exposicion_iva y exposicion_renta reflejan correctamente:
  - Ingresos CR sin FE → IVA presunto (13/113) + Renta presunta (30%)
  - Gastos DB sin FE   → IVA no acreditable (13/113) + Escudo renta perdido (30%)

NO toca score_total ni I1-I5. Solo las tarjetas de exposición.
"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.conciliacion.fiscal_engine import calcular_score_v2

print("=" * 60)
print("SIM — Fórmulas Fiscales Hacienda CR (exposicion v2)")
print("=" * 60)

PASSED = FAILED = 0

def approx(a, b, tol=1.0):
    return math.isclose(a, b, abs_tol=tol)

def check(name, got, expected, tol=1.0):
    global PASSED, FAILED
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        ok = approx(got, expected, tol)
    else:
        ok = (got == expected)
    status = "✅ PASS" if ok else "❌ FAIL"
    if not ok:
        status += f" (got={got!r}, expected={expected!r})"
    print(f"  {status}: {name}")
    if ok:
        PASSED += 1
    else:
        FAILED += 1

def make_txn(typ, monto, estado="SIN_FE", desc="PAGO PROVEEDOR"):
    return {
        "tipo": typ, "monto": monto, "match_estado": estado,
        "descripcion": desc, "beneficiario_nombre": "TEST",
        "beneficiario_categoria": "TERCERO", "iva_estimado": None,
    }

# ── SIM-01: Solo ingresos CR sin FE ─────────────────────────────────────────
print("\nSIM-01: Solo CR SIN_FE → iva_presunto + renta_presunta")
txns_01 = [make_txn("CR", 113_000, "SIN_FE")]   # 100k base + 13k IVA incluido
r01 = calcular_score_v2(txns_01, [], [], 113_000, 0)

iva_esperado_cr    = round(113_000 * 13 / 113, 2)   # ≈ 13,000
renta_esperada_cr  = round((113_000 - iva_esperado_cr) * 0.25, 2)  # tasa max PF 2025
check("SIM-01 exposicion_iva (solo CR)",   r01["exposicion_iva"],   iva_esperado_cr,   50)
check("SIM-01 exposicion_renta (solo CR)", r01["exposicion_renta"], renta_esperada_cr, 200)
check("SIM-01 version = v2",               r01.get("version"),      "v2",              0)

# ── SIM-02: Solo gastos DB sin FE ────────────────────────────────────────────
print("\nSIM-02: Solo DB SIN_FE → iva_no_acreditable + escudo_perdido")
txns_02 = [make_txn("DB", 113_000, "SIN_FE")]
r02 = calcular_score_v2(txns_02, [], [], 0, 0)

iva_no_acred  = round(113_000 * 13 / 113, 2)   # ≈ 13,000
escudo_perdido = round(113_000 * 0.25, 2)       # tasa max PF 2025
check("SIM-02 exposicion_iva (DB no_acred)",    r02["exposicion_iva"],   iva_no_acred,   50)
check("SIM-02 exposicion_renta (DB escudo)",    r02["exposicion_renta"], escudo_perdido, 200)

# ── SIM-03: Mix CR + DB sin FE ───────────────────────────────────────────────
print("\nSIM-03: Mix CR + DB SIN_FE → totales correctos")
txns_03 = [
    make_txn("CR", 113_000, "SIN_FE"),
    make_txn("DB", 113_000, "SIN_FE"),
]
r03 = calcular_score_v2(txns_03, [], [], 113_000, 0)

total_iva_esperado   = iva_esperado_cr + iva_no_acred
total_renta_esperada = renta_esperada_cr + escudo_perdido
check("SIM-03 exposicion_iva (CR + DB)",     r03["exposicion_iva"],    total_iva_esperado,   100)
check("SIM-03 exposicion_renta (CR + DB)",   r03["exposicion_renta"],  total_renta_esperada, 400)
check("SIM-03 exposicion_total = IVA+Renta", r03["exposicion_total"],  total_iva_esperado + total_renta_esperada, 200)

# ── SIM-04: Sin SIN_FE → exposicion = 0 ─────────────────────────────────────
print("\nSIM-04: Todas CON_FE → exposicion = 0")
txns_04 = [
    make_txn("CR", 100_000, "CON_FE"),
    make_txn("DB",  50_000, "CON_FE"),
]
r04 = calcular_score_v2(txns_04, [], [], 100_000, 0)
check("SIM-04 exposicion_iva = 0",   r04["exposicion_iva"],   0, 1)
check("SIM-04 exposicion_renta = 0", r04["exposicion_renta"], 0, 1)

# ── SIM-05: CON_FE no contamina los sin FE ───────────────────────────────────
print("\nSIM-05: Mix CON_FE + SIN_FE → solo SIN_FE suma")
txns_05 = [
    make_txn("CR", 113_000, "CON_FE"),   # no debe sumar
    make_txn("CR", 226_000, "SIN_FE"),   # solo este
]
r05 = calcular_score_v2(txns_05, [], [], 339_000, 0)
iva_solo_sinfe = round(226_000 * 13 / 113, 2)
check("SIM-05 solo SIN_FE suma en exposicion_iva", r05["exposicion_iva"], iva_solo_sinfe, 50)

# ── SIM-06: score_total e I1-I5 NO cambian por la nueva lógica ───────────────
print("\nSIM-06: score_total e indicadores intactos (no rompemos nada)")
txns_06 = [make_txn("CR", 113_000, "SIN_FE")]
r06 = calcular_score_v2(txns_06, [], [], 113_000, 0)
check("SIM-06 score_total entre 0-100",    0 <= r06["score_total"] <= 100,  True, 0)
check("SIM-06 I1_cobertura existe",        "I1_cobertura_documental" in r06.get("indicadores", {}), True, 0)
check("SIM-06 I2_exposicion_iva existe",   "I2_exposicion_iva"       in r06.get("indicadores", {}), True, 0)

# ── Resultado ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if FAILED == 0:
    print(f"ALL {PASSED} SIM TESTS PASSED ✅")
else:
    print(f"❌ {FAILED} FAILED / {PASSED} PASSED")
print("=" * 60)
sys.exit(FAILED)
