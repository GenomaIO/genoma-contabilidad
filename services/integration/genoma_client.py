"""
integration/genoma_client.py
════════════════════════════════════════════════════════════
Cliente HTTP para consultar documentos FE/FEC desde Genoma Contable.

Contrato de API:
  GET /api/v1/documentos/enviados?period=YYYYMM&page=1&limit=10
  GET /api/v1/documentos/recibidos?period=YYYYMM&page=1&limit=10

Retorna lista de documentos aceptados por Hacienda con sus líneas CABYS.

Reglas de Oro:
- Timeout 10s (Render/PaaS: no bloquear workers)
- Retry 2x con backoff en caso de 5xx
- Autenticación por tenant_token (JWT del partner)
- Nunca lanza excepción — retorna dict con ok=False y error
"""
import logging
import os
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# URL base de Genoma Contable (configurable por ENV)
GENOMA_CONTABLE_URL = os.getenv(
    "GENOMA_CONTABLE_URL",
    "https://api.genoma.io"
)
REQUEST_TIMEOUT = 10          # segundos
MAX_RETRIES     = 2


def _get_headers(tenant_token: str) -> dict:
    """Headers de autenticación para la API de Genoma Contable."""
    return {
        "Authorization": f"Bearer {tenant_token}",
        "Content-Type":  "application/json",
        "X-Client":      "genoma-contabilidad/1.0",
    }


def _safe_request(method: str, url: str, headers: dict, params: dict) -> dict:
    """
    Ejecuta request con retry y timeout.
    Nunca lanza excepción — retorna {'ok': False, 'error': '...'} si falla.
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
            if resp.status_code in (401, 403):
                return {"ok": False, "error": f"Sin autorización ({resp.status_code})"}
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(0.5 * (attempt + 1))  # back-off simple
                continue
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except requests.Timeout:
            if attempt < MAX_RETRIES:
                continue
            return {"ok": False, "error": "Timeout: Genoma Contable no respondió en 10s"}
        except Exception as ex:
            return {"ok": False, "error": str(ex)}

    return {"ok": False, "error": "Max reintentos agotados"}


def pull_documentos_enviados(
    tenant_token: str,
    period: str,          # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala documentos FE/TE/ND/NC enviados por el tenant desde Genoma Contable.

    Retorna:
      {
        ok: bool,
        items: [{
          clave, numero_doc, tipo_doc, fecha,
          emisor_nombre, receptor_nombre,
          total_venta, total_exento, total_iva, total_doc,
          moneda, estado_hacienda,
          lineas: [{
            cabys_code, descripcion, cantidad, precio_unitario,
            monto_total, tarifa_codigo, monto_iva, monto_exonerado
          }]
        }],
        total: int,
        page: int,
        total_pages: int
      }
    """
    url = f"{GENOMA_CONTABLE_URL}/api/v1/documentos/enviados"
    params = {"period": period, "page": page, "limit": limit, "estado": "ACEPTADO"}
    result = _safe_request("GET", url, _get_headers(tenant_token), params)
    if not result["ok"]:
        logger.warning(f"⚠️ pull_documentos_enviados: {result['error']}")
        return {"ok": False, "items": [], "total": 0, "error": result["error"]}
    return {"ok": True, **result["data"]}


def pull_documentos_recibidos(
    tenant_token: str,
    period: str,          # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala documentos FEC/RECIBIDOS aceptados por Hacienda desde Genoma Contable.
    Incluye las líneas con código CABYS por ítem.

    Retorna misma estructura que pull_documentos_enviados
    (lineas[] con cabys_code por ítem)
    """
    url = f"{GENOMA_CONTABLE_URL}/api/v1/documentos/recibidos"
    params = {"period": period, "page": page, "limit": limit, "estado": "ACEPTADO"}
    result = _safe_request("GET", url, _get_headers(tenant_token), params)
    if not result["ok"]:
        logger.warning(f"⚠️ pull_documentos_recibidos: {result['error']}")
        return {"ok": False, "items": [], "total": 0, "error": result["error"]}
    return {"ok": True, **result["data"]}
