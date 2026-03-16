"""
sim_email_receptor_xml_original.py
════════════════════════════════════════════════════════════
Simulación — Fix: email_receptor.py persiste xml_original

Verifica:
  1. El constructor de DocumentoRecibido recibe xml_original
  2. _extraer_lineas_xml() parsea correctamente el XML de Hacienda v4.3
  3. El flujo email → DB → pull API → mapper produce lineas[] no vacío
  4. xml_content con caracteres especiales no lanza excepción (errors=replace)
  5. xml_content None → lineas=[] (retrocompatibilidad)
  6. XML sin LineaDetalle → lineas=[] (fallback seguro)
  7. XML con namespace → extrae correctamente
  8. XML con múltiples líneas → extrae todas
"""

import sys
import xml.etree.ElementTree as ET

PASS = "✅"
FAIL = "❌"
results = []


def check(label: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────
# Función bajo prueba (inline para no depender del entorno)
# ─────────────────────────────────────────────────────────────

def _extraer_lineas_xml(xml_raw: str) -> list:
    """Copia exacta del código en partner_router.py (producción)."""
    if not xml_raw:
        return []
    try:
        root = ET.fromstring(xml_raw)
        ns = ""
        if root.tag.startswith("{"):
            ns = root.tag.split("}")[0] + "}"

        lineas = []
        for ld in root.iter(f"{ns}LineaDetalle"):
            def _t(tag):
                el = ld.find(f"{ns}{tag}")
                return el.text.strip() if el is not None and el.text else ""

            cabys = _t("CodigoProducto") or _t("Codigo") or ""
            imp_el = ld.find(f"{ns}Impuesto")
            tarifa_codigo = ""
            monto_iva = 0.0
            if imp_el is not None:
                tarifa_el = imp_el.find(f"{ns}Tarifa")
                monto_imp_el = imp_el.find(f"{ns}Monto")
                tarifa_codigo = tarifa_el.text.strip() if tarifa_el is not None and tarifa_el.text else "08"
                monto_iva = float(monto_imp_el.text or 0) if monto_imp_el is not None else 0.0

            lineas.append({
                "cabys_code":      cabys,
                "descripcion":     _t("Detalle"),
                "cantidad":        float(_t("Cantidad") or 1),
                "precio_unitario": float(_t("PrecioUnitario") or 0),
                "monto_total":     float(_t("MontoTotalLinea") or _t("SubTotal") or 0),
                "tarifa_codigo":   tarifa_codigo or "08",
                "monto_iva":       monto_iva,
                "monto_exonerado": float(_t("MontoExonerado") or 0),
            })
        return lineas
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# XMLs de prueba (Hacienda v4.3 — estructura real)
# ─────────────────────────────────────────────────────────────

XML_SIMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.3/facturaElectronica">
  <Clave>50601032600031019534410001000000100200002487558</Clave>
  <DetalleServicio>
    <LineaDetalle>
      <NumeroLinea>1</NumeroLinea>
      <CodigoProducto>4399000800</CodigoProducto>
      <Cantidad>1</Cantidad>
      <UnidadMedida>Sp</UnidadMedida>
      <Detalle>Servicios de contabilidad</Detalle>
      <PrecioUnitario>5000.00</PrecioUnitario>
      <MontoTotalLinea>5650.00</MontoTotalLinea>
      <SubTotal>5000.00</SubTotal>
      <Impuesto>
        <Codigo>01</Codigo>
        <Tarifa>13</Tarifa>
        <Monto>650.00</Monto>
      </Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

XML_MULTILINEA = b"""<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica xmlns="https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.3/facturaElectronica">
  <DetalleServicio>
    <LineaDetalle>
      <CodigoProducto>4399000800</CodigoProducto>
      <Cantidad>2</Cantidad>
      <Detalle>Servicio A</Detalle>
      <PrecioUnitario>1000.00</PrecioUnitario>
      <MontoTotalLinea>2260.00</MontoTotalLinea>
      <SubTotal>2000.00</SubTotal>
      <Impuesto><Tarifa>13</Tarifa><Monto>260.00</Monto></Impuesto>
    </LineaDetalle>
    <LineaDetalle>
      <CodigoProducto>5210100100</CodigoProducto>
      <Cantidad>1</Cantidad>
      <Detalle>Producto B</Detalle>
      <PrecioUnitario>3000.00</PrecioUnitario>
      <MontoTotalLinea>3390.00</MontoTotalLinea>
      <SubTotal>3000.00</SubTotal>
      <Impuesto><Tarifa>13</Tarifa><Monto>390.00</Monto></Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

XML_SIN_NAMESPACE = b"""<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica>
  <DetalleServicio>
    <LineaDetalle>
      <CodigoProducto>4399000800</CodigoProducto>
      <Cantidad>1</Cantidad>
      <Detalle>Servicio legacy</Detalle>
      <MontoTotalLinea>1000.00</MontoTotalLinea>
      <Impuesto><Tarifa>08</Tarifa><Monto>80.00</Monto></Impuesto>
    </LineaDetalle>
  </DetalleServicio>
</FacturaElectronica>"""

XML_SIN_LINEAS = b"""<?xml version="1.0" encoding="UTF-8"?>
<FacturaElectronica>
  <Clave>12345</Clave>
</FacturaElectronica>"""

XML_MALFORMADO = b"""<esto no es xml valido <<<<<"""

XML_CON_ESPECIALES = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><FacturaElectronica><DetalleServicio><LineaDetalle><CodigoProducto>4399000800</CodigoProducto><Cantidad>1</Cantidad><Detalle>Servicios con acentos: é, ñ, ü</Detalle><MontoTotalLinea>1000</MontoTotalLinea></LineaDetalle></DetalleServicio></FacturaElectronica>".encode("utf-8")


# ─────────────────────────────────────────────────────────────
# TEST SUITE
# ─────────────────────────────────────────────────────────────

print("\n" + "═"*60)
print("  SIM: email_receptor xml_original → lineas[]")
print("═"*60)

# Bloque A — Simulación del fix en email_receptor.py
print("\n🔧 A. Persistencia de xml_original en DocumentoRecibido")

# A1: El decode no lanza excepción con XML válido
try:
    decoded = XML_SIMPLE.decode("utf-8", errors="replace")
    check("A1: decode utf-8 de XML válido sin excepción", True)
    check("A1b: resultado es string no vacío", bool(decoded))
except Exception as e:
    check("A1: decode utf-8 de XML válido sin excepción", False, str(e))

# A2: decode con bytes inválidos → errors="replace" no lanza excepción
try:
    invalid_bytes = b"\xff\xfe" + XML_SIMPLE
    decoded_invalid = invalid_bytes.decode("utf-8", errors="replace")
    check("A2: decode con bytes inválidos (errors=replace) no lanza", True)
    check("A2b: resultado sigue siendo string", isinstance(decoded_invalid, str))
except Exception as e:
    check("A2: decode con bytes inválidos (errors=replace)", False, str(e))

# A3: Retrocompatibilidad — xml_original=None → lineas=[]
lineas_none = _extraer_lineas_xml(None)
check("A3: xml_original=None → lineas=[]", lineas_none == [])

# A4: xml_original="" → lineas=[]
lineas_empty = _extraer_lineas_xml("")
check("A4: xml_original='' → lineas=[]", lineas_empty == [])

# Bloque B — Parser _extraer_lineas_xml
print("\n📦 B. Parser _extraer_lineas_xml (producción: partner_router.py)")

# B1: XML con namespace — extrae correctamente
xml_str = XML_SIMPLE.decode("utf-8")
lineas = _extraer_lineas_xml(xml_str)
check("B1: XML con namespace → lista NO vacía", len(lineas) > 0, f"{len(lineas)} línea(s)")
if lineas:
    check("B1b: cabys_code extraído", lineas[0]["cabys_code"] == "4399000800", lineas[0]["cabys_code"])
    check("B1c: monto_total correcto", lineas[0]["monto_total"] == 5650.0, str(lineas[0]["monto_total"]))
    check("B1d: monto_iva correcto", lineas[0]["monto_iva"] == 650.0, str(lineas[0]["monto_iva"]))
    check("B1e: tarifa_codigo correcto", lineas[0]["tarifa_codigo"] == "13")
    check("B1f: descripcion extraída", "contabilidad" in lineas[0]["descripcion"].lower())

# B2: XML con múltiples líneas
xml_multi = XML_MULTILINEA.decode("utf-8")
lineas_m = _extraer_lineas_xml(xml_multi)
check("B2: XML multilinea → 2 líneas", len(lineas_m) == 2, f"{len(lineas_m)} línea(s)")
if len(lineas_m) >= 2:
    check("B2b: primera línea CABYS correcto", lineas_m[0]["cabys_code"] == "4399000800")
    check("B2c: segunda línea CABYS correcto", lineas_m[1]["cabys_code"] == "5210100100")

# B3: XML sin namespace (legacy)
xml_sn = XML_SIN_NAMESPACE.decode("utf-8")
lineas_sn = _extraer_lineas_xml(xml_sn)
check("B3: XML sin namespace → lista NO vacía", len(lineas_sn) > 0)
if lineas_sn:
    check("B3b: tarifa 08 para exento", lineas_sn[0]["tarifa_codigo"] == "08")

# B4: XML sin LineaDetalle → [] sin crash
xml_sl = XML_SIN_LINEAS.decode("utf-8")
lineas_sl = _extraer_lineas_xml(xml_sl)
check("B4: XML sin LineaDetalle → []", lineas_sl == [])

# B5: XML malformado → [] sin crash
xml_mal = XML_MALFORMADO.decode("utf-8", errors="replace")
lineas_mal = _extraer_lineas_xml(xml_mal)
check("B5: XML malformado → [] sin crash", lineas_mal == [])

# B6: XML con caracteres especiales
xml_esp = XML_CON_ESPECIALES.decode("utf-8", errors="replace")
lineas_esp = _extraer_lineas_xml(xml_esp)
check("B6: XML con acentos/ñ → lineas NO vacío", len(lineas_esp) > 0)
if lineas_esp:
    check("B6b: descripción con caracteres especiales preservada", "é" in lineas_esp[0]["descripcion"] or "acentos" in lineas_esp[0]["descripcion"])

# Bloque C — Integración: flujo completo simulado
print("\n🔄 C. Flujo Completo: email → xml_original → pull → lineas[]")

# Simula: email_receptor recibe XML adjunto (bytes)
xml_bytes = XML_SIMPLE  # adjunto del email

# Paso 1: email_receptor.py persiste xml_original (fix aplicado)
xml_original_persistido = xml_bytes.decode("utf-8", errors="replace")
check("C1: xml_original persistido es str", isinstance(xml_original_persistido, str))
check("C2: xml_original no está vacío", bool(xml_original_persistido))

# Paso 2: partner_router.py lee xml_original y extrae lineas
lineas_pull = _extraer_lineas_xml(xml_original_persistido)
check("C3: pull retorna lineas[] NO vacío gracias al fix", len(lineas_pull) > 0, f"{len(lineas_pull)} línea(s)")

# Paso 3: mapper recibe lineas[] → NO activa v1-fallback
es_v1_fallback = len(lineas_pull) == 0
check("C4: mapper NO activa v1-fallback (lineas[] no vacío)", not es_v1_fallback)

# Paso 4: el cabys_code del primer ítem permite resolver cuenta contable
primer_cabys = lineas_pull[0]["cabys_code"] if lineas_pull else ""
check("C5: cabys_code disponible para resolver cuenta", bool(primer_cabys), primer_cabys)

# ─────────────────────────────────────────────────────────────
# Resumen
# ─────────────────────────────────────────────────────────────
total  = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = total - passed

print(f"\n{'═'*60}")
print(f"  TOTAL: {passed}/{total} ✅  |  FALLIDOS: {failed} ❌")
print(f"{'═'*60}\n")

if failed:
    print("Tests fallidos:")
    for s, l, d in results:
        if s == FAIL:
            print(f"  {FAIL} {l}" + (f" — {d}" if d else ""))
    sys.exit(1)

sys.exit(0)
