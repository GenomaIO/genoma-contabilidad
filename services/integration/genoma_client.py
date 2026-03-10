"""
integration/genoma_client.py
════════════════════════════════════════════════════════════
Cliente HTTP para consultar documentos FE/FEC desde Genoma Contable (Facturador).

ESTRATEGIA: Opción B — Reutilizar endpoints EXISTENTES del Facturador.
  Cero cambios al Facturador. Solo lectura de sus APIs ya operativas.

Endpoints del Facturador que reutilizamos:
  GET {host}/invoices/list            → Facturas emitidas (FE/TE/ND/NC)
  GET {host}/api/reception/list       → Documentos recibidos (FEC)

Ambos filtran por:
  - tenant_id (del JWT del token Bearer)
  - estado_hacienda=ACEPTADO / estado=ACEPTADO     ← Solo aceptados por Hacienda

CABYS:
  - Enviados: se extrae de documento_json["lineas"] — almacenado en la tabla facturas
  - Recibidos: condicion_impuesto + iva_acreditado + iva_gasto (suficiente para asiento)

Reglas de Oro:
  - Timeout 10s (Render/PaaS: no bloquear workers)
  - Retry 2x con backoff en caso de 5xx
  - Autenticación por tenant_token (JWT del contador)
  - Nunca lanza excepción — retorna dict con ok=False y error
"""
import logging
import os
import time
from calendar import monthrange
from datetime import date
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# URL base del Facturador (Genoma Contable)
GENOMA_CONTABLE_URL = os.getenv(
    "GENOMA_CONTABLE_URL",
    "https://api.genoma.io"
)
REQUEST_TIMEOUT = 10          # segundos
MAX_RETRIES     = 2


