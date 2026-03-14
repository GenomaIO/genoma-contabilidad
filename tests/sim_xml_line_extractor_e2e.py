"""
SIM-XML — xml_line_extractor: parser de XML Hacienda v4.4
══════════════════════════════════════════════════════════
Prueba la función parse_cabys_lines() con XML sintético (sin llamadas de red).
Cubre: namespace v4.4, namespace v4.3, sin namespace, XML malformado, XML vacío.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.xml_line_extractor import (
    parse_cabys_lines, fetch_and_parse_cabys,
    parse_otros_cargos, parse_doc_metadata, fetch_and_enrich,
)

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

# ─── XML real de ICE (usa CodigoCABYS con mayúscula A) ───────────
XML_ICE = """<?xml version="1.0" encoding="utf-8" ?>
<FacturaElectronica xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica">
  <DetalleServicio>
    <LineaDetalle>
      <NumeroLinea>1</NumeroLinea>
      <CodigoCABYS>8413100000000</CodigoCABYS>
      <Detalle>COSTO POR DISPONIBILIDAD DE LA RED</Detalle>
      <SubTotal>1280.00000</SubTotal>
      <Impuesto>
        <CodigoTarifaIVA>08</CodigoTarifaIVA>
        <Tarifa>13.0</Tarifa>
        <Monto>166.40000</Monto>
      </Impuesto>
    </LineaDetalle>
    <LineaDetalle>
      <NumeroLinea>2</NumeroLinea>
      <CodigoCABYS>8413300000000</CodigoCABYS>
      <Detalle>INTERNET MOVIL</Detalle>
      <SubTotal>5464.88175</SubTotal>
      <Impuesto>
        <CodigoTarifaIVA>08</CodigoTarifaIVA>
        <Tarifa>13.0</Tarifa>
        <Monto>710.43462</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

print("\nSIM-XML-09: ICE usa CodigoCABYS (mayúscula A)")
lines_ice = parse_cabys_lines(XML_ICE)
check("Retorna 2 líneas",                      len(lines_ice) == 2)
check("L1 CodigoCABYS = 8413100000000",        lines_ice[0]["cabys_code"] == "8413100000000")
check("L1 descripcion = DISPONIBILIDAD RED",   "DISPONIBILIDAD" in lines_ice[0]["descripcion"])
check("L1 monto_iva = 166.4",                  lines_ice[0]["monto_iva"] == 166.4)
check("L2 CodigoCABYS = 8413300000000",        lines_ice[1]["cabys_code"] == "8413300000000")
check("L2 descripcion = INTERNET MOVIL",       "INTERNET" in lines_ice[1]["descripcion"])

# ─── XML ICE con OtrosCargos (Cruz Roja + 911) ───────────────────
XML_ICE_CON_OTROS = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica">
  <CondicionVenta>02</CondicionVenta>
  <DetalleServicio>
    <LineaDetalle>
      <CodigoCABYS>8413100000000</CodigoCABYS>
      <Detalle>DISPONIBILIDAD RED</Detalle>
      <SubTotal>22179.65</SubTotal>
      <Impuesto>
        <Tarifa>13</Tarifa>
        <Monto>2883.35</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
  <OtrosCargos>
    <TipoDocumentoOC>02</TipoDocumentoOC>
    <Detalle>IMPUESTO CRUZ ROJA</Detalle>
    <MontoCargo>127.98</MontoCargo>
  </OtrosCargos>
  <OtrosCargos>
    <TipoDocumentoOC>99</TipoDocumentoOC>
    <Detalle>IMPUESTO 911</Detalle>
    <MontoCargo>99.55</MontoCargo>
  </OtrosCargos>
  <ResumenFactura>
    <TotalComprobante>25290.53</TotalComprobante>
  </ResumenFactura>
