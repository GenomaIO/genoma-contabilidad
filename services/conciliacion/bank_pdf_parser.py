"""
bank_pdf_parser.py — Parser de estados de cuenta bancarios CR

Soporta BAC, BCR, BN (Fase 1).
Framework extensible para las demás 35 entidades SUGEF.

Output estándar por transacción:
{
    "fecha": "2026-01-15",
    "descripcion": "SINPE MOVIL 8999-8877 PAGO FACTURA",
    "tipo": "CR",          # CR=crédito/ingreso, DB=débito/gasto
    "monto": 150000.0,
    "saldo": 2350000.0,
    "referencia": "REF001",
    "banco": "BAC",
    "telefono": "89998877"  # si se extrae de la descripción
}
"""
from __future__ import annotations
import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Regex para extraer teléfonos CR (7-8 dígitos, prefijo 2,4,6,7,8) ────────
_PHONE_RE = re.compile(r'\b([2-9]\d{3}[-\s]?\d{4})\b')

# ── Mapeo de nombres de banco → clave interna ────────────────────────────────
BANCO_KEYS = {
    # Estatales
    "Banco de Costa Rica": "BCR",
    "BCR": "BCR",
    "Banco Nacional": "BN",
    "BN": "BN",
    "Banco Popular": "BPDC",
    "BPDC": "BPDC",
    "BANHVI": "BANHVI",
    # Privados
    "BAC": "BAC",
    "BAC San José": "BAC",
    "Davivienda": "DAVIVIENDA",
    "Scotiabank": "SCOTIABANK",
    "BCT": "BCT",
    "Cathay": "CATHAY",
    "CMB": "CMB",
    "Banco General": "GENERAL",
    "Improsa": "IMPROSA",
    "Lafise": "LAFISE",
    "Promerica": "PROMERICA",
    "Prival": "PRIVAL",
    # Cooperativas (más comunes)
    "Coocique": "COOCIQUE",
    "Coopealianza": "COOPEALIANZA",
    "Coopenae": "COOPENAE",
    "Coopemep": "COOPEMEP",
    "Coopecaja": "COOPECAJA",
    "Coopeande": "COOPEANDE",
    "Coopenacional": "COOPENACIONAL",
}


def extraer_telefono(descripcion: str) -> Optional[str]:
    """Extrae número de teléfono CR de la descripción del movimiento."""
    if not descripcion:
        return None
    match = _PHONE_RE.search(descripcion)
    if match:
        return re.sub(r'[-\s]', '', match.group(1))
    return None


def _parse_monto_cr(s: str) -> float:
    """Convierte '1.234.567,89' o '1,234,567.89' a float."""
    s = s.strip().replace(' ', '')
    # Formato CR: puntos como miles, coma como decimal
    if re.match(r'^\d{1,3}(\.\d{3})*(,\d+)?$', s):
        s = s.replace('.', '').replace(',', '.')
    else:
        # Formato anglosajón
        s = s.replace(',', '')
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_fecha_cr(s: str) -> Optional[str]:
    """Intenta parsear fechas en múltiples formatos CR."""
    s = s.strip()
    formatos = ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"]
    for fmt in formatos:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Parsers específicos por banco ────────────────────────────────────────────

