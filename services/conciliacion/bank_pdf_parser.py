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
from datetime import datetime, date
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


# ── Meses en español (nombres completos y abreviaturas) ─────────────────────
_MESES_ES = {
    'enero': 1,       'ene': 1,
    'febrero': 2,     'feb': 2,
    'marzo': 3,       'mar': 3,
    'abril': 4,       'abr': 4,
    'mayo': 5,        'may': 5,
    'junio': 6,       'jun': 6,
    'julio': 7,       'jul': 7,
    'agosto': 8,      'ago': 8,
    'septiembre': 9,  'sep': 9,  'set': 9,
    'octubre': 10,    'oct': 10,
    'noviembre': 11,  'nov': 11,
    'diciembre': 12,  'dic': 12,
}

# ── Regex auxiliares ─────────────────────────────────────────────────────────
_MESES_PATRON = '|'.join(sorted(_MESES_ES.keys(), key=len, reverse=True))
# Fecha con mes en letras: "22 enero 2026", "22-ENE-26", "22 ENE 2026"
_FECHA_LETRAS = re.compile(
    r'(\d{1,2})\s*[-/.]?\s*(' + _MESES_PATRON + r')\s*[-/.]?\s*(\d{2,4})',
    re.IGNORECASE
)
# Fecha solo dd-mm (sin año): "22-12", "02-01", "13/01"
_FECHA_DDMM = re.compile(r'^(\d{1,2})[-/](\d{1,2})$')
# Fecha dd-mm-yy o dd/mm/yyyy o variantes
_FECHA_NUMERICA = re.compile(
    r'(\d{1,4})[\-/\.](\d{1,2})[\-/\.](\d{2,4})'
)


def parse_fecha_universal(
    s: str,
    context_year: Optional[int] = None,
    context_fecha_inicio: Optional[date] = None,
    context_fecha_fin: Optional[date] = None,
) -> Optional[str]:
    """
    Parser universal de fechas bancarias CR.

    Maneja todos los formatos conocidos de los 37 bancos SUGEF:
      - dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy
      - dd/mm/yy, dd-mm-yy
      - yyyy-mm-dd  (ISO)
      - dd-mm  (sin año — BN, algunos BCR)
      - dd mes_letra yyyy  (ej: 22 enero 2026, 22-ENE-26)
      - Separadores mixtos: /, -, ., espacio

    Para formatos sin año (dd-mm) usa context_fecha_fin del header
    del PDF para inferir el año correcto, incluso cuando el corte
    cruza meses (ej: mes=12 en un PDF cuyo header dice 16/01/2026
    → año = 2025).

    Returns: str en formato ISO 'YYYY-MM-DD', o None si no se puede parsear.
    """
    if not s:
        return None
    s = s.strip()

    # 1. Intentar con mes en letras primero (más específico)
    m = _FECHA_LETRAS.match(s)
    if m:
        try:
            day  = int(m.group(1))
            mes  = _MESES_ES.get(m.group(2).lower())
            yr   = int(m.group(3))
            if yr < 100:  # año de 2 dígitos
                yr += 2000
            if mes and 1 <= day <= 31 and 1 <= mes <= 12:
                return date(yr, mes, day).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass

    # 2. Intentar formato numérico con año
    m = _FECHA_NUMERICA.match(s)
    if m:
        p1, p2, p3 = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Detectar si es ISO (yyyy-mm-dd) o CR (dd-mm-yyyy)
        if p1 > 31:          # primer campo > 31 → es año (ISO)
            yr, mes, day = p1, p2, p3
        elif p3 > 31:        # tercer campo > 31 → es año (CR/anglosajón)
            day, mes, yr = p1, p2, p3
            if yr < 100:
                yr += 2000
        else:
            # Año de 2 dígitos en p3, asumir CR
            day, mes, yr = p1, p2, p3 + 2000
        try:
            if 1 <= day <= 31 and 1 <= mes <= 12:
                return date(yr, mes, day).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass

    # 3. Formato dd-mm sin año (BN y otros bancos CR)
    m = _FECHA_DDMM.match(s)
    if m:
        day, mes = int(m.group(1)), int(m.group(2))
        if not (1 <= day <= 31 and 1 <= mes <= 12):
            return None

        # Inferir año usando el contexto del header del PDF
        if context_fecha_fin:
            # El año del corte nos dice en qué año cae cada mes
            # Si el mes de la transacción > mes del corte → año anterior
            anio_corte = context_fecha_fin.year
            mes_corte  = context_fecha_fin.month
            if mes > mes_corte + 1:       # ej: mes=12, corte=1 → año anterior
                yr = anio_corte - 1
            else:
                yr = anio_corte
        elif context_year:
            yr = context_year
        else:
            yr = datetime.now().year     # fallback: año actual

        try:
            return date(yr, mes, day).strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            return None

    return None


