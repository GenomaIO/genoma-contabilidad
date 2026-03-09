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
    Compara las transacciones cargadas vs. el Libro Diario del período.
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

    # Obtener transacciones del banco para esta sesión
    bank_txns = [dict(r._mapping) for r in db.execute(text(
        "SELECT * FROM bank_transactions WHERE recon_id = :id ORDER BY fecha"
    ), {"id": recon_id}).fetchall()]

    # Obtener asientos del Libro Diario del período
    year, month = period[:4], period[4:6]
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
        "period":       f"{year}-{month}",
        "account_code": account_code,
    }).fetchall()]

    matched = match_transactions(bank_txns, journal_lines)
    solo    = find_solo_libros(matched, journal_lines)

    # Saldo en libros: suma de créditos - débitos de la cuenta en el período
    saldo_libros_row = db.execute(text("""
        SELECT COALESCE(SUM(jl.credit), 0) - COALESCE(SUM(jl.debit), 0)
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE jl.tenant_id    = :tenant_id
          AND jl.account_code = :account_code
          AND je.period       = :period
          AND je.status       = 'POSTED'
    """), {
        "tenant_id": tenant_id, "account_code": account_code,
        "period": f"{year}-{month}"
    }).scalar() or 0.0
    saldo_libros = float(saldo_libros_row)

    diff = calcular_diferencia_saldo(float(saldo_final_banco or 0), saldo_libros)

    # Actualizar estados en bank_transactions
    for txn in matched:
        db.execute(text("""
            UPDATE bank_transactions
            SET match_estado = :estado, match_confianza = :conf, matched_entry_id = :eid
            WHERE id = :id
        """), {
            "estado": txn["match_estado"],
            "conf":   txn.get("match_confianza", 0),
            "eid":    txn.get("matched_entry_id"),
            "id":     txn["id"],
        })
    db.commit()

    stats = {
        "conciliados":  sum(1 for t in matched if t["match_estado"] == "CONCILIADO"),
        "probables":    sum(1 for t in matched if t["match_estado"] == "PROBABLE"),
        "sin_asiento":  sum(1 for t in matched if t["match_estado"] == "SIN_ASIENTO"),
        "solo_libros":  len(solo),
        "total_banco":  len(matched),
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
    Detecta fugas A/B/C y calcula el score de riesgo fiscal.
    """
    from services.conciliacion.fiscal_engine import (
        clasificar_fuga, calcular_score
    )
    from services.conciliacion.reconciliation_engine import calcular_diferencia_saldo

    row = db.execute(text(
        "SELECT tenant_id, period, saldo_final FROM bank_reconciliation WHERE id = :id"
    ), {"id": recon_id}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")

    tenant_id, period, saldo_final_banco = row

    # Transacciones sin asiento = candidatas a fugas
    sin_match = [dict(r._mapping) for r in db.execute(text("""
        SELECT * FROM bank_transactions
        WHERE recon_id = :id AND match_estado IN ('SIN_ASIENTO', 'SOLO_LIBROS')
    """), {"id": recon_id}).fetchall()]

    # FE emitidas del período (para cruce Tipo A y C)
    year, month = period[:4], period[4:6]
    fe_emitidas = [dict(r._mapping) for r in db.execute(text("""
        SELECT * FROM journal_entries
        WHERE tenant_id = :tenant_id AND period = :period
          AND source IN ('FE', 'TE', 'NC', 'ND') AND status = 'POSTED'
    """), {"tenant_id": tenant_id, "period": f"{year}-{month}"}).fetchall()]

    fe_recibidas = []  # Para fase futura (FE recibidas módulo)

    fugas = []
    for txn in sin_match:
        fuga = clasificar_fuga(txn, fe_emitidas, fe_recibidas)
        if fuga:
            fuga["txn_id"]          = txn["id"]
            fuga["txn_descripcion"] = txn.get("descripcion", "")
            fuga["txn_monto"]       = float(txn.get("monto", 0))
            fuga["txn_fecha"]       = str(txn.get("fecha", ""))
            fugas.append(fuga)

            # Actualizar transacción en BD
            db.execute(text("""
                UPDATE bank_transactions
                SET fuga_tipo = :ft, score_puntos = :sp, iva_estimado = :iva,
                    base_estimada = :base, d270_codigo = :d270, accion = :accion
                WHERE id = :id
            """), {
                "ft": fuga.get("fuga_tipo"),
                "sp": fuga.get("score_pts", 0),
                "iva": fuga.get("iva_riesgo", 0),
                "base": fuga.get("base_riesgo", 0),
                "d270": fuga.get("d270_codigo"),
                "accion": fuga.get("accion"),
                "id": txn["id"],
            })

    # Score total
    total_fe_monto = sum(float(fe.get("total_amount", 0) or 0) for fe in fe_emitidas)
    ingresos_banco = sum(float(t.get("monto", 0)) for t in db.execute(text(
        "SELECT monto FROM bank_transactions WHERE recon_id = :id AND tipo = 'CR'"
    ), {"id": recon_id}).fetchall())

    saldo_libros = 0.0
    diff = calcular_diferencia_saldo(float(saldo_final_banco or 0), saldo_libros)

    result = calcular_score(fugas, diff, ingresos_banco, total_fe_monto)

    # Guardar score en centinela_score
    db.execute(text("""
        INSERT INTO centinela_score
          (tenant_id, period, score_total, fugas_tipo_a, fugas_tipo_b, fugas_tipo_c,
           exposicion_iva, exposicion_renta, exposicion_total, d270_regs, score_detalle)
        VALUES
          (:tenant_id, :period, :score, :a, :b, :c, :iva, :renta, :total, :d270, :det::jsonb)
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

    # Actualizar score en bank_reconciliation
    db.execute(text(
        "UPDATE bank_reconciliation SET score_riesgo = :s, estado = 'ANALIZADO' WHERE id = :id"
    ), {"s": result["score_total"], "id": recon_id})
    db.commit()

    return {
        "ok":     True,
        "recon_id": recon_id,
        "score":  result,
        "fugas":  fugas,
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

    rows = db.execute(text("""
        SELECT bt.descripcion, bt.base_estimada AS monto, bt.d270_codigo,
               bt.accion AS observacion, br.period
        FROM bank_transactions bt
        JOIN bank_reconciliation br ON br.id = bt.recon_id
        WHERE br.tenant_id   = :tenant_id
          AND br.period       = :period
          AND bt.d270_codigo IS NOT NULL
          AND bt.accion_tomada = FALSE
        ORDER BY bt.d270_codigo, bt.monto DESC
    """), {"tenant_id": tenant_id, "period": period}).fetchall()

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