def _parse_bac(text: str) -> list[dict]:
    """
    Parser para estados de cuenta BAC San José.
    BAC usa tablas con columnas: Fecha | Descripción | Débito | Crédito | Saldo
    Algunas versiones incluyen columna Referencia.
    """
    transactions = []
    lines = text.split('\n')

    # Patrón línea BAC: fecha dd/mm/yyyy al inicio
    DATE_PAT = re.compile(r'^(\d{2}/\d{2}/\d{4})\s+(.+?)(?:\s+([\d.,]+))?\s+([\d.,]+)\s+([\d.,]+)\s*$')
    # Patrón simplificado cuando hay separación por espacios múltiples
    DATE_SIMPLE = re.compile(r'(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s*$')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = DATE_PAT.match(line) or DATE_SIMPLE.match(line)
        if not m:
            continue

        try:
            groups = m.groups()
            fecha_str = groups[0]
            fecha = _parse_fecha_cr(fecha_str)
            if not fecha:
                continue

            descripcion = groups[1].strip() if groups[1] else ""
            # Determinar débito/crédito según el número de columnas numéricas
            if len(groups) >= 5 and groups[2]:
                # Tiene débito, crédito y saldo
                debito  = _parse_monto_cr(groups[2]) if groups[2] else 0.0
                credito = _parse_monto_cr(groups[3]) if groups[3] else 0.0
                saldo   = _parse_monto_cr(groups[4]) if groups[4] else 0.0
            else:
                # Solo 2 columnas numéricas al final
                debito, credito = 0.0, 0.0
                monto_raw = groups[-2] if len(groups) >= 2 else "0"
                saldo_raw = groups[-1] if groups[-1] else "0"
                monto = _parse_monto_cr(monto_raw)
                saldo = _parse_monto_cr(saldo_raw)
                # Si la descripción tiene CR o DB como indicador
                if "CR" in descripcion.upper() or "CREDITO" in descripcion.upper():
                    credito = monto
                else:
                    debito = monto

            tipo  = "CR" if credito > 0 else "DB"
            monto = credito if credito > 0 else debito

            transactions.append({
                "fecha": fecha,
                "descripcion": descripcion,
                "tipo": tipo,
                "monto": monto,
                "saldo": saldo,
                "referencia": "",
                "banco": "BAC",
                "telefono": extraer_telefono(descripcion),
            })
        except Exception as exc:
            logger.debug(f"BAC parse skip: {exc} / line={line[:80]}")
            continue

    return transactions


def _parse_bcr(text: str) -> list[dict]:
    """
    Parser para estados de cuenta BCR.
    BCR usa formato: Fecha | Número movimiento | Concepto | Débito | Crédito | Saldo
    """
    transactions = []
    lines = text.split('\n')
    DATE_PAT = re.compile(r'(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})\s+(\S+)\s+(.+?)\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)\s*$')

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = DATE_PAT.match(line)
        if not m:
            continue
        try:
            fecha = _parse_fecha_cr(m.group(1))
            if not fecha:
                continue
            referencia  = m.group(2)
            descripcion = m.group(3).strip()
            debito  = _parse_monto_cr(m.group(4))
            credito = _parse_monto_cr(m.group(5))
            saldo   = _parse_monto_cr(m.group(6))
            tipo  = "CR" if credito > 0 else "DB"
            monto = credito if credito > 0 else debito
            transactions.append({
                "fecha": fecha,
                "descripcion": descripcion,
                "tipo": tipo,
                "monto": monto,
                "saldo": saldo,
                "referencia": referencia,
                "banco": "BCR",
                "telefono": extraer_telefono(descripcion),
            })
        except Exception as exc:
            logger.debug(f"BCR parse skip: {exc}")
    return transactions


def _parse_bn(text: str) -> list[dict]:
    """
    Parser para estados de cuenta Banco Nacional.
    BN usa: Fecha | Descripción | Crédito | Débito | Saldo disponible
    """
    transactions = []
    lines = text.split('\n')
    DATE_PAT = re.compile(r'(\d{2}/\d{2}/\d{4})\s+(.+?)\s+([\d.,]*)\s+([\d.,]*)\s+([\d.,]+)\s*$')

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = DATE_PAT.match(line)
        if not m:
            continue
        try:
            fecha = _parse_fecha_cr(m.group(1))
            if not fecha:
                continue
            descripcion = m.group(2).strip()
            credito = _parse_monto_cr(m.group(3)) if m.group(3) else 0.0
            debito  = _parse_monto_cr(m.group(4)) if m.group(4) else 0.0
            saldo   = _parse_monto_cr(m.group(5))
            tipo  = "CR" if credito > 0 else "DB"
            monto = credito if credito > 0 else debito
            transactions.append({
                "fecha": fecha,
                "descripcion": descripcion,
                "tipo": tipo,
                "monto": monto,
                "saldo": saldo,
                "referencia": "",
                "banco": "BN",
                "telefono": extraer_telefono(descripcion),
            })
        except Exception as exc:
            logger.debug(f"BN parse skip: {exc}")
    return transactions


