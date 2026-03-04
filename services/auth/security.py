"""
Auth Service — Seguridad JWT y hashing
Reglas de Oro:
  - JWT_SECRET siempre desde env var
  - tenant_id SIEMPRE embebido en el JWT (nunca en el body del request)
  - Tokens con expiración configurable (default 8h)
  - Passwords con bcrypt (nunca en texto plano, nunca en logs)
"""
import os
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt

# ── Configuración desde env ──────────────────────────────────────
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "8"))


def _require_secret() -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET no configurado en variables de entorno")
    return JWT_SECRET


# ── Password ─────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ──────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    tenant_id: str,
    tenant_type: str,  # "partner_linked" | "standalone"
    role: str,
    nombre: str,
    partner_id: Optional[str] = None,
) -> str:
    """
    Genera un JWT con la identidad completa del usuario.
    tenant_id y tenant_type quedan embebidos — el backend
    los extrae sin necesitar otro lookup a la DB por request.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRE_HOURS)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "tenant_type": tenant_type,
        "role": role,
        "nombre": nombre,
        "exp": expire,
    }
    if partner_id:
        payload["partner_id"] = partner_id

    return jwt.encode(payload, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decodifica y valida el JWT.
    Raises JWTError si el token es inválido o expirado.
    """
    return jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])


def extract_tenant_id(token: str) -> str:
    """Shortcut para obtener tenant_id del JWT."""
    payload = decode_token(token)
    return payload["tenant_id"]
