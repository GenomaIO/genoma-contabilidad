"""
file_parser.py — Parser multi-formato para estados de cuenta bancarios CR

Soporta:
  PDF  → texto extraído en frontend con PDF.js o enviado como archivo
  CSV  → descarga directa de banca en línea (BAC, BCR, cooperativas)
  XLSX → exportación Excel (BN Virtual, algunos privados)

La función pública parse_bank_file(content_bytes, filename, banco)
detecta el formato por extensión y parsea retornando la estructura
estándar de transacciones.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

IVA_RATE = 0.13


# ── Utilidades compartidas ───────────────────────────────────────────────────

def extraer_telefono(descripcion: str) -> Optional[str]:
    """Extrae número de teléfono CR de la descripción."""
    if not descripcion:
        return None
    m = re.search(r'\b([2-9]\d{3}[-\s]?\d{4})\b', descripcion)
    return re.sub(r'[-\s]', '', m.group(1)) if m else None


def _parse_monto(s: str) -> float:
    """
    Convierte montos bancarios CR a float.
    
    Formatos soportados:
      CR anglosajón:  50,000 / 1,234,567.89  → 50000 / 1234567.89
      CR colones:     50.000 / 1.234.567,89  → 50000 / 1234567.89
      Sin separador:  150000                 → 150000
    """
    if not s:
        return 0.0
    s = str(s).strip()
    # Eliminar símbolo ₡ (U+20A1), CRC, comillas y espacios
    for ch in ['\u20a1', '₡', 'CRC', '"', "'", ' ']:
        s = s.replace(ch, '')
    s = s.strip()
    if not s:
        return 0.0

    # Contar punto(s) y coma(s)
    n_puntos = s.count('.')
    n_comas  = s.count(',')

    if n_puntos == 0 and n_comas == 0:
        # Sin separadores: número puro
        pass
    elif n_puntos > 0 and n_comas == 0:
        # Solo puntos: pueden ser miles CR (1.234.567) o decimal anglosajón (1234.50)
        # Si hay más de 1 punto o el texto después del último punto tiene 3 dígitos → miles
        partes = s.split('.')
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            # Formato CR con puntos como miles: 1.234.567 o 50.000
            s = s.replace('.', '')
        # else: decimal anglosajón 1234.50 → dejar como está
    elif n_puntos == 0 and n_comas > 0:
        # Solo comas: pueden ser miles anglosajones (1,234,567) o decimal CR (1234,50)
        partes = s.split(',')
        if len(partes) > 2 or (len(partes) == 2 and len(partes[-1]) == 3):
            # Miles anglosajón: 1,234,567 o 50,000
            s = s.replace(',', '')
        else:
            # Decimal CR: 1234,50
            s = s.replace(',', '.')
    else:
        # Tiene tanto puntos como comas → determinar cuál es el separador decimal
        ultimo_punto = s.rfind('.')
        ultima_coma  = s.rfind(',')
        if ultima_coma > ultimo_punto:
            # La coma está al final → es el decimal (formato CR: 1.234.567,89)
            s = s.replace('.', '').replace(',', '.')
        else:
            # El punto está al final → es el decimal (formato anglosajón: 1,234,567.89)
            s = s.replace(',', '')

    try:
        return abs(float(s))
    except ValueError:
        return 0.0



def _parse_fecha(s: str) -> Optional[str]:
    """Parsea fechas en múltiples formatos CR."""
    s = str(s).strip()
    for fmt in ["%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y",
                "%d-%m-%y", "%Y/%m/%d", "%m/%d/%Y"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _txn(fecha, desc, tipo, monto, saldo=0.0, ref="", banco="", raw_row=None) -> dict:
    """Construye el dict estándar de una transacción."""
    return {
        "fecha":       fecha,
        "descripcion": str(desc or "").strip(),
        "tipo":        tipo,                    # CR=ingreso, DB=gasto
        "monto":       round(float(monto), 2),
        "saldo":       round(float(saldo), 2),
        "referencia":  str(ref or "").strip(),
        "banco":       banco,
        "telefono":    extraer_telefono(str(desc or "")),
        "_raw":        raw_row,                 # fila original para debug
    }


# ── Parser CSV genérico ──────────────────────────────────────────────────────

def _detectar_separator(text: str) -> str:
    """Detecta si el CSV usa coma, punto y coma o tabulación."""
    sample = text[:2000]
    counts = {",": sample.count(","), ";": sample.count(";"), "\t": sample.count("\t")}
    return max(counts, key=counts.get)


def _normalizar_header(h: str) -> str:
    return re.sub(r'[^a-z0-9]', '_', h.lower().strip())


# Columnas candidatas por semántica (orden de prioridad)
_FECHA_COLS  = {"fecha", "date", "fec", "fecha_mov", "fecha_trans", "fecha_valor",
                "fecha_operacion", "fecha_transaccion", "fecha_de_transaccion"}
_DESC_COLS   = {"descripcion", "description", "concepto", "detalle", "motivo",
                "referencia_desc", "descripcion_movimiento", "glosa", "concepto_movimiento"}
_DB_COLS     = {"debito", "debito_", "debe", "cargo", "db", "salida", "debit",
                "monto_debito", "egreso", "monto_cargo"}
_CR_COLS     = {"credito", "credito_", "haber", "abono", "cr", "entrada", "credit",
                "monto_credito", "ingreso", "monto_abono"}
_SALDO_COLS  = {"saldo", "balance", "saldo_disponible", "saldo_actual"}
_REF_COLS    = {"referencia", "ref", "num_ref", "numero_referencia", "numero_movimiento",
                "comprobante", "num_trans", "numero_transaccion"}
_MONTO_COLS  = {"monto", "importe", "amount", "valor", "monto_colon", "monto_transaccion"}
_TIPO_COLS   = {"tipo", "type", "tipo_mov", "tipo_transaccion", "tipo_movimiento"}


def _find_col(headers: list[str], candidates: set) -> Optional[str]:
    """Busca la columna que coincide con los candidatos.
    Primero por coincidencia exacta, luego por substring (ej. 'valor_debito' contiene 'debito').
    """
    # 1. Coincidencia exacta
    for h in headers:
        if h in candidates:
            return h
    # 2. El header contiene alguna candidata (ej. 'valor_debito' → 'debito')
    for h in headers:
        for cand in candidates:
            if cand in h:
                return h
    return None


def parse_csv(content: str, banco: str) -> list[dict]:
    """Parsea un CSV de estado de cuenta bancario."""
    sep = _detectar_separator(content)
    reader = csv.DictReader(io.StringIO(content), delimiter=sep)

    # Normalizar headers
    raw_headers = reader.fieldnames or []
    norm_map = {h: _normalizar_header(h) for h in raw_headers}
    norm_headers = list(norm_map.values())

    fecha_col = _find_col(norm_headers, _FECHA_COLS)
    desc_col  = _find_col(norm_headers, _DESC_COLS)
    db_col    = _find_col(norm_headers, _DB_COLS)
    cr_col    = _find_col(norm_headers, _CR_COLS)
    saldo_col = _find_col(norm_headers, _SALDO_COLS)
    ref_col   = _find_col(norm_headers, _REF_COLS)
    monto_col = _find_col(norm_headers, _MONTO_COLS)
    tipo_col  = _find_col(norm_headers, _TIPO_COLS)

    if not fecha_col:
        logger.warning(f"CSV {banco}: no se encontró columna de fecha en {norm_headers}")
        return []

    transactions = []
    for row in reader:
        # Re-mapear con headers normalizados
        norm_row = {norm_map[k]: v for k, v in row.items() if k in norm_map}

        fecha_raw = norm_row.get(fecha_col, "")
        fecha = _parse_fecha(fecha_raw)
        if not fecha:
            continue

        desc = norm_row.get(desc_col, "")
        ref  = norm_row.get(ref_col, "") if ref_col else ""
        saldo = _parse_monto(norm_row.get(saldo_col, "0")) if saldo_col else 0.0

        # Determinar tipo y monto
        if db_col and cr_col:
            debito  = _parse_monto(norm_row.get(db_col, "0"))
            credito = _parse_monto(norm_row.get(cr_col, "0"))
            if credito > 0 and debito == 0:
                tipo, monto = "CR", credito
            elif debito > 0 and credito == 0:
                tipo, monto = "DB", debito
            elif credito > 0 and debito > 0:
                # Columna de monto duplicada — tomar la mayor
                tipo = "CR" if credito >= debito else "DB"
                monto = max(credito, debito)
            else:
                continue  # Fila vacía / encabezado
        elif monto_col:
            monto = _parse_monto(norm_row.get(monto_col, "0"))
            if monto <= 0:
                continue
            # Inferir tipo por columna 'tipo' o descripción
            if tipo_col:
                tipo_val = (norm_row.get(tipo_col) or "").upper()
                tipo = "CR" if any(k in tipo_val for k in ["CR", "CRED", "ABONO", "ING"]) else "DB"
            else:
                desc_up = (desc or "").upper()
                tipo = "CR" if any(k in desc_up for k in ["SINPE", "DEPOSITO", "ABONO", "CREDITO"]) else "DB"
        else:
            continue  # Sin columnas de monto reconocibles

        if monto <= 0:
            continue

        transactions.append(_txn(fecha, desc, tipo, monto, saldo, ref, banco, dict(norm_row)))

    logger.info(f"CSV {banco}: {len(transactions)} transacciones parseadas")
    return transactions


# ── Parser Excel (XLSX) ──────────────────────────────────────────────────────

def parse_xlsx(content_bytes: bytes, banco: str) -> list[dict]:
    """Parsea un archivo Excel (.xlsx) de estado de cuenta bancario."""
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl no instalado. Instalar con: pip install openpyxl")
        return []

    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    # Buscar la fila de encabezados (primera fila con texto no vacío)
    header_row_idx = None
    headers = []
    for i, row in enumerate(rows):
        row_vals = [str(c or "").strip() for c in row]
        non_empty = [v for v in row_vals if v]
        if len(non_empty) >= 3:  # Al menos 3 columnas con datos
            header_row_idx = i
            headers = [_normalizar_header(v) for v in row_vals]
            break

    if header_row_idx is None:
        logger.warning(f"XLSX {banco}: no se encontró fila de encabezados")
        return []

    fecha_col_idx = next((i for i, h in enumerate(headers) if h in _FECHA_COLS), None)
    desc_col_idx  = next((i for i, h in enumerate(headers) if h in _DESC_COLS), None)
    db_col_idx    = next((i for i, h in enumerate(headers) if h in _DB_COLS), None)
    cr_col_idx    = next((i for i, h in enumerate(headers) if h in _CR_COLS), None)
    saldo_col_idx = next((i for i, h in enumerate(headers) if h in _SALDO_COLS), None)
    ref_col_idx   = next((i for i, h in enumerate(headers) if h in _REF_COLS), None)
    monto_col_idx = next((i for i, h in enumerate(headers) if h in _MONTO_COLS), None)
    tipo_col_idx  = next((i for i, h in enumerate(headers) if h in _TIPO_COLS), None)

    def _cell(row, idx):
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    transactions = []
    for row in rows[header_row_idx + 1:]:
        fecha_val = _cell(row, fecha_col_idx)
        if not fecha_val:
            continue

        # Las fechas en Excel pueden venir como datetime
        if hasattr(fecha_val, "strftime"):
            fecha = fecha_val.strftime("%Y-%m-%d")
        else:
            fecha = _parse_fecha(str(fecha_val))
        if not fecha:
            continue

        desc  = str(_cell(row, desc_col_idx)  or "").strip()
        ref   = str(_cell(row, ref_col_idx)   or "").strip()
        saldo = _parse_monto(str(_cell(row, saldo_col_idx) or "0")) if saldo_col_idx else 0.0

        if db_col_idx is not None and cr_col_idx is not None:
            debito  = _parse_monto(str(_cell(row, db_col_idx)  or "0"))
            credito = _parse_monto(str(_cell(row, cr_col_idx) or "0"))
            if credito > 0 and debito == 0:
                tipo, monto = "CR", credito
            elif debito > 0 and credito == 0:
                tipo, monto = "DB", debito
            elif credito > 0 and debito > 0:
                tipo = "CR" if credito >= debito else "DB"
                monto = max(credito, debito)
            else:
                continue
        elif monto_col_idx is not None:
            monto = _parse_monto(str(_cell(row, monto_col_idx) or "0"))
            if monto <= 0:
                continue
            if tipo_col_idx is not None:
                tipo_val = str(_cell(row, tipo_col_idx) or "").upper()
                tipo = "CR" if any(k in tipo_val for k in ["CR", "CRED", "ABONO"]) else "DB"
            else:
                desc_up = desc.upper()
                tipo = "CR" if any(k in desc_up for k in ["SINPE", "DEPOSITO", "ABONO"]) else "DB"
        else:
            continue

        if monto <= 0:
            continue

        transactions.append(_txn(fecha, desc, tipo, monto, saldo, ref, banco))

    logger.info(f"XLSX {banco}: {len(transactions)} transacciones parseadas")
    return transactions


# ── Interfaz pública ─────────────────────────────────────────────────────────

FORMATO_SOPORTE = {
    ".csv":  "CSV — Texto separado por comas o punto y coma",
    ".xlsx": "Excel — Hoja de cálculo (requiere openpyxl)",
    ".xls":  "Excel legacy — Hoja de cálculo (requiere xlrd)",
    ".pdf":  "PDF — Texto extraído (requiere pdfplumber en backend o PDF.js en frontend)",
    ".txt":  "Texto plano — CSV con extensión .txt",
}


def parse_bank_file(
    content: bytes | str,
    filename: str,
    banco: str,
) -> dict:
    """
    Detecta el formato del archivo y parsea las transacciones.

    Args:
        content:  Bytes del archivo (para XLSX/PDF) o texto (para CSV/TXT)
        filename: Nombre del archivo (para detectar extensión)
        banco:    Clave del banco (ej: 'BAC', 'BCR', 'BN', 'COOCIQUE')

    Returns:
        {
            "formato":         "CSV" | "XLSX" | "PDF" | "TXT",
            "banco":           "BAC",
            "transacciones":   [...],
            "total":           N,
            "saldo_inicial":   X,
            "saldo_final":     Y,
            "warnings":        [...],
        }
    """
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    banco = banco.upper()
    warnings = []

    # ── CSV y TXT ────────────────────────────────────────────────────────────
    if ext in ("csv", "txt"):
        if isinstance(content, bytes):
            # Intentar UTF-8, fallback a latin-1 (documentos CR suelen usar latin-1)
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
        else:
            text = content
        txns = parse_csv(text, banco)
        formato = "CSV"
        saldo_inicial = txns[0].get("saldo", 0.0) if txns else 0.0
        saldo_final   = txns[-1].get("saldo", 0.0) if txns else 0.0

    # ── Excel ────────────────────────────────────────────────────────────────
    elif ext in ("xlsx", "xls"):
        if isinstance(content, str):
            content = content.encode("latin-1")
        if ext == "xls":
            warnings.append("Formato .xls (Excel antiguo) — se recomienda guardar como .xlsx")
            try:
                import xlrd
                wb = xlrd.open_workbook(file_contents=content)
                ws = wb.sheet_by_index(0)
                # Convertir a CSV para reusar la lógica
                rows_text = "\n".join(
                    ";".join(str(ws.cell_value(r, c)) for c in range(ws.ncols))
                    for r in range(ws.nrows)
                )
                txns = parse_csv(rows_text, banco)
            except ImportError:
                warnings.append("xlrd no instalado — sube el archivo como .xlsx")
                txns = []
        else:
            txns = parse_xlsx(content, banco)
        formato = "XLSX" if ext == "xlsx" else "XLS"
        saldo_inicial = txns[0].get("saldo", 0.0) if txns else 0.0
        saldo_final   = txns[-1].get("saldo", 0.0) if txns else 0.0

    # ── PDF (texto ya extraído) ───────────────────────────────────────────────
    elif ext == "pdf":
        # El frontend (PDF.js) extrae el texto y lo envía como string
        # En backend también se puede usar pdfplumber si se sube el archivo
        if isinstance(content, bytes):
            try:
                import pdfplumber
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            except ImportError:
                warnings.append("pdfplumber no instalado — para PDFs, instalar con: pip install pdfplumber")
                text = content.decode("latin-1", errors="ignore")
        else:
            text = content

        from services.conciliacion.bank_pdf_parser import parse_pdf_text, extract_saldos
        txns = parse_pdf_text(text, banco)
        saldos = extract_saldos(text)
        saldo_inicial = saldos["saldo_inicial"]
        saldo_final   = saldos["saldo_final"]
        formato = "PDF"

    else:
        return {
            "formato":        "DESCONOCIDO",
            "banco":          banco,
            "transacciones":  [],
            "total":          0,
            "saldo_inicial":  0.0,
            "saldo_final":    0.0,
            "warnings":       [f"Formato no soportado: .{ext}. Use CSV, XLSX o PDF."],
            "error":          True,
        }

    # Post-procesamiento: remover filas de metadata
    txns = [t for t in txns if t["monto"] > 0]

    if not txns:
        warnings.append(
            f"No se encontraron transacciones. "
            f"Verifica que el archivo sea un estado de cuenta de {banco} "
            f"en formato {formato}."
        )

    return {
        "formato":        formato,
        "banco":          banco,
        "transacciones":  txns,
        "total":          len(txns),
        "saldo_inicial":  saldo_inicial,
        "saldo_final":    saldo_final,
        "warnings":       warnings,
    }


def formatos_aceptados() -> dict:
    """Retorna los formatos de archivo aceptados por el módulo."""
    return {
        "aceptados": list(FORMATO_SOPORTE.keys()),
        "descripcion": FORMATO_SOPORTE,
        "nota": (
            "Sube el extracto bancario en el formato que tu banco lo exporta. "
            "CSV y XLSX se procesan directamente. "
            "Para PDF, el texto se extrae automáticamente."
        ),
    }