def _parse_generico(text: str, banco_key: str) -> list[dict]:
    """
    Parser genérico para bancos sin parser específico.
    Busca patrones de fecha + montos en líneas de texto.
    """
    transactions = []
    lines = text.split('\n')
    DATE_PAT = re.compile(r'(\d{2}[/-]\d{2}[/-]\d{2,4})\s+(.+?)\s+([\d.,]+)\s*$')

    for line in lines:
        line = line.strip()
        if not line or len(line) < 15:
            continue
        m = DATE_PAT.match(line)
        if not m:
            continue
        try:
            fecha = _parse_fecha_cr(m.group(1))
            if not fecha:
                continue
            descripcion = m.group(2).strip()
            monto = _parse_monto_cr(m.group(3))
            tipo = "CR" if any(k in descripcion.upper() for k in ["CR", "CREDITO", "DEPOSITO", "SINPE"]) else "DB"
            transactions.append({
                "fecha": fecha,
                "descripcion": descripcion,
                "tipo": tipo,
                "monto": monto,
                "saldo": 0.0,
                "referencia": "",
                "banco": banco_key,
                "telefono": extraer_telefono(descripcion),
            })
        except Exception as exc:
            logger.debug(f"Generico parse skip ({banco_key}): {exc}")
    return transactions


# ── Interfaz pública ─────────────────────────────────────────────────────────

def parse_pdf_text(text: str, banco: str) -> list[dict]:
    """
    Parsea el texto extraído de un PDF de estado de cuenta.
    
    Args:
        text:  Texto completo del PDF (ya extraído por pdfplumber o similar)
        banco: Clave del banco (ej: "BAC", "BCR", "BN", "COOCIQUE")
    
    Returns:
        Lista de transacciones en formato estándar.
    """
    banco = banco.upper()
    logger.info(f"🏦 Parseando {len(text)} chars de {banco}")

    parsers = {
        "BAC": _parse_bac,
        "BCR": _parse_bcr,
        "BN":  _parse_bn,
    }

    fn = parsers.get(banco, lambda t: _parse_generico(t, banco))
    transactions = fn(text)

    # Post-procesamiento: limpiar montos negativos, normalizar
    result = []
    for txn in transactions:
        if txn["monto"] <= 0:
            continue  # Ignorar líneas de encabezado/subtotal
        result.append(txn)

    logger.info(f"  → {len(result)} transacciones extraídas de {banco}")
    return result


def extract_saldos(text: str) -> dict:
    """
    Extrae el saldo inicial y final del texto del estado de cuenta.
    Busca patrones comunes como 'Saldo anterior', 'Saldo final'.
    """
    saldo_inicial = 0.0
    saldo_final   = 0.0

    pat_inicial = re.compile(
        r'(?:saldo\s+anterior|saldo\s+inicial|balance\s+anterior)[:\s]+([\d.,]+)',
        re.IGNORECASE
    )
    pat_final = re.compile(
        r'(?:saldo\s+final|saldo\s+actual|balance\s+final|saldo\s+al\s+\d)[:\s]+([\d.,]+)',
        re.IGNORECASE
    )

    m = pat_inicial.search(text)
    if m:
        saldo_inicial = _parse_monto_cr(m.group(1))

    m = pat_final.search(text)
    if m:
        saldo_final = _parse_monto_cr(m.group(1))

    return {"saldo_inicial": saldo_inicial, "saldo_final": saldo_final}


