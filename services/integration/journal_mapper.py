"""
Motor de Mapeo Contable Automático
Genoma Contabilidad · Integración Facturador → Ledger

Convierte documentos electrónicos en asientos contables NIIF CR:
  FE/TE → Registro de venta (CxC, Ingresos, IVA por pagar)
  NC    → Reversión de venta (contra la FE original)
  ND    → Registro de cargo adicional
  REP   → Cobro de CxC (Banco/Efectivo ↔ CxC)
  FEC   → Registro de compra (Gastos/PPE, IVA acreditable, CxP)

Fiscal tagging (Art. 8/9 Ley Renta, Art. 15 Ley IVA 9635):
- Ventas: DEDUCTIBLE/EXEMPT según tipo de tarifa IVA
- Compras: DEDUCTIBLE si tiene IVA acreditable (factor prorrata)
- IVA diferido (cond. venta 11): marca la cuenta 2108

Reglas de Oro:
- Todas las líneas tienen tenant_id
- DECIMAL(18,5) — float en-app, NUMERIC en DB
- El asiento resultante SIEMPRE queda en DRAFT (contador aprueba)
- Si no hay cuenta en catálogo → usa código genérico + alerta
"""
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from services.ledger.models import JournalLine, JournalEntry, EntryStatus
from services.ledger.audit_log import AuditAction
from services.ledger.audit_logger import log_action

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Cuentas por defecto (fallback cuando no hay catálogo personalizado)
# ─────────────────────────────────────────────────────────────────

DEFAULT_ACCOUNTS = {
    # Activos
    "CXC":          "1102",   # Cuentas por Cobrar Comerciales
    "IVA_CREDITO":  "1104",   # IVA Acreditable (Crédito Fiscal)
    "BANCO":        "1101",   # Efectivo y Equivalentes
    # Pasivos
    "CXP":          "2101",   # Cuentas por Pagar Comerciales
    "IVA_DEBITO":   "2102",   # IVA por Pagar (Débito Fiscal 13%)
    "IVA_DIFERIDO": "2108",   # IVA Diferido (cond. venta 11)
    # Ingresos
    "INGRESO_VENTAS": "4101", # Ventas de Mercancías
    "INGRESO_SERV":   "4102", # Ventas de Servicios
    "INGRESO_EXENTO": "4103", # Ventas Exentas de IVA
    # Gastos/Costos
    "GASTO_COMPRA": "5101",   # Costo de Mercancías Vendidas
    "GASTO_SERV":   "5102",   # Costo de Servicios Prestados
}


def _resolve_account(db: Session, tenant_id: str, generic_key: str) -> str:
    """
    Resuelve el código de cuenta para el tenant.
    Primero busca en accounts del tenant, luego usa el default del catálogo NIIF.
    """
    code = DEFAULT_ACCOUNTS.get(generic_key, generic_key)
    # Verificar que la cuenta existe en la tabla accounts del tenant
    row = db.execute(text("""
        SELECT code FROM accounts
        WHERE tenant_id = :tid AND code = :code AND is_active = TRUE
        LIMIT 1
    """), {"tid": tenant_id, "code": code}).fetchone()

    if row:
        return code
    # Si no existe, usar el código genérico directo
    logger.warning(f"⚠️ Cuenta {code} no encontrada para tenant {tenant_id}, usando código genérico")
    return generic_key


def _build_line(entry_id, tenant_id, code, desc, debit, credit, deductible, legal_basis=None,
                dim_segment=None):
    return JournalLine(
        id=str(uuid.uuid4()),
        entry_id=entry_id,
        tenant_id=tenant_id,
        account_code=code,
        description=desc,
        debit=round(float(debit), 5),
        credit=round(float(credit), 5),
        deductible_status=deductible,
        legal_basis=legal_basis,
        dim_segment=dim_segment,
        created_at=datetime.now(timezone.utc),
    )


# ─────────────────────────────────────────────────────────────────
# Motor principal
# ─────────────────────────────────────────────────────────────────

