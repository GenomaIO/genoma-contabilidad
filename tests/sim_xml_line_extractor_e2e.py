"""
SIM-XML — xml_line_extractor: parser de XML Hacienda v4.4
══════════════════════════════════════════════════════════
Prueba la función parse_cabys_lines() con XML sintético (sin llamadas de red).
Cubre: namespace v4.4, namespace v4.3, sin namespace, XML malformado, XML vacío.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.xml_line_extractor import parse_cabys_lines, fetch_and_parse_cabys

PASS = 0; FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond: print(f"  ✅ PASS: {label}"); PASS += 1
    else:    print(f"  ❌ FAIL: {label}"); FAIL += 1

print("=" * 65)
print("SIM-XML — xml_line_extractor CABYS Parser")
print("=" * 65)

# ─── XML de ejemplo con namespace v4.4 ────────────────────────────
XML_V44 = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica">
  <Clave>50614031500310121853200100001010000000007199999999</Clave>
  <DetalleServicio>
    <LineaDetalle>
      <NumeroLinea>1</NumeroLinea>
      <CodigoProducto>4151903010</CodigoProducto>
      <Detalle>Monitor 27 pulgadas LG</Detalle>
      <SubTotal>50000.00</SubTotal>
      <Impuesto>
        <Codigo>01</Codigo>
        <Tarifa>13</Tarifa>
        <Monto>6500.00</Monto>
      </Impuesto>
    </LineaDetalle>
    <LineaDetalle>
      <NumeroLinea>2</NumeroLinea>
      <CodigoProducto>9399001000</CodigoProducto>
      <Detalle>Servicio de consultoría técnica</Detalle>
      <SubTotal>80000.00</SubTotal>
      <Impuesto>
        <Codigo>01</Codigo>
        <Tarifa>13</Tarifa>
        <Monto>10400.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

# ─── XML con namespace v4.3 (legacy) ──────────────────────────────
XML_V43 = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.3/facturaElectronica">
  <DetalleServicio>
    <LineaDetalle>
      <NumeroLinea>1</NumeroLinea>
      <CodigoProducto>8010101000</CodigoProducto>
      <Detalle>Alquiler de oficina</Detalle>
      <SubTotal>200000.00</SubTotal>
      <Impuesto>
        <Tarifa>13</Tarifa>
        <Monto>26000.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

# ─── XML sin namespace ────────────────────────────────────────────
XML_NO_NS = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica>
  <DetalleServicio>
    <LineaDetalle>
      <CodigoProducto>5210201000</CodigoProducto>
      <Detalle>Servicio telefónico ICE</Detalle>
      <SubTotal>25290533.00</SubTotal>
      <Impuesto>
        <Tarifa>13</Tarifa>
        <Monto>2883354.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

# ─── XML malformado ───────────────────────────────────────────────
XML_BAD = "<FacturaElectronica><unclosed>"

# ─── XML vacío ────────────────────────────────────────────────────
XML_EMPTY = ""

# ─── XML línea con tarifa 0 (exento) ─────────────────────────────
XML_EXENTO = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica">
  <DetalleServicio>
    <LineaDetalle>
      <CodigoProducto>1011101000</CodigoProducto>
      <Detalle>Medicamento exento</Detalle>
      <SubTotal>15000.00</SubTotal>
      <Impuesto>
        <Tarifa>0</Tarifa>
        <Monto>0.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

# ══════════════════════════════════════════════════════════════════
print("\nSIM-XML-01: XML v4.4 con 2 líneas CABYS")
lines_v44 = parse_cabys_lines(XML_V44)
check("Retorna 2 líneas",                      len(lines_v44) == 2)
check("L1 CABYS = 4151903010",                lines_v44[0]["cabys_code"] == "4151903010")
check("L1 descripcion contiene 'Monitor'",    "Monitor" in lines_v44[0]["descripcion"])
check("L1 monto_total = 50000",               lines_v44[0]["monto_total"] == 50000.0)
check("L1 monto_iva = 6500",                  lines_v44[0]["monto_iva"] == 6500.0)
check("L1 tarifa_codigo = '08' (13%)",        lines_v44[0]["tarifa_codigo"] == "08")
check("L2 CABYS = 9399001000",                lines_v44[1]["cabys_code"] == "9399001000")
check("L2 monto_total = 80000",               lines_v44[1]["monto_total"] == 80000.0)

print("\nSIM-XML-02: XML v4.3 legacy con 1 línea")
lines_v43 = parse_cabys_lines(XML_V43)
check("Retorna 1 línea",                      len(lines_v43) == 1)
check("CABYS = 8010101000",                   lines_v43[0]["cabys_code"] == "8010101000")
check("monto_iva = 26000",                    lines_v43[0]["monto_iva"] == 26000.0)

print("\nSIM-XML-03: XML sin namespace (tiquetes)")
lines_nons = parse_cabys_lines(XML_NO_NS)
check("Retorna 1 línea",                      len(lines_nons) == 1)
check("CABYS = 5210201000",                   lines_nons[0]["cabys_code"] == "5210201000")
check("ICE: monto_total = 25290533",          lines_nons[0]["monto_total"] == 25290533.0)

print("\nSIM-XML-04: XML malformado → graceful degradation")
lines_bad = parse_cabys_lines(XML_BAD)
check("Retorna [] sin crash",                 lines_bad == [])

print("\nSIM-XML-05: XML vacío → graceful degradation")
lines_empty = parse_cabys_lines(XML_EMPTY)
check("Retorna [] sin crash",                 lines_empty == [])

print("\nSIM-XML-06: Línea exenta (tarifa=0)")
lines_ex = parse_cabys_lines(XML_EXENTO)
check("Retorna 1 línea",                      len(lines_ex) == 1)
check("tarifa_codigo = '01' (exento)",        lines_ex[0]["tarifa_codigo"] == "01")
check("monto_iva = 0",                        lines_ex[0]["monto_iva"] == 0.0)

print("\nSIM-XML-07: fetch_and_parse_cabys con clave corta (inválida)")
lines_short = fetch_and_parse_cabys("CLAVE_CORTA")
check("Clave inválida → [] sin crash",        lines_short == [])

print("\nSIM-XML-08: fetch_and_parse_cabys con clave vacía")
lines_vacia = fetch_and_parse_cabys("")
check("Clave vacía → [] sin crash",           lines_vacia == [])

print("\n" + "=" * 65)
if FAIL == 0:
    print(f"ALL {PASS} SIM-XML TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 65)
