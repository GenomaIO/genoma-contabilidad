"""
integration/xml_line_extractor.py
════════════════════════════════════════════════════════════
Extrae líneas CABYS del XML de Hacienda para documentos recibidos.

Flujo:
  1. fetch_hacienda_xml(clave)
       → GET https://api.hacienda.go.cr/fe/ae?clave={clave}
       → retorna el XML firmado del comprobante (o None si falla)

  2. parse_cabys_lines(xml_str)
       → parsea <DetalleServicio><LineaDetalle>
       → extrae cabys_code, descripcion, monto_total, monto_iva, tarifa_codigo
       → retorna lista de dicts compatible con journal_mapper_v2

Reglas de Oro:
  - Nunca lanza excepción hacia el llamador
  - Si falla → retorna [] (graceful degradation: el mapper usa 5999 genérico)
  - Timeout corto (6s) — no bloquea el pull
  - Solo lectura, sin autenticación, sin side effects
"""
import logging
import xml.etree.ElementTree as ET
from typing import Optional

import requests

logger = logging.getLogger(__name__)

HACIENDA_API_URL = "https://api.hacienda.go.cr/fe/ae"
FETCH_TIMEOUT    = 6   # segundos — corto para no bloquear el pull


# ── Namespace de Hacienda v4.3 / v4.4 ──────────────────────────────────────
# Los XML usan namespace sin prefijo. ElementTree los requiere explícitos.
_NS_V43 = "https://tribunet.hacienda.go.cr/docs/esquemas/2017/v4.3/facturaElectronica"
_NS_V44 = "https://cdn.comprobanteselectronicos.go.cr/xml-schemas/v4.4/facturaElectronica"
# Intentamos ambos namespaces al parsear (v4.3 legacy + v4.4 actual)
_NAMESPACES = [
    {"fe": _NS_V44},
    {"fe": _NS_V43},
    {},   # sin namespace (documentos malformados o tiquetes)
]


def fetch_hacienda_xml(clave: str) -> Optional[str]:
    """
    Consulta la API pública de Hacienda y retorna el XML del comprobante.
    Retorna None si falla (timeout, 404, error de red).
    """
    if not clave or len(clave) < 49:
        return None
    try:
        resp = requests.get(
            HACIENDA_API_URL,
            params={"clave": clave},
            timeout=FETCH_TIMEOUT,
            headers={"Accept": "application/xml, text/xml, */*"},
        )
        if resp.status_code == 200:
            # La API puede retornar JSON con campo 'xml' o el XML directamente
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                data = resp.json()
                return data.get("xml") or data.get("comprobante") or None
            return resp.text
        logger.warning(
            f"⚠️ xml_extractor: Hacienda API {resp.status_code} para clave {clave[:20]}..."
        )
        return None
    except requests.Timeout:
        logger.warning(f"⚠️ xml_extractor: timeout para clave {clave[:20]}...")
        return None
    except Exception as ex:
        logger.warning(f"⚠️ xml_extractor: error fetch — {ex}")
        return None


def _extract_ns(root) -> str:
    """Extrae el namespace del tag raíz del XML. Retorna '' si no tiene."""
    tag = root.tag
    if tag.startswith("{"):
        return tag[1: tag.index("}")]
    return ""


def _local(elem) -> str:
    """Retorna el local-name del tag (sin namespace)."""
    t = elem.tag
    return t[t.index("}") + 1:] if "}" in t else t


def _text(elem, local_name: str, ns_uri: str) -> str:
    """Busca un hijo directo por local-name y retorna su texto o ''."""
    if ns_uri:
        child = elem.find(f"{{{ns_uri}}}{local_name}")
    else:
        child = elem.find(local_name)
        if child is None:
            child = next((c for c in elem if _local(c) == local_name), None)
    return (child.text or "").strip() if child is not None else ""


def _find_child(elem, local_name: str, ns_uri: str):
    """Retorna el primer hijo directo con el local-name dado."""
    if ns_uri:
        return elem.find(f"{{{ns_uri}}}{local_name}")
    found = elem.find(local_name)
    if found is None:
        found = next((c for c in elem if _local(c) == local_name), None)
    return found


def _iter_local(root, local_name: str):
    """Itera todos los descendientes con el local-name dado, cualquier namespace."""
    return [e for e in root.iter() if _local(e) == local_name]


