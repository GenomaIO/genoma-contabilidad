"""
bccr_exchange.py — Tipo de Cambio Histórico BCCR

Consulta el API del Banco Central de Costa Rica (BCCR) para obtener el
tipo de cambio USD/CRC de cualquier fecha histórica.

API pública BCCR (sin autenticación):
  https://gee.bccr.fi.cr/Indicadores/Suscripciones/WS/wsindicadoreseconomicos.asmx

Indicadores relevantes:
  317  = Tipo de Cambio Venta USD (moneda que usa el banco al vender dólares)
  318  = Tipo de Cambio Compra USD (moneda que usa el banco al comprar dólares)

Para contabilidad CR:
  - Ingresos en USD  → usar tipo de cambio COMPRA del día (318)
  - Egresos en USD   → usar tipo de cambio VENTA del día (317)
  - Conservador      → usar VENTA siempre (más restrictivo = más prudente)
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Caché en memoria para no repetir llamadas al API ────────────────────────
_CACHE: dict[str, float] = {}

BCCR_URL = (
    "https://gee.bccr.fi.cr/Indicadores/Suscripciones/WS/"
    "wsindicadoreseconomicos.asmx/ObtenerIndicadoresEconomicosXML"
)

INDICADOR_VENTA  = "317"   # TC Venta USD
INDICADOR_COMPRA = "318"   # TC Compra USD

# TC fallback si el API no está disponible
TC_FALLBACK = 515.0  # ~TC USD promedio 2026 (actualizar si es necesario)


def _fecha_bccr(d: date) -> str:
    """Formatea fecha para el API BCCR: 'dd/mm/yyyy'."""
    return d.strftime("%d/%m/%Y")


def consultar_tc_bccr(
    fecha: date,
    indicador: str = INDICADOR_VENTA,
    timeout: int = 5
) -> float:
    """
    Consulta el tipo de cambio del BCCR para una fecha específica.

    Args:
        fecha:      Fecha de la transacción (date)
        indicador:  '317' (venta) o '318' (compra)
        timeout:    Segundos de timeout para la consulta HTTP

    Returns:
        Tipo de cambio como float. Si el API falla, retorna TC_FALLBACK.
    """
    cache_key = f"{indicador}_{fecha.isoformat()}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    fecha_str = _fecha_bccr(fecha)
    params = urllib.parse.urlencode({
        "Indicador":      indicador,
        "FechaInicio":    fecha_str,
        "FechaFinal":     fecha_str,
        "Nombre":         "GENOMA_CONTA",
        "SubNiveles":     "N",
        "CorreoElectronico": "info@genomacrm.com",
        "Token":          "GEN0MACONT4",  # Token público de identificación
    })
    url = f"{BCCR_URL}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            content = resp.read().decode("utf-8")

        # El XML tiene la forma: <NUM_VALOR>515.48</NUM_VALOR>
        import re
        match = re.search(r'<NUM_VALOR>([\d.]+)</NUM_VALOR>', content)
        if match:
            tc = float(match.group(1))
            _CACHE[cache_key] = tc
            logger.debug(f"TC BCCR {indicador} {fecha_str}: ₡{tc}")
            return tc

        # Si el xml viene vacío (feriado o fin de semana), buscar el día anterior
        tc = consultar_tc_bccr(fecha - timedelta(days=1), indicador, timeout)
        _CACHE[cache_key] = tc
        return tc

    except Exception as exc:
        logger.warning(f"BCCR API no disponible ({exc}) → usando fallback ₡{TC_FALLBACK}")
        _CACHE[cache_key] = TC_FALLBACK
        return TC_FALLBACK


def get_tc_para_fecha(fecha_str: str, modo: str = "venta") -> dict:
    """
    Obtiene el tipo de cambio para una fecha dada.

    Args:
        fecha_str:  Fecha en formato 'YYYY-MM-DD'
        modo:       'venta' (egresos) | 'compra' (ingresos) | 'promedio'

    Returns:
        {
            "fecha":    "2026-01-15",
            "tc":       515.48,
            "modo":     "venta",
            "indicador": "317",
            "fuente":   "BCCR" | "FALLBACK",
        }
    """
    try:
        d = datetime.strptime(fecha_str, "%Y-%m-%d").date()
    except ValueError:
        d = date.today()

    if modo == "compra":
        indicador = INDICADOR_COMPRA
    elif modo == "promedio":
        # Promedio de compra y venta
        tc_venta  = consultar_tc_bccr(d, INDICADOR_VENTA)
        tc_compra = consultar_tc_bccr(d, INDICADOR_COMPRA)
        tc = round((tc_venta + tc_compra) / 2, 2)
        return {
            "fecha": fecha_str, "tc": tc, "modo": "promedio",
            "indicador": "317+318",
            "tc_venta":  tc_venta, "tc_compra": tc_compra,
            "fuente": "BCCR" if cache_key_exists(d) else "FALLBACK",
        }
    else:
        indicador = INDICADOR_VENTA

    tc = consultar_tc_bccr(d, indicador)
    cache_key = f"{indicador}_{d.isoformat()}"

    return {
        "fecha":     fecha_str,
        "tc":        tc,
        "modo":      modo,
        "indicador": indicador,
        "fuente":    "BCCR" if cache_key in _CACHE else "FALLBACK",
    }


def cache_key_exists(d: date) -> bool:
    """Verifica si la fecha ya fue consultada (BCCR respondió)."""
    return (
        f"{INDICADOR_VENTA}_{d.isoformat()}" in _CACHE or
        f"{INDICADOR_COMPRA}_{d.isoformat()}" in _CACHE
    )


# ── Detección de moneda en transacciones ────────────────────────────────────

MONEDAS_KEYWORDS = {
    "USD": ["usd", "dolares", "dólares", "us$", "dollar", "$", "usd$"],
    "EUR": ["eur", "euros", "€"],
    "CRC": ["crc", "colones", "₡"],
}


def detectar_moneda(descripcion: str, monto_raw: str = "") -> str:
    """
    Detecta la moneda de una transacción por la descripción o el monto.
    Retorna 'CRC' por defecto (moneda funcional CR).
    """
    text = (descripcion + " " + monto_raw).lower()
    for moneda, keywords in MONEDAS_KEYWORDS.items():
        if any(k in text for k in keywords):
            return moneda
    return "CRC"


def convertir_a_crc(
    monto_usd: float,
    fecha_str: str,
    modo: str = "venta"
) -> dict:
    """
    Convierte un monto en USD a CRC al tipo de cambio histórico del BCCR.

    Args:
        monto_usd:  Monto en USD
        fecha_str:  Fecha de la transacción 'YYYY-MM-DD'
        modo:       'venta' (para egresos) | 'compra' (para ingresos)

    Returns:
        {
            "monto_usd":  500.0,
            "monto_crc":  257740.0,
            "tc":         515.48,
            "fecha":      "2026-01-15",
            "modo":       "venta",
        }
    """
    tc_info = get_tc_para_fecha(fecha_str, modo)
    tc = tc_info["tc"]
    monto_crc = round(monto_usd * tc, 2)

    return {
        "monto_usd": monto_usd,
        "monto_crc": monto_crc,
        "tc":        tc,
        "fecha":     fecha_str,
        "modo":      modo,
        "fuente":    tc_info.get("fuente", "FALLBACK"),
    }


# ── Enriquecedor de transacciones en USD ────────────────────────────────────

def enriquecer_con_tc(txn: dict) -> dict:
    """
    Toma una transacción y, si está en USD, la enriquece con el TC del BCCR.
    
    Regla contable CR:
    - Egresos (DB) en USD → TC de VENTA del día (el banco le cobra más)
    - Ingresos (CR) en USD → TC de COMPRA del día (el banco te paga menos)

    Agrega al dict:
        moneda:         'USD' o 'CRC'
        monto_orig_usd: monto original en USD (si aplica)
        tc_bccr:        tipo de cambio usado
        monto_crc:      monto en CRC (para matching)
        alerta_tc:      si hay diferencia vs monto_crc en libros
    """
    desc       = txn.get("descripcion", "")
    monto_raw  = str(txn.get("monto", ""))
    moneda     = detectar_moneda(desc, monto_raw)
    txn["moneda"] = moneda

    if moneda == "USD":
        monto_usd = float(txn.get("monto", 0))
        fecha_str = str(txn.get("fecha", ""))
        modo = "compra" if txn.get("tipo") == "CR" else "venta"

        conv = convertir_a_crc(monto_usd, fecha_str, modo)
        txn["monto_orig_usd"] = monto_usd
        txn["monto_crc"]      = conv["monto_crc"]
        txn["tc_bccr"]        = conv["tc"]
        txn["tc_fuente"]      = conv["fuente"]
        txn["monto"]          = conv["monto_crc"]  # El matching trabaja en CRC
        logger.debug(
            f"USD→CRC: ${monto_usd} × ₡{conv['tc']} = ₡{conv['monto_crc']} "
            f"({modo}, {fecha_str})"
        )
    else:
        txn["monto_orig_usd"] = None
        txn["monto_crc"]      = float(txn.get("monto", 0))
        txn["tc_bccr"]        = None

    return txn
