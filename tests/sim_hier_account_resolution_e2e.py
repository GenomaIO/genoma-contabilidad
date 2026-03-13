"""
SIM-HIER — Resolución Jerárquica de Cuentas (catálogos 4d+)
═══════════════════════════════════════════════════════════
Verifica que _resolver_cuenta_jerarquica:
  - HIER-01: Exact match en catálogo simple (4 dígitos)
  - HIER-02: Prefix match con catálogo de 6 dígitos
  - HIER-03: Prefix match con catálogo dotado (1.1.02.01)
  - HIER-04: Prefix match con catálogo con guiones (1102-01)
  - HIER-05: Sin match → fallback al código base con warning
  - HIER-06: Escoge el código de MENOR profundidad cuando hay varios hijos
  - HIER-07: Normalización de código: '1.1.02' matchea prefix '1102'
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.journal_mapper_v2 import (
    _normalizar_codigo,
    _resolver_cuenta_jerarquica,
)

PASS = 0; FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond: print(f"  ✅ PASS: {label}"); PASS += 1
    else:    print(f"  ❌ FAIL: {label}"); FAIL += 1

# ── Mock de DB para SIM ──────────────────────────────────────────────
class MockDB:
    """
    Simula un catálogo de cuentas del tenant en memoria.
    Detecta el tipo de query por los parámetros pasados en lugar del
    string SQL (que puede variar según el estado de SQLAlchemy).
    """
    def __init__(self, cuentas: list[str]):
        self.cuentas = set(cuentas)

    def execute(self, stmt, params):
        # Detectamos por las KEYS del params dict — 100% robusto al estado de SQLAlchemy
        if "code" in params and "prefix" not in params:
            # Exact match
            code = params.get("code", "")
            return MockResult([code] if code in self.cuentas else [])
        elif "prefix" in params:
            # Prefix match normalizado
            prefix = params.get("prefix", "")
            matches = sorted(
                [c for c in self.cuentas
                 if _normalizar_codigo(c).startswith(prefix)],
                key=len
            )
            return MockResult([matches[0]] if matches else [])
        return MockResult([])

class MockResult:
    def __init__(self, items):
        self._items = items
    def fetchone(self):
        return (self._items[0],) if self._items else None

print("=" * 65)
print("SIM-HIER — Resolución Jerárquica de Cuentas (catálogos 4d+)")
print("=" * 65)

# ─── HIER-01: Exact match en catálogo simple ────────────────────────
print("\nHIER-01: Exact match 4d en catálogo simple")
db = MockDB(["1101", "1102", "2101", "2102", "4101", "5101"])
result = _resolver_cuenta_jerarquica(db, "tenant_simple", "1102")
check("Exact match retorna '1102'", result == "1102")

# ─── HIER-02: Prefix match catálogo 6 dígitos ───────────────────────
print("\nHIER-02: Prefix match 6d (1102 → 110201)")
db = MockDB(["110201", "110202", "220101", "510101"])
result = _resolver_cuenta_jerarquica(db, "tenant_6d", "1102")
check("Prefix match retorna '110201' (primer hijo)", result == "110201")

# ─── HIER-03: Catálogo dotado (1.1.02.01) ───────────────────────────
print("\nHIER-03: Catálogo dotado '1.1.02' matchea base '11'")
db = MockDB(["1.1.01", "1.1.02", "2.1.01", "5.1.01"])
result = _resolver_cuenta_jerarquica(db, "tenant_dotado", "11")
check("Dotado: '1.1.01' matchea prefix '11' (normalizado)", result in ("1.1.01", "1.1.02"))

# ─── HIER-04: Catálogo con guiones (1102-01) ────────────────────────
print("\nHIER-04: Catálogo con guiones '1102-01' matchea base '1102'")
db = MockDB(["1102-01", "1102-02", "2101-01"])
result = _resolver_cuenta_jerarquica(db, "tenant_guion", "1102")
check("Guiones: '1102-01' matchea prefix '1102'", result in ("1102-01", "1102-02"))

# ─── HIER-05: Sin match → fallback ──────────────────────────────────
print("\nHIER-05: Sin match en catálogo → fallback al código base")
db = MockDB(["3001", "3002"])
result = _resolver_cuenta_jerarquica(db, "tenant_nada", "1102")
check("Fallback retorna el código base '1102'", result == "1102")

# ─── HIER-06: Escoge código menos profundo ──────────────────────────
print("\nHIER-06: Varios hijos → menor profundidad primero")
db = MockDB(["11020101", "110201", "1102010101"])  # 3 hijos, distintas profundidades
result = _resolver_cuenta_jerarquica(db, "tenant_deep", "1102")
check("Escoge '110201' (más corto)", result == "110201")

# ─── HIER-07: Normalización _normalizar_codigo ──────────────────────
print("\nHIER-07: _normalizar_codigo quita puntos y guiones")
check("'1.1.02' → '1102'", _normalizar_codigo("1.1.02") == "1102")
check("'1102-01' → '110201'", _normalizar_codigo("1102-01") == "110201")
check("'5.1.0 1' → '5101'", _normalizar_codigo("5.1.0 1") == "5101")

print("\n" + "=" * 65)
if FAIL == 0: print(f"ALL {PASS} SIM-HIER TESTS PASSED ✅")
else:         print(f"{PASS} passed, {FAIL} FAILED ❌"); sys.exit(1)
print("=" * 65)
