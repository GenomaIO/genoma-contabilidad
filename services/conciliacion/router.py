"""
router.py — Endpoints REST para Conciliación Bancaria + CENTINELA Fiscal

Endpoints:
  GET  /conciliacion/entidades           → Lista de 37 bancos/cooperativas
  POST /conciliacion/parse               → Parsea TEXTO plano → transacciones
  POST /conciliacion/parse-file          → Parsea archivo (PDF/XLSX/CSV) multipart
  POST /conciliacion/ocr-image           → Imagen → Gemini Vision → transacciones
  POST /conciliacion/sesion              → Crea sesión de conciliación
  POST /conciliacion/match/{recon_id}    → Corre motor de matching vs Diario
  POST /centinela/analyze/{recon_id}     → Análisis CENTINELA completo
  GET  /centinela/score/{period}         → Score del período YYYYMM
  GET  /centinela/d270/{period}          → Datos pre-llenados D-270
  GET  /centinela/d270/{period}/export   → CSV formato Tribu-CR
  POST /conciliacion/rule                → Guarda Bank Rule
  GET  /conciliacion/rules               → Lista Bank Rules del tenant
  POST /conciliacion/approve/{txn_id}    → Aprueba asiento sugerido → Diario
"""
from __future__ import annotations
import logging
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Modelos Pydantic ─────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    text: str
    banco: str

class UploadSession(BaseModel):
    banco: str
    period: str          # YYYYMM
    account_code: str
    saldo_inicial: float = 0.0
    saldo_final: float   = 0.0

class BankRule(BaseModel):
    pattern: str
    pattern_type: str = "description_contains"   # phone | keyword | description_contains
    contact_name: Optional[str] = None
    ledger_account: Optional[str] = None
    d270_codigo: Optional[str] = None
    note: Optional[str] = None

class ApproveRequest(BaseModel):
    cuenta_debito: str
    cuenta_credito: str
    descripcion: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_db():
    from services.gateway.main import _engine
    from sqlalchemy.orm import Session
    with Session(_engine) as session:
        yield session

def _get_tenant(request):
    """Extrae tenant_id del JWT. Usa services.auth.security (módulo real del proyecto)."""
    from services.auth.security import decode_token
    from fastapi import Request
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token requerido")
    token = auth.split(" ", 1)[1]
    payload = decode_token(token)
    tenant_id = payload.get("tenant_id") or payload.get("sub")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="tenant_id no encontrado en token")
    return tenant_id


# ── Endpoints de Conciliación Bancaria ──────────────────────────────────────

@router.get("/conciliacion/entidades")
def get_entidades():
    """Lista completa de 37 entidades bancarias SUGEF soportadas."""
    from services.conciliacion.bank_pdf_parser import entidades_disponibles
    return {"entidades": entidades_disponibles()}


