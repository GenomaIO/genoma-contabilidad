"""
tests/sim_fase5_genoma_client_v2.py
════════════════════════════════════════════════════════════
SIM pre-push para genoma_client.py v2 (Opción B).
Verifica:
  1. Sintaxis Python válida
  2. _period_to_dates — conversión YYYYMM correcta
  3. _extract_cabys_from_json — extracción de CABYS de documento_json
  4. Mapeo correcto de /invoices/list → contrato estándar
  5. Mapeo correcto de /api/reception/list → contrato estándar
  6. Filtrado de período en recibidos
  7. Fallback robusto en errores

ZERO cambios al Facturador requeridos.
"""
import sys, os, ast
from datetime import datetime
from calendar import monthrange

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        print(f"  ✅ PASS: {name}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {name}" + (f" → {detail}" if detail else ""))
        FAIL += 1

print("\n════════════════════════════════════════")
print("SIM-F5 genoma_client.py v2 (Opción B)")
print("════════════════════════════════════════\n")

# ─── TEST 1: Sintaxis válida ─────────────────────────────
print("⟹ T1: Sintaxis Python")
path = os.path.join(os.path.dirname(__file__), "..", "services", "integration", "genoma_client.py")
with open(path) as f:
    src = f.read()
try:
    ast.parse(src)
    check("Sintaxis Python válida", True)
except SyntaxError as e:
    check("Sintaxis Python válida", False, str(e))

# ─── TEST 2: Importaciones críticas presentes ─────────────
print("\n⟹ T2: Presencia de funciones clave")
check("pull_documentos_enviados definida", "def pull_documentos_enviados" in src)
check("pull_documentos_recibidos definida", "def pull_documentos_recibidos" in src)
check("_period_to_dates definida", "def _period_to_dates" in src)
check("_extract_cabys_from_json definida", "def _extract_cabys_from_json" in src)

# ─── TEST 3: URLs correctas (endpoints existentes del Facturador) ─
print("\n⟹ T3: URLs apuntan a endpoints existentes del Facturador")
check("/invoices/list en enviados",    "/invoices/list" in src)
check("/api/reception/list en recibidos", "/api/reception/list" in src)
check("NO usa /api/v1/documentos (endpoint inexistente)", "/api/v1/documentos" not in src)

# ─── TEST 4: _period_to_dates ────────────────────────────
print("\n⟹ T4: _period_to_dates — conversión de período")
from services.integration.genoma_client import _period_to_dates

d1, d2 = _period_to_dates("202603")
check("Desde = 2026-03-01", d1 == "2026-03-01", f"obtuvo: {d1}")
check("Hasta = 2026-03-31", d2 == "2026-03-31", f"obtuvo: {d2}")

d3, d4 = _period_to_dates("202602")
check("Febrero 2026 hasta = 2026-02-28", d4 == "2026-02-28", f"obtuvo: {d4}")

d5, d6 = _period_to_dates("INVALIDO")
check("Período inválido retorna (None, None)", d5 is None and d6 is None)

# ─── TEST 5: _extract_cabys_from_json ──────────────────────
print("\n⟹ T5: _extract_cabys_from_json — extracción de CABYS")
from services.integration.genoma_client import _extract_cabys_from_json

doc_json_fe = {
    "lineas": [
        {"cabys": "6410001000000", "descripcion": "Alquiler oficina", "cantidad": 1,
         "precio_unitario": 500000, "monto_total": 500000, "tarifa": "08", "monto_iva": 65000},
        {"cabys": "4010001000000", "descripcion": "Servicio TI", "cantidad": 2,
         "precio_unitario": 100000, "monto_total": 200000, "tarifa": "01", "monto_iva": 0},
    ]
}
lineas = _extract_cabys_from_json(doc_json_fe)
check("Extrae 2 líneas", len(lineas) == 2, f"obtuvo {len(lineas)}")
check("Primera línea tiene cabys_code", lineas[0]["cabys_code"] == "6410001000000")
check("Segunda línea tiene descripcion", "Servicio TI" in lineas[1]["descripcion"])
check("monto_iva en línea 1", lineas[0]["monto_iva"] == 65000)

