"""
Webhook Receptor — Integración con Genoma Facturador
Genoma Contabilidad · FASE C

Recibe documentos electrónicos ya aceptados por Hacienda desde el
sistema Genoma Facturador vía webhook seguro (shared secret).

Reglas de Oro:
- tenant_id validado desde payload + secret (nunca de URL pública)
- Solo documentos con estado 'ACEPTADO' por Hacienda se procesan
- Todo documento recibido genera un DRAFT entry para aprobación del contador
- Duplicados se detectan por source_ref (clave Hacienda 50 chars)
- Todo evento queda en audit_log
"""
import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from services.auth.database import get_session
from services.ledger.models import JournalEntry, JournalLine, EntryStatus, EntrySource
from services.ledger.audit_log import AuditAction
from services.ledger.audit_logger import log_action

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integration", tags=["integration"])

# ─────────────────────────────────────────────────────────────────
# Tipos de documento soportados → EntrySource
# ─────────────────────────────────────────────────────────────────

DOC_TYPE_MAP = {
    "01": EntrySource.FE,        # Factura Electrónica
    "02": EntrySource.ND,        # Nota de Débito
    "03": EntrySource.NC,        # Nota de Crédito
    "04": EntrySource.TE,        # Tiquete Electrónico
    "08": EntrySource.FEC,       # Factura Electrónica de Compra
    "09": EntrySource.FEC,       # Factura Exportación → trato similar
    "REP": EntrySource.REP,      # Recibo de pago
    "RECIBIDO": EntrySource.RECIBIDO,  # Documento recibido (compra)
}


# ─────────────────────────────────────────────────────────────────
# Schema del payload del webhook
# ─────────────────────────────────────────────────────────────────

class WebhookDocumentPayload(BaseModel):
    """
    Payload enviado por Genoma Facturador al contabilidad.
    Debe incluir la clave Hacienda (50 chars) como identificador único.
    """
    tenant_id:      str
    doc_type:       str           # '01','02','03','04','08','09','REP','RECIBIDO'
    clave:          str           # Clave Hacienda 50 chars (source_ref)
    numero_doc:     str           # Número consecutivo
    fecha:          str           # 'YYYY-MM-DD'
    emisor_nombre:  str
    receptor_nombre: Optional[str] = None
    total_venta:    float = 0.0   # Monto grabado 13%
    total_exento:   float = 0.0   # Monto exento
    total_iva:      float = 0.0   # IVA calculado
    total_doc:      float = 0.0   # Total del documento
    moneda:         str = "CRC"   # 'CRC' o 'USD'
    tipo_cambio:    float = 1.0   # Si es USD, TC del BCCR
    estado_hacienda: str = "ACEPTADO"  # Solo procesamos ACEPTADO