def extract_header_info(text: str) -> dict:
    """
    Extrae metadatos del header de un estado de cuenta bancario.

    Captura:
      - fecha_inicio: 'Fecha último estado' o 'Fecha anterior'
      - fecha_fin:    'Fecha éste estado' o 'Fecha actual'
      - numero_cuenta, nombre_titular, banco_detectado

    Retorna dict con las claves (None si no se encuentra).
    """
    result = {
        'fecha_inicio': None,    # date
        'fecha_fin':    None,    # date
        'numero_cuenta': None,
        'nombre_titular': None,
        'banco_detectado': None,
    }

    # Detectar banco por texto en el documento
    for nombre, clave in [
        ('BANCO NACIONAL', 'BN'), ('Banco Nacional', 'BN'),
        ('BANCO DE COSTA RICA', 'BCR'), ('Banco de Costa Rica', 'BCR'),
        ('BAC SAN JOSE', 'BAC'), ('BAC San José', 'BAC'),
        ('BANCO POPULAR', 'BPDC'),
        ('DAVIVIENDA', 'DAVIVIENDA'), ('SCOTIABANK', 'SCOTIABANK'),
        ('COOCIQUE', 'COOCIQUE'), ('COOPEALIANZA', 'COOPEALIANZA'),
    ]:
        if nombre in text:
            result['banco_detectado'] = clave
            break

    # Patrones para fechas de corte (formatos vistos en el mercado CR)
    # BN:  "Fecha último estado:\t19/12/2025"
    # BCR: "Fecha de corte: 31/01/2026"
    # BAC: "Estado de cuenta al 31/01/2026"
    PAT_INICIO = re.compile(
        r'(?:fecha\s+(?:último|ultimo)\s+estado|fecha\s+anterior|saldo\s+al)[:\s]+'
        r'(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})',
        re.IGNORECASE
    )
    PAT_FIN = re.compile(
        r'(?:fecha\s+[eé]ste\s+estado|fecha\s+(?:de\s+)?corte|fecha\s+actual|al\s+\d)[:\s]*'
        r'(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})',
        re.IGNORECASE
    )
    # Patrón simple dd/mm/yyyy en cualquier contexto de "fecha"
    PAT_FECHA_SIMPLE = re.compile(r'(\d{2}[/\-]\d{2}[/\-]\d{4})')

    m = PAT_INICIO.search(text)
    if m:
        iso = parse_fecha_universal(m.group(1))
        if iso:
            from datetime import date as _date
            result['fecha_inicio'] = _date.fromisoformat(iso)

    m = PAT_FIN.search(text)
    if m:
        iso = parse_fecha_universal(m.group(1))
        if iso:
            from datetime import date as _date
            result['fecha_fin'] = _date.fromisoformat(iso)

    # Número de cuenta (Banco Nacional: "Número de cuenta: 200-01-012-080146-5")
    m = re.search(r'(?:n[úu]mero\s+de\s+cuenta|cuenta)[:\s]+([\d\-]+)', text, re.IGNORECASE)
    if m:
        result['numero_cuenta'] = m.group(1).strip()

    # Nombre del titular
    m = re.search(r'(?:nombre|titular)[:\s]+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{4,50})', text, re.IGNORECASE)
    if m:
        result['nombre_titular'] = m.group(1).strip()

    return result


def split_transactions_by_period(transactions: list[dict]) -> dict[str, list[dict]]:
    """
    Agrupa transacciones por período YYYY-MM.

    Cuando un PDF de banco cruza meses (ej: BN corta el 16 de enero
    con transacciones de diciembre Y enero), esta función las separa
    por mes calendario para que cada grupo se reconcilie correctamente
    con su período del Libro Diario.

    Returns: {'2025-12': [txn, ...], '2026-01': [txn, ...]}
    """
    grupos: dict[str, list[dict]] = {}
    for txn in transactions:
        fecha = txn.get('fecha', '')
        if fecha and len(fecha) >= 7:
            period = fecha[:7]       # 'YYYY-MM'
        else:
            period = 'UNKNOWN'
        grupos.setdefault(period, []).append(txn)
    return grupos


