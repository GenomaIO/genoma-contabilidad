"""
Assets — Activos Fijos (Models)
Genoma Contabilidad · Motor Contable NIIF PYMES Sección 17

Reglas de Oro aplicadas:
- DECIMAL(18,5) para montos — nunca FLOAT (Regla de Oro #3)
- tenant_id en cada tabla (Regla de Oro #1)
- Append-only: bajas = cambio de estado, nunca DELETE real
- Depreciación NIIF: inicia en fecha_disponible, no en fecha_adquisicion
"""
import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Column, String, Integer, Boolean, DateTime,
    Enum, Text, Numeric, Index
)

from services.auth.models import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class AssetCategoria(str, enum.Enum):
    """
    Categorías de activos fijos según NIIF PYMES Sección 17.
    Cada categoría tiene cuentas contables típicas asociadas.
    """
    INMUEBLE   = "INMUEBLE"    # 1201.01-.03 Terrenos, Edificios
    VEHICULO   = "VEHICULO"    # 1201.04 Vehículos y Medios de Transporte
    EQUIPO     = "EQUIPO"      # 1201.03 Equipo y Maquinaria
    MOBILIARIO = "MOBILIARIO"  # 1201.05 Mobiliario y Equipo de Oficina
    INTANGIBLE = "INTANGIBLE"  # 1300.x Activos Intangibles
    OTRO       = "OTRO"


class AssetMetodo(str, enum.Enum):
    """
    Métodos de depreciación permitidos por NIIF PYMES Sección 17.16.
    LINEA_RECTA es el más común para PYMES CR.
    """
    LINEA_RECTA          = "LINEA_RECTA"          # Cuota constante mensual
    SALDO_DECRECIENTE    = "SALDO_DECRECIENTE"    # Tasa % sobre valor neto residual
    UNIDADES_PRODUCCION  = "UNIDADES_PRODUCCION"  # Por unidades producidas (no automático)


class AssetEstado(str, enum.Enum):
    ACTIVO  = "ACTIVO"   # En uso y depreciable
    BAJA    = "BAJA"     # Dado de baja (obsoleto, destruido)
    VENDIDO = "VENDIDO"  # Vendido — puede generar ganancia/pérdida de capital


# ─────────────────────────────────────────────────────────────────
# FixedAsset — Ficha del Activo Fijo
# ─────────────────────────────────────────────────────────────────

class FixedAsset(Base):
    """
    Activo Fijo individual.

    PATRÓN DE DETECCIÓN (Mass-Add desde Apertura):
    - account_code apunta a la cuenta GL de COSTO (1201.xx o child N5)
    - dep_acum_account apunta a la cuenta de depreciación acumulada (1202.xx)
    - dep_gasto_account apunta al gasto de depreciación (5xxx)
    - apertura_line_id: link opcional a la línea del asiento de apertura

    NIIF PYMES Sección 17.16:
    - Depreciación inicia en fecha_disponible (cuando está listo para usar)
    - Se detiene cuando valor_neto_contable = valor_residual
    - Componentización: activos con partes significativas deben depreciarse por separado
    """
    __tablename__ = "fixed_assets"
    __table_args__ = (
        Index("idx_fa_tenant",    "tenant_id"),
        Index("idx_fa_tenant_st", "tenant_id", "estado"),
    )

    id          = Column(String(36), primary_key=True, default=gen_uuid)
    tenant_id   = Column(String(36), nullable=False, index=True)

    # ── Clasificación ──────────────────────────────────────────────
    categoria   = Column(Enum(AssetCategoria), nullable=False,
                         default=AssetCategoria.OTRO)

    # ── Descripción del activo ─────────────────────────────────────
    nombre         = Column(String(200), nullable=False)           # "Toyota Hilux 2024"
    descripcion    = Column(Text,        nullable=True)
    numero_serie   = Column(String(100), nullable=True)            # Placa/chassis/serie
    ubicacion      = Column(String(100), nullable=True)            # Sucursal/bodega
    proveedor      = Column(String(200), nullable=True)
    numero_factura = Column(String(100), nullable=True)            # Referencia compra

    # ── Mapeo Contable — las 3 cuentas que necesita el generador ──
    #    account_code   → COSTO histórico      (1201.xx)
    #    dep_acum_code  → Dep. Acumulada       (1202.xx)
    #    dep_gasto_code → Gasto Depreciación   (5xxx.xx)
    account_code    = Column(String(20), nullable=False)  # cuenta GL de costo
    dep_acum_code   = Column(String(20), nullable=False)  # cuenta dep. acumulada
    dep_gasto_code  = Column(String(20), nullable=False)  # cuenta gasto depreciación

    # ── Valoración NIIF ────────────────────────────────────────────
    fecha_adquisicion = Column(String(10), nullable=False)   # ISO date 'YYYY-MM-DD'
    fecha_disponible  = Column(String(10), nullable=False)   # NIIF: depreciación inicia aquí
    costo_historico   = Column(Numeric(18, 5), nullable=False)
    valor_residual    = Column(Numeric(18, 5), nullable=False, default=0)
    vida_util_meses   = Column(Integer, nullable=False)       # total desde adquisición

    metodo_depreciacion = Column(Enum(AssetMetodo), nullable=False,
                                 default=AssetMetodo.LINEA_RECTA)

    # ── Estado al registrar (para activos de apertura) ────────────
    # dep_acum_apertura: saldo de dep. acum. en el asiento de apertura.
    # meses_usados_apertura: cuántos meses de vida útil ya estaban consumidos.
    # El motor de depreciación usa estos valores para calcular la cuota residual.
    dep_acum_apertura   = Column(Numeric(18, 5), nullable=False, default=0)
    meses_usados_apertura = Column(Integer, nullable=False, default=0)

    # ── Link a apertura (Mass-Add desde apertura) ─────────────────
    apertura_line_id = Column(String(36), nullable=True)   # FK soft a journal_lines.id

    # ── Estado y control ──────────────────────────────────────────
    estado      = Column(Enum(AssetEstado),  nullable=False, default=AssetEstado.ACTIVO)
    baja_fecha  = Column(String(10), nullable=True)   # fecha de la baja
    baja_motivo = Column(Text,       nullable=True)

    created_by  = Column(String(36), nullable=False)
    created_at  = Column(DateTime(timezone=True), default=now_utc, nullable=False)
    updated_at  = Column(DateTime(timezone=True), onupdate=now_utc, nullable=True)

    # ── Propiedades calculadas (no persistidas) ───────────────────
    @property
    def depreciable_base(self) -> float:
        """Valor que queda por depreciar a partir del registro."""
        base = float(self.costo_historico) - float(self.valor_residual)
        ya_dep = float(self.dep_acum_apertura)
        return max(base - ya_dep, 0)

    @property
    def meses_restantes(self) -> int:
        """Meses de vida útil que quedan por depreciar."""
        return max(self.vida_util_meses - self.meses_usados_apertura, 0)

    @property
    def cuota_mensual(self) -> float:
        """Cuota mensual LINEA_RECTA. Devuelve 0 si ya está totalmente depreciado."""
        if self.metodo_depreciacion == AssetMetodo.LINEA_RECTA:
            if self.meses_restantes == 0:
                return 0.0
            return round(self.depreciable_base / self.meses_restantes, 5)
        # SALDO_DECRECIENTE y UNIDADES_PRODUCCION requieren input manual adicional
        return 0.0

    def __repr__(self):
        return (
            f"<FixedAsset {self.nombre!r} [{self.estado}] "
            f"costo={self.costo_historico} tenant={self.tenant_id}>"
        )
