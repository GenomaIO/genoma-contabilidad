"""
Assets — Activos Fijos (Router)
Genoma Contabilidad · NIIF PYMES Sección 17

Endpoints:
  GET  /assets               — Lista de activos del tenant
  GET  /assets/from-apertura — Detecta cuentas 1201.x en asiento de apertura
  POST /assets               — Registrar activo
  GET  /assets/{id}          — Detalle de un activo
  PATCH /assets/{id}         — Actualizar campos del activo
  POST /assets/{id}/depreciate — Generar asiento DRAFT de depreciación mensual
  POST /assets/{id}/baja    — Dar de baja
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from services.auth.database import get_session
from services.auth.security import get_current_user
from services.assets.models import (
    FixedAsset, AssetCategoria, AssetMetodo, AssetEstado
)

router = APIRouter(prefix="/assets", tags=["assets"])


def _uid(u: dict) -> str:
    return u.get("sub") or u.get("user_id") or u.get("id") or "unknown"


def _gen_uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ─────────────────────────────────────────────────────────────────

class AssetIn(BaseModel):
    categoria:          AssetCategoria = AssetCategoria.OTRO
    nombre:             str
    descripcion:        Optional[str] = None
    numero_serie:       Optional[str] = None
    ubicacion:          Optional[str] = None
    proveedor:          Optional[str] = None
    numero_factura:     Optional[str] = None

    # Cuentas contables — las 3 que necesita el generador de depreciación
    account_code:   str    # 1201.04 (costo)
    dep_acum_code:  str    # 1202.03 (dep. acumulada)
    dep_gasto_code: str    # 5301.01 (gasto depreciación)

    # Valoración NIIF
    fecha_adquisicion: str    # 'YYYY-MM-DD'
    fecha_disponible:  str    # NIIF: depreciación inicia aquí
    costo_historico:   float
    valor_residual:    float  = 0.0

    # ── Modo Tasa Fiscal (Decreto 18455-H, Art. 24) ──────────────────
    # Si tasa_anual > 0: el sistema infiere vida_util_meses y meses_usados.
    # Cuota mensual = costo_historico × tasa_anual% / 12 (constante sempre).
    tasa_anual:    Optional[float] = None  # ej: 10.0 para 10%

    # ── Modo NIIF Detallado ──────────────────────────────────────
    # Requerido cuando tasa_anual es None. Opcional con tasa (se recalculan).
    vida_util_meses:   Optional[int] = None

    metodo_depreciacion: AssetMetodo = AssetMetodo.LINEA_RECTA

    # Estado al momento del registro (para activos de apertura)
    dep_acum_apertura:     float = 0.0
    meses_usados_apertura: int   = 0

    # Link opcional a la línea de apertura
    apertura_line_id: Optional[str] = None


# Tasas fiscales máximas CR — Decreto 18455-H, Art. 24 Ley 7092
# Usadas para inferir vida_util y cuota en el Modo Tasa Fiscal.
TASAS_CR: dict[str, float] = {
    "INMUEBLE":   2.5,   # Edificios: 2.5% → 40 años
    "VEHICULO":   10.0,  # Vehículos: 10% → 10 años
    "EQUIPO":     10.0,  # Maquinaria: 10% → 10 años
    "MOBILIARIO": 10.0,  # Muebles: 10% → 10 años
    "INTANGIBLE": 10.0,  # Intangibles: 10% → 10 años
    "OTRO":       10.0,  # Default conservador
}


class BajaIn(BaseModel):
    motivo: str
    fecha:  str   # 'YYYY-MM-DD'


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _asset_to_dict(a: FixedAsset) -> dict:
    return {
        "id":              a.id,
        "tenant_id":       a.tenant_id,
        "categoria":       a.categoria.value if hasattr(a.categoria, 'value') else str(a.categoria),
        "nombre":          a.nombre,
        "descripcion":     a.descripcion,
        "numero_serie":    a.numero_serie,
        "ubicacion":       a.ubicacion,
        "proveedor":       a.proveedor,
        "numero_factura":  a.numero_factura,
        "account_code":    a.account_code,
        "dep_acum_code":   a.dep_acum_code,
        "dep_gasto_code":  a.dep_gasto_code,
        "fecha_adquisicion":    a.fecha_adquisicion,
        "fecha_disponible":     a.fecha_disponible,
        "costo_historico":      float(a.costo_historico),
        "valor_residual":       float(a.valor_residual),
        "vida_util_meses":      a.vida_util_meses,
        "tasa_anual":           float(a.tasa_anual) if a.tasa_anual else None,
        "metodo_depreciacion":  a.metodo_depreciacion.value if hasattr(a.metodo_depreciacion, 'value') else str(a.metodo_depreciacion),
        "dep_acum_apertura":    float(a.dep_acum_apertura),
        "meses_usados_apertura": a.meses_usados_apertura,
        "apertura_line_id":     a.apertura_line_id,
        "estado":               a.estado.value if hasattr(a.estado, 'value') else str(a.estado),
        "baja_fecha":           a.baja_fecha,
        "baja_motivo":          a.baja_motivo,
        "created_by":           a.created_by,
        "created_at":           a.created_at.isoformat() if a.created_at else None,
        # Calculados
        "depreciable_base":  a.depreciable_base,
        "meses_restantes":   a.meses_restantes,
        "cuota_mensual":     a.cuota_mensual,
        "valor_neto_contable": round(float(a.costo_historico) - float(a.dep_acum_apertura), 5),
    }


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("")
def list_assets(
    estado: Optional[str] = Query(None, description="ACTIVO | BAJA | VENDIDO"),
    categoria: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Lista de activos fijos del tenant con sus saldos calculados."""
    tenant_id = current_user["tenant_id"]
    q = db.query(FixedAsset).filter(FixedAsset.tenant_id == tenant_id)
    if estado:
        q = q.filter(FixedAsset.estado == estado)
    if categoria:
        q = q.filter(FixedAsset.categoria == categoria)
    assets = q.order_by(FixedAsset.account_code, FixedAsset.nombre).all()
    return {"assets": [_asset_to_dict(a) for a in assets], "total": len(assets)}