def map_document_to_entry(
    db:          Session,
    entry:       JournalEntry,
    doc:         dict,            # payload del webhook ya parseado
    user_ref:    dict = None,     # {'user_id','role','email'}
) -> JournalEntry:
    """
    Rellena las líneas contables de un JournalEntry placeholder.

    El JournalEntry ya debe existir en DB (creado por webhook_receiver).
    Este motor reemplaza las líneas placeholder con las líneas NIIF correctas.

    doc contiene:
        doc_type, total_venta, total_exento, total_iva, total_doc,
        moneda, tipo_cambio, emisor_nombre, receptor_nombre,
        es_exportacion, condicion_venta, clave, numero_doc
    """
    tenant_id = entry.tenant_id
    entry_id  = entry.id
    now       = datetime.now(timezone.utc)

    # Borrar líneas placeholder
    db.query(JournalLine).filter(
        JournalLine.entry_id == entry_id,
        JournalLine.account_code == "PENDIENTE"
    ).delete()

    doc_type     = doc.get("doc_type", "01")
    total_venta  = float(doc.get("total_venta",  0))
    total_exento = float(doc.get("total_exento", 0))
    total_iva    = float(doc.get("total_iva",    0))
    total_doc    = float(doc.get("total_doc",    0))
    condicion    = doc.get("condicion_venta", "01")  # 01=contado, 02=credito
    es_exportacion = doc.get("es_exportacion", False)

    lines = []

    # ── FE / TE — Factura Electrónica / Tiquete ───────────────────
    if doc_type in ("01", "04"):
        # Venta a crédito → CxC; contado → Efective/Banco
        if condicion == "01":  # contado
            dr_cuenta = _resolve_account(db, tenant_id, "BANCO")
            dr_desc   = "Cobro contado — " + doc.get("numero_doc", "")
        elif condicion == "11":  # venta diferida IVA
            dr_cuenta = _resolve_account(db, tenant_id, "CXC")
            dr_desc   = "CxC diferida (cond.11) — " + doc.get("numero_doc", "")
        else:
            dr_cuenta = _resolve_account(db, tenant_id, "CXC")
            dr_desc   = "CxC — " + doc.get("numero_doc", "")

        # Línea 1: Débito CxC / Banco por total documento
        lines.append(_build_line(
            entry_id, tenant_id, dr_cuenta, dr_desc,
            debit=total_doc, credit=0,
            deductible="EXEMPT",
            legal_basis="Art. 22 Ley IVA 9635"
        ))

        # Línea 2: Crédito Ingresos (monto grabado)
        if total_venta > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "INGRESO_VENTAS"),
                "Ingreso por venta grabada 13%",
                debit=0, credit=total_venta,
                deductible="DEDUCTIBLE" if not es_exportacion else "EXEMPT",
                legal_basis="Art. 8 Ley Renta 7092"
            ))

        # Línea 3: Crédito Ingresos Exentos
        if total_exento > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "INGRESO_EXENTO"),
                "Ingreso exento de IVA",
                debit=0, credit=total_exento,
                deductible="EXEMPT",
                legal_basis="Art. 8 Ley Renta 7092 / Art. 9 Ley IVA 9635"
            ))

        # Línea 4: Crédito IVA por pagar (o IVA diferido si cond.11)
        if total_iva > 0:
            if condicion == "11":
                iva_cuenta = _resolve_account(db, tenant_id, "IVA_DIFERIDO")
                iva_desc   = "IVA diferido condVenta11 — Art.17 Ley IVA 9635"
            else:
                iva_cuenta = _resolve_account(db, tenant_id, "IVA_DEBITO")
                iva_desc   = "IVA Débito Fiscal 13% — Art.15 Ley IVA 9635"

            lines.append(_build_line(
                entry_id, tenant_id, iva_cuenta, iva_desc,
                debit=0, credit=total_iva,
                deductible="EXEMPT",
                legal_basis="Art. 15 Ley IVA 9635"
            ))

    # ── NC — Nota de Crédito ──────────────────────────────────────
    elif doc_type == "03":
        # Inversión del asiento de venta
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "INGRESO_VENTAS"),
            "NC — reversa ingreso por venta",
            debit=total_venta, credit=0,
            deductible="DEDUCTIBLE",
            legal_basis="Art. 8 Ley Renta 7092"
        ))
        if total_iva > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "IVA_DEBITO"),
                "NC — reversa IVA Débito Fiscal",
                debit=total_iva, credit=0,
                deductible="EXEMPT",
                legal_basis="Art. 15 Ley IVA 9635"
            ))
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "CXC"),
            "NC — reduce CxC al cliente",
            debit=0, credit=total_doc,
            deductible="EXEMPT",
            legal_basis="Art. 22 Ley IVA 9635"
        ))

    # ── ND — Nota de Débito ───────────────────────────────────────
    elif doc_type == "02":
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "CXC"),
            "ND — cargo adicional al cliente",
            debit=total_doc, credit=0,
            deductible="EXEMPT",
            legal_basis="Art. 22 Ley IVA 9635"
        ))
        if total_venta > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "INGRESO_VENTAS"),
                "ND — ingreso cargo adicional",
                debit=0, credit=total_venta,
                deductible="DEDUCTIBLE",
                legal_basis="Art. 8 Ley Renta 7092"
            ))
        if total_iva > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "IVA_DEBITO"),
                "ND — IVA cargo adicional",
                debit=0, credit=total_iva,
                deductible="EXEMPT",
                legal_basis="Art. 15 Ley IVA 9635"
            ))

    # ── FEC / Compra recibida ─────────────────────────────────────
    elif doc_type in ("08", "09", "RECIBIDO"):
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "GASTO_COMPRA"),
            "Compra recibida — costo/gasto",
            debit=total_venta, credit=0,
            deductible="DEDUCTIBLE",
            legal_basis="Art. 8 Ley Renta 7092"
        ))
        if total_iva > 0:
            lines.append(_build_line(
                entry_id, tenant_id,
                _resolve_account(db, tenant_id, "IVA_CREDITO"),
                "IVA Acreditable (crédito fiscal)",
                debit=total_iva, credit=0,
                deductible="DEDUCTIBLE",
                legal_basis="Art. 29 Ley IVA 9635 — factor prorrata"
            ))
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "CXP"),
            "CxP proveedor",
            debit=0, credit=total_doc,
            deductible="EXEMPT",
            legal_basis="Art. 8 Ley Renta 7092"
        ))

    # ── REP — Recibo de Pago ──────────────────────────────────────
    elif doc_type == "REP":
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "BANCO"),
            "Cobro recibo de pago",
            debit=total_doc, credit=0,
            deductible="EXEMPT",
            legal_basis=None
        ))
        lines.append(_build_line(
            entry_id, tenant_id,
            _resolve_account(db, tenant_id, "CXC"),
            "Cancela CxC — recibo de pago",
            debit=0, credit=total_doc,
            deductible="EXEMPT",
            legal_basis=None
        ))

    else:
        # Tipo desconocido → línea de alerta
        logger.warning(f"⚠️ Motor mapeo: tipo de doc '{doc_type}' desconocido, asiento vacío")

    for line in lines:
        db.add(line)

    # Marcar que este entry ya fue mapeado (nota en descripción)
    entry.description = entry.description.rstrip() + " [MAPEADO]"

    if user_ref:
        log_action(
            db, tenant_id, user_ref,
            AuditAction.AUTO_ENTRY_GENERATED,
            entity_type="journal_entry", entity_id=entry_id,
            after={
                "doc_type":    doc_type,
                "lines_built": len(lines),
                "total_doc":   total_doc,
            },
            note=f"Motor mapeo automático doc_type={doc_type}"
        )

    db.commit()
    db.refresh(entry)
    logger.info(f"✅ Motor mapeo: {len(lines)} líneas generadas para entry {entry_id[:8]}...")
    return entry
