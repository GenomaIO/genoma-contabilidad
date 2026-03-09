#!/usr/bin/env python3
"""
sim_score_fiscal_v2_e2e.py — SIM + E2E  Fase 6
================================================
Verifica calcular_score_v2() con 3 perfiles de riesgo:
  - Perfil VERDE: todas las txns tienen CON_FE
  - Perfil MODERADO: 50% con FE, 50% sin FE
  - Perfil CRITICO: casi todas SIN_FE, SINPE sin comprobante
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
print("\n[SIM-0] Importación de calcular_score_v2")
try:
    from services.conciliacion.fiscal_engine import calcular_score_v2, _score_vacio
    check(True, "calcular_score_v2 importado OK")
except Exception as ex:
    check(False, f"Import falló: {ex}")
    sys.exit(1)


# ── Helpers ───────────────────────────────────────────────────────────────────
def make_txn(estado, tipo, monto, desc="TEST", bnom="PEPITO", iva=0.0):
    return {"match_estado": estado, "tipo": tipo, "monto": monto,
            "descripcion": desc, "beneficiario_nombre": bnom,
            "beneficiario_categoria": "TERCERO", "iva_estimado": iva}

FE_VACIA = []   # sin FE emitidas (peor caso para I5)


# ── PERFIL VERDE: 100% CON_FE ─────────────────────────────────────────────────
print("\n[SIM-1] Perfil VERDE (100% CON_FE)")
TXNS_VERDE = [
    make_txn("CON_FE", "CR", 500_000.0),
    make_txn("CON_FE", "CR", 250_000.0),
    make_txn("CON_FE", "DB", 100_000.0),
    make_txn("CON_FE", "DB",  50_000.0),
]
FE_VERDE = [{"monto": 750_000.0}]  # FE cubre los ingresos
r_verde = calcular_score_v2(TXNS_VERDE, FE_VERDE, [], 1_800_000.0, 1_800_000.0)
check(r_verde["score_total"] >= 80,    f"Score VERDE >= 80 (got {r_verde['score_total']})")
check(r_verde["nivel"] in ("VERDE", "BAJO"), f"Nivel VERDE o BAJO (got {r_verde['nivel']})")
check(r_verde["version"] == "v2",      "version = v2")
check(r_verde["exposicion_iva"] == 0.0, "exposicion_iva = 0 (todo CON_FE)")
check("I1_cobertura_documental" in r_verde["indicadores"], "indicador I1 presente")
check(r_verde["indicadores"]["I1_cobertura_documental"] == 100.0, "I1 = 100 (100% CON_FE)")


# ── PERFIL MODERADO: 50% sin FE, gastos mixtos ───────────────────────────────
print("\n[SIM-2] Perfil MODERADO (50% SIN_FE)")
TXNS_MODERADO = [
    make_txn("CON_FE", "CR", 300_000.0),
    make_txn("SIN_FE", "CR", 200_000.0, "DEPOSITO CUENTA", iva=22_124.0),
    make_txn("CON_FE", "DB", 100_000.0),
    make_txn("SIN_FE", "DB",  80_000.0, "JUAN CARLOS PERSONA"),
]
FE_MOD = [{"monto": 300_000.0}]
r_mod = calcular_score_v2(TXNS_MODERADO, FE_MOD, [], 500_000.0, 300_000.0)
check(r_mod["score_total"] >= 40 and r_mod["score_total"] <= 80,
      f"Score MODERADO entre 40-80 (got {r_mod['score_total']})")
check(r_mod["nivel"] in ("MODERADO", "BAJO"), f"Nivel MODERADO o BAJO (got {r_mod['nivel']})")
check(r_mod["exposicion_iva"] > 0, f"IVA en riesgo > 0 (got {r_mod['exposicion_iva']})")
check(r_mod["indicadores"]["I1_cobertura_documental"] == 50.0,
      f"I1 = 50% (2 de 4 con FE, got {r_mod['indicadores']['I1_cobertura_documental']})")


# ── PERFIL CRITICO: SINPE masivo sin FE ──────────────────────────────────────
print("\n[SIM-3] Perfil CRITICO (SINPE sin FE, concentración en 2 beneficiarios)")
TXNS_CRITICO = [
    make_txn("SIN_FE", "CR", 500_000.0, "SINPE MOVIL 88443928", bnom="CLIENTE_A", iva=55_752.0),
    make_txn("SIN_FE", "CR", 300_000.0, "TRANSFERENCIA BCR",    bnom="CLIENTE_B", iva=33_451.0),
    make_txn("SIN_FE", "DB", 400_000.0, "PROVEEDOR FANTASMA",   bnom="PROVEEDOR_X"),
    make_txn("SIN_FE", "DB", 200_000.0, "TRANSFER DESCONOCIDO", bnom="PROVEEDOR_X"),
    make_txn("CON_FE", "DB", 10_000.0),   # solo 1 CON_FE de 5
]
r_crit = calcular_score_v2(TXNS_CRITICO, FE_VACIA, [], 1_500_000.0, 200_000.0)
check(r_crit["score_total"] < 50, f"Score CRITICO < 50 (got {r_crit['score_total']})")
check(r_crit["nivel"] in ("CRITICO", "MODERADO"), f"Nivel CRITICO o MODERADO (got {r_crit['nivel']})")
check(r_crit["exposicion_iva"] > 80_000.0,
      f"IVA expuesto > ₡80,000 (got ₡{r_crit['exposicion_iva']:,.0f})")
# I4: SINPE sin FE → sin referencia trazable
check(r_crit["indicadores"]["I4_sin_referencia"] < 80,
      f"I4 sin referencia bajo < 80 (got {r_crit['indicadores']['I4_sin_referencia']})")


# ── SIM-4: Score vacío ────────────────────────────────────────────────────────
print("\n[SIM-4] Sin transacciones → score vacío")
r_vacio = calcular_score_v2([], FE_VACIA, [], 0.0, 0.0)
check(r_vacio["score_total"] == 100.0, "Sin txns → score 100 (no hay riesgo)")
check(r_vacio["nivel"] == "VERDE",     "Sin txns → nivel VERDE")


# ── SIM-5: Función presente en fiscal_engine.py ──────────────────────────────
print("\n[SIM-5] Verificación estática")
src = (ROOT / "services" / "conciliacion" / "fiscal_engine.py").read_text(encoding="utf-8")
check("calcular_score_v2"          in src, "calcular_score_v2 en fiscal_engine.py")
check("I1_cobertura_documental"    in src, "indicador I1 definido")
check("I2_exposicion_iva"          in src, "indicador I2 definido")
check("I3_concentracion_sinfe"     in src, "indicador I3 definido")
check("I4_sin_referencia"          in src, "indicador I4 definido")
check("I5_discrepancia_d101"       in src, "indicador I5 definido")
check("0.30" in src and "0.25" in src and "0.20" in src, "pesos 30/25/20 definidos")


# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F6 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