@router.get("/from-apertura")
def detect_from_apertura(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Detecta cuentas de activos fijos (1201.x) y depreciación acumulada (1202.x)
    en el asiento de apertura del tenant.

    Escenario A: la N4 tiene el saldo total (ej: 1201.04 = ₡13,555,935)
    Escenario B: el N5 tiene activos individuales (ej: 1201.04.01, 1201.04.02)

    Retorna candidatos de COSTO (DR 1201.x) y sus contrapartes DE DEP.ACUM (CR 1202.x).
    """
    tenant_id = current_user["tenant_id"]

    # Buscar asiento(s) de apertura POSTED
    apertura_rows = db.execute(text("""
        SELECT jl.id        AS line_id,
               jl.account_code,
               jl.debit,
               jl.credit,
               jl.description,
               je.id        AS entry_id,
               je.date      AS entry_date
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.entry_id
        WHERE je.tenant_id = :tid
          AND je.status    = 'POSTED'
          AND je.source    = 'APERTURA'
          AND (
            jl.account_code LIKE '12%'  -- PPE: costo (1201.x) y dep.acum (1202.x)
          )
        ORDER BY jl.account_code
    """), {"tid": tenant_id}).fetchall()

    # Ya registrados como activos (para evitar duplicados)
    already = {a.apertura_line_id for a in
               db.query(FixedAsset.apertura_line_id)
               .filter(FixedAsset.tenant_id == tenant_id,
                       FixedAsset.apertura_line_id.isnot(None)).all()
               if a.apertura_line_id}

    # Costo: 1201.xx → saldo DR (son activos)
    costo = []
    dep_acum = []
    for r in apertura_rows:
        code = r.account_code
        if code.startswith("1201"):          # costo — DR
            costo.append({
                "line_id":      r.line_id,
                "account_code": code,
                "debit":        float(r.debit or 0),
                "credit":       float(r.credit or 0),
                "description":  r.description,
                "entry_id":     r.entry_id,
                "entry_date":   r.entry_date,
                "already_registered": r.line_id in already,
                # Sugerencia de cuenta dep.acum: reemplaza '1201' → '1202'
                "suggested_dep_acum": code.replace("1201", "1202"),
            })
        elif code.startswith("1202"):        # dep. acumulada — CR
            dep_acum.append({
                "line_id":      r.line_id,
                "account_code": code,
                "debit":        float(r.debit or 0),
                "credit":       float(r.credit or 0),
                "description":  r.description,
            })

    return {
        "has_apertura":   len(apertura_rows) > 0,
        "costo_lines":    costo,
        "dep_acum_lines": dep_acum,
        "pending_count":  sum(1 for c in costo if not c["already_registered"]),
    }


@router.post("")
def create_asset(
    body: AssetIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Registrar un activo fijo nuevo o importado desde la apertura."""
    tenant_id = current_user["tenant_id"]

    # ── Modo Tasa Fiscal: inferir vida_util y meses_usados automáticamente ──
    tasa = body.tasa_anual
    vida_util = body.vida_util_meses
    meses_usados = body.meses_usados_apertura

    if tasa and tasa > 0:
        if tasa > 100 or tasa <= 0:
            raise HTTPException(400, "tasa_anual debe estar entre 0.1 y 100")
        cuota_constante = body.costo_historico * (tasa / 100) / 12
        vida_util  = round(12 * 100 / tasa)          # ej: 10% → 120 meses
        meses_usados = round(body.dep_acum_apertura / cuota_constante) if cuota_constante > 0 else 0
        meses_usados = max(0, min(meses_usados, vida_util - 1))  # clamp
    else:
        # Modo NIIF Detallado: validaciones manuales
        if not vida_util or vida_util <= 0:
            raise HTTPException(400, "vida_util_meses es requerido en Modo NIIF Detallado")

    # Validaciones comunes
    if body.costo_historico <= 0:
        raise HTTPException(400, "costo_historico debe ser > 0")
    if body.valor_residual < 0:
        raise HTTPException(400, "valor_residual no puede ser negativo")
    if body.valor_residual >= body.costo_historico:
        raise HTTPException(400, "valor_residual no puede ser >= costo_historico")
    if body.dep_acum_apertura < 0:
        raise HTTPException(400, "dep_acum_apertura no puede ser negativo")

    asset = FixedAsset(
        id                   = _gen_uuid(),
        tenant_id            = tenant_id,
        categoria            = body.categoria,
        nombre               = body.nombre,
        descripcion          = body.descripcion,
        numero_serie         = body.numero_serie,
        ubicacion            = body.ubicacion,
        proveedor            = body.proveedor,
        numero_factura       = body.numero_factura,
        account_code         = body.account_code,
        dep_acum_code        = body.dep_acum_code,
        dep_gasto_code       = body.dep_gasto_code,
        fecha_adquisicion    = body.fecha_adquisicion,
        fecha_disponible     = body.fecha_disponible,
        costo_historico      = body.costo_historico,
        valor_residual       = body.valor_residual,
        vida_util_meses      = vida_util or 120,
        tasa_anual           = tasa,
        metodo_depreciacion  = body.metodo_depreciacion,
        dep_acum_apertura    = body.dep_acum_apertura,
        meses_usados_apertura = meses_usados,
        apertura_line_id     = body.apertura_line_id,
        estado               = AssetEstado.ACTIVO,
        created_by           = _uid(current_user),
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return _asset_to_dict(asset)


@router.get("/{asset_id}")
def get_asset(
    asset_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    tenant_id = current_user["tenant_id"]
    a = db.query(FixedAsset).filter(
        FixedAsset.id == asset_id,
        FixedAsset.tenant_id == tenant_id,
    ).first()
    if not a:
        raise HTTPException(404, "Activo no encontrado")
    return _asset_to_dict(a)


@router.post("/{asset_id}/depreciate")
def generate_depreciation_entry(
    asset_id: str,
    period: str = Query(..., description="Período a depreciar. Formato: YYYY-MM"),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Genera un asiento DRAFT de depreciación mensual para este activo.

    El asiento:
      DR: dep_gasto_code  (Gasto Depreciación)  cuota_mensual
      CR: dep_acum_code   (Dep. Acumulada)      cuota_mensual

    El contador revisa y aprueba — nunca POSTED directo (auditabilidad).
    Regla NIIF: verifica que no se exceda costo_historico - valor_residual.
    """
    import json as _json
    tenant_id = current_user["tenant_id"]
    user_id   = _uid(current_user)

    a = db.query(FixedAsset).filter(
        FixedAsset.id == asset_id,
        FixedAsset.tenant_id == tenant_id,
    ).first()
    if not a:
        raise HTTPException(404, "Activo no encontrado")
    if a.estado != AssetEstado.ACTIVO:
        raise HTTPException(409, f"Activo en estado {a.estado.value} — no se puede depreciar")

    cuota = a.cuota_mensual
    if cuota <= 0:
        raise HTTPException(409, "Activo ya totalmente depreciado — cuota = 0")

    # Verificar período válido
    try:
        year, month = period.split("-")
        int(year); int(month)
        assert 1 <= int(month) <= 12
    except Exception:
        raise HTTPException(400, "period debe tener formato YYYY-MM")

    entry_date   = f"{period}-01"

    # Verificar si ya existe un asiento DRAFT/POSTED de depreciación en este período
    existing = db.execute(text("""
        SELECT je.id FROM journal_entries je
        WHERE je.tenant_id = :tid
          AND je.period     = :period
          AND je.source     = 'DEPRECIACION'
          AND je.status    != 'VOIDED'
          AND EXISTS (
            SELECT 1 FROM journal_lines jl
            WHERE jl.entry_id     = je.id
              AND jl.account_code = :gasto_code
          )
    """), {
        "tid": tenant_id, "period": period,
        "gasto_code": a.dep_gasto_code
    }).first()

    if existing:
        raise HTTPException(409,
            f"Ya existe un asiento de depreciación para {a.dep_gasto_code} en {period}")

    entry_id = _gen_uuid()
    now_iso  = datetime.now(timezone.utc).isoformat()
    desc     = f"Depreciación {a.nombre} — {period}"

    db.execute(text("""
        INSERT INTO journal_entries
            (id, tenant_id, period, date, description, status, source, created_by, created_at)
        VALUES
            (:id, :tid, :period, :date, :desc, 'DRAFT', 'DEPRECIACION', :uid, NOW())
    """), {
        "id": entry_id, "tid": tenant_id, "period": period,
        "date": entry_date, "desc": desc, "uid": user_id
    })

    # DR: Gasto Depreciación
    db.execute(text("""
        INSERT INTO journal_lines
            (id, entry_id, tenant_id, account_code, description, debit, credit, created_at)
        VALUES (:id, :eid, :tid, :code, :desc, :amt, 0, NOW())
    """), {
        "id": _gen_uuid(), "eid": entry_id, "tid": tenant_id,
        "code": a.dep_gasto_code, "desc": desc, "amt": cuota
    })

    # CR: Depreciación Acumulada
    db.execute(text("""
        INSERT INTO journal_lines
            (id, entry_id, tenant_id, account_code, description, debit, credit, created_at)
        VALUES (:id, :eid, :tid, :code, :desc, 0, :amt, NOW())
    """), {
        "id": _gen_uuid(), "eid": entry_id, "tid": tenant_id,
        "code": a.dep_acum_code, "desc": desc, "amt": cuota
    })

    db.commit()
    return {
        "entry_id":      entry_id,
        "period":        period,
        "activo":        a.nombre,
        "cuota":         cuota,
        "gasto_account": a.dep_gasto_code,
        "acum_account":  a.dep_acum_code,
        "status":        "DRAFT",
        "message":       f"Asiento de depreciación generado — revisa y aprueba en el Diario",
    }


@router.post("/{asset_id}/baja")
def dar_de_baja(
    asset_id: str,
    body: BajaIn,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """Dar de baja un activo. El activo queda en estado BAJA — no se elimina."""
    tenant_id = current_user["tenant_id"]
    a = db.query(FixedAsset).filter(
        FixedAsset.id == asset_id,
        FixedAsset.tenant_id == tenant_id,
    ).first()
    if not a:
        raise HTTPException(404, "Activo no encontrado")
    if a.estado != AssetEstado.ACTIVO:
        raise HTTPException(409, f"Activo ya en estado {a.estado.value}")

    a.estado      = AssetEstado.BAJA
    a.baja_fecha  = body.fecha
    a.baja_motivo = body.motivo
    db.commit()
    return {"message": f"Activo '{a.nombre}' dado de baja", "id": a.id, "estado": "BAJA"}
