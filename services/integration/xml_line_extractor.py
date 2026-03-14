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
        # CABYS — CodigoProducto o Codigo
        cabys = ""
        for tag in ("CodigoProducto", "Codigo", "CodigoCabys"):
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



def fetch_and_parse_cabys(clave: str) -> list:
    """
    Helper combinado: fetch + parse en una sola llamada.
    Retorna [] si cualquier paso falla.
    """
    xml = fetch_hacienda_xml(clave)
    if not xml:
        return []
    return parse_cabys_lines(xml)
