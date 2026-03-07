"""
services/ledger/semantic_guard.py
═══════════════════════════════════════════════════════════════════════
Seguro Semántico de Asientos Contables
═══════════════════════════════════════════════════════════════════════

Valida que las cuentas en un asiento sean coherentes por TIPO (ACTIVO,
PASIVO, INGRESO, GASTO, PATRIMONIO) y por KEYWORDS del nombre de cuenta.

Expande fácilmente: agrega reglas en SEMANTIC_RULES.

Uso:
    from services.ledger.semantic_guard import validate_entry_lines
    validate_entry_lines(source='DEPRECIACION', lines=..., accounts_map=...)
    # Lanza SemanticViolationError si algo no cuadra
"""

import logging
from typing import Optional

logger = logging.getLogger("genoma.semantic_guard")


# ── Error semántico ───────────────────────────────────────────────────

class SemanticViolationError(Exception):
    """
    Se lanza cuando un asiento viola las reglas semánticas.
    Código HTTP sugerido: 422 Unprocessable Entity.
    """
    def __init__(self, source: str, account_code: str, expected: str, got: str, hint: str = ""):
        self.source       = source
        self.account_code = account_code
        self.expected     = expected
        self.got          = got
        self.hint         = hint
        super().__init__(
            f"[{source}] Cuenta {account_code}: se esperaba {expected}, "
            f"se encontró '{got}'. {hint}"
        )


# ── Reglas semánticas por fuente de asiento ───────────────────────────
#
# Cada regla define:
#   debit_types  → tipos permitidos en el Débito
#   credit_types → tipos permitidos en el Crédito
#   debit_keywords  → (opcional) keywords que debe contener el nombre de la cuenta déb
#   credit_keywords → (opcional) keywords que debe contener el nombre de la cuenta cré
#
# Los tipos son los values de account_type en el catálogo:
#   ACTIVO | PASIVO | PATRIMONIO | INGRESO | GASTO
#
SEMANTIC_RULES: dict[str, dict] = {
    # ── Depreciación mensual ──────────────────────────────────────────
    "DEPRECIACION": {
        "debit_types":    ["GASTO"],
        "credit_types":   ["ACTIVO"],          # dep. acumulada es contra-activo
        "debit_keywords":  ["dep", "depreci"],
        "credit_keywords": ["acum", "dep"],
        "hint": "DR debe ser Gasto Depreciación · CR debe ser Dep. Acumulada (ACTIVO contra-activo)",
    },

    # ── Provisiones (vacaciones, aguinaldo, indem.) ───────────────────
    "PROVISION": {
        "debit_types":  ["GASTO"],
        "credit_types": ["PASIVO"],
        "hint": "DR debe ser Gasto · CR debe ser Pasivo acumulado",
    },

    # ── Asiento de apertura / saldo inicial ───────────────────────────
    "APERTURA": {
        "debit_types":  ["ACTIVO", "GASTO"],
        "credit_types": ["PASIVO", "PATRIMONIO", "INGRESO"],
        "hint": "Apertura: Activos/Gastos al Debe · Pasivos/Patrimonio al Haber",
    },

    # ── Nómina / planilla ─────────────────────────────────────────────
    "NOMINA": {
        "debit_types":  ["GASTO"],
        "credit_types": ["PASIVO", "ACTIVO"],   # ACTIVO = banco/caja
        "hint": "Nómina: Gastos de personal al Debe · Banco o CxP al Haber",
    },

    # ── Cierre de ingresos / gastos a resultados ──────────────────────
    "CIERRE": {
        "debit_types":  ["INGRESO", "PATRIMONIO"],
        "credit_types": ["GASTO", "PATRIMONIO"],
        "hint": "Cierre: Ingresos DR / Gastos CR → transfiere a Resultados",
    },

    # ── Intereses financieros ─────────────────────────────────────────
    "INTERES": {
        "debit_types":  ["GASTO"],
        "credit_types": ["PASIVO", "ACTIVO"],
        "debit_keywords":  ["inter"],
        "hint": "Intereses: Gasto financiero DR · Banco o Pasivo CR",
    },

    # ── Ajuste FX (diferencia en tipo de cambio) ──────────────────────
    "FX": {
        "debit_types":  ["GASTO", "ACTIVO"],
        "credit_types": ["INGRESO", "ACTIVO", "PASIVO"],
        "hint": "FX: puede ser activo/gasto/ingreso según si es pérdida o ganancia",
    },
    # Nota: MANUAL no tiene restricciones — el contador es responsable
}


# ── Función principal de validación ──────────────────────────────────