def parse_cabys_lines(xml_str: str) -> list:
    """
    Parsea el XML de Hacienda y extrae las líneas CABYS del DetalleServicio.

    Retorna lista de dicts compatible con journal_mapper_v2:
      [{
        "cabys_code":    "4151903010",
        "descripcion":   "Monitor 27 pulgadas",
        "monto_total":   50000.0,    # monto neto (sin IVA)
        "monto_iva":     6500.0,
        "tarifa_codigo": "08",       # '08'=13%, '01'=exento, ...
      }, ...]

    Retorna [] si falla o no hay líneas.
    """
    if not xml_str or not xml_str.strip():
        return []

    try:
        xml_clean = xml_str.strip().lstrip("\ufeff")
        root = ET.fromstring(xml_clean)
    except ET.ParseError as ex:
        logger.warning(f"⚠️ xml_extractor: XML inválido — {ex}")
        return []

    # Detectar namespace del XML raíz (v4.4, v4.3 o sin namespace)
    ns = _extract_ns(root)

    # Buscar todos los LineaDetalle (cualquier namespace)
    lineas_elem = _iter_local(root, "LineaDetalle")
    if not lineas_elem:
        logger.warning("⚠️ xml_extractor: sin LineaDetalle en XML")
        return []

    lines = []
    tarifa_map = {
        "13": "08", "8": "05", "4": "02",
        "2": "07", "1": "06", "0": "01",
    }

    for ld in lineas_elem:
        # CABYS — CodigoProducto (v4.3), CodigoCABYS (ICE/v4.4), Codigo
        cabys = ""
        for tag in ("CodigoProducto", "CodigoCABYS", "Codigo", "CodigoCabys"):
            cabys = _text(ld, tag, ns)
            if cabys:
                break

        descripcion = _text(ld, "Detalle", ns) or _text(ld, "Descripcion", ns) or "Compra"
        monto_total_str = _text(ld, "SubTotal", ns) or _text(ld, "MontoTotalLinea", ns) or "0"
        monto_total = float(monto_total_str)

        tarifa_str = _text(ld, "Tarifa", ns)
        monto_iva  = 0.0

        # IVA dentro de <Impuesto>
        imp = _find_child(ld, "Impuesto", ns) or _find_child(ld, "LineaTotalImpuesto", ns)
        if imp is not None:
            monto_iva_str = _text(imp, "Monto", ns)
            if monto_iva_str:
                try:
                    monto_iva = float(monto_iva_str)
                except ValueError:
                    pass
            if not tarifa_str:
                tarifa_str = _text(imp, "Tarifa", ns)

        tarifa_pct  = str(int(float(tarifa_str))) if tarifa_str else "13"
        tarifa_code = tarifa_map.get(tarifa_pct, "08")

        lines.append({
            "cabys_code":    cabys,
            "descripcion":   descripcion[:120],
            "monto_total":   round(monto_total, 5),
            "monto_iva":     round(monto_iva, 5),
            "tarifa_codigo": tarifa_code,
        })

    logger.info(f"✅ xml_extractor: {len(lines)} líneas CABYS extraídas del XML (ns={ns[:30] if ns else 'none'})")
    return lines



# ── Mapeo OtrosCargos tipo_doc_oc → cuenta contable ───────────────────────
_OTROS_CARGOS_CUENTAS = {
    "01": "5710",  # Intereses moratorios — Gastos Financieros
    "02": "5990",  # Impuesto Cruz Roja  — Contribuciones Obligatorias
    "03": "5480",  # Envío / Flete       — Fletes y Acarreos
    "04": "5420",  # Seguro transporte   — Seguros
    "05": "5710",  # Cargo financiero    — Gastos Financieros
    "99": "5990",  # Otro especificado   — Contribuciones Obligatorias
}


def parse_doc_metadata(xml_str: str) -> dict:
    """
    Extrae metadatos del documento del XML de Hacienda v4.4.

    Regla de Oro #1 — Colonización: total_comprobante_crc ya en CRC.
    Regla de Oro #2 — CR fuente de verdad: total_comprobante_crc.
    Regla de Oro #3 — CondicionVenta determina CxP vs Banco.

    Retorna:
      {
        "moneda":               "CRC",     # CodigoMoneda
        "tipo_cambio":          1.0,       # TipoCambio (1.0 si CRC)
        "total_comprobante":    25290.53,  # en la moneda original del XML
        "total_comprobante_crc": 25290.53, # colonizado a CRC
        "condicion_venta":      "02",      # CondicionVenta
        "medio_pago":           "05",      # TipoMedioPago (referencia)
      }
    """
    result = {
        "moneda": "CRC",
        "tipo_cambio": 1.0,
        "total_comprobante": 0.0,
        "total_comprobante_crc": 0.0,
        "condicion_venta": "02",
        "medio_pago": "01",
    }
    if not xml_str or not xml_str.strip():
        return result
    try:
        root = ET.fromstring(xml_str.strip().lstrip("\ufeff"))
    except ET.ParseError:
        return result

    ns = _extract_ns(root)

    # CondicionVenta
    condicion = _text(root, "CondicionVenta", ns)
    if condicion:
        result["condicion_venta"] = condicion

    # MedioPago
    medio_elem = _find_child(root, "MedioPago", ns)
    if medio_elem is not None:
        medio = _text(medio_elem, "TipoMedioPago", ns)
        if medio:
            result["medio_pago"] = medio

    # Moneda y TipoCambio — dentro de ResumenFactura > CodigoTipoMoneda
    resumen = _find_child(root, "ResumenFactura", ns)
    if resumen is not None:
        cod_mon = _find_child(resumen, "CodigoTipoMoneda", ns)
        if cod_mon is not None:
            moneda = _text(cod_mon, "CodigoMoneda", ns)
            tc_str = _text(cod_mon, "TipoCambio", ns)
            if moneda:
                result["moneda"] = moneda
            if tc_str:
                try:
                    result["tipo_cambio"] = float(tc_str)
                except ValueError:
                    pass

        # TotalComprobante
        tc_total = _text(resumen, "TotalComprobante", ns)
        if tc_total:
            try:
                total = float(tc_total)
                result["total_comprobante"] = total
                # Regla #1: colonizar a CRC
                result["total_comprobante_crc"] = round(
                    total * result["tipo_cambio"], 5
                )
            except ValueError:
                pass

    return result


