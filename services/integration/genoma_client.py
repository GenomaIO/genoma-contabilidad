"""
integration/genoma_client.py  v3
════════════════════════════════════════════════════════════
Cliente HTTP del Contabilidad para jalar documentos del Facturador.

ARQUITECTURA CORRECTA (v3):
  El contador (partner) tiene un facturador_token en su gc_token (del handoff).
  Ese token se usa con X-Partner-Token para llamar al endpoint de partner del
  Facturador, que valida que el tenant_id del cliente pertenece al partner
  antes de retornar sus documentos.

ENDPOINT DEL FACTURADOR QUE SE USA:
  GET {host}/api/partners/portal/cliente/{tenant_id}/documentos
      ?tipo=enviados|recibidos&period=YYYYMM
  Header: X-Partner-Token: {facturador_token}

Esto garantiza:
  ✅ Tenant isolation: el Facturador verifica que el cliente le pertenece al partner
  ✅ Solo documentos ACEPTADOS por Hacienda
  ✅ CABYS extraído de documento_json (enviados)
  ✅ condicion_impuesto + iva_acreditado (recibidos)
  ✅ Cero cambios a reception/router.py o api/invoices_list_router.py del Facturador

Reglas de Oro:
  - Timeout 10s, retry 2x con backoff
  - Nunca lanza excepción — retorna {"ok": False, "error": "..."}
  - 401 del Facturador → token expirado, usuario debe re-ingresar desde Partner Dashboard
  - 403 del Facturador → cliente no pertenece al partner (log de seguridad)
"""
import logging
import os
import time
from calendar import monthrange
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# URL base del Facturador (Genoma Contable)
GENOMA_CONTABLE_URL = os.getenv(
    "GENOMA_CONTABLE_URL",
    os.getenv("FACTURADOR_BASE_URL", "https://app.genomaio.com")
)
REQUEST_TIMEOUT = 10
MAX_RETRIES     = 2


def _get_headers(facturador_token: str) -> dict:
    """
    Header de autenticación para el endpoint de partner del Facturador.
    El Facturador espera X-Partner-Token (no Authorization Bearer).
    """
    return {
        "X-Partner-Token": facturador_token,
        "X-Client":        "genoma-contabilidad/3.0",
    }


def _safe_request(method: str, url: str, headers: dict, params: dict) -> dict:
    """
    Request con retry y timeout. Nunca lanza excepción.
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.request(
                method, url,
                headers=headers,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return {"ok": True, "data": resp.json()}
            if resp.status_code == 401:
                return {
                    "ok": False,
                    "error": "TOKEN_EXPIRADO",
                    "error_detail": (
                        "Tu sesión con el Facturador expiró. "
                        "Volvé al Panel de Partners y hacé clic en 'Sistema de Contabilidad'."
                    )
                }
            if resp.status_code == 403:
                logger.warning(f"[SEGURIDAD] 403 al acceder a datos de cliente. URL={url}")
                return {
                    "ok": False,
                    "error": "SIN_ACCESO",
                    "error_detail": "No tenés acceso a los documentos de este cliente."
                }
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(0.5 * (attempt + 1))
                continue
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except requests.Timeout:
            if attempt < MAX_RETRIES:
                continue
            return {"ok": False, "error": "Timeout: El Facturador no respondió en 10s"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    return {"ok": False, "error": "Max reintentos agotados"}


def _period_to_dates(period: str):
    """
    Convierte YYYYMM en (fecha_desde='YYYY-MM-01', fecha_hasta='YYYY-MM-DD').
    Retorna (None, None) si el formato es inválido.
    """
    try:
        year      = int(period[:4])
        month     = int(period[4:6])
        last_day  = monthrange(year, month)[1]
        fecha_desde = f"{year}-{month:02d}-01"
        fecha_hasta = f"{year}-{month:02d}-{last_day:02d}"
        return fecha_desde, fecha_hasta
    except Exception:
        return None, None


def pull_documentos_enviados(
    facturador_token: str,
    cliente_tenant_id: str,   # tenant_id de Álvaro en el Facturador
    period: str,              # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala FE/TE/ND/NC enviados ACEPTADOS por Hacienda de un cliente del partner.

    El Facturador verifica que cliente_tenant_id pertenece al partner del token.
    Los CABYS vienen en cada línea (extraídos de documento_json por el Facturador).

    Retorna:
      {
        ok: bool,
        items: [{ clave, numero_doc, tipo_doc, fecha,
                  emisor_cedula, receptor_cedula, receptor_nombre,
                  moneda, tipo_cambio,
                  total_venta, total_iva, total_doc, estado_hacienda,
                  lineas: [{ cabys_code, descripcion, cantidad,
                             precio_unitario, monto_total, tarifa_codigo,
                             monto_iva, monto_exonerado }] }],
        total, page, total_pages
      }
    """
    if not facturador_token:
        return {
            "ok": False, "items": [], "total": 0,
            "error": "TOKEN_EXPIRADO",
            "error_detail": "No hay token del Facturador. Volvé al Panel de Partners."
        }

    fecha_desde, fecha_hasta = _period_to_dates(period)
    if not fecha_desde:
        return {"ok": False, "items": [], "total": 0,
                "error": f"Período inválido: {period}"}

    url    = f"{GENOMA_CONTABLE_URL}/api/partners/portal/cliente/{cliente_tenant_id}/documentos"
    params = {"tipo": "enviados", "period": period}

    result = _safe_request("GET", url, _get_headers(facturador_token), params)
    if not result["ok"]:
        return {"ok": False, "items": [], "total": 0,
                "error": result.get("error"), "error_detail": result.get("error_detail")}

    data  = result["data"]
    items = data.get("items", [])

    total       = data.get("total", len(items))
    page_start  = (page - 1) * limit
    page_items  = items[page_start: page_start + limit]
    total_pages = max(1, (total + limit - 1) // limit)

    return {
        "ok":          True,
        "items":       page_items,
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
    }


def pull_documentos_recibidos(
    facturador_token: str,
    cliente_tenant_id: str,   # tenant_id de Álvaro en el Facturador
    period: str,              # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala FEC recibidos ACEPTADOS por Hacienda de un cliente del partner.

    Para recibidos, el Facturador retorna:
      condicion_impuesto + iva_acreditado + iva_gasto (suficiente para asiento contable)

    El campo 'lineas' viene vacío (CABYS por línea no almacenado en documentos_recibidos).
    """
    if not facturador_token:
        return {
            "ok": False, "items": [], "total": 0,
            "error": "TOKEN_EXPIRADO",
            "error_detail": "No hay token del Facturador. Volvé al Panel de Partners."
        }

    fecha_desde, fecha_hasta = _period_to_dates(period)
    if not fecha_desde:
        return {"ok": False, "items": [], "total": 0,
                "error": f"Período inválido: {period}"}

    url    = f"{GENOMA_CONTABLE_URL}/api/partners/portal/cliente/{cliente_tenant_id}/documentos"
    params = {"tipo": "recibidos", "period": period}

    result = _safe_request("GET", url, _get_headers(facturador_token), params)
    if not result["ok"]:
        return {"ok": False, "items": [], "total": 0,
                "error": result.get("error"), "error_detail": result.get("error_detail")}

    data  = result["data"]
    items = data.get("items", [])

    total       = data.get("total", len(items))
    page_start  = (page - 1) * limit
    page_items  = items[page_start: page_start + limit]
    total_pages = max(1, (total + limit - 1) // limit)

    return {
        "ok":          True,
        "items":       page_items,
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
    }
