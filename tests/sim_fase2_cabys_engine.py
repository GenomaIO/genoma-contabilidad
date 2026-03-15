"""
SIM Fase 2 — Motor CABYS Engine
Verifica la lógica pura de resolución CABYS → cuenta + herencia IVA + flag activo.
Todos los SIM son offline — sin base de datos real.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.cabys_engine import resolver_cabys, iva_tipo_desde_tarifa

PASS = 0
FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond:
        print(f"  ✅ PASS: {label}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {label}")
        FAIL += 1

# Mock del DB para los SIM
class MockDB:
    def __init__(self, rules=None):
        self.rules = rules or []  # lista de dicts simulando cabys_account_rules

    def execute(self, stmt, params=None):
        return MockResult(self.rules, params or {})

class MockResult:
    def __init__(self, rules, params):
        self._rows = []
        cabys  = params.get("cabys",  "") or ""
        prefix = params.get("prefix", "") or cabys[:2]
        for r in rules:
            if cabys and r.get("cabys_code") == cabys:
                self._rows.append(r)
            elif prefix and not cabys and r.get("cabys_prefix") == prefix and not r.get("cabys_code"):
                self._rows.append(r)

    def fetchone(self):
        return DictRow(self._rows[0]) if self._rows else None

    def fetchall(self):
        return [DictRow(r) for r in self._rows]

class DictRow:
    def __init__(self, d): self._d = d
    def __getattr__(self, k): return self._d.get(k)
    def _mapping(self): return self._d

print("=" * 60)
print("SIM-F2 — Motor CABYS Engine")
print("=" * 60)

# ─── SIM-F2-01: Regla exacta del tenant ───────────────────────────
print("\nSIM-F2-01: Regla exacta (confidence = 1.0)")
db = MockDB(rules=[{
    "cabys_code": "4151903010",
    "cabys_prefix": None,
    "account_code": "1201",
    "asset_flag": True,
    "min_amount": 50000,
    "fuente": "MANUAL",
}])
res = resolver_cabys(db, "t1", "4151903010", "Computadora Intel", 850000, "t1_token")
check("account_code = 1201", res["account_code"] == "1201")
check("confidence = 1.0", res["confidence"] == 1.0)
check("fuente = EXACTA", res["fuente"] == "EXACTA")
check("asset_flag True + monto > min_amount → needs_review", res["asset_flag"] == True)

# ─── SIM-F2-02: Sin regla → fallback a 5299 (Otros Gastos Operativos) ───────────
print("\nSIM-F2-02: Sin regla conocida → fallback 5299 (cuenta real del catálogo)")
db_empty = MockDB(rules=[])
res2 = resolver_cabys(db_empty, "t1", "9999999999", "Artículo raro", 1000, "t1_token")
check("account_code = 5299", res2["account_code"] == "5299")
check("confidence = 0.3", res2["confidence"] == 0.3)
check("fuente = FALLBACK", res2["fuente"] == "FALLBACK")
check("asset_flag False en fallback", res2["asset_flag"] == False)

# ─── SIM-F2-03: tarifa 08 → GRAVADO 13% ───────────────────────────
print("\nSIM-F2-03: Herencia IVA tarifa 08 → GRAVADO")
iva = iva_tipo_desde_tarifa("08")
check("iva_tipo = GRAVADO", iva["tipo"] == "GRAVADO")
check("tarifa = 13.0", iva["tarifa"] == 13.0)
check("acreditable = True", iva["acreditable"] == True)

# ─── SIM-F2-04: tarifa 01 → EXENTO ────────────────────────────────
print("\nSIM-F2-04: tarifa 01 → EXENTO")
iva4 = iva_tipo_desde_tarifa("01")
check("iva_tipo = EXENTO", iva4["tipo"] == "EXENTO")
check("tarifa = 0.0", iva4["tarifa"] == 0.0)
check("acreditable = False", iva4["acreditable"] == False)

# ─── SIM-F2-05: tarifa 05 → REDUCIDO 8% ──────────────────────────
print("\nSIM-F2-05: tarifa 05 → REDUCIDO_8")
iva5 = iva_tipo_desde_tarifa("05")
check("iva_tipo = REDUCIDO", "REDUCIDO" in iva5["tipo"])
check("tarifa = 8.0", iva5["tarifa"] == 8.0)

# ─── SIM-F2-06: asset_flag pero monto < umbral → no molesta ───────
print("\nSIM-F2-06: Asset flag pero monto < umbral mínimo")
db_asset = MockDB(rules=[{
    "cabys_code": "4151903010",
    "cabys_prefix": None,
    "account_code": "5101",  # gasto por defecto si < umbral
    "asset_flag": True,
    "min_amount": 50000,
    "fuente": "MANUAL",
}])
res6 = resolver_cabys(db_asset, "t1", "4151903010", "USB pequeño", 1500, "t1_token")
check("asset_flag False si monto < min_amount", res6["asset_flag"] == False)

# ─── SIM-F2-07: Regla por prefijo ─────────────────────────────────
print("\nSIM-F2-07: Regla por prefijo '41' (electrónica)")
db_pref = MockDB(rules=[{
    "cabys_code": None,
    "cabys_prefix": "41",
    "account_code": "5301",
    "asset_flag": False,
    "min_amount": None,
    "fuente": "MANUAL",
}])
res7 = resolver_cabys(db_pref, "t1", "4199000000", "Accesorio electrónico", 5000, "t1_token")
check("account_code = 5301 por prefijo", res7["account_code"] == "5301")
check("confidence = 0.8", res7["confidence"] == 0.8)
check("fuente = PREFIJO", res7["fuente"] == "PREFIJO")

print("\n" + "=" * 60)
if FAIL == 0:
    print(f"ALL {PASS} SIM-F2 TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 60)
