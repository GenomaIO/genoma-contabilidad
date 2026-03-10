"""
integration/cabys_engine.py
════════════════════════════════════════════════════════════
Motor de resolución CABYS → Cuenta Contable

Dado un código CABYS (del XML de Hacienda), resuelve la cuenta contable
correcta del catálogo del tenant con score de confianza.

Jerarquía de resolución:
  1. Regla exacta del tenant (cabys_account_rules.cabys_code = exacto) → 1.0
  2. Regla por prefijo 2 dígitos (sector CABYS)                        → 0.8
  3. Búsqueda semántica por descripción en catálogo CABYS existente     → 0.6
  4. Fallback: 5999 Otros Gastos                                        → 0.3

Herencia IVA:
  tarifa_codigo 01=Exento · 02-05=Reducido · 08=13% Gravado
  Tipo exoneración: EXONERADO si viene con tipo_exoneracion

Reglas de Oro:
  - Función pura: no modifica DB, solo lee
  - Siempre retorna un resultado (nunca None)
  - Si asset_flag y monto >= min_amount → needs_review = True
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Cuenta de fallback cuando no hay regla ni match semántico
CUENTA_OTROS_GASTOS = "5999"

# Mapa de tarifa_codigo → tipo y porcentaje IVA (Hacienda v4.4)
TARIFA_MAP = {
    "01": {"tipo": "EXENTO",     "tarifa": 0.0,  "acreditable": False},
    "02": {"tipo": "REDUCIDO_1", "tarifa": 1.0,  "acreditable": True},
    "03": {"tipo": "REDUCIDO_2", "tarifa": 2.0,  "acreditable": True},
    "04": {"tipo": "REDUCIDO_4", "tarifa": 4.0,  "acreditable": True},
    "05": {"tipo": "REDUCIDO_8", "tarifa": 8.0,  "acreditable": True},
    "08": {"tipo": "GRAVADO",    "tarifa": 13.0, "acreditable": True},
}


def iva_tipo_desde_tarifa(tarifa_codigo: str, tipo_exoneracion: str = None) -> dict:
    """
    Convierte el código de tarifa Hacienda al tratamiento IVA contable.

    Args:
        tarifa_codigo: '01','02','03','04','05','08'
        tipo_exoneracion: si viene del XML, clasifica como EXONERADO

    Returns:
        {tipo, tarifa, acreditable}
    """
    if tipo_exoneracion:
        return {"tipo": "EXONERADO", "tarifa": 0.0, "acreditable": False}

    result = TARIFA_MAP.get(tarifa_codigo)
    if result:
        return dict(result)  # copia defensiva

    # Caso no mapeado → tratar como NO_SUJETO
    logger.warning(f"⚠️ cabys_engine: tarifa_codigo '{tarifa_codigo}' desconocida → NO_SUJETO")
    return {"tipo": "NO_SUJETO", "tarifa": 0.0, "acreditable": False}


def resolver_cabys(
    db,
    tenant_id: str,
    cabys_code: str,
    descripcion: str,
    monto: float,
    tenant_token: str = None,
) -> dict:
    """
    Resuelve el código CABYS a una cuenta contable para el tenant.

    Args:
        db:          Sesión SQLAlchemy (solo lectura)
        tenant_id:   ID del tenant
        cabys_code:  Código CABYS del ítem (del XML de Hacienda)
        descripcion: Descripción del ítem (para búsqueda semántica)
        monto:       Monto del ítem (para evaluar umbral de activo)
        tenant_token: Token del tenant (reservado para futura búsqueda semántica)

    Returns:
        {
          account_code: str,
          confidence: float,
          fuente: 'EXACTA'|'PREFIJO'|'SEMANTICA'|'FALLBACK',
          asset_flag: bool,
          cabys_code: str,
        }
    """
    prefix = (cabys_code or "")[:2]

    # ── 1. Regla exacta del tenant ───────────────────────────────────
    if cabys_code:
        row = db.execute(text("""
            SELECT account_code, asset_flag, min_amount
            FROM cabys_account_rules
            WHERE tenant_id = :tid
              AND cabys_code = :cabys
            ORDER BY prioridad DESC
            LIMIT 1
        """), {"tid": tenant_id, "cabys": cabys_code}).fetchone()

        if row:
            asset = bool(row.asset_flag) and (monto or 0) >= (row.min_amount or 0)
            return {
                "account_code": row.account_code,
                "confidence":   1.0,
                "fuente":       "EXACTA",
                "asset_flag":   asset,
                "cabys_code":   cabys_code,
            }

    # ── 2. Regla por prefijo (2 dígitos del sector CABYS) ───────────
    if prefix:
        row_p = db.execute(text("""
            SELECT account_code, asset_flag, min_amount
            FROM cabys_account_rules
            WHERE tenant_id  = :tid
              AND cabys_code  IS NULL
              AND cabys_prefix = :prefix
            ORDER BY prioridad DESC
            LIMIT 1
        """), {"tid": tenant_id, "prefix": prefix}).fetchone()

        if row_p:
            asset = bool(row_p.asset_flag) and (monto or 0) >= (row_p.min_amount or 0)
            return {
                "account_code": row_p.account_code,
                "confidence":   0.8,
                "fuente":       "PREFIJO",
                "asset_flag":   asset,
                "cabys_code":   cabys_code,
            }

    # ── 3. Búsqueda semántica por descripción en catálogo CABYS ─────
    # Busca en el catálogo CABYS por similitud de descripción
    if descripcion:
        sem = _buscar_semantico(db, tenant_id, descripcion)
        if sem:
            return {
                "account_code": sem["account_code"],
                "confidence":   0.6,
                "fuente":       "SEMANTICA",
                "asset_flag":   False,
                "cabys_code":   cabys_code,
            }

    # ── 4. Fallback — Otros Gastos 5999 ─────────────────────────────
    logger.info(f"cabys_engine: FALLBACK 5999 para CABYS={cabys_code} desc='{descripcion[:30]}'")
    return {
        "account_code": CUENTA_OTROS_GASTOS,
        "confidence":   0.3,
        "fuente":       "FALLBACK",
        "asset_flag":   False,
        "cabys_code":   cabys_code,
    }


def _buscar_semantico(db, tenant_id: str, descripcion: str) -> dict | None:
    """
    Búsqueda por palabras clave de la descripción del ítem en
    el catálogo CABYS → cuenta del tenant.

    Intenta encontrar una cuenta del catálogo del tenant cuyo nombre
    contenga palabras significativas de la descripción.
    Retorna None si no hay match suficiente.
    """
    keywords = [w.lower() for w in descripcion.split() if len(w) >= 4]
    if not keywords:
        return None

    for kw in keywords[:3]:  # max 3 keywords para no sobrecargar
        try:
            row = db.execute(text("""
                SELECT code AS account_code
                FROM accounts
                WHERE tenant_id = :tid
                  AND is_active = TRUE
                  AND LOWER(name) LIKE :kw
                  AND account_type = 'GASTO'
                ORDER BY code
                LIMIT 1
            """), {"tid": tenant_id, "kw": f"%{kw}%"}).fetchone()

            if row:
                return {"account_code": row.account_code}
        except Exception:
            pass

    return None