</FacturaElectronica>"""

print("\nSIM-XML-10: OtrosCargos → parse_otros_cargos (Regla #1 y #2)")
otros = parse_otros_cargos(XML_ICE_CON_OTROS)
check("Retorna 2 OtrosCargos",                 len(otros) == 2)
check("OC-1 tipo=02 (Cruz Roja)",              otros[0]["tipo_doc_oc"] == "02")
check("OC-1 cuenta=5990",                      otros[0]["cuenta"] == "5990")
check("OC-1 monto_cargo_crc=127.98",           abs(otros[0]["monto_cargo_crc"] - 127.98) < 0.01)
check("OC-1 descripcion contiene CRUZ",        "CRUZ" in otros[0]["descripcion"])
check("OC-2 tipo=99 (otro)",                   otros[1]["tipo_doc_oc"] == "99")
check("OC-2 cuenta=5990",                      otros[1]["cuenta"] == "5990")
check("OC-2 monto_cargo_crc=99.55",            abs(otros[1]["monto_cargo_crc"] - 99.55) < 0.01)

print("\nSIM-XML-11: parse_doc_metadata → TotalComprobante + CondicionVenta (Regla #2 y #3)")
meta = parse_doc_metadata(XML_ICE_CON_OTROS)
check("TotalComprobante extraído",             abs(meta["total_comprobante"] - 25290.53) < 0.01)
check("total_comprobante_crc = total (CRC)",   abs(meta["total_comprobante_crc"] - 25290.53) < 0.01)
check("CondicionVenta = '02'",                 meta["condicion_venta"] == "02")
check("moneda = 'CRC' (default)",              meta["moneda"] == "CRC")
check("tipo_cambio = 1.0 (default)",           meta["tipo_cambio"] == 1.0)

# ─── XML en USD con TipoCambio ────────────────────────────────────
XML_USD = """<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica">
  <CondicionVenta>01</CondicionVenta>
  <DetalleServicio>
    <LineaDetalle>
      <CodigoProducto>4151903010</CodigoProducto>
      <Detalle>Software License USD</Detalle>
      <SubTotal>100.00</SubTotal>
      <Impuesto>
        <Tarifa>13</Tarifa>
        <Monto>13.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
  <ResumenFactura>
    <CodigoTipoMoneda>
      <CodigoMoneda>USD</CodigoMoneda>
      <TipoCambio>512.34</TipoCambio>
    </CodigoTipoMoneda>
    <TotalComprobante>113.00</TotalComprobante>
  </ResumenFactura>
</FacturaElectronica>"""

print("\nSIM-XML-12: Factura USD → colonización con TipoCambio (Regla #1)")
meta_usd = parse_doc_metadata(XML_USD)
check("moneda = 'USD'",                        meta_usd["moneda"] == "USD")
check("tipo_cambio = 512.34",                  abs(meta_usd["tipo_cambio"] - 512.34) < 0.01)
check("total_comprobante = 113.00 USD",        abs(meta_usd["total_comprobante"] - 113.00) < 0.01)
check("total_comprobante_crc colonizado",      abs(meta_usd["total_comprobante_crc"] - 57894.42) < 1.0)
check("CondicionVenta = '01' (contado)",       meta_usd["condicion_venta"] == "01")

from services.integration.xml_line_extractor import parse_cabys_lines_colonized
lines_usd = parse_cabys_lines_colonized(XML_USD, tipo_cambio=512.34)
check("Línea USD colonizada a CRC",            len(lines_usd) == 1)
check("monto_total en CRC ≈ 51234",           abs(lines_usd[0]["monto_total"] - 51234.0) < 1.0)
check("monto_iva en CRC ≈ 6660",              abs(lines_usd[0]["monto_iva"] - 6660.42) < 1.0)

print("\nSIM-XML-13: fetch_and_enrich con clave vacía → dict vacío sin crash (graceful)")
enriched_empty = fetch_and_enrich("")
check("Clave vacía → lineas=[]",               enriched_empty["lineas"] == [])
check("Clave vacía → otros_cargos=[]",         enriched_empty["otros_cargos"] == [])
check("Clave vacía → total_comprobante_crc=0", enriched_empty["total_comprobante_crc"] == 0.0)

print("\n" + "=" * 65)
if FAIL == 0:
    print(f"ALL {PASS} SIM-XML TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 65)