@router.post("/conciliacion/parse")
def parse_pdf(req: ParseRequest):
    """
    Parsea texto plano (CSV, TXT) de un estado de cuenta bancario.

    Nota: Los PDFs se procesan vía /conciliacion/parse-file (pdfplumber).
    Este endpoint recibe el texto ya extraído para CSV/TXT.
    """
    from services.conciliacion.bank_pdf_parser import (
        parse_pdf_text, extract_saldos, BANCO_KEYS,
    )

    # WARN-01 fix: validar que el banco sea una clave reconocida
    banco_upper = req.banco.strip().upper()
    claves_validas = set(BANCO_KEYS.values())  # set de claves internas
    if banco_upper not in claves_validas:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Banco '{req.banco}' no reconocido. "
                f"Valores válidos: {', '.join(sorted(claves_validas))}"
            )
        )

    try:
        txns   = parse_pdf_text(req.text, banco_upper)
        saldos = extract_saldos(req.text)
        return {
            "ok": True,
            "banco": banco_upper,
            "transacciones": txns,
            "total_transacciones": len(txns),
            "saldo_inicial": saldos["saldo_inicial"],
            "saldo_final":   saldos["saldo_final"],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parseando texto {banco_upper}: {e}")
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/conciliacion/parse-file")
async def parse_file_upload(
    file:  UploadFile = File(...),
    banco: str        = Form(...),
):
    """
    Parsea un archivo multipart: PDF, XLSX o CSV.

    - PDF  → pdfplumber extrae el texto, luego bank_pdf_parser lo procesa
    - XLSX → openpyxl convierte las filas a CSV-like, luego parser
    - CSV  → lee como texto directamente

    Retorna el mismo formato estándar que /conciliacion/parse.
    """
    from services.conciliacion.bank_pdf_parser import (
        parse_pdf_text, extract_saldos, extract_header_info,
        split_transactions_by_period,
    )

    fname = (file.filename or "").lower()
    raw   = await file.read()

    try:
        if fname.endswith(".pdf"):
            import pdfplumber, io
            text_parts = []
            with pdfplumber.open(io.BytesIO(raw)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            text = "\n".join(text_parts)

        elif fname.endswith((".xlsx", ".xls")):
            import openpyxl, io
            wb  = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
            ws  = wb.active
            rows = []
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                rows.append("  ".join(cells))
            text = "\n".join(rows)

        else:
            # CSV / TXT — decodificar directo
            text = raw.decode("utf-8", errors="replace")

        txns   = parse_pdf_text(text, banco)
        saldos = extract_saldos(text)
        header = extract_header_info(text)
        grupos = split_transactions_by_period(txns)

        return {
            "ok":                  True,
            "banco":               banco,
            "transacciones":       txns,
            "total_transacciones": len(txns),
            "saldo_inicial":       saldos["saldo_inicial"],
            "saldo_final":         saldos["saldo_final"],
            "periodos_detectados": list(grupos.keys()),
            "fecha_inicio":        str(header.get("fecha_inicio") or ""),
            "fecha_fin":           str(header.get("fecha_fin") or ""),
            "numero_cuenta":       header.get("numero_cuenta"),
        }

    except Exception as e:
        logger.error(f"parse-file error ({fname}): {e}", exc_info=True)
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/conciliacion/ocr-image")
async def ocr_image(
    file:  UploadFile = File(...),
    banco: str        = Form(...),
):
    """
    Recibe una imagen (jpg/png/webp/pdf-escaneado) de un estado de cuenta
    bancario, usa Gemini Vision para extraer el texto estructurado, y luego
    corre el bank_pdf_parser normal.

    Requiere: GEMINI_API_KEY en las variables de entorno.
    """
    import os, io, base64
    from services.conciliacion.bank_pdf_parser import (
        parse_pdf_text, extract_saldos, extract_header_info,
        split_transactions_by_period,
    )

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY no configurada. Contacta al administrador."
        )

    fname = (file.filename or "").lower()
    raw   = await file.read()

    # Determinar MIME type
    if fname.endswith(".png"):
        mime = "image/png"
    elif fname.endswith((".jpg", ".jpeg")):
        mime = "image/jpeg"
    elif fname.endswith(".webp"):
        mime = "image/webp"
    elif fname.endswith(".pdf"):
        mime = "application/pdf"
    else:
        raise HTTPException(status_code=400,
                            detail=f"Formato no soportado: {fname}. Use jpg/png/webp/pdf")

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        prompt = (
            "Eres un extractor de datos contables. Analiza esta imagen de un "
            "estado de cuenta bancario costarricense y extrae TODAS las transacciones "
            "en formato de tabla de texto plano con las columnas:\n"
            "FECHA  DESCRIPCION  MONTO  TIPO(CR/DB)  SALDO\n\n"
            "Reglas:\n"
            "- FECHA: usa el formato que aparece en el documento (dd/mm/yyyy, dd-mm, etc.)\n"
            "- MONTO: solo el número con decimales, sin signo\n"
            "- TIPO: CR si es crédito/ingreso, DB si es débito/gasto\n"
            "- Incluye los saldos del header: 'Saldo anterior: X' y 'Saldo actual: Y'\n"
            "- NO omitas ninguna transacción\n"
            "- Si hay información del header (banco, número de cuenta, "
            "  fecha último estado, fecha éste estado), inclúyela al inicio\n\n"
            "Responde SOLO con el texto extraído, sin explicaciones adicionales."
        )

        img_part = {"mime_type": mime, "data": base64.b64encode(raw).decode()}
        response = model.generate_content([prompt, img_part])
        text     = response.text or ""

        if not text.strip():
            raise ValueError("Gemini no pudo extraer texto de la imagen")

        txns   = parse_pdf_text(text, banco)
        saldos = extract_saldos(text)
        header = extract_header_info(text)
        grupos = split_transactions_by_period(txns)

        logger.info(
            f"OCR exitoso ({fname}): {len(txns)} txns, "
            f"periodos={list(grupos.keys())}"
        )

        return {
            "ok":                  True,
            "banco":               banco,
            "fuente":              "gemini-vision",
            "transacciones":       txns,
            "total_transacciones": len(txns),
            "saldo_inicial":       saldos["saldo_inicial"],
            "saldo_final":         saldos["saldo_final"],
            "periodos_detectados": list(grupos.keys()),
            "fecha_inicio":        str(header.get("fecha_inicio") or ""),
            "fecha_fin":           str(header.get("fecha_fin") or ""),
            "numero_cuenta":       header.get("numero_cuenta"),
            "texto_extraido":      text[:500] + "..." if len(text) > 500 else text,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OCR error ({fname}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error OCR: {str(e)}")

@router.post("/conciliacion/sesion")
def crear_sesion(req: UploadSession, request: Request, db: Session = Depends(_get_db)):
    """
    Crea una sesión de conciliación (sin transacciones aún).
    Devuelve el recon_id para agregar transacciones después.

    SEGURIDAD: tenant_id se extrae del JWT — nunca del body.
    Impide que un tenant cree sesiones bajo otro tenant.
    """
    import uuid

    # ─ Extraer tenant_id del JWT (misma lógica que toda la app) ──────────
    tenant_id = _get_tenant(request)

    try:
        recon_id = str(uuid.uuid4())
        db.execute(text("""
            INSERT INTO bank_reconciliation
              (id, tenant_id, period, banco, account_code,
               saldo_inicial, saldo_final, estado)
            VALUES
              (:id, :tenant_id, :period, :banco, :account_code,
               :saldo_inicial, :saldo_final, 'PENDIENTE')
        """), {
            "id":           recon_id,
            "tenant_id":    tenant_id,
            "period":       req.period,
            "banco":        req.banco,
            "account_code": req.account_code,
            "saldo_inicial": req.saldo_inicial,
            "saldo_final":   req.saldo_final,
        })
        db.commit()
        logger.info(f"✅ Sesión creada recon_id={recon_id} tenant={tenant_id}")
        return {"ok": True, "recon_id": recon_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creando sesión: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Historial de sesiones (consultable, no efímero) ──────────────────────────

@router.get("/conciliacion/sesiones")
def list_sesiones(request: Request, db: Session = Depends(_get_db)):
    """
    Lista todas las sesiones de conciliación del tenant autenticado.
    Ordenadas por fecha descendente — consultables en cualquier momento.

    SEGURIDAD: tenant_id del JWT, nunca del body.
    """
    tenant_id = _get_tenant(request)
    rows = db.execute(text("""
        SELECT id, banco, period, account_code,
               saldo_inicial, saldo_final, estado, score_riesgo,
               created_at,
               (SELECT COUNT(*) FROM bank_transactions bt WHERE bt.recon_id = br.id) AS n_txns,
               (SELECT COUNT(*) FROM bank_transactions bt
                WHERE bt.recon_id = br.id AND bt.match_estado = 'CON_FE') AS n_con_fe,
               (SELECT COUNT(*) FROM bank_transactions bt
                WHERE bt.recon_id = br.id AND bt.match_estado = 'SIN_FE') AS n_sin_fe
        FROM bank_reconciliation br
        WHERE tenant_id = :tid
        ORDER BY created_at DESC
        LIMIT 50
    """), {"tid": tenant_id}).fetchall()
    return {"sesiones": [dict(r._mapping) for r in rows]}


@router.get("/conciliacion/sesion/{recon_id}/detalle")
def get_sesion_detalle(recon_id: str, request: Request, db: Session = Depends(_get_db)):
    """
    Devuelve el detalle completo de una sesión: cabecera + todas sus transacciones.
    Permite consultar resultados de análisis previos sin re-subir el PDF.

    SEGURIDAD: verifica que el recon_id pertenece al tenant del JWT.
    """
    tenant_id = _get_tenant(request)

    sesion = db.execute(text(
        "SELECT * FROM bank_reconciliation WHERE id = :id AND tenant_id = :tid"
    ), {"id": recon_id, "tid": tenant_id}).fetchone()

    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada o sin acceso")

    txns = db.execute(text("""
        SELECT id, fecha, descripcion, monto, tipo, moneda, telefono,
               match_estado, beneficiario_nombre, beneficiario_categoria,
               tiene_fe, fe_numero, iva_estimado, base_estimada, tarifa_iva,
               d270_codigo, accion, score_puntos
        FROM bank_transactions
        WHERE recon_id = :id
        ORDER BY fecha, tipo DESC
    """), {"id": recon_id}).fetchall()

    return {
        "sesion":       dict(sesion._mapping),
        "transacciones": [dict(r._mapping) for r in txns],
        "total":        len(txns),
    }



class BulkTransactionItem(BaseModel):
    fecha: str
    descripcion: str
    monto: float
    tipo: str                          # 'CR' | 'DB'
    moneda: Optional[str] = "CRC"
    telefono: Optional[str] = None
    monto_orig_usd: Optional[float] = None
    tc_bccr: Optional[float] = None

class BulkTransactionRequest(BaseModel):
    transactions: list[BulkTransactionItem]


@router.post("/conciliacion/sesion/{recon_id}/transactions")
def bulk_insert_transactions(
    recon_id: str,
    req:     BulkTransactionRequest,
    request: Request,
    db:      Session = Depends(_get_db),
):
    """
    Inserta las transacciones bancarias del período en una sesión de conciliación.

    SEGURIDAD: valida que el recon_id pertenece al tenant autenticado.
    Permite reemplazar transacciones previas (DELETE + INSERT) para re-cargas.

    Body: { "transactions": [ {fecha, descripcion, monto, tipo, moneda?, telefono?}, ... ] }
    """
    import uuid as uuid_lib

    tenant_id = _get_tenant(request)

    # Verificar que la sesión pertenece al tenant
    row = db.execute(text(
        "SELECT tenant_id FROM bank_reconciliation WHERE id = :id"
    ), {"id": recon_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    if row.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    try:
        from services.conciliacion.beneficiario_extractor import extraer_beneficiario

        # Limpiar txns anteriores de esta sesión (permite re-cargas)
        db.execute(text(
            "DELETE FROM bank_transactions WHERE recon_id = :id"
        ), {"id": recon_id})

        # Insertar todas las transacciones
        for txn in req.transactions:
            # Extraer beneficiario en tiempo de inserción (sin DB extra, función pura)
            benef = extraer_beneficiario(txn.descripcion, txn.telefono)

            db.execute(text("""
                INSERT INTO bank_transactions
                  (id, recon_id, tenant_id, fecha, descripcion, monto, tipo,
                   moneda, telefono, monto_orig_usd, tc_bccr, match_estado,
                   beneficiario_nombre, beneficiario_telefono_norm, beneficiario_categoria)
                VALUES
                  (:id, :recon_id, :tenant_id, :fecha, :descripcion, :monto, :tipo,
                   :moneda, :telefono, :monto_orig_usd, :tc_bccr, 'PENDIENTE',
                   :bnom, :btel, :bcat)
            """), {
                "id":           str(uuid_lib.uuid4()),
                "recon_id":     recon_id,
                "tenant_id":    tenant_id,
                "fecha":        txn.fecha,
                "descripcion":  txn.descripcion,
                "monto":        txn.monto,
                "tipo":         txn.tipo,
                "moneda":       txn.moneda or "CRC",
                "telefono":     txn.telefono,
                "monto_orig_usd": txn.monto_orig_usd,
                "tc_bccr":      txn.tc_bccr,
                "bnom":         benef["nombre_norm"],
                "btel":         benef["telefono_norm"],
                "bcat":         benef["categoria"],
            })

        db.commit()
        logger.info(f"✅ {len(req.transactions)} txns insertadas en recon_id={recon_id} (con beneficiario)")
        return {
            "ok": True,
            "recon_id":     recon_id,
            "total_insertadas": len(req.transactions),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk-insert txns: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@router.post("/conciliacion/match/{recon_id}")
def run_match(recon_id: str, db: Session = Depends(_get_db)):
    """
    Corre el motor de matching para una sesión de conciliación.

    Estrategia en dos capas:
    1. Primero cruza contra FE emitidas/recibidas del sistema (comprobante fiscal real)
    2. Fallback: cruza contra asientos POSTED del Libro Diario
    3. También clasifica automáticamente BANK_FEE/BANK_INTEREST (siempre CON_FE)

    Estados resultantes:
      CON_FE      → tiene FE o es cargo bancario (comprobado fiscalmente)
      SIN_FE      → sin comprobante → riesgo fiscal
      PROBABLE    → posible match en libros (confianza media)
      SOLO_LIBROS → en libros pero no en banco (cheques pendientes)
    """
    from services.conciliacion.reconciliation_engine import (
        match_transactions, find_solo_libros, calcular_diferencia_saldo
    )

    # Obtener sesión
    row = db.execute(text(
        "SELECT tenant_id, period, banco, account_code, saldo_final FROM bank_reconciliation WHERE id = :id"
    ), {"id": recon_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    tenant_id, period, banco, account_code, saldo_final_banco = row
    year, month = period[:4], period[4:6]
    period_fmt = f"{year}-{month}"

    # ── Capa 1: transacciones del banco ───────────────────────────────────────
    bank_txns = [dict(r._mapping) for r in db.execute(text(
        "SELECT * FROM bank_transactions WHERE recon_id = :id ORDER BY fecha"
    ), {"id": recon_id}).fetchall()]

    # ── Capa 2: FE emitidas del período (ingresos con comprobante) ─────────────
    # try/except: si journal_entries no tiene las columnas esperadas → vacío
    try:
        fe_emitidas = [dict(r._mapping) for r in db.execute(text("""
            SELECT je.id, je.date::text AS fecha,
                   COALESCE(SUM(jl.credit), 0) AS monto,
                   je.source, je.description
            FROM journal_entries je
            JOIN journal_lines jl ON jl.entry_id = je.id
            WHERE je.tenant_id = :tid
              AND je.period     = :period
              AND je.source    IN ('FE', 'TE', 'NC', 'ND')
              AND je.status     = 'POSTED'
            GROUP BY je.id, je.date, je.source, je.description
            HAVING COALESCE(SUM(jl.credit), 0) > 0
        """), {"tid": tenant_id, "period": period_fmt}).fetchall()]
        db.rollback()   # limpia la transacción fallida si la hubo
    except Exception as e_fe:
        logger.warning(f"⚠️  FE emitidas no disponibles: {e_fe}")
        db.rollback()
        fe_emitidas = []

    # ── Capa 3: FE recibidas del período (gastos con comprobante) ─────────────
    # try/except: la tabla 'recibidos' puede no existir en todos los tenants
    try:
        fe_recibidas = [dict(r._mapping) for r in db.execute(text("""
            SELECT id, fecha::text AS fecha, monto_total AS monto,
                   emisor_nombre AS description
            FROM recibidos
            WHERE tenant_id = :tid
              AND DATE_TRUNC('month', fecha) = DATE(:period || '-01')
        """), {"tid": tenant_id, "period": period_fmt}).fetchall()]
        db.rollback()
    except Exception as e_rec:
        logger.warning(f"⚠️  FE recibidas no disponibles: {e_rec}")
        db.rollback()
        fe_recibidas = []

    # ── Capa 4: asientos del Libro Diario (fallback) ──────────────────────────
    journal_lines = [dict(r._mapping) for r in db.execute(text("""
        SELECT je.id, je.description, jl.debit, jl.credit, jl.account_code,
               je.date::text AS date
        FROM journal_entries je
        JOIN journal_lines jl ON jl.entry_id = je.id
        WHERE je.tenant_id = :tenant_id
          AND je.period     = :period
          AND je.status     = 'POSTED'
          AND jl.account_code = :account_code
    """), {
        "tenant_id":    tenant_id,
        "period":       period_fmt,
        "account_code": account_code,
    }).fetchall()]

    # ──────────────────────────────────────────────────────────────────────────
    # ALGORITMO CORRECTO DE MATCHING (Regla de negocio)
    # ──────────────────────────────────────────────────────────────────────────
    # MÁXIMA: una txn bancaria es CON_FE SOLO SI existe un asiento (debit/credit)
    # en el Libro Diario para la cuenta bancaria con:
    #   1. Misma fecha exacta
    #   2. Monto que coincide ±2%  (debit=DB, credit=CR)
    #   3. Descripción con al menos 1 token significativo en común
    #
    # Si el asiento existe y su source es FE/TE/NC/ND → CON_FE
    # Si el asiento existe pero source MANUAL/otro      → PROBABLE
    # Si NO existe asiento                              → SIN_FE (siempre)
    # ──────────────────────────────────────────────────────────────────────────

    FUENTES_FE = {'FE', 'TE', 'NC', 'ND'}
    TOLERANCIA = 0.02   # ±2% de diferencia de monto

    # Cargamos TODOS los asientos POSTED del período para esta cuenta bancaria
    # incluyendo el source del journal_entry para saber si tiene FE
    asientos_periodo = [dict(r._mapping) for r in db.execute(text("""
        SELECT je.id AS entry_id, je.date::text AS fecha, je.description AS desc_asiento,
               je.source, jl.debit, jl.credit, jl.account_code
        FROM journal_entries je
        JOIN journal_lines jl ON jl.entry_id = je.id
        WHERE je.tenant_id    = :tenant_id
          AND je.period       = :period
          AND je.status       = 'POSTED'
          AND jl.account_code = :account_code
        ORDER BY je.date
    """), {
        "tenant_id":    tenant_id,
        "period":       period_fmt,
        "account_code": account_code,
    }).fetchall()]

    def _tokens(s: str) -> set:
        """Extrae tokens significativos (len>2, solo alfanuméricos)."""
        import re
        return {t.upper() for t in re.split(r'[\s/\-_.,]+', str(s or '')) if len(t) > 2}

    def _descriptions_match(bank_desc: str, asiento_desc: str) -> bool:
        """True si las descripciones comparten al menos 1 token significativo."""
        t1 = _tokens(bank_desc)
        t2 = _tokens(asiento_desc)
        # Excluir tokens muy genéricos que aparecen en todos lados
        STOP = {'DEL', 'LAS', 'LOS', 'CON', 'POR', 'PAGO', 'TXN', 'TRANS', 'BANCO', 'BNCR'}
        t1 -= STOP
        t2 -= STOP
        return bool(t1 & t2)

    usados_asientos: set = set()  # entry_id ya usados (1-a-1)

    for txn in bank_txns:
        txn_fecha = str(txn.get("fecha", ""))[:10]    # YYYY-MM-DD
        txn_monto = abs(float(txn.get("monto", 0)))
        txn_tipo  = txn.get("tipo", "DB")              # CR=crédito en banco, DB=débito
        txn_desc  = str(txn.get("descripcion", ""))

        best_asiento  = None
        best_diff     = 1.0
        best_conf     = 0.0

        for asi in asientos_periodo:
            # 1. Fecha exacta
            if str(asi["fecha"])[:10] != txn_fecha:
                continue

            # 2. Monto ±2% en el lado correcto (CR banco → credit del asiento, etc.)
            if txn_tipo == "CR":
                asi_monto = float(asi.get("credit", 0) or 0)
            else:
                asi_monto = float(asi.get("debit",  0) or 0)

            if asi_monto <= 0:
                continue

            diff = abs(txn_monto - asi_monto) / max(asi_monto, 1)
            if diff > TOLERANCIA:
                continue

            # 3. Descripción: al menos 1 token en común (secundario / mejora confianza)
            desc_ok = _descriptions_match(txn_desc, asi.get("desc_asiento", ""))
            conf    = round((1.0 - diff) * 100, 1)
            if desc_ok:
                conf = min(conf + 10, 100.0)  # bonus si la descripción concuerda

            # Preferir el asiento con mejor ajuste de monto
            if diff < best_diff and asi["entry_id"] not in usados_asientos:
                best_diff    = diff
                best_conf    = conf
                best_asiento = asi

        if best_asiento:
            usados_asientos.add(best_asiento["entry_id"])
            tiene_fe = best_asiento["source"] in FUENTES_FE
            txn["match_estado"]    = "CON_FE"    if tiene_fe else "PROBABLE"
            txn["match_confianza"] = best_conf
            txn["tiene_fe"]        = tiene_fe
            txn["fe_numero"]       = best_asiento["entry_id"] if tiene_fe else None
        else:
            # SIN asiento en libros → SIN FE siempre (regla de negocio estricta)
            txn["match_estado"]    = "SIN_FE"
            txn["match_confianza"] = 0.0
            txn["tiene_fe"]        = False
            txn["fe_numero"]       = None


    # ── Solo libros ───────────────────────────────────────────────────────────
    solo = find_solo_libros(bank_txns, journal_lines)

    # ── Saldo en libros: real desde journal_lines ─────────────────────────────
    saldo_libros_row = db.execute(text("""
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE jl.tenant_id    = :tenant_id
          AND jl.account_code = :account_code
          AND je.period       = :period
          AND je.status       = 'POSTED'
    """), {
        "tenant_id": tenant_id, "account_code": account_code, "period": period_fmt
    }).scalar() or 0.0
    saldo_libros = float(saldo_libros_row)

    diff = calcular_diferencia_saldo(float(saldo_final_banco or 0), saldo_libros)

    # ── Persistir estados en bank_transactions ────────────────────────────────
    for txn in bank_txns:
        db.execute(text("""
            UPDATE bank_transactions
            SET match_estado = :estado, match_confianza = :conf,
                tiene_fe = :tfe, fe_numero = :fnum
            WHERE id = :id
        """), {
            "estado": txn["match_estado"],
            "conf":   txn.get("match_confianza", 0),
            "tfe":    txn.get("tiene_fe", False),
            "fnum":   txn.get("fe_numero"),
            "id":     txn["id"],
        })
    db.commit()

    con_fe_count = sum(1 for t in bank_txns if t["match_estado"] == "CON_FE")
    stats = {
        "con_fe":       con_fe_count,
        "conciliados":  con_fe_count,   # alias retrocompatible
        "sin_fe":       sum(1 for t in bank_txns if t["match_estado"] == "SIN_FE"),
        "probable":     sum(1 for t in bank_txns if t["match_estado"] == "PROBABLE"),
        "solo_libros":  len(solo),
        "total_banco":  len(bank_txns),
        "fe_usadas":    len(usados_asientos),   # asientos del Libro Diario que hicieron match
    }

    return {
        "ok":           True,
        "recon_id":     recon_id,

        "stats":        stats,
        "saldo_diff":   diff,
        "solo_libros":  solo[:20],
    }


# ── Endpoints CENTINELA ──────────────────────────────────────────────────────

@router.post("/centinela/analyze/{recon_id}")
def run_centinela(recon_id: str, db: Session = Depends(_get_db)):
    """
    Corre el análisis CENTINELA completo para una sesión de conciliación.

    Pasos:
    1. Detecta txns SIN_FE (riesgo fiscal real, ya no SIN_ASIENTO vacío)
    2. Aplica tarifa IVA semántica correcta por transacción (Ley 9635)
    3. Clasifica fugas A/B/C y calcula score
    4. Acumula datos en bank_counterparties (cross-meses)
    5. Detecta beneficiarios que superan umbral D-150 (>₡1,000,000 anuales)
    """
    from services.conciliacion.fiscal_engine import (
        clasificar_fuga, calcular_score, estimar_tarifa, calcular_iva_incluido
    )
    from services.conciliacion.reconciliation_engine import calcular_diferencia_saldo

    row = db.execute(text(
        "SELECT tenant_id, period, saldo_final FROM bank_reconciliation WHERE id = :id"
    ), {"id": recon_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    tenant_id, period, saldo_final_banco = row
    year, month = period[:4], period[4:6]
    period_fmt = f"{year}-{month}"

    # ── Paso 1: transacciones SIN_FE → riesgo fiscal real ─────────────────────
    sin_match = [dict(r._mapping) for r in db.execute(text("""
        SELECT * FROM bank_transactions
        WHERE recon_id = :id AND match_estado IN ('SIN_FE', 'SIN_ASIENTO', 'SOLO_LIBROS')
    """), {"id": recon_id}).fetchall()]

    # ── FE emitidas del período ────────────────────────────────────────────────
    fe_emitidas = [dict(r._mapping) for r in db.execute(text("""
        SELECT * FROM journal_entries
        WHERE tenant_id = :tid AND period = :period
          AND source IN ('FE', 'TE', 'NC', 'ND') AND status = 'POSTED'
    """), {"tid": tenant_id, "period": period_fmt}).fetchall()]

    fe_recibidas = []  # FE recibidas módulo (fase futura)

    # ── Paso 2: clasificar fugas con tarifa IVA semántica ─────────────────────
    fugas = []
    for txn in sin_match:
        desc = txn.get("descripcion", "")
        cat  = txn.get("beneficiario_categoria", "TERCERO")

        # Aplicar tarifa correcta por Ley 9635 ANTES de calcular IVA
        tarifa = estimar_tarifa(desc, cat)
        calc   = calcular_iva_incluido(float(txn.get("monto", 0)), tarifa)

        fuga = clasificar_fuga(txn, fe_emitidas, fe_recibidas)
        if fuga:
            fuga["txn_id"]          = txn["id"]
            fuga["txn_descripcion"] = desc
            fuga["txn_monto"]       = float(txn.get("monto", 0))
            fuga["txn_fecha"]       = str(txn.get("fecha", ""))
            # Sobrescribir con IVA calculado con tarifa semántica correcta
            fuga["iva_riesgo"]      = calc["iva"]
            fuga["base_riesgo"]     = calc["base"]
            fugas.append(fuga)

            db.execute(text("""
                UPDATE bank_transactions
                SET fuga_tipo = :ft, score_puntos = :sp, iva_estimado = :iva,
                    base_estimada = :base, d270_codigo = :d270, accion = :accion,
                    tarifa_iva = :tarifa
                WHERE id = :id
            """), {
                "ft":     fuga.get("fuga_tipo"),
                "sp":     fuga.get("score_pts", 0),
                "iva":    calc["iva"],
                "base":   calc["base"],
                "d270":   fuga.get("d270_codigo"),
                "accion": fuga.get("accion"),
                "tarifa": int(tarifa * 100),
                "id":     txn["id"],
            })

    # ── Paso 3: score fiscal ───────────────────────────────────────────────────
    total_fe_monto = sum(float(fe.get("total_amount", 0) or 0) for fe in fe_emitidas)
    ingresos_banco = sum(
        float(r[0]) for r in db.execute(text(
            "SELECT monto FROM bank_transactions WHERE recon_id = :id AND tipo = 'CR'"
        ), {"id": recon_id}).fetchall()
    )

    # Saldo real en libros (NO hardcodeado a 0)
    saldo_libros = float(db.execute(text("""
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE jl.tenant_id = :tid AND je.period = :period AND je.status = 'POSTED'
    """), {"tid": tenant_id, "period": period_fmt}).scalar() or 0)

    diff   = calcular_diferencia_saldo(float(saldo_final_banco or 0), saldo_libros)
    result = calcular_score(fugas, diff, ingresos_banco, total_fe_monto)

    # ── Paso 4: acumular en bank_counterparties (cross-meses) ─────────────────
    all_txns = [dict(r._mapping) for r in db.execute(text(
        "SELECT * FROM bank_transactions WHERE recon_id = :id"
    ), {"id": recon_id}).fetchall()]

    from collections import defaultdict
    por_beneficiario: dict[str, dict] = defaultdict(lambda: {
        "debitos": 0.0, "creditos": 0.0, "n": 0, "tel": None, "cat": "TERCERO"
    })
    for txn in all_txns:
        bnom = txn.get("beneficiario_nombre") or "DESCONOCIDO"
        bcat = txn.get("beneficiario_categoria", "TERCERO")
        if bcat in ("BANK_FEE", "BANK_INTEREST"):
            continue   # No acumular cargos bancarios en counterparties
        por_beneficiario[bnom]["n"]        += 1
        por_beneficiario[bnom]["tel"]       = txn.get("beneficiario_telefono_norm") or por_beneficiario[bnom]["tel"]
        por_beneficiario[bnom]["cat"]       = bcat
        if txn.get("tipo") == "DB":
            por_beneficiario[bnom]["debitos"]  += float(txn.get("monto", 0))
        else:
            por_beneficiario[bnom]["creditos"] += float(txn.get("monto", 0))

    # Año para umbral D-150
    year_str = period[:4]

    for nombre, datos in por_beneficiario.items():
        # Suma anual existente para umbral D-150
        existing_anual = db.execute(text("""
            SELECT COALESCE(d150_monto_anual, 0)
            FROM bank_counterparties
            WHERE tenant_id = :tid AND nombre_norm = :nom
        """), {"tid": tenant_id, "nom": nombre}).scalar() or 0.0

        monto_nuevo_anual = float(existing_anual) + datos["debitos"] + datos["creditos"]
        d150_flag = monto_nuevo_anual >= 1_000_000.0

        db.execute(text("""
            INSERT INTO bank_counterparties
              (tenant_id, nombre_norm, telefono, categoria,
               total_debitos, total_creditos, n_transacciones,
               primer_periodo, ultimo_periodo,
               d150_monto_anual, d150_flag, updated_at)
            VALUES
              (:tid, :nom, :tel, :cat,
               :deb, :cred, :n,
               :period, :period,
               :d150a, :d150f, NOW())
            ON CONFLICT (tenant_id, nombre_norm)
            DO UPDATE SET
              total_debitos    = bank_counterparties.total_debitos + :deb,
              total_creditos   = bank_counterparties.total_creditos + :cred,
              n_transacciones  = bank_counterparties.n_transacciones + :n,
              ultimo_periodo   = :period,
              d150_monto_anual = bank_counterparties.d150_monto_anual + :deb + :cred,
              d150_flag        = :d150f,
              telefono         = COALESCE(bank_counterparties.telefono, :tel),
              updated_at       = NOW()
        """), {
            "tid": tenant_id, "nom": nombre, "tel": datos["tel"],
            "cat": datos["cat"], "deb": datos["debitos"], "cred": datos["creditos"],
            "n": datos["n"], "period": period,
            "d150a": monto_nuevo_anual, "d150f": d150_flag,
        })

    # ── Guardar score en centinela_score ──────────────────────────────────────
    db.execute(text("""
        INSERT INTO centinela_score
          (tenant_id, period, score_total, fugas_tipo_a, fugas_tipo_b, fugas_tipo_c,
           exposicion_iva, exposicion_renta, exposicion_total, d270_regs, score_detalle)
        VALUES
          (:tenant_id, :period, :score, :a, :b, :c, :iva, :renta, :total, :d270, CAST(:det AS JSONB))
        ON CONFLICT (tenant_id, period)
        DO UPDATE SET
          score_total = EXCLUDED.score_total, fugas_tipo_a = EXCLUDED.fugas_tipo_a,
          fugas_tipo_b = EXCLUDED.fugas_tipo_b, fugas_tipo_c = EXCLUDED.fugas_tipo_c,
          exposicion_iva = EXCLUDED.exposicion_iva, d270_regs = EXCLUDED.d270_regs,
          score_detalle = EXCLUDED.score_detalle
    """), {
        "tenant_id": tenant_id, "period": period,
        "score": result["score_total"],
        "a": result["fugas_tipo_a"], "b": result["fugas_tipo_b"], "c": result["fugas_tipo_c"],
        "iva": result["exposicion_iva"], "renta": result["exposicion_renta"],
        "total": result["exposicion_total"], "d270": result["d270_regs"],
        "det": str({"detalle": result["detalle"]}),
    })

    db.execute(text(
        "UPDATE bank_reconciliation SET score_riesgo = :s, estado = 'ANALIZADO' WHERE id = :id"
    ), {"s": result["score_total"], "id": recon_id})
    db.commit()

    return {
        "ok":       True,
        "recon_id": recon_id,
        "score":    result,
        "fugas":    fugas,
        "saldo_diff": diff,
        "n_counterparties_actualizados": len(por_beneficiario),
    }



# ─────────────────────────────────────────────────────────────────────────────
# CENTINELA CONSOLIDADO POR PERÍODO (multi-cuenta)
# Análisis fiscal de TODAS las cuentas bancarias de un período en una pasada.
# Rule #1 (Safe Fallback): si una cuenta falla, se omite y se continúa.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/centinela/analyze-period/{period}")
def run_centinela_period(period: str, request: Request, db: Session = Depends(_get_db)):
    """
    Corre CENTINELA consolidado sobre TODAS las cuentas del período.

    A diferencia de /centinela/analyze/{recon_id} (por sesión), este endpoint:
    1. Localiza todos los bank_reconciliation del tenant para el período dado.
    2. Lee bank_transactions SIN_FE de TODAS esas sesiones juntas.
    3. Corre el análisis fiscal unificado (tarifa, clasificación, score).
    4. Persiste el score en centinela_score (UPSERT por period).
    5. Actualiza score_riesgo + estado='ANALIZADO' en cada bank_reconciliation.

    Retorna score consolidado + fugas + breakdown por cuenta.
    """
    from services.conciliacion.fiscal_engine import (
        clasificar_fuga, calcular_score, estimar_tarifa, calcular_iva_incluido
    )
    from services.conciliacion.reconciliation_engine import calcular_diferencia_saldo
    from collections import defaultdict

    tenant_id   = _get_tenant(request)
    year        = period[:4]
    month       = period[4:6] if len(period) >= 6 else "01"
    period_fmt  = f"{year}-{month}"

    # ── 1. Todos los recon_ids del tenant para este período ───────────────────
    # bank_reconciliation guarda period en formato 'YYYY-MM' (con guión)
    # pero el endpoint recibe 'YYYYMM' → normalizamos ambos
    sesiones_rows = db.execute(text("""
        SELECT id, banco, account_code, saldo_final
        FROM bank_reconciliation
        WHERE tenant_id = :tid
          AND (period = :period OR period = :period_fmt)
        ORDER BY created_at DESC
    """), {"tid": tenant_id, "period": period, "period_fmt": period_fmt}).fetchall()

    if not sesiones_rows:
        raise HTTPException(status_code=404,
            detail=f"No hay sesiones de conciliación para el período {period}")


    sesiones   = [dict(r._mapping) for r in sesiones_rows]
    recon_ids  = [s["id"] for s in sesiones]
    logger.info(f"🔬 CENTINELA period={period} — {len(recon_ids)} sesiones")

    # ── 2. Leer SIN_FE + todas las txns de cada sesión (Safe Fallback) ────────
    sin_match_all: list[dict] = []
    all_txns_all:  list[dict] = []
    cuentas_procesadas = []
    cuentas_fallidas   = []

    for sesion in sesiones:
        rid = sesion["id"]
        try:
            sin_fe = [dict(r._mapping) for r in db.execute(text("""
                SELECT * FROM bank_transactions
                WHERE recon_id = :id
                  AND match_estado IN ('SIN_FE', 'SIN_ASIENTO', 'SOLO_LIBROS')
            """), {"id": rid}).fetchall()]
            all_txns = [dict(r._mapping) for r in db.execute(text(
                "SELECT * FROM bank_transactions WHERE recon_id = :id"
            ), {"id": rid}).fetchall()]
            sin_match_all.extend(sin_fe)
            all_txns_all.extend(all_txns)
            cuentas_procesadas.append({
                "recon_id": rid, "banco": sesion.get("banco"),
                "account_code": sesion.get("account_code"),
                "sin_fe": len(sin_fe), "total_txns": len(all_txns),
            })
        except Exception as e_sess:
            logger.warning(f"⚠️  Sesión {rid} omitida: {e_sess}")
            db.rollback()
            cuentas_fallidas.append({"recon_id": rid, "error": str(e_sess)})

    # ── 3. FE emitidas del período ────────────────────────────────────────────
    try:
        fe_emitidas = [dict(r._mapping) for r in db.execute(text("""
            SELECT * FROM journal_entries
            WHERE tenant_id = :tid AND period = :period
              AND source IN ('FE', 'TE', 'NC', 'ND') AND status = 'POSTED'
        """), {"tid": tenant_id, "period": period_fmt}).fetchall()]
    except Exception:
        db.rollback()
        fe_emitidas = []

    fe_recibidas: list = []

    # ── 4. Clasificar fugas (todas las cuentas juntas) ────────────────────────
    fugas = []
    for txn in sin_match_all:
        desc   = txn.get("descripcion", "")
        cat    = txn.get("beneficiario_categoria", "TERCERO")
        tarifa = estimar_tarifa(desc, cat)
        calc   = calcular_iva_incluido(float(txn.get("monto", 0)), tarifa)
        fuga   = clasificar_fuga(txn, fe_emitidas, fe_recibidas)
        if not fuga:
            continue
        fuga.update({
            "txn_id": txn["id"], "txn_descripcion": desc,
            "txn_monto": float(txn.get("monto", 0)),
            "txn_fecha": str(txn.get("fecha", "")),
            "iva_riesgo": calc["iva"], "base_riesgo": calc["base"],
        })
        fugas.append(fuga)
        try:
            db.execute(text("""
                UPDATE bank_transactions
                SET fuga_tipo=:ft, score_puntos=:sp, iva_estimado=:iva,
                    base_estimada=:base, d270_codigo=:d270, accion=:accion, tarifa_iva=:tarifa
                WHERE id=:id
            """), {
                "ft": fuga.get("fuga_tipo"), "sp": fuga.get("score_pts", 0),
                "iva": calc["iva"], "base": calc["base"],
                "d270": fuga.get("d270_codigo"), "accion": fuga.get("accion"),
                "tarifa": int(tarifa * 100), "id": txn["id"],
            })
        except Exception as e_upd:
            logger.warning(f"⚠️  txn {txn.get('id')}: {e_upd}")
            db.rollback()

    # ── 5. Score consolidado ──────────────────────────────────────────────────
    total_fe_monto = sum(float(fe.get("total_amount", 0) or 0) for fe in fe_emitidas)
    ingresos_banco = sum(float(t.get("monto", 0)) for t in all_txns_all if t.get("tipo") == "CR")
    try:
        saldo_libros = float(db.execute(text("""
            SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id
            WHERE jl.tenant_id=:tid AND je.period=:p AND je.status='POSTED'
        """), {"tid": tenant_id, "p": period_fmt}).scalar() or 0)
    except Exception:
        db.rollback()
        saldo_libros = 0.0

    saldo_final_total = sum(float(s.get("saldo_final") or 0) for s in sesiones)
    diff   = calcular_diferencia_saldo(saldo_final_total, saldo_libros)
    result = calcular_score(fugas, diff, ingresos_banco, total_fe_monto)

    # ── 6. Acumular bank_counterparties ───────────────────────────────────────
    por_beneficiario: dict = defaultdict(lambda: {
        "debitos": 0.0, "creditos": 0.0, "n": 0, "tel": None, "cat": "TERCERO"
    })
    for txn in all_txns_all:
        bnom = txn.get("beneficiario_nombre") or "DESCONOCIDO"
        bcat = txn.get("beneficiario_categoria", "TERCERO")
        if bcat in ("BANK_FEE", "BANK_INTEREST"):
            continue
        por_beneficiario[bnom]["n"] += 1
        por_beneficiario[bnom]["tel"] = txn.get("beneficiario_telefono_norm") or por_beneficiario[bnom]["tel"]
        por_beneficiario[bnom]["cat"] = bcat
        if txn.get("tipo") == "DB":
            por_beneficiario[bnom]["debitos"]  += float(txn.get("monto", 0))
        else:
            por_beneficiario[bnom]["creditos"] += float(txn.get("monto", 0))

    for nombre, datos in por_beneficiario.items():
        try:
            ea = db.execute(text(
                "SELECT COALESCE(d150_monto_anual,0) FROM bank_counterparties WHERE tenant_id=:t AND nombre_norm=:n"
            ), {"t": tenant_id, "n": nombre}).scalar() or 0.0
            nuevo_anual = float(ea) + datos["debitos"] + datos["creditos"]
            db.execute(text("""
                INSERT INTO bank_counterparties
                  (tenant_id, nombre_norm, telefono, categoria, total_debitos, total_creditos,
                   n_transacciones, primer_periodo, ultimo_periodo, d150_monto_anual, d150_flag, updated_at)
                VALUES (:t,:n,:tel,:cat,:deb,:cred,:cnt,:p,:p,:d150a,:d150f,NOW())
                ON CONFLICT (tenant_id, nombre_norm) DO UPDATE SET
                  total_debitos=bank_counterparties.total_debitos+:deb,
                  total_creditos=bank_counterparties.total_creditos+:cred,
                  n_transacciones=bank_counterparties.n_transacciones+:cnt,
                  ultimo_periodo=:p, d150_monto_anual=bank_counterparties.d150_monto_anual+:deb+:cred,
                  d150_flag=:d150f, telefono=COALESCE(bank_counterparties.telefono,:tel), updated_at=NOW()
            """), {
                "t": tenant_id, "n": nombre, "tel": datos["tel"], "cat": datos["cat"],
                "deb": datos["debitos"], "cred": datos["creditos"], "cnt": datos["n"],
                "p": period, "d150a": nuevo_anual, "d150f": nuevo_anual >= 1_000_000.0,
            })
        except Exception as e_cp:
            logger.warning(f"⚠️  counterparty {nombre}: {e_cp}")
            db.rollback()

    # ── 7. Guardar score + marcar sesiones ────────────────────────────────────
    try:
        db.execute(text("""
            INSERT INTO centinela_score
              (tenant_id, period, score_total, fugas_tipo_a, fugas_tipo_b, fugas_tipo_c,
               exposicion_iva, exposicion_renta, exposicion_total, d270_regs, score_detalle)
            VALUES (:tid,:period,:score,:a,:b,:c,:iva,:renta,:total,:d270,CAST(:det AS JSONB))
            ON CONFLICT (tenant_id, period) DO UPDATE SET
              score_total=EXCLUDED.score_total, fugas_tipo_a=EXCLUDED.fugas_tipo_a,
              fugas_tipo_b=EXCLUDED.fugas_tipo_b, fugas_tipo_c=EXCLUDED.fugas_tipo_c,
              exposicion_iva=EXCLUDED.exposicion_iva, d270_regs=EXCLUDED.d270_regs,
              score_detalle=EXCLUDED.score_detalle
        """), {
            "tid": tenant_id, "period": period,
            "score": result["score_total"], "a": result["fugas_tipo_a"],
            "b": result["fugas_tipo_b"], "c": result["fugas_tipo_c"],
            "iva": result["exposicion_iva"], "renta": result["exposicion_renta"],
            "total": result["exposicion_total"], "d270": result["d270_regs"],
            "det": str({"cuentas": cuentas_procesadas, "detalle": result["detalle"]}),
        })
    except Exception as e_score:
        logger.warning(f"⚠️  centinela_score: {e_score}")
        db.rollback()

    for rid in recon_ids:
        try:
            db.execute(text(
                "UPDATE bank_reconciliation SET score_riesgo=:s, estado='ANALIZADO' WHERE id=:id"
            ), {"s": result["score_total"], "id": rid})
        except Exception:
            pass

    db.commit()

    return {
        "ok":               True,
        "period":           period,
        "score":            result,
        "fugas":            fugas,
        "saldo_diff":       diff,
        "cuentas_analizadas": cuentas_procesadas,
        "cuentas_fallidas": cuentas_fallidas,
        "total_sin_fe":     len(sin_match_all),
        "total_txns":       len(all_txns_all),
        "n_counterparties": len(por_beneficiario),
    }


@router.get("/centinela/beneficiarios")
def list_beneficiarios(request: Request, db: Session = Depends(_get_db)):
    """
    Lista todos los beneficiarios del tenant con acumulados históricos.
    Ordenados por total movido DESC — útil para detectar proveedores sin FE.

    SEGURIDAD: tenant_id del JWT, nunca del body.
    """
    tenant_id = _get_tenant(request)
    rows = db.execute(text("""
        SELECT nombre_norm, telefono, categoria,
               total_debitos, total_creditos,
               total_debitos + total_creditos AS total_movido,
               n_transacciones, primer_periodo, ultimo_periodo,
               d150_monto_anual, d150_flag, riesgo_nivel, updated_at
        FROM bank_counterparties
        WHERE tenant_id = :tid
        ORDER BY (total_debitos + total_creditos) DESC
        LIMIT 200
    """), {"tid": tenant_id}).fetchall()
    return {
        "beneficiarios": [dict(r._mapping) for r in rows],
        "d150_flagged":  sum(1 for r in rows if r.d150_flag),
    }


@router.get("/centinela/beneficiario/{nombre_norm}")
def get_beneficiario_detalle(nombre_norm: str, request: Request, db: Session = Depends(_get_db)):
    """
    Detalle período a período de un beneficiario específico.
    Muestra todas sus transacciones y evolución de montos.

    SEGURIDAD: tenant_id del JWT.
    """
    tenant_id = _get_tenant(request)

    resumen = db.execute(text(
        "SELECT * FROM bank_counterparties WHERE tenant_id = :tid AND nombre_norm = :nom"
    ), {"tid": tenant_id, "nom": nombre_norm.upper()}).fetchone()

    txns = db.execute(text("""
        SELECT bt.fecha, bt.monto, bt.tipo, bt.descripcion,
               bt.match_estado, bt.tiene_fe, bt.iva_estimado,
               bt.base_estimada, bt.tarifa_iva, br.period, br.banco
        FROM bank_transactions bt
        JOIN bank_reconciliation br ON br.id = bt.recon_id
        WHERE br.tenant_id = :tid
          AND bt.beneficiario_nombre = :nom
        ORDER BY bt.fecha DESC
        LIMIT 100
    """), {"tid": tenant_id, "nom": nombre_norm.upper()}).fetchall()

    return {
        "resumen": dict(resumen._mapping) if resumen else {},
        "transacciones": [dict(r._mapping) for r in txns],
        "total": len(txns),
    }


@router.get("/centinela/score/{period}")

def get_score(period: str, request: Request, db: Session = Depends(_get_db)):
    """Obtiene el score CENTINELA para un período YYYYMM.

    SEGURIDAD: solo devuelve datos del tenant autenticado.
    """
    tenant_id = _get_tenant(request)
    row = db.execute(text(
        "SELECT * FROM centinela_score "
        "WHERE tenant_id = :tenant_id AND period = :period "
        "ORDER BY created_at DESC LIMIT 1"
    ), {"tenant_id": tenant_id, "period": period}).fetchone()
    if not row:
        return {"period": period, "score_total": 0, "nivel": "SIN_DATOS"}
    return dict(row._mapping)


@router.get("/centinela/d270/{period}")
def get_d270_preview(period: str, request: Request, db: Session = Depends(_get_db)):
    """Retorna el preview del D-270 para el período dado.

    SEGURIDAD: solo devuelve partidas del tenant autenticado.
    """
    from services.conciliacion.fiscal_engine import generar_d270_resumen, D270_CODIGOS
    tenant_id = _get_tenant(request)

    year_d = period[:4]
    month_d = period[4:6] if len(period) >= 6 else "01"
    period_fmt_d = f"{year_d}-{month_d}"

    rows = db.execute(text("""
        SELECT bt.descripcion, bt.base_estimada AS monto, bt.d270_codigo,
               bt.accion AS observacion, br.period
        FROM bank_transactions bt
        JOIN bank_reconciliation br ON br.id = bt.recon_id
        WHERE br.tenant_id   = :tenant_id
          AND (br.period = :period OR br.period = :period_fmt)
          AND bt.d270_codigo IS NOT NULL
          AND bt.accion_tomada = FALSE
        ORDER BY bt.d270_codigo, bt.monto DESC
    """), {"tenant_id": tenant_id, "period": period, "period_fmt": period_fmt_d}).fetchall()

    items = [dict(r._mapping) for r in rows]
    resumen = generar_d270_resumen(items)

    return {
        "period":       period,
        "items":        items,
        "resumen":      resumen,
        "codigos_desc": D270_CODIGOS,
        "plazo_limite": f"Presentar antes del día 10 del mes siguiente",
    }



@router.get("/centinela/d270/{period}/export", response_class=PlainTextResponse)
def export_d270(period: str, db: Session = Depends(_get_db)):
    """Exporta el CSV del D-270 en formato Tribu-CR."""
    from services.conciliacion.fiscal_engine import generar_d270_csv

    rows = db.execute(text("""
        SELECT bt.base_estimada AS monto, bt.d270_codigo, bt.descripcion
        FROM bank_transactions bt
        JOIN bank_reconciliation br ON br.id = bt.recon_id
        WHERE br.period = :period AND bt.d270_codigo IS NOT NULL
    """), {"period": period}).fetchall()

    items = [dict(r._mapping) for r in rows]
    csv = generar_d270_csv("", "", "", period, items)
    return PlainTextResponse(
        content=csv,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=D270_{period}.csv"}
    )


# ── D-150 — Declaración informativa anual ────────────────────────────────────

@router.get("/centinela/d150/{year}")
def get_d150_preview(year: str, request: Request, db: Session = Depends(_get_db)):
    """
    Pre-forma D-150: beneficiarios con transacciones acumuladas ≥ ₡1,000,000 en el año.

    La D-150 es una declaración informativa anual (Formulario D-150) que deben
    presentar contribuyentes que paguen a un mismo proveedor/persona más de
    ₡1,000,000 en el año calendario.

    SEGURIDAD: tenant_id del JWT.
    """
    tenant_id = _get_tenant(request)

    rows = db.execute(text("""
        SELECT nombre_norm, telefono, categoria,
               total_debitos, total_creditos,
               d150_monto_anual,
               n_transacciones, primer_periodo, ultimo_periodo
        FROM bank_counterparties
        WHERE tenant_id = :tid
          AND d150_flag = TRUE
          AND d150_monto_anual >= 1000000
        ORDER BY d150_monto_anual DESC
    """), {"tid": tenant_id}).fetchall()

    partidas = []
    for r in rows:
        row = dict(r._mapping)
        row["cedula"] = "PENDIENTE"   # El usuario debe completar la cédula
        row["aviso"]  = "⚠️ Verifique cédula del beneficiario antes de presentar el D-150"
        partidas.append(row)

    return {
        "year":           year,
        "partidas":       partidas,
        "total_partidas": len(partidas),
        "umbral":         1_000_000,
        "moneda":         "CRC",
        "plazo_limite":   "Enero del año siguiente (consulte Hacienda para fecha exacta)",
        "nota":           "Las cédulas aparecen como PENDIENTE — complete antes de declarar",
    }


@router.get("/centinela/d150/{year}/export", response_class=PlainTextResponse)
def export_d150(year: str, request: Request, db: Session = Depends(_get_db)):
    """Exporta el D-150 pre-forma como CSV descargable."""
    tenant_id = _get_tenant(request)

    rows = db.execute(text("""
        SELECT nombre_norm, telefono, d150_monto_anual, n_transacciones
        FROM bank_counterparties
        WHERE tenant_id = :tid
          AND d150_flag = TRUE
          AND d150_monto_anual >= 1000000
        ORDER BY d150_monto_anual DESC
    """), {"tid": tenant_id}).fetchall()

    lines = ["beneficiario,cedula,telefono,monto_total_crc,n_transacciones,aviso"]
    for r in rows:
        row = dict(r._mapping)
        lines.append(
            f"{row['nombre_norm']},PENDIENTE,{row.get('telefono','')or''},"
            f"{row['d150_monto_anual']:.2f},{row['n_transacciones']},"
            f"Completar cédula antes de declarar"
        )

    csv_content = "\n".join(lines)
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=D150_{year}.csv"}
    )


@router.get("/centinela/resultado/{recon_id}/export", response_class=PlainTextResponse)
def export_resultado(recon_id: str, request: Request, db: Session = Depends(_get_db)):
    """
    Exporta el resultado completo de una sesión de conciliación como CSV.
    Incluye: fecha, descripcion, monto, tipo, tiene_fe, tarifa_iva, iva_estimado,
             beneficiario_nombre, match_estado.

    Equivalente a un Excel — permite análisis externo y revisión del contador.
    SEGURIDAD: verifica tenant_id del JWT.
    """
    tenant_id = _get_tenant(request)

    sesion = db.execute(text(
        "SELECT banco, period FROM bank_reconciliation WHERE id = :id AND tenant_id = :tid"
    ), {"id": recon_id, "tid": tenant_id}).fetchone()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    rows = db.execute(text("""
        SELECT fecha, descripcion, monto, tipo, moneda,
               tiene_fe, fe_numero, tarifa_iva, iva_estimado, base_estimada,
               match_estado, beneficiario_nombre, beneficiario_categoria,
               d270_codigo, accion
        FROM bank_transactions
        WHERE recon_id = :id
        ORDER BY fecha, tipo DESC
    """), {"id": recon_id}).fetchall()

    lines = [
        "fecha,descripcion,monto,tipo,moneda,tiene_fe,tarifa_iva_pct,"
        "iva_estimado,base_estimada,match_estado,beneficiario,categoria,d270,accion"
    ]
    for r in rows:
        rd = dict(r._mapping)
        tiene_fe_str = "SI" if rd.get("tiene_fe") else "NO"
        lines.append(
            f"{rd.get('fecha','')},{rd.get('descripcion','').replace(',',';')},"
            f"{rd.get('monto','')},{rd.get('tipo','')},{rd.get('moneda','CRC')},"
            f"{tiene_fe_str},{rd.get('tarifa_iva','')},{rd.get('iva_estimado','') or 0},"
            f"{rd.get('base_estimada','') or 0},{rd.get('match_estado','')},"
            f"{(rd.get('beneficiario_nombre','') or '').replace(',',';')},"
            f"{rd.get('beneficiario_categoria','')},"
            f"{rd.get('d270_codigo','') or ''},{(rd.get('accion','') or '').replace(',',';')}"
        )

    csv_content = "\n".join(lines)
    banco = sesion.banco or "BANCO"
    period = sesion.period or "periodo"
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=Conciliacion_{banco}_{period}.csv"}
    )


# ── Bank Rules ───────────────────────────────────────────────────────────────



@router.post("/conciliacion/rule")
def save_rule(rule: BankRule, request: Request, db: Session = Depends(_get_db)):
    """Guarda o actualiza una Bank Rule de clasificación.

    SEGURIDAD: las reglas se guardan bajo el tenant autenticado.
    """
    tenant_id = _get_tenant(request)
    db.execute(text("""
        INSERT INTO bank_rules (tenant_id, pattern, pattern_type, contact_name,
                                ledger_account, d270_codigo, note)
        VALUES (:tid, :pat, :ptype, :cn, :la, :d270, :note)
        ON CONFLICT (tenant_id, pattern_type, pattern)
        DO UPDATE SET contact_name = EXCLUDED.contact_name,
                      ledger_account = EXCLUDED.ledger_account,
                      d270_codigo = EXCLUDED.d270_codigo,
                      uses_count = bank_rules.uses_count + 1
    """), {
        "tid": tenant_id, "pat": rule.pattern, "ptype": rule.pattern_type,
        "cn": rule.contact_name, "la": rule.ledger_account,
        "d270": rule.d270_codigo, "note": rule.note,
    })
    db.commit()
    return {"ok": True}


@router.get("/conciliacion/rules")
def list_rules(request: Request, db: Session = Depends(_get_db)):
    """Lista las Bank Rules del tenant autenticado.

    SEGURIDAD: solo muestra las reglas del tenant del JWT.
    """
    tenant_id = _get_tenant(request)
    rows = db.execute(text(
        "SELECT * FROM bank_rules WHERE tenant_id = :tid ORDER BY uses_count DESC"
    ), {"tid": tenant_id}).fetchall()
    return {"rules": [dict(r._mapping) for r in rows]}
