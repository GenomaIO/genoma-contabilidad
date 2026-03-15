"""
services/tax/router.py
Genoma Contabilidad — Módulo Fiscal
Perfil Fiscal + Tramos de Renta (por año) + Proyección de Impuesto sobre la Renta CR
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.auth.database import get_session
from services.auth.router import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tax", tags=["tax"])


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────

class FiscalProfileIn(BaseModel):
    taxpayer_type: str          # 'PJ' | 'PF'
    is_large_taxpayer: bool = False
    fiscal_year_end_month: int = 9   # 9 = Septiembre (estándar CR)
    prorrata_iva: float = 1.0        # 0.0-1.0: % de IVA acreditable (Art. 31 Ley 9635)


class TaxBracket(BaseModel):
    taxpayer_type: Optional[str] = None  # redundante si viene en TaxBracketsIn; se acepta pero no es requerido
    income_from: float
    income_to: Optional[float]  # None = sin límite superior
    rate: float                 # 0.05 = 5%


class TaxBracketsIn(BaseModel):
    fiscal_year: int
    taxpayer_type: str
    brackets: list[TaxBracket]


# ─────────────────────────────────────────────
# Tramos 2026 oficiales (Decreto 45333-H)
# Solo se usan para el pre-llenado. No son constantes de lógica.
# ─────────────────────────────────────────────
SEED_2026 = [
    # Personas Jurídicas
    {"taxpayer_type": "PJ", "income_from": 0,          "income_to": 5_621_000,  "rate": 0.05},
    {"taxpayer_type": "PJ", "income_from": 5_621_000,  "income_to": 8_433_000,  "rate": 0.10},
    {"taxpayer_type": "PJ", "income_from": 8_433_000,  "income_to": 11_243_000, "rate": 0.15},
    {"taxpayer_type": "PJ", "income_from": 11_243_000, "income_to": None,       "rate": 0.20},
    # PJ Grande contribuyente (renta bruta > ₡119,174,000) → tasa fija 30%
    {"taxpayer_type": "PJ_GRANDE", "income_from": 0, "income_to": None, "rate": 0.30},
    # Personas Físicas con Actividad Lucrativa
    {"taxpayer_type": "PF", "income_from": 0,           "income_to": 6_244_000,  "rate": 0.00},
    {"taxpayer_type": "PF", "income_from": 6_244_000,   "income_to": 8_329_000,  "rate": 0.10},
    {"taxpayer_type": "PF", "income_from": 8_329_000,   "income_to": 10_414_000, "rate": 0.15},
    {"taxpayer_type": "PF", "income_from": 10_414_000,  "income_to": 20_872_000, "rate": 0.20},
    {"taxpayer_type": "PF", "income_from": 20_872_000,  "income_to": None,       "rate": 0.25},
]


# ─────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────

def _get_profile(tenant_id: str, db: Session) -> dict | None:
    row = db.execute(
        text("SELECT * FROM fiscal_profiles WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    ).mappings().first()
    return dict(row) if row else None


def get_prorrata(tenant_id: str, db: Session) -> float:
    """
    Retorna el factor de prorrata IVA del tenant (Art. 31 Ley 9635).
    - 1.0 = 100% acreditable (default, empresas con actividad 100% gravada)
    - 0.7 = 70% acreditable (empresa con 70% ventas gravadas / 30% exentas)
    - 0.0 = 0% acreditable (empresa 100% exenta)
    Importado por journal_mapper_v2 para aplicar la regla línea a línea.
    """
    row = db.execute(
        text("SELECT prorrata_iva FROM fiscal_profiles WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    ).fetchone()
    if row and row[0] is not None:
        val = float(row[0])
        return max(0.0, min(1.0, val))   # clamp 0.0-1.0 por seguridad
    return 1.0   # default: 100% acreditable


def _get_brackets(tenant_id: str, fiscal_year: int, taxpayer_type: str, db: Session) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT income_from, income_to, rate
            FROM tax_brackets
            WHERE tenant_id = :tid AND fiscal_year = :yr AND taxpayer_type = :tp
            ORDER BY income_from ASC
        """),
        {"tid": tenant_id, "yr": fiscal_year, "tp": taxpayer_type},
    ).mappings().all()
    return [dict(r) for r in rows]


