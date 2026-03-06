"""
AuditLogger — Helper para registrar en audit_log
Uso:
    from services.ledger.audit_logger import log_action
    log_action(db, tenant_id, user, action, entity_type=..., entity_id=...,
               before=..., after=..., note=...)
"""
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from services.ledger.audit_log import AuditLog, AuditAction


def log_action(
    db:          Session,
    tenant_id:   str,
    user:        dict,           # {'user_id', 'role', 'email'}
    action:      AuditAction,
    entity_type: str  = None,
    entity_id:   str  = None,
    before:      dict = None,
    after:       dict = None,
    note:        str  = None,
    ip:          str  = None,
    commit:      bool = False,
) -> AuditLog:
    """
    Registra una acción en el audit_log de forma inmutable.
    Retorna el AuditLog creado (sin commit por defecto — se hace junto
    con la transacción principal para atomicidad).
    """
    entry = AuditLog(
        id          = str(uuid.uuid4()),
        tenant_id   = tenant_id,
        user_id     = user.get("sub") or user.get("user_id") or user.get("id") or "",
        user_role   = user.get("role", ""),
        user_email  = user.get("email"),
        action      = action,
        entity_type = entity_type,
        entity_id   = entity_id,
        before_json = json.dumps(before, default=str) if before else None,
        after_json  = json.dumps(after,  default=str) if after  else None,
        note        = note,
        ip          = ip,
        created_at  = datetime.now(timezone.utc),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