def _get_headers(tenant_token: str) -> dict:
    """Headers de autenticación para la API del Facturador."""
    return {
        "Authorization": f"Bearer {tenant_token}",
        "Content-Type":  "application/json",
        "X-Client":      "genoma-contabilidad/2.0",
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
                return {
                    "ok": False,
                    "error": f"Sin autorización ({resp.status_code}). "
                             "Verifica que el token del contador sea válido en el Facturador."
                }
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(0.5 * (attempt + 1))  # back-off simple
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
    Usado para filtrar por mes en /invoices/list.
    """
    try:
        year  = int(period[:4])
        month = int(period[4:6])
        last_day = monthrange(year, month)[1]
        fecha_desde = f"{year}-{month:02d}-01"
        fecha_hasta = f"{year}-{month:02d}-{last_day:02d}"
        return fecha_desde, fecha_hasta
    except Exception:
        return None, None


def _extract_cabys_from_json(documento_json: dict) -> list:
    """
    Extrae líneas con CABYS del campo documento_json de la tabla facturas.
    El JSON almacena la estructura completa del documento, incluyendo
    las líneas de detalle con CodigoComercial tipo '04' (CABYS).
    """
    if not documento_json:
        return []
    try:
        lineas = documento_json.get("lineas", []) or documento_json.get("detalle", []) or []
        resultado = []
        for linea in lineas:
            cabys = (
                linea.get("cabys") or
                linea.get("cabys_code") or
                linea.get("codigo_cabys") or
                ""
            )
            resultado.append({
                "cabys_code":       cabys,
                "descripcion":      linea.get("descripcion", linea.get("detalle", "")),
                "cantidad":         float(linea.get("cantidad", 1)),
                "precio_unitario":  float(linea.get("precio_unitario", linea.get("montoPrecioUnitario", 0))),
                "monto_total":      float(linea.get("monto_total", linea.get("montoTotal", linea.get("monto", 0)))),
                "tarifa_codigo":    linea.get("tarifa", linea.get("tarifa_codigo", "08")),  # 08=13%
                "monto_iva":        float(linea.get("monto_iva", linea.get("montoImpuesto", 0))),
                "monto_exonerado":  float(linea.get("monto_exonerado", 0)),
            })
        return resultado
    except Exception as e:
        logger.warning(f"_extract_cabys_from_json: error extrayendo líneas: {e}")
        return []


def pull_documentos_enviados(
    tenant_token: str,
    period: str,          # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala documentos FE/TE/ND/NC enviados ACEPTADOS por Hacienda.
    Reutiliza el endpoint existente GET /invoices/list del Facturador.
    Extrae líneas con CABYS desde el campo documento_json.

    Retorna:
      {
        ok: bool,
        items: [{
          clave, numero_doc, tipo_doc, fecha,
          emisor_nombre, receptor_nombre,
          total_venta, total_exento, total_iva, total_doc,
          moneda, estado_hacienda,
          lineas: [{ cabys_code, descripcion, cantidad, precio_unitario,
                     monto_total, tarifa_codigo, monto_iva, monto_exonerado }]
        }],
        total, page, total_pages
      }
    """
    fecha_desde, fecha_hasta = _period_to_dates(period)
    if not fecha_desde:
        return {"ok": False, "items": [], "total": 0, "error": f"Período inválido: {period}"}

    url    = f"{GENOMA_CONTABLE_URL}/invoices/list"
    params = {
        "estado_hacienda": "ACEPTADO",
        "fecha_desde":     fecha_desde,
        "fecha_hasta":     fecha_hasta,
        "limit":           1000 if limit > 100 else limit,  # /invoices/list soporta hasta limit
        "offset":          (page - 1) * limit,
    }

    result = _safe_request("GET", url, _get_headers(tenant_token), params)
    if not result["ok"]:
        logger.warning(f"⚠️ pull_documentos_enviados: {result['error']}")
        return {"ok": False, "items": [], "total": 0, "error": result["error"]}

    data  = result["data"]
    items = data.get("items", [])

    # Mapear al contrato estándar + extraer CABYS de documento_json
    mapped = []
    for f in items:
        doc_json = f.get("documento_json") or {}
        lineas   = _extract_cabys_from_json(doc_json)
        mapped.append({
            "clave":             f.get("clave_hacienda", ""),
            "numero_doc":        f.get("consecutivo", ""),
            "tipo_doc":          f.get("tipo_documento", "01"),
            "fecha":             f.get("fecha", ""),
            "emisor_cedula":     f.get("emisor_cedula", ""),
            "emisor_nombre":     f.get("emisor_nombre", ""),
            "receptor_cedula":   f.get("receptor_cedula", ""),
            "receptor_nombre":   f.get("receptor_nombre", ""),
            "moneda":            f.get("moneda", "CRC"),
            "tipo_cambio":       float(f.get("tipo_cambio", 1)),
            "total_venta":       float(f.get("total_comprobante", 0)),
            "total_iva":         float(f.get("total_impuestos", 0)),
            "total_doc":         float(f.get("total_comprobante", 0)),
            "estado_hacienda":   f.get("estado_hacienda", "ACEPTADO"),
            "lineas":            lineas,
        })

    total       = data.get("total", len(mapped))
    total_pages = max(1, (total + limit - 1) // limit)

    return {
        "ok":         True,
        "items":      mapped,
        "total":      total,
        "page":       page,
        "total_pages": total_pages,
    }


def pull_documentos_recibidos(
    tenant_token: str,
    period: str,          # YYYYMM
    page: int = 1,
    limit: int = 10,
) -> dict:
    """
    Jala documentos FEC recibidos ACEPTADOS por Hacienda.
    Reutiliza el endpoint existente GET /api/reception/list del Facturador.

    Para recibidos, el CABYS por línea no se almacena en la DB del Facturador,
    pero tenemos: condicion_impuesto, iva_acreditado, iva_gasto que son suficientes
    para generar el asiento contable correcto con IVA acreditable/gasto.

    El campo 'concepto' contiene las descripciones de líneas concatenadas (texto).
    """
    fecha_desde, fecha_hasta = _period_to_dates(period)
    target_year  = int(period[:4]) if len(period) >= 6 else 0
    target_month = int(period[4:6]) if len(period) >= 6 else 0

    url    = f"{GENOMA_CONTABLE_URL}/api/reception/list"
    params = {
        "estado":     "ACEPTADO",
        "pagina":     1,
        "por_pagina": 1000,   # traer todos y filtrar por mes en cliente
    }

    result = _safe_request("GET", url, _get_headers(tenant_token), params)
    if not result["ok"]:
        logger.warning(f"⚠️ pull_documentos_recibidos: {result['error']}")
        return {"ok": False, "items": [], "total": 0, "error": result["error"]}

    data  = result["data"]
    items = data.get("items", [])

    # Filtrar por mes (el endpoint no tiene filtro de período propio)
    def _in_period(doc_fecha_str: str) -> bool:
        if not doc_fecha_str or not target_year:
            return True
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(doc_fecha_str.replace("Z", "+00:00"))
            return dt.year == target_year and dt.month == target_month
        except Exception:
            return True  # si no se puede parsear, incluir

    # Mapear al contrato estándar
    mapped = []
    for doc in items:
        fecha = doc.get("fecha", "")
        if not _in_period(fecha):
            continue

        mapped.append({
            "clave":              doc.get("clave", ""),
            "numero_doc":         doc.get("clave", "")[-20:] if doc.get("clave") else "",
            "tipo_doc":           doc.get("tipo", "01"),
            "fecha":              fecha,
            "emisor_cedula":      doc.get("emisor_cedula", ""),
            "emisor_nombre":      doc.get("emisor_nombre", ""),
            "receptor_cedula":    "",
            "receptor_nombre":    "",
            "moneda":             doc.get("moneda", "CRC"),
            "tipo_cambio":        1.0,
            "total_venta":        float(doc.get("total", 0)),
            "total_iva":          float(doc.get("impuesto", 0)),
            "total_doc":          float(doc.get("total", 0)),
            "estado_hacienda":    "ACEPTADO",
            # IVA tratamiento — crítico para el asiento contable
            "condicion_impuesto": doc.get("mr_codigo", "01"),  # 1=Acept, 2=Parcial, 3=Rechazo
            "iva_acreditado":     float(doc.get("iva_acreditado", doc.get("impuesto", 0))),
            "iva_gasto":          float(doc.get("iva_gasto", 0)),
            # Descripción de líneas (texto concatenado del Facturador)
            "concepto":           doc.get("concepto", ""),
            # lineas[] vacío para recibidos (CABYS no almacenado a nivel de línea)
            # Se usa condicion_impuesto + iva_acreditado para el asiento
            "lineas":             [],
        })

    total       = len(mapped)
    page_start  = (page - 1) * limit
    page_items  = mapped[page_start: page_start + limit]
    total_pages = max(1, (total + limit - 1) // limit)

    return {
        "ok":          True,
        "items":       page_items,
        "total":       total,
        "page":        page,
        "total_pages": total_pages,
    }