def verificar_cadena_saldos(
    pdf_saldos: list[dict]
) -> dict:
    """
    Verifica la cadena de saldos entre PDFs consecutivos.

    Args:
        pdf_saldos: lista de dicts ordenada cronológicamente, cada uno con:
            {'label': str, 'saldo_inicial': float, 'saldo_final': float}

    Returns: dict con 'ok' (bool), pares verificados y gaps detectados.
    """
    if len(pdf_saldos) < 2:
        return {'ok': True, 'pares': [], 'gaps': []}

    pares  = []
    gaps   = []
    TOLERANCIA = 1.0   # ₡1 de tolerancia por redondeo

    for i in range(len(pdf_saldos) - 1):
        a = pdf_saldos[i]
        b = pdf_saldos[i + 1]
        diff = abs(a['saldo_final'] - b['saldo_inicial'])
        ok   = diff <= TOLERANCIA
        par  = {
            'de':    a['label'],
            'a':     b['label'],
            'saldo_final_a':    a['saldo_final'],
            'saldo_inicial_b':  b['saldo_inicial'],
            'diff':  diff,
            'ok':    ok,
        }
        pares.append(par)
        if not ok:
            gaps.append(par)

    return {'ok': len(gaps) == 0, 'pares': pares, 'gaps': gaps}


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

    BN v2 — estado de cuenta electrónica Colones:
    - Columna FECHA: 'dd-mm' (sin año) — año se infiere del header
    - Columna NÚMERO: número de comprobante
    - Columna DESCRIPCIÓN: texto libre
    - Columna MONTO: con guión al final si es débito (ej: "200,000-")
    - Columna SALDO DIARIO: saldo acumulado
    El PDF cruza meses; el año se determina por 'Fecha éste estado' del header.
    """
    header = extract_header_info(text)
    fecha_fin   = header.get('fecha_fin')    # date|None
    fecha_inicio = header.get('fecha_inicio')  # date|None

    transactions = []
    lines = text.split('\n')

    # Patrón BN: fecha dd-mm + numero + descripción + monto + saldo
    # Fecha puede ser: "22-12", "02-01", "13/01", "13 01"
    # Monto puede tener guión al final (débito): "200,000-" o sin guión (crédito): "9,034.45+"
    DATE_PAT_BN = re.compile(
        r'^(\d{1,2}[-/]\d{1,2})\s+'     # fecha dd-mm
        r'(\d+)\s+'                        # número de transacción
        r'(.+?)\s+'                        # descripción
        r'([\d.,]+[-+]?)\s+'              # monto (con - para débito, + para crédito)
        r'([\d.,]+)\s*$'                  # saldo diario
    )
    # Patrón alternativo cuando monto y saldo están juntos sin descriptor
    DATE_PAT_BN_SHORT = re.compile(
        r'^(\d{1,2}[-/]\d{1,2})\s+'
        r'(.+?)\s+'
        r'([\d.,]+[-+]?)\s+'
        r'([\d.,]+)\s*$'
    )

    for line in lines:
        line = line.strip()
        if not line or len(line) < 10:
            continue

        m = DATE_PAT_BN.match(line) or DATE_PAT_BN_SHORT.match(line)
        if not m:
            continue

        try:
            groups    = m.groups()
            fecha_str = groups[0]   # dd-mm

            # Inferir año usando los datos del header
            fecha_iso = parse_fecha_universal(
                fecha_str,
                context_fecha_fin=fecha_fin,
            )
            if not fecha_iso:
                continue

            if len(groups) == 5:
                # Patrón completo: fecha, num, desc, monto, saldo
                descripcion = groups[2].strip()
                monto_raw   = groups[3]
                saldo_raw   = groups[4]
            else:
                # Patrón corto: fecha, desc, monto, saldo
                descripcion = groups[1].strip()
                monto_raw   = groups[2]
                saldo_raw   = groups[3]

            # Determinar tipo por el indicador al final del monto
            if monto_raw.endswith('-'):
                tipo  = 'DB'
                monto = _parse_monto_cr(monto_raw[:-1])
            elif monto_raw.endswith('+'):
                tipo  = 'CR'
                monto = _parse_monto_cr(monto_raw[:-1])
            else:
                # Sin indicador: asumir débito (BN default para débitos sin signo)
                tipo  = 'DB'
                monto = _parse_monto_cr(monto_raw)

            saldo = _parse_monto_cr(saldo_raw)

            transactions.append({
                'fecha':       fecha_iso,
                'descripcion': descripcion,
                'tipo':        tipo,
                'monto':       monto,
                'saldo':       saldo,
                'referencia':  groups[1] if len(groups) == 5 else '',
                'banco':       'BN',
                'telefono':    extraer_telefono(descripcion),
                'period':      fecha_iso[:7],   # YYYY-MM para split posterior
            })
        except Exception as exc:
            logger.debug(f'BN parse skip: {exc} / line={line[:80]}')
            continue

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

def parse_pdf_text(
    text: str,
    banco: str,
    split_by_period: bool = True,
) -> list[dict]:
    """
    Parsea el texto extraído de un PDF de estado de cuenta.

    Args:
        text:            Texto completo del PDF
        banco:           Clave del banco ('BN', 'BCR', 'BAC', etc.)
        split_by_period: Si True, agrega campo 'period' a cada txn (YYYY-MM)

    Returns:
        Lista de transacciones en formato estándar con campo 'period'.
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