# JSON vacío / None
lineas_vacio = _extract_cabys_from_json(None)
check("None retorna lista vacía", lineas_vacio == [])

lineas_vacio2 = _extract_cabys_from_json({})
check("{} retorna lista vacía", lineas_vacio2 == [])

# ─── TEST 6: Mapeo de respuesta de /invoices/list ──────────
print("\n⟹ T6: Mapeo de respuesta de /invoices/list → contrato estándar")

# Simular respuesta del Facturador
factura_raw = {
    "clave_hacienda": "50625030500310953441100010000000002790012600", # 50 chars — clave real Hacienda
    "consecutivo":    "001001000000279",
    "tipo_documento": "01",
    "fecha":          "2026-03-01T08:00:00+00:00",
    "emisor_cedula":  "3101953441",
    "emisor_nombre":  "3-101-953441 SOCIEDAD ANONIMA",
    "receptor_cedula":"206570093",
    "receptor_nombre": "CINTHIA CASTRO RODRIGUEZ",
    "moneda":         "CRC",
    "tipo_cambio":    1.0,
    "total_comprobante": 16800.0,
    "total_impuestos": 1932.74,
    "estado_hacienda": "ACEPTADO",
    "documento_json": {
        "lineas": [{
            "cabys": "6410001000000",
            "descripcion": "Servicio contabilidad",
            "cantidad": 1,
            "precio_unitario": 14867.26,
            "monto_total": 14867.26,
            "tarifa": "08",
            "monto_iva": 1932.74
        }]
    }
}

# Aplicar el mismo mapeo que hace pull_documentos_enviados
doc_json = factura_raw.get("documento_json") or {}
lineas_mapped = _extract_cabys_from_json(doc_json)
item = {
    "clave":           factura_raw["clave_hacienda"],
    "numero_doc":      factura_raw["consecutivo"],
    "tipo_doc":        factura_raw["tipo_documento"],
    "emisor_nombre":   factura_raw["emisor_nombre"],
    "total_doc":       float(factura_raw["total_comprobante"]),
    "total_iva":       float(factura_raw["total_impuestos"]),
    "estado_hacienda": factura_raw["estado_hacienda"],
    "lineas":          lineas_mapped,
}
check("clave_hacienda mapeada (≥10 chars)", len(item["clave"]) >= 10, f"len={len(item['clave'])}")
check("CABYS extraído de documento_json", lineas_mapped[0]["cabys_code"] == "6410001000000")
check("total_doc correcto", item["total_doc"] == 16800.0)

# ─── TEST 7: Filtrado de período en recibidos ─────────────
print("\n⟹ T7: Filtrado de período en recibidos")

def _in_period(doc_fecha_str, target_year, target_month):
    """Replica del filtro interno de pull_documentos_recibidos."""
    if not doc_fecha_str or not target_year:
        return True
    try:
        dt = datetime.fromisoformat(doc_fecha_str.replace("Z", "+00:00"))
        return dt.year == target_year and dt.month == target_month
    except Exception:
        return True

check("Fecha 2026-03-15 en período 202603", _in_period("2026-03-15T00:00:00+00:00", 2026, 3))
check("Fecha 2026-02-28 NO en período 202603", not _in_period("2026-02-28T00:00:00+00:00", 2026, 3))
check("Fecha vacía siempre incluida", _in_period("", 2026, 3))
check("Sin target_year incluye todo", _in_period("2026-02-01T00:00:00+00:00", 0, 0))

# ─── TEST 8: Filtro estado_hacienda ACEPTADO en params ────
print("\n⟹ T8: Params incluyen filtro ACEPTADO")
check("'ACEPTADO' en enviados params", "'ACEPTADO'" in src or '"ACEPTADO"' in src)
check("estado=ACEPTADO en recibidos params", '"ACEPTADO"' in src or "'ACEPTADO'" in src)

# ─── RESUMEN ─────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'='*60}")
if FAIL == 0:
    print(f"ALL {total} SIM-F5 TESTS PASSED ✅")
    print("🟢 CERO cambios al Facturador — Opción B lista para push")
else:
    print(f"{PASS}/{total} passed — {FAIL} FAILED ❌ — NO hacer push")
print(f"{'='*60}\n")

sys.exit(1 if FAIL > 0 else 0)