def _apply_brackets(utilidad: float, brackets: list[dict]) -> dict:
    """
    Aplica tramos progresivos sobre la utilidad neta fiscal proyectada.
    Retorna el impuesto calculado + desglose por tramo.
    """
    renta_total = 0.0
    desglose = []

    for b in sorted(brackets, key=lambda x: x["income_from"]):
        desde = float(b["income_from"])
        hasta = float(b["income_to"]) if b["income_to"] is not None else float("inf")
        tasa  = float(b["rate"])

        if utilidad <= desde:
            break

        base = min(utilidad, hasta) - desde
        impuesto_tramo = base * tasa
        renta_total += impuesto_tramo

        desglose.append({
            "desde": desde,
            "hasta": b["income_to"],
            "tasa_pct": round(tasa * 100, 2),
            "base_gravable": round(base, 2),
            "impuesto": round(impuesto_tramo, 2),
        })

    return {"total": round(renta_total, 2), "desglose": desglose}



# ─────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────

@router.get("/prorrata-calc")
def calcular_prorrata_automatica(
    fiscal_year: int = None,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Calcula automáticamente el factor de prorrata IVA (Art. 31 Ley 9635)
    a partir del Libro Diario del tenant.

    Fórmula: prorrata = CR_gravadas / (CR_gravadas + CR_exentas)
    - Cuentas gravadas:  4101 (ventas bienes), 4102 (ventas servicios)
    - Cuentas exentas:   4103 (ventas exentas / no sujetas)

    Si no hay datos suficientes, retorna 1.0 (100% acreditable) como default
    seguro junto con un mensaje de advertencia.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    # Año fiscal: default al año en curso
    year = fiscal_year or date.today().year

    try:
        # Sumar CRs por prefijo de cuenta en el período fiscal
        row = db.execute(text("""
            SELECT
                COALESCE(SUM(CASE
                    WHEN REPLACE(REPLACE(jl.account_code, '.', ''), '-', '') LIKE '4101%'
                      OR REPLACE(REPLACE(jl.account_code, '.', ''), '-', '') LIKE '4102%'
                    THEN jl.credit ELSE 0 END), 0) AS ventas_gravadas,
                COALESCE(SUM(CASE
                    WHEN REPLACE(REPLACE(jl.account_code, '.', ''), '-', '') LIKE '4103%'
                    THEN jl.credit ELSE 0 END), 0) AS ventas_exentas
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE jl.tenant_id   = :tid
              AND je.period      LIKE :yr
              AND je.status      != 'DELETED'
        """), {"tid": tenant_id, "yr": f"{year}-%"}).fetchone()

        gravadas = float(row[0]) if row else 0.0
        exentas  = float(row[1]) if row else 0.0
        total    = gravadas + exentas

        if total < 1.0:
            # Sin datos suficientes — no podemos calcular
            return {
                "ok": True,
                "prorrata": 1.0,
                "porcentaje": 100.0,
                "ventas_gravadas": 0.0,
                "ventas_exentas": 0.0,
                "total_ventas": 0.0,
                "fiscal_year": year,
                "origen": "SIN_DATOS",
                "advertencia": (
                    f"No hay ventas registradas para el año {year}. "
                    "Se usa 100% como estimado seguro (Art. 35.2 Ley 9635)."
                ),
            }

        prorrata   = round(gravadas / total, 4)
        porcentaje = round(prorrata * 100, 2)

        logger.info(
            f"📊 prorrata-calc tenant={tenant_id[:8]} year={year} "
            f"gravadas={gravadas:,.0f} exentas={exentas:,.0f} → {porcentaje}%"
        )

        return {
            "ok": True,
            "prorrata": prorrata,
            "porcentaje": porcentaje,
            "ventas_gravadas": round(gravadas, 2),
            "ventas_exentas": round(exentas, 2),
            "total_ventas": round(total, 2),
            "fiscal_year": year,
            "origen": "LIBRO_DIARIO",
            "advertencia": None,
        }

    except Exception as ex:
        logger.error(f"❌ prorrata-calc error: {ex}")
        return {
            "ok": False,
            "prorrata": 1.0,
            "porcentaje": 100.0,
            "fiscal_year": year,
            "origen": "ERROR",
            "advertencia": str(ex),
        }


@router.get("/fiscal-profile")
def get_fiscal_profile(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Retorna el perfil fiscal del tenant activo."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    profile = _get_profile(tenant_id, db)
    if not profile:
        return {"configured": False}

    return {"configured": True, **profile}


@router.put("/fiscal-profile")
def save_fiscal_profile(
    body: FiscalProfileIn,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Crea o actualiza el perfil fiscal del tenant."""
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    if body.taxpayer_type not in ("PJ", "PF"):
        raise HTTPException(400, "taxpayer_type debe ser 'PJ' o 'PF'")
    if not 1 <= body.fiscal_year_end_month <= 12:
        raise HTTPException(400, "fiscal_year_end_month debe estar entre 1 y 12")
    if not 0.0 <= body.prorrata_iva <= 1.0:
        raise HTTPException(400, "prorrata_iva debe estar entre 0.0 y 1.0")

    db.execute(
        text("""
            INSERT INTO fiscal_profiles
                (tenant_id, taxpayer_type, is_large_taxpayer, fiscal_year_end_month, prorrata_iva)
            VALUES
                (:tid, :tp, :large, :month, :prorrata)
            ON CONFLICT (tenant_id) DO UPDATE SET
                taxpayer_type         = EXCLUDED.taxpayer_type,
                is_large_taxpayer     = EXCLUDED.is_large_taxpayer,
                fiscal_year_end_month = EXCLUDED.fiscal_year_end_month,
                prorrata_iva          = EXCLUDED.prorrata_iva,
                updated_at            = NOW()
        """),
        {
            "tid":      tenant_id,
            "tp":       body.taxpayer_type,
            "large":    body.is_large_taxpayer,
            "month":    body.fiscal_year_end_month,
            "prorrata": body.prorrata_iva,
        },
    )
    db.commit()
    logger.info(f"✅ Perfil fiscal guardado para tenant {tenant_id} (prorrata={body.prorrata_iva})")
    return {"ok": True, "message": "Perfil fiscal guardado"}


@router.get("/tax-brackets/years")
def get_available_years(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Lista los años fiscales que ya tienen tramos cargados."""
    tenant_id = current_user.get("tenant_id")
    rows = db.execute(
        text("""
            SELECT DISTINCT fiscal_year
            FROM tax_brackets
            WHERE tenant_id = :tid
            ORDER BY fiscal_year DESC
        """),
        {"tid": tenant_id},
    ).fetchall()
    return {"years": [r[0] for r in rows]}


@router.get("/tax-brackets")
def get_tax_brackets(
    year: int,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """Retorna los tramos de un año fiscal específico."""
    tenant_id = current_user.get("tenant_id")

    # Agrupa por tipo
    result = {}
    for tp in ("PJ", "PF", "PJ_GRANDE"):
        brackets = _get_brackets(tenant_id, year, tp, db)
        if brackets:
            result[tp] = brackets

    if not result:
        return {"fiscal_year": year, "configured": False, "brackets": {}}

    return {"fiscal_year": year, "configured": True, "brackets": result}


@router.put("/tax-brackets")
def save_tax_brackets(
    body: TaxBracketsIn,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Guarda (reemplaza) los tramos de renta de un año fiscal para un tipo de contribuyente.
    Elimina los tramos previos del mismo año+tipo y los reinserta.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    if not body.brackets:
        raise HTTPException(400, "Debe enviar al menos un tramo")

    # Eliminar tramos anteriores del mismo año+tipo
    db.execute(
        text("""
            DELETE FROM tax_brackets
            WHERE tenant_id = :tid AND fiscal_year = :yr AND taxpayer_type = :tp
        """),
        {"tid": tenant_id, "yr": body.fiscal_year, "tp": body.taxpayer_type},
    )

    for b in body.brackets:
        db.execute(
            text("""
                INSERT INTO tax_brackets
                    (tenant_id, fiscal_year, taxpayer_type, income_from, income_to, rate)
                VALUES (:tid, :yr, :tp, :from_, :to_, :rate)
            """),
            {
                "tid":   tenant_id,
                "yr":    body.fiscal_year,
                "tp":    body.taxpayer_type,
                "from_": b.income_from,
                "to_":   b.income_to,
                "rate":  b.rate,
            },
        )

    db.commit()
    logger.info(f"✅ Tramos {body.fiscal_year}/{body.taxpayer_type} guardados para tenant {tenant_id}")
    return {"ok": True, "message": f"Tramos {body.fiscal_year} guardados correctamente"}


@router.post("/tax-brackets/prefill-2026")
def prefill_2026(
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Pre-llena los tramos oficiales 2026 (Decreto 45333-H) para todos los tipos.
    Solo inserta si el año 2026 no tiene datos — idempotente.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    # Verificar si ya existen
    existing = db.execute(
        text("SELECT COUNT(*) FROM tax_brackets WHERE tenant_id = :tid AND fiscal_year = 2026"),
        {"tid": tenant_id},
    ).scalar()

    if existing and existing > 0:
        return {"ok": True, "message": "Los tramos 2026 ya existen. No se sobreescribieron.", "were_existing": True}

    for b in SEED_2026:
        db.execute(
            text("""
                INSERT INTO tax_brackets
                    (tenant_id, fiscal_year, taxpayer_type, income_from, income_to, rate)
                VALUES (:tid, 2026, :tp, :from_, :to_, :rate)
                ON CONFLICT DO NOTHING
            """),
            {
                "tid":   tenant_id,
                "tp":    b["taxpayer_type"],
                "from_": b["income_from"],
                "to_":   b["income_to"],
                "rate":  b["rate"],
            },
        )
    db.commit()
    logger.info(f"✅ Pre-llenado tramos 2026 para tenant {tenant_id}")
    return {"ok": True, "message": "Tramos 2026 pre-llenados con datos oficiales (Decreto 45333-H)", "were_existing": False}


@router.get("/renta-projection")
def get_renta_projection(
    year: int | None = None,
    db: Session = Depends(get_session),
    current_user: dict = Depends(get_current_user),
):
    """
    Calcula la proyección de Impuesto sobre la Renta al cierre del año fiscal.

    Lógica:
    1. Lee la utilidad neta acumulada de journal_lines (cuentas 4xxx - 5xxx).
    2. Proyecta a 12 meses según el mes actual.
    3. Aplica los tramos del año configurados por el tenant.
    4. Retorna estimado anual + provisión mensual sugerida.
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(400, "tenant_id no encontrado en token")

    # Año fiscal a calcular
    target_year = year or date.today().year

    # Leer perfil fiscal
    profile = _get_profile(tenant_id, db)
    if not profile:
        raise HTTPException(404, "Perfil fiscal no configurado. Ve a Configuración → Perfil Fiscal.")

    taxpayer_type = profile["taxpayer_type"]
    is_large = profile.get("is_large_taxpayer", False)

    # Si es Gran Contribuyente, usar tipo especial
    effective_type = "PJ_GRANDE" if (taxpayer_type == "PJ" and is_large) else taxpayer_type

    # Obtener tramos para el año
    brackets = _get_brackets(tenant_id, target_year, effective_type, db)
    if not brackets:
        raise HTTPException(404, f"No hay tramos de renta configurados para {target_year}/{effective_type}. "
                                 f"Ve a Configuración → Perfil Fiscal → Tramos de Renta.")

    # ── Calcular Utilidad Neta del ledger ──────────────────────────────────
    # Ingresos (4xxx) - Gastos (5xxx) en el año fiscal
    # Solo asientos POSTED
    period_prefix = f"{target_year}-%"

    utilidad_row = db.execute(
        text("""
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN jl.account_code LIKE '4%' THEN (jl.credit - jl.debit)
                        WHEN jl.account_code LIKE '5%' THEN (jl.debit  - jl.credit)
                        ELSE 0
                    END
                ), 0) AS utilidad_neta
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.entry_id
            WHERE jl.tenant_id = :tid
              AND je.status    = 'POSTED'
              AND je.period    LIKE :prefix
        """),
        {"tid": tenant_id, "prefix": period_prefix},
    ).first()

    utilidad_acumulada = float(utilidad_row[0]) if utilidad_row else 0.0

    # ── Proyección anual ────────────────────────────────────────────────────
    mes_actual = date.today().month
    utilidad_proyectada = (utilidad_acumulada / mes_actual) * 12 if mes_actual > 0 else 0.0

    # Si la utilidad proyectada es negativa, no hay impuesto
    if utilidad_proyectada <= 0:
        return {
            "fiscal_year": target_year,
            "taxpayer_type": effective_type,
            "mes_actual": mes_actual,
            "utilidad_acumulada": round(utilidad_acumulada, 2),
            "utilidad_proyectada_anual": round(utilidad_proyectada, 2),
            "renta_estimada_anual": 0.0,
            "provision_mensual_sugerida": 0.0,
            "tasa_efectiva_pct": 0.0,
            "desglose_tramos": [],
            "nota": "Utilidad proyectada negativa o cero — sin impuesto estimado.",
        }

    # Aplicar tramos
    calculo = _apply_brackets(utilidad_proyectada, brackets)
    renta_anual = calculo["total"]
    provision_mensual = renta_anual / 12
    tasa_efectiva = (renta_anual / utilidad_proyectada * 100) if utilidad_proyectada > 0 else 0

    return {
        "fiscal_year":             target_year,
        "taxpayer_type":           effective_type,
        "mes_actual":              mes_actual,
        "utilidad_acumulada":      round(utilidad_acumulada, 2),
        "utilidad_proyectada_anual": round(utilidad_proyectada, 2),
        "renta_estimada_anual":    round(renta_anual, 2),
        "provision_mensual_sugerida": round(provision_mensual, 2),
        "tasa_efectiva_pct":       round(tasa_efectiva, 2),
        "desglose_tramos":         calculo["desglose"],
        "nota": (
            f"Proyección basada en {mes_actual} mes(es) transcurrido(s). "
            f"Tramos {target_year} aplicados según Perfil Fiscal del tenant."
        ),
    }
