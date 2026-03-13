"""
SIM-FER — Documentos Recibidos: Técnica Contable Correcta (E2E)
═══════════════════════════════════════════════════════════════
Verifica que un documento recibido (FEC/compra) siempre genera:
  DR  5xxx  Gasto (o 5999 genérico si sin CABYS)
  DR  1104  IVA Crédito (acreditable)
  CR  2101  CxP Proveedor (total = gasto + IVA)

Y que NUNCA usa:
  4xxx  Ingresos
  1102  CxC
  2102  IVA Débito

Casos probados:
  FER-01: Recibido con tipo_doc="RECIBIDO" y sin lineas[] → v1-fallback correcto
  FER-02: Recibido con tipo_doc="08" y sin lineas[]      → v1-fallback correcto
  FER-03: BUG HISTÓRICO: tipo_doc="01" + _es_recibido=True → debe ser egreso
  FER-04: Recibido con tipo_doc="RECIBIDO" y CON lineas[] → v2 correcto (5xxx/IVA/CxP)
  FER-05: Enviado tipo_doc="01" CON lineas[]             → sigue como ingreso (CxC/4xxx/2102)
  FER-06: Balance cuadrado en todos los casos
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.journal_mapper_v2 import _build_entry_lines_from_doc

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

def balanced(lines):
    dr = round(sum(l["debit"]  for l in lines), 2)
    cr = round(sum(l["credit"] for l in lines), 2)
    return abs(dr - cr) < 0.02

def uses_ingreso(lines):
    """Retorna True si alguna línea usa cuenta 4xxx (ingreso) — MALO para recibidos."""
    return any(str(l["account_code"]).startswith("4") for l in lines)

def uses_cxc(lines):
    """Retorna True si alguna línea usa 1102 CxC — MALO para recibidos."""
    return any(str(l["account_code"]) == "1102" for l in lines)

def uses_iva_debito(lines):
    """Retorna True si alguna línea usa 2102 IVA Débito — MALO para recibidos."""
    return any(str(l["account_code"]) == "2102" for l in lines)

def uses_cxp(lines):
    """Retorna True si alguna línea usa 2101 CxP — BUENO para recibidos."""
    return any(str(l["account_code"]) == "2101" for l in lines)

def uses_iva_credito(lines):
    """Retorna True si alguna línea usa 1104 IVA Crédito — BUENO para recibidos."""
    return any(str(l["account_code"]) in ("1104", "1115") for l in lines)

def uses_gasto(lines):
    """Retorna True si alguna línea usa cuenta 5xxx — BUENO para recibidos."""
    return any(str(l["account_code"]).startswith("5") for l in lines)

print("=" * 65)
print("SIM-FER — Documentos Recibidos: Técnica Contable Correcta")
print("=" * 65)

# ─── FER-01: RECIBIDO sin lineas[] → v1-fallback, tipo 'RECIBIDO' ───
print("\nFER-01: tipo_doc='RECIBIDO' sin lineas[] → EGRESO correcto")
doc_recibido_v1 = {
    "clave":          "R" * 50,
    "tipo_doc":       "RECIBIDO",
    "numero_doc":     "00100010010000000099",
    "fecha":          "2026-03-01",
    "emisor_nombre":  "Proveedor Eléctrico S.A.",
    "total_venta":    50000.0,
    "total_iva":      6500.0,
    "total_doc":      56500.0,
    "moneda":         "CRC",
    # SIN lineas[]
}
lines_fer01 = _build_entry_lines_from_doc(doc_recibido_v1, "tenant1", "entry-fer01", {})
check("FER-01: Genera líneas",          len(lines_fer01) >= 2)
check("FER-01: Balanceado",             balanced(lines_fer01))
check("FER-01: NO usa cuenta 4xxx",     not uses_ingreso(lines_fer01))
check("FER-01: NO usa CxC (1102)",      not uses_cxc(lines_fer01))
check("FER-01: NO usa IVA Débito 2102", not uses_iva_debito(lines_fer01))
check("FER-01: USA CxP (2101)",         uses_cxp(lines_fer01))
check("FER-01: USA Gasto (5xxx)",       uses_gasto(lines_fer01))

# ─── FER-02: tipo_doc='08' sin lineas[] → v1-fallback FEC ──────────
print("\nFER-02: tipo_doc='08' sin lineas[] → EGRESO correcto")
doc_fec_v1 = {
    "clave":          "E" * 50,
    "tipo_doc":       "08",
    "numero_doc":     "00100010010000000100",
    "fecha":          "2026-03-02",
    "emisor_nombre":  "Librería del Sur S.A.",
    "total_venta":    10000.0,
    "total_iva":      1300.0,
    "total_doc":      11300.0,
    "moneda":         "CRC",
}
lines_fer02 = _build_entry_lines_from_doc(doc_fec_v1, "tenant1", "entry-fer02", {})
check("FER-02: Genera líneas",          len(lines_fer02) >= 2)
check("FER-02: Balanceado",             balanced(lines_fer02))
check("FER-02: NO usa cuenta 4xxx",     not uses_ingreso(lines_fer02))
check("FER-02: NO usa CxC (1102)",      not uses_cxc(lines_fer02))
check("FER-02: USA CxP (2101)",         uses_cxp(lines_fer02))
check("FER-02: USA Gasto (5xxx)",       uses_gasto(lines_fer02))
check("FER-02: USA IVA Crédito",        uses_iva_credito(lines_fer02))

# ─── FER-03: BUG HISTÓRICO — tipo_doc='01' + _es_recibido=True ──────
print("\nFER-03: BUG HISTÓRICO — tipo_doc='01' pero _es_recibido=True → EGRESO correcto")
doc_bug = {
    "clave":          "B" * 50,
    "tipo_doc":       "01",      # <-- BUG: el Facturador retorna el tipo real del doc
    "_es_recibido":   True,      # <-- FIX: router_pull.py normaliza con este flag
    "numero_doc":     "00100010010000000101",
    "fecha":          "2026-03-01",
    "emisor_nombre":  "CINTHIA CASTRO RODRIGUEZ",
    "total_venta":    16800.0,
    "total_iva":      1932.74,
    "total_doc":      18732.74,
    "moneda":         "CRC",
}
lines_fer03 = _build_entry_lines_from_doc(doc_bug, "tenant1", "entry-fer03", {})
check("FER-03: Genera líneas",          len(lines_fer03) >= 2)
check("FER-03: Balanceado",             balanced(lines_fer03))
check("FER-03: NO usa cuenta 4xxx",     not uses_ingreso(lines_fer03))
check("FER-03: NO usa CxC (1102)",      not uses_cxc(lines_fer03))
check("FER-03: USA CxP (2101)",         uses_cxp(lines_fer03))
check("FER-03: USA Gasto (5xxx)",       uses_gasto(lines_fer03))

# ─── FER-04: Recibido CON lineas[] → v2 completo ──────────────────
print("\nFER-04: RECIBIDO con lineas[] → v2 mapeo por CABYS (egreso correcto)")
doc_recibido_v2 = {
    "clave":         "V2" + "X" * 48,
    "tipo_doc":      "08",
    "numero_doc":    "00100010010000000200",
    "fecha":         "2026-03-03",
    "emisor_nombre": "Suministros Tech S.A.",
    "total_doc":     56500.0,
    "moneda":        "CRC",
    "lineas": [
        {"cabys_code": "4151903010", "descripcion": "Monitor 27 pulgadas",
         "monto_total": 50000.0, "tarifa_codigo": "08", "monto_iva": 6500.0},
    ]
}
lines_fer04 = _build_entry_lines_from_doc(doc_recibido_v2, "tenant1", "entry-fer04", {})
check("FER-04: Genera líneas",          len(lines_fer04) >= 2)
check("FER-04: Balanceado",             balanced(lines_fer04))
check("FER-04: NO usa cuenta 4xxx",     not uses_ingreso(lines_fer04))
check("FER-04: NO usa CxC (1102)",      not uses_cxc(lines_fer04))
check("FER-04: NO usa IVA Débito",      not uses_iva_debito(lines_fer04))
check("FER-04: USA CxP (2101)",         uses_cxp(lines_fer04))
check("FER-04: USA IVA Crédito",        uses_iva_credito(lines_fer04))

# ─── FER-05: Enviado tipo_doc='01' CON lineas[] → INGRESO (sin cambio) ─
print("\nFER-05: Enviado tipo_doc='01' CON lineas[] → INGRESO correcto (sin regresión)")
doc_enviado = {
    "clave":          "FE01" + "X" * 46,
    "tipo_doc":       "01",
    "numero_doc":     "FE-0001",
    "fecha":          "2026-03-01",
    "emisor_nombre":  "Mi Empresa S.A.",
    "receptor_nombre": "Cliente Final",
    "total_doc":      56500.0,
    "moneda":         "CRC",
    "lineas": [
        {"cabys_code": "9211002000", "descripcion": "Consultoría",
         "monto_total": 50000.0, "tarifa_codigo": "08", "monto_iva": 6500.0},
    ]
}
lines_fer05 = _build_entry_lines_from_doc(doc_enviado, "tenant1", "entry-fer05", {})
check("FER-05: Genera líneas",           len(lines_fer05) >= 3)
check("FER-05: Balanceado",              balanced(lines_fer05))
check("FER-05: USA cuenta 4xxx (ingreso)", uses_ingreso(lines_fer05))
check("FER-05: USA CxC (1102)",          uses_cxc(lines_fer05))
check("FER-05: USA IVA Débito (2102)",   uses_iva_debito(lines_fer05))
check("FER-05: NO usa CxP (2101)",       not uses_cxp(lines_fer05))

print("\n" + "=" * 65)
if FAIL == 0:
    print(f"ALL {PASS} SIM-FER TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 65)