def entidades_disponibles() -> list[dict]:
    """Retorna la lista de las 35 entidades SUGEF soportadas."""
    return [
        # Estatales
        {"clave": "BCR",          "nombre": "Banco de Costa Rica",              "tipo": "Estatal"},
        {"clave": "BN",           "nombre": "Banco Nacional de Costa Rica",     "tipo": "Estatal"},
        {"clave": "BPDC",         "nombre": "Banco Popular y Des. Comunal",     "tipo": "Estatal"},
        {"clave": "BANHVI",       "nombre": "Banco Hipotecario de la Vivienda", "tipo": "Estatal"},
        # Privados
        {"clave": "BAC",          "nombre": "Banco BAC San José",               "tipo": "Privado"},
        {"clave": "DAVIVIENDA",   "nombre": "Banco Davivienda Costa Rica",      "tipo": "Privado"},
        {"clave": "SCOTIABANK",   "nombre": "Scotiabank de Costa Rica",         "tipo": "Privado"},
        {"clave": "BCT",          "nombre": "Banco BCT",                         "tipo": "Privado"},
        {"clave": "CATHAY",       "nombre": "Banco Cathay de Costa Rica",       "tipo": "Privado"},
        {"clave": "CMB",          "nombre": "Banco CMB (Costa Rica)",           "tipo": "Privado"},
        {"clave": "GENERAL",      "nombre": "Banco General Costa Rica",         "tipo": "Privado"},
        {"clave": "IMPROSA",      "nombre": "Banco Improsa",                    "tipo": "Privado"},
        {"clave": "LAFISE",       "nombre": "Banco Lafise",                     "tipo": "Privado"},
        {"clave": "PROMERICA",    "nombre": "Banco Promerica de Costa Rica",    "tipo": "Privado"},
        {"clave": "PRIVAL",       "nombre": "Prival Bank Costa Rica",           "tipo": "Privado"},
        # Cooperativas
        {"clave": "COOCIQUE",       "nombre": "Coocique R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEALIANZA",   "nombre": "Coopealianza R.L.",   "tipo": "Cooperativa"},
        {"clave": "COOPECAJA",      "nombre": "Coopecaja R.L.",      "tipo": "Cooperativa"},
        {"clave": "COOPENAE",       "nombre": "Coopenae R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEMEP",       "nombre": "Coopemep R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEJUDICIAL",  "nombre": "Coopejudicial R.L.",  "tipo": "Cooperativa"},
        {"clave": "COOPEMEDICOS",   "nombre": "Coopemédicos R.L.",   "tipo": "Cooperativa"},
        {"clave": "COOPEANDE",      "nombre": "Coopeande No.1 R.L.", "tipo": "Cooperativa"},
        {"clave": "COOPEUNA",       "nombre": "Coopeuna R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEGRECIA",    "nombre": "Coopegrecia R.L.",    "tipo": "Cooperativa"},
        {"clave": "COOPESANMARCOS", "nombre": "Coopesanmarcos R.L.", "tipo": "Cooperativa"},
        {"clave": "COOPESANRAMON",  "nombre": "Coopesanramón R.L.",  "tipo": "Cooperativa"},
        {"clave": "COOPECAR",       "nombre": "Coopecar R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEFYL",       "nombre": "Coopefyl R.L.",       "tipo": "Cooperativa"},
        {"clave": "COOPEBANPO",     "nombre": "Coopebanpo R.L.",     "tipo": "Cooperativa"},
        {"clave": "COOPAVEGRA",     "nombre": "Coopavegra R.L.",     "tipo": "Cooperativa"},
        {"clave": "COOPEAYA",       "nombre": "Coopeaya R.L.",       "tipo": "Cooperativa"},
        {"clave": "CREDECOOP",      "nombre": "Credecoop R.L.",      "tipo": "Cooperativa"},
        # Financieras
        {"clave": "CAFSA",          "nombre": "Financiera Cafsa",       "tipo": "Financiera"},
        {"clave": "COMECA",         "nombre": "Financiera Comeca",      "tipo": "Financiera"},
        {"clave": "MONGE",          "nombre": "Financiera Monge",       "tipo": "Financiera"},
        {"clave": "MULTIMONEY",     "nombre": "Financiera Multimoney",  "tipo": "Financiera"},
    ]