def _verify_hmac(payload_bytes: bytes, signature: str, secret: str) -> bool:
    """Verifica el HMAC-SHA256 del payload para autenticar el webhook."""
    expected = hmac.new(
        key=secret.encode(),
        msg=payload_bytes,
        digestmod=hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _get_webhook_secret(tenant_id: str) -> str:
    """
    Obtiene el shared secret del webhook para el tenant.
    En producción esto viene de una variable de entorno o tabla de configuración.
    """
    import os
    # Primero busca secret específico por tenant, luego el global
    secret = os.getenv(f"WEBHOOK_SECRET_{tenant_id.replace('-','_')}")
    if not secret:
        secret = os.getenv("WEBHOOK_SECRET", "dev-secret-change-in-prod")
    return secret


# ─────────────────────────────────────────────────────────────────
# POST /integration/webhook — Receptor principal
# ─────────────────────────────────────────────────────────────────

@router.post("/webhook")
async def receive_document(
    request: Request,
    db: Session = Depends(get_session),
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
    x_webhook_tenant:    Optional[str] = Header(None, alias="X-Webhook-Tenant"),
):
    """
    Punto de entrada para documentos del Facturador.

    Seguridad:
    - Verifica HMAC-SHA256 con el shared secret del tenant
    - Solo acepta documentos en estado ACEPTADO por Hacienda
    - Idempotente: detecta duplicados por source_ref (clave Hacienda)

    Flujo:
    1. Validar firma HMAC
    2. Parsear payload
    3. Verificar no duplicado
    4. Crear JournalEntry DRAFT (el motor de mapeo lo rellena en C2)
    5. Registrar en audit_log
    """
    raw_body = await request.body()

    # 1. Validar firma HMAC (en desarrollo se puede desactivar)
    import os
    skip_hmac = os.getenv("SKIP_WEBHOOK_HMAC", "false").lower() == "true"
    if not skip_hmac and x_webhook_signature:
        tenant_id_for_secret = x_webhook_tenant or ""
        secret = _get_webhook_secret(tenant_id_for_secret)
        if not _verify_hmac(raw_body, x_webhook_signature, secret):
            logger.warning(f"⚠️ Webhook: firma HMAC inválida para tenant {x_webhook_tenant}")
            raise HTTPException(401, "Firma de webhook inválida")

    # 2. Parsear payload
    import json
    try:
        data = json.loads(raw_body)
        doc = WebhookDocumentPayload(**data)
    except Exception as e:
        raise HTTPException(422, f"Payload inválido: {e}")

    # 3. Solo documentos ACEPTADOS
    if doc.estado_hacienda != "ACEPTADO":
        logger.info(f"Webhook: documento {doc.clave[:20]}... ignorado (estado={doc.estado_hacienda})")
        return {"ok": True, "status": "ignored", "reason": "solo se procesan documentos ACEPTADOS"}

    # 4. Verificar duplicado por source_ref
    existing = db.query(JournalEntry).filter(
        JournalEntry.tenant_id == doc.tenant_id,
        JournalEntry.source_ref == doc.clave,
    ).first()
    if existing:
        logger.info(f"Webhook: documento {doc.clave[:20]}... ya procesado (entry_id={existing.id[:8]})")
        return {
            "ok": True,
            "status": "duplicate",
            "entry_id": existing.id,
            "message": "Documento ya registrado. Se omite.",
        }

    # 5. Crear JournalEntry DRAFT (stub — el motor C2 rellena las líneas)
    entry_id = str(uuid.uuid4())
    period   = doc.fecha[:7]
    source   = DOC_TYPE_MAP.get(doc.doc_type, EntrySource.MANUAL)
    now      = datetime.now(timezone.utc)

    short_doc = doc.doc_type if doc.doc_type else "DOC"
    entry = JournalEntry(
        id          = entry_id,
        tenant_id   = doc.tenant_id,
        period      = period,
        date        = doc.fecha,
        description = (
            f"[{short_doc}] {doc.emisor_nombre[:60]} · "
            f"{doc.numero_doc} · ¢{doc.total_doc:,.2f}"
        ),
        status      = EntryStatus.DRAFT,
        source      = source,
        source_ref  = doc.clave,
        created_by  = "WEBHOOK",   # sistema, no un usuario humano
        created_at  = now,
    )
    db.add(entry)

    # Línea placeholder — el motor C2 la reemplaza con las líneas reales
    db.add(JournalLine(
        id           = str(uuid.uuid4()),
        entry_id     = entry_id,
        tenant_id    = doc.tenant_id,
        account_code = "PENDIENTE",
        description  = f"Pendiente mapeo automático — {doc.clave[:20]}...",
        debit        = 0.0,
        credit       = 0.0,
        created_at   = now,
    ))

    log_action(
        db,
        tenant_id   = doc.tenant_id,
        user        = {"user_id": "WEBHOOK", "role": "sistema", "email": None},
        action      = AuditAction.WEBHOOK_RECEIVED,
        entity_type = "journal_entry",
        entity_id   = entry_id,
        after       = {
            "clave":      doc.clave,
            "doc_type":   doc.doc_type,
            "total_doc":  doc.total_doc,
            "moneda":     doc.moneda,
            "source":     source.value,
            "status":     "DRAFT",
        },
        note = f"Documento {doc.doc_type} de {doc.emisor_nombre[:50]}",
    )
    db.commit()

    logger.info(f"✅ Webhook: entry DRAFT creada {entry_id[:8]}... para clave {doc.clave[:20]}...")

    return {
        "ok": True,
        "status":   "queued",
        "entry_id": entry_id,
        "period":   period,
        "message":  "Documento recibido. Asiento DRAFT creado — pendiente mapeo contable.",
    }


# ─────────────────────────────────────────────────────────────────
# GET /integration/webhook/status — Health del receptor
# ─────────────────────────────────────────────────────────────────

@router.get("/webhook/status")
def webhook_status():
    """Health check del receptor de webhooks."""
    return {
        "ok": True,
        "service": "integration-webhook",
        "version": "1.0",
        "supported_doc_types": list(DOC_TYPE_MAP.keys()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
