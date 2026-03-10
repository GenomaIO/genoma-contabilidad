"""
SIM — asignar_d270_auto()
Verifica la asignación automática de código D-270 a txns SIN_FE:
  DB SIN_FE ≥ ₡1          → C (compras)
  CR SIN_FE con INTERES    → I (intereses)
  CR SIN_FE genérico       → V (ventas)
  CON_FE                   → sin código (None)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.conciliacion.fiscal_engine import asignar_d270_auto

PASS = 0
FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  ✅ PASS: {label}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {label} → esperado={expected!r}, got={got!r}")
        FAIL += 1

print("=" * 60)
print("SIM — D-270 Auto-Asignación desde CENTINELA")
print("=" * 60)

# ─── SIM-01: DB SIN_FE ≥ ₡1 → código C ─────────────────────────
print("\nSIM-01: DB SIN_FE → C (compras)")
txns_01 = [
    {"id": 1, "tipo": "DB", "monto": 150000, "match_estado": "SIN_FE",
     "descripcion": "SUPERMERCADO XYZ"},
    {"id": 2, "tipo": "DB", "monto": 1,      "match_estado": "SIN_FE",
     "descripcion": "COMISION BANCO"},  # mínimo ₡1
]
res_01 = asignar_d270_auto(txns_01)
check("SIM-01 compra grande → C",      res_01[0].get("d270_codigo"), "C")
check("SIM-01 compra ₡1    → C",       res_01[1].get("d270_codigo"), "C")

# ─── SIM-02: CR SIN_FE con palabras de interés → I ─────────────
print("\nSIM-02: CR SIN_FE con INTERES/RDTO → I")
txns_02 = [
    {"id": 3, "tipo": "CR", "monto": 9238,  "match_estado": "SIN_FE",
     "descripcion": "BNCR/INTERESES GANADOS EN SU C..."},
    {"id": 4, "tipo": "CR", "monto": 5000,  "match_estado": "SIN_FE",
     "descripcion": "RDTO CUENTA AHORRO"},
    {"id": 5, "tipo": "CR", "monto": 1200,  "match_estado": "SIN_FE",
     "descripcion": "RENDIMIENTO PLAZO FIJO"},
]
res_02 = asignar_d270_auto(txns_02)
check("SIM-02 INTERESES   → I", res_02[0].get("d270_codigo"), "I")
check("SIM-02 RDTO        → I", res_02[1].get("d270_codigo"), "I")
check("SIM-02 RENDIMIENTO → I", res_02[2].get("d270_codigo"), "I")

# ─── SIM-03: CR SIN_FE genérico → V ─────────────────────────────
print("\nSIM-03: CR SIN_FE genérico → V (ventas)")
txns_03 = [
    {"id": 6, "tipo": "CR", "monto": 200000, "match_estado": "SIN_FE",
     "descripcion": "SINPE/CLIENTE JUAN PEREZ"},
    {"id": 7, "tipo": "CR", "monto": 32099,  "match_estado": "SIN_FE",
     "descripcion": "CIDEP CENTRO IBEROAMER"},
]
res_03 = asignar_d270_auto(txns_03)
check("SIM-03 SINPE cliente → V",  res_03[0].get("d270_codigo"), "V")
check("SIM-03 CIDEP pago   → V",   res_03[1].get("d270_codigo"), "V")

# ─── SIM-04: CON_FE → no asigna código ──────────────────────────
print("\nSIM-04: CON_FE → d270_codigo = None")
txns_04 = [
    {"id": 8, "tipo": "DB", "monto": 50000, "match_estado": "CON_FE",
     "descripcion": "PROVEEDOR CON FACTURA"},
    {"id": 9, "tipo": "CR", "monto": 75000, "match_estado": "CONCILIADO",
     "descripcion": "CLIENTE CON FE"},
]
res_04 = asignar_d270_auto(txns_04)
check("SIM-04 CON_FE DB → sin código", res_04[0].get("d270_codigo"), None)
check("SIM-04 CONCILIADO → sin código", res_04[1].get("d270_codigo"), None)

# ─── SIM-05: Mix de estados ──────────────────────────────────────
print("\nSIM-05: Mix SIN_FE + CON_FE")
txns_05 = [
    {"id": 10, "tipo": "DB", "monto": 60000, "match_estado": "SIN_FE",
     "descripcion": "SODA RUTA 35"},
    {"id": 11, "tipo": "CR", "monto": 44107, "match_estado": "SIN_FE",
     "descripcion": "BNCR/INTERESES GANADOS"},
    {"id": 12, "tipo": "DB", "monto": 25000, "match_estado": "CON_FE",
     "descripcion": "PROVEEDOR OK"},
]
res_05 = asignar_d270_auto(txns_05)
check("SIM-05 DB SIN_FE → C",    res_05[0].get("d270_codigo"), "C")
check("SIM-05 CR INTERES → I",   res_05[1].get("d270_codigo"), "I")
check("SIM-05 CON_FE → None",    res_05[2].get("d270_codigo"), None)

# ─────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
if FAIL == 0:
    print(f"ALL {PASS} SIM TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 60)