def parse_otros_cargos(xml_str: str, tipo_cambio: float = 1.0) -> list:
    """
    Extrae <OtrosCargos> del XML de Hacienda v4.4.

    Regla de Oro #1 — Colonización: montos ya multiplicados por tipo_cambio.

    Retorna lista de dicts:
      [{
        "descripcion":    "IMPUESTO CRUZ ROJA",
        "monto_cargo_crc": 127.98,   # en CRC (colonizado)
        "tipo_doc_oc":    "02",
        "cuenta":         "5990",    # cuenta contable pre-asignada
      }]
    Retorna [] si no hay OtrosCargos o falla.
    """
    if not xml_str or not xml_str.strip():
        return []
    try:
        root = ET.fromstring(xml_str.strip().lstrip("\ufeff"))
    except ET.ParseError:
        return []

    ns = _extract_ns(root)
    cargos_elem = _iter_local(root, "OtrosCargos")
    result = []

    for cargo in cargos_elem:
        tipo = _text(cargo, "TipoDocumentoOC", ns) or "99"
        desc = (
            _text(cargo, "Detalle", ns)
            or _text(cargo, "TipoDocumentoOTROS", ns)
            or f"OtroCargo tipo {tipo}"
        )
        monto_str = _text(cargo, "MontoCargo", ns) or "0"
        try:
            monto = float(monto_str)
        except ValueError:
            monto = 0.0

        if monto <= 0:
            continue

        # Regla #1: colonizar
        monto_crc = round(monto * tipo_cambio, 5)
        cuenta = _OTROS_CARGOS_CUENTAS.get(tipo, "5990")

        result.append({
            "descripcion":    desc[:80],
            "monto_cargo_crc": monto_crc,
            "tipo_doc_oc":    tipo,
            "cuenta":         cuenta,
        })

    if result:
        logger.info(f"✅ xml_extractor: {len(result)} OtrosCargos extraídos")
    return result


def fetch_and_enrich(clave: str) -> dict:
    """
    Helper central: fetch XML + parse CABYS lines + parse OtrosCargos + metadata.
    Regla de Oro #1: todo en CRC (colonizado).

    Retorna dict compatible con genoma_client.py:
      {
        "lineas":              [...],     # líneas CABYS en CRC
        "otros_cargos":        [...],     # OtrosCargos en CRC
        "total_comprobante_crc": 25290.53, # CR fuente de verdad (Regla #2)
        "condicion_venta":     "02",      # Banco o CxP (Regla #3)
        "tipo_cambio":         1.0,
        "moneda":              "CRC",
      }
    Si falla → retorna dict vacío (graceful degradation, mapper usa fallback v1).
    """
    _empty = {
        "lineas": [], "otros_cargos": [], "total_comprobante_crc": 0.0,
        "condicion_venta": "02", "tipo_cambio": 1.0, "moneda": "CRC",
    }
    xml = fetch_hacienda_xml(clave)
    if not xml:
        return _empty

    # 1 — Metadata (tipo_cambio, moneda, total, condicion)
    meta = parse_doc_metadata(xml)
    tc   = meta["tipo_cambio"]

    # 2 — Líneas CABYS (ya colonizadas internamente)
    lineas = parse_cabys_lines_colonized(xml, tc)

    # 3 — OtrosCargos (colonizados)
    otros = parse_otros_cargos(xml, tc)

    return {
        "lineas":               lineas,
        "otros_cargos":         otros,
        "total_comprobante_crc": meta["total_comprobante_crc"],
        "condicion_venta":      meta["condicion_venta"],
        "tipo_cambio":          tc,
        "moneda":               meta["moneda"],
    }


def parse_cabys_lines_colonized(xml_str: str, tipo_cambio: float = 1.0) -> list:
    """
    Igual que parse_cabys_lines() pero aplica colonización a los montos.
    Regla de Oro #1: si tipo_cambio != 1.0, multiplica monto_total y monto_iva.
    """
    lineas = parse_cabys_lines(xml_str)
    if tipo_cambio == 1.0:
        return lineas
    # Colonizar
    for l in lineas:
        l["monto_total"] = round(l["monto_total"] * tipo_cambio, 5)
        l["monto_iva"]   = round(l["monto_iva"]   * tipo_cambio, 5)
    return lineas


# ── Alias de compatibilidad (no rompe imports existentes) ───────────────────
def fetch_and_parse_cabys(clave: str) -> list:
    """Alias legacy — usa fetch_and_enrich internamente."""
    return fetch_and_enrich(clave).get("lineas", [])