def validate_entry_lines(
    source: str,
    lines: list[dict],
    accounts_map: dict[str, dict],
    strict_keywords: bool = False,
) -> None:
    """
    Valida las líneas de un asiento contra las reglas semánticas.

    Args:
        source:        Fuente del asiento ('DEPRECIACION', 'CIERRE', etc.)
        lines:         Lista de dicts con keys: account_code, debit, credit
        accounts_map:  Dict {account_code: {account_type, name}} del catálogo
        strict_keywords: Si True, valida también los keywords del nombre

    Raises:
        SemanticViolationError si alguna línea viola las reglas.
    """
    rule = SEMANTIC_RULES.get(source)
    if not rule:
        logger.debug(f"SemanticGuard: sin reglas para source='{source}' — pass")
        return

    debit_types      = rule.get("debit_types", [])
    credit_types     = rule.get("credit_types", [])
    debit_keywords   = rule.get("debit_keywords", [])
    credit_keywords  = rule.get("credit_keywords", [])
    hint             = rule.get("hint", "")

    for line in lines:
        code  = line.get("account_code", "")
        debit = float(line.get("debit", 0) or 0)
        cred  = float(line.get("credit", 0) or 0)

        acct = accounts_map.get(code)
        if not acct:
            logger.warning(f"SemanticGuard: cuenta {code} no encontrada en catálogo — no validada")
            continue

        atype = acct.get("account_type") or acct.get("type") or ""
        aname = (acct.get("name") or acct.get("nombre") or "").lower()

        if debit > 0 and debit_types:
            if atype not in debit_types:
                raise SemanticViolationError(
                    source, code,
                    expected=f"tipo {debit_types} en Débito",
                    got=atype,
                    hint=hint,
                )
            if strict_keywords and debit_keywords:
                ok = any(kw in aname for kw in debit_keywords)
                if not ok:
                    raise SemanticViolationError(
                        source, code,
                        expected=f"nombre conteniendo {debit_keywords} en Débito",
                        got=aname,
                        hint=hint,
                    )

        if cred > 0 and credit_types:
            if atype not in credit_types:
                raise SemanticViolationError(
                    source, code,
                    expected=f"tipo {credit_types} en Crédito",
                    got=atype,
                    hint=hint,
                )
            if strict_keywords and credit_keywords:
                ok = any(kw in aname for kw in credit_keywords)
                if not ok:
                    raise SemanticViolationError(
                        source, code,
                        expected=f"nombre conteniendo {credit_keywords} en Crédito",
                        got=aname,
                        hint=hint,
                    )


# ── Validación rápida de par de cuentas (para registro de activos) ───

def validate_depreciation_account_pair(
    dep_gasto_code: str,
    dep_acum_code: str,
    accounts_map: dict[str, dict],
) -> None:
    """
    Valida que dep_gasto_code sea tipo GASTO y dep_acum_code sea tipo ACTIVO.
    Usable antes de guardar un activo fijo.

    Raises:
        SemanticViolationError
    """
    # Validar gasto
    acct_g = accounts_map.get(dep_gasto_code)
    if acct_g:
        atype_g = acct_g.get("account_type") or acct_g.get("type") or ""
        if atype_g != "GASTO":
            raise SemanticViolationError(
                "REGISTRO_ACTIVO", dep_gasto_code,
                expected="tipo GASTO (cuenta de Gasto Depreciación)",
                got=atype_g,
                hint="El campo 'Gasto Depreciación' debe apuntar a una cuenta de tipo GASTO (5.x.x.xx)",
            )
    else:
        logger.warning(f"SemanticGuard: dep_gasto_code={dep_gasto_code} no encontrado en catálogo")

    # Validar acumulada
    acct_a = accounts_map.get(dep_acum_code)
    if acct_a:
        atype_a = acct_a.get("account_type") or acct_a.get("type") or ""
        if atype_a != "ACTIVO":
            raise SemanticViolationError(
                "REGISTRO_ACTIVO", dep_acum_code,
                expected="tipo ACTIVO (cuenta de Dep. Acumulada — contra-activo)",
                got=atype_a,
                hint="El campo 'Dep. Acumulada' debe apuntar a una cuenta de tipo ACTIVO (1.x.x.xx)",
            )
    else:
        logger.warning(f"SemanticGuard: dep_acum_code={dep_acum_code} no encontrado en catálogo")


# ── Carga el mapa de cuentas desde la BD ─────────────────────────────

def load_accounts_map(db, tenant_id: str) -> dict[str, dict]:
    """
    Carga todas las cuentas del catálogo para un tenant.
    Devuelve {code: {account_type, name}}.
    """
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT code, account_type, name
        FROM accounts
        WHERE tenant_id = :tid
    """), {"tid": tenant_id}).fetchall()

    return {
        r.code: {"account_type": r.account_type, "name": r.name}
        for r in rows
    }
