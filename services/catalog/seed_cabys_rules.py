"""
catalog/seed_cabys_rules.py
════════════════════════════════════════════════════════════
Siembra cabys_account_rules con reglas por PREFIJO (2 dígitos CABYS)
para todos los tenants con catálogo activo.

Filosofía:
  - Una regla por prefijo CABYS (los primeros 2 dígitos definen el sector)
  - Mapea al grupo de cuenta NIIF más apropiado del catálogo estándar CR
  - 100% idempotente: ON CONFLICT (tenant_id, cabys_prefix) DO NOTHING
  - prioridad=5 (más baja que reglas MANUALES del contador, que van a 10)
  - NO sobreescribe reglas exactas (cabys_code) — esas tienen prioridad absoluta

Mapa CABYS 2d → Cuenta NIIF (basado en catálogo CABYS oficial Hacienda CR):
  01-09: Productos alimenticios y bebidas        → 5101 Costo de Mercancías
  11-15: Productos textiles y calzado            → 5101 Costo de Mercancías
  16-19: Papel, plásticos, químicos              → 5213 Materiales y Suministros
  31-34: Metales, minerales, materiales          → 5213 Materiales y Suministros
  36-39: Muebles, equipo doméstico               → 5213 Materiales y Suministros
  41:    Equipos eléctricos/electrónica          → 5201 (con asset_flag=True)
  42:    Vehículos y transporte                  → 1201.04 (activo, asset_flag=True)
  43:    Maquinaria y equipo industrial          → 1201.03 (activo, asset_flag=True)
  44:    Equipo de oficina y cómputo             → 1201.06 (activo, asset_flag=True)
  45-49: Otros bienes de capital                → 5213 Materiales y Suministros
  51-59: Servicios generales                    → 5209 Honorarios y Servicios Prof.
  61-69: Servicios de salud                     → 5209 Honorarios y Servicios Prof.
  71-79: Servicios de educación y capacitación  → 5209 Honorarios y Servicios Prof.
  81-84: Servicios de telecomunicaciones/TI     → 5214 Servicios Tecnología
  85-89: Servicios financieros y seguros        → 5208 Seguros / 5301 Intereses
  91:    Servicios públicos (agua, luz, tel)    → 5204 Electricidad Agua Teléfono
  92-99: Otros servicios / sin clasificar       → 5209 Honorarios y Servicios Prof.

Reglas de Oro:
  - Nunca touches reglas existentes (DO NOTHING en conflicto)
  - Siempre tenant_id en cada fila (aislamiento multi-tenant)
  - prioridad=5 → el contador puede sobrescribir con regla manual (prioridad=10)
"""
import logging
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ── Mapa prefijo CABYS (2 dígitos) → (account_code, asset_flag, min_amount) ──
# account_code: cuenta del catálogo NIIF estándar CR
# asset_flag:   True si el ítem puede ser un activo fijo (revisar monto)
# min_amount:   monto mínimo en CRC para marcar como activo (Art. 8 Ley Renta 7092)
# Ref: Decreto 18455-H — umbral activo fijo = ¢215,000 (ajustado anualmente)
_UMBRAL_ACTIVO_CRC = 215_000.0

CABYS_PREFIX_RULES = [
    # ─── Mercancías y bienes de consumo (01-39) ────────────────────────────
    ("01", "5101", False, None),   # Animales vivos, carne, pescado
    ("02", "5101", False, None),   # Lácteos y huevos
    ("03", "5101", False, None),   # Aceites y grasas
    ("04", "5101", False, None),   # Cereales, harinas, almidones
    ("05", "5101", False, None),   # Frutas y vegetales preparados
    ("06", "5101", False, None),   # Azúcar, cacao, confitería
    ("07", "5101", False, None),   # Preparados alimenticios
    ("08", "5101", False, None),   # Bebidas (alcohol/sin alcohol)
    ("09", "5101", False, None),   # Tabaco y afines
    ("11", "5101", False, None),   # Textiles, fibras
    ("12", "5101", False, None),   # Confecciones, ropa
    ("13", "5101", False, None),   # Cuero y calzado
    ("14", "5213", False, None),   # Papel, cartón, impresos
    ("15", "5213", False, None),   # Plásticos, caucho
    ("16", "5213", False, None),   # Productos químicos
    ("17", "5213", False, None),   # Farmacéuticos
    ("18", "5213", False, None),   # Cosméticos, higiene
    ("19", "5213", False, None),   # Limpieza, detergentes
    ("21", "5213", False, None),   # Materiales de construcción
    ("22", "5213", False, None),   # Vidrio y cerámica
    ("23", "5213", False, None),   # Hierro, acero
    ("24", "5213", False, None),   # Metales preciosos
    ("25", "5213", False, None),   # Otros metales
    ("31", "5213", False, None),   # Minerales
    ("32", "5213", False, None),   # Combustibles sólidos
    ("33", "5205", False, None),   # Combustibles líquidos / lubricantes
    ("34", "5213", False, None),   # Gas, electricidad como product
    ("36", "5213", False, None),   # Muebles y enseres
    ("37", "5213", False, None),   # Equipo doméstico menor
    ("38", "5213", False, None),   # Instrumentos musicales, juguetes
    ("39", "5213", False, None),   # Artículos de papel y oficina
    # ─── Bienes de capital — pueden ser activos fijos (41-44) ─────────────
    ("41", "1201.06", True,  _UMBRAL_ACTIVO_CRC),  # Equipo electrónico/cómputo → PPE Cómputo
    ("42", "1201.04", True,  _UMBRAL_ACTIVO_CRC),  # Vehículos → PPE Vehículos
    ("43", "1201.03", True,  _UMBRAL_ACTIVO_CRC),  # Maquinaria industrial → PPE Maquinaria
    ("44", "1201.05", True,  _UMBRAL_ACTIVO_CRC),  # Equipo de oficina → PPE Mobiliario/Oficina
    ("45", "5213", False, None),   # Otros instrumentos científicos / ópticos
    ("46", "5213", False, None),   # Armas y municiones
    ("47", "5213", False, None),   # Otros bienes manufacturados
    ("48", "5213", False, None),   # Residuos y desechos
    ("49", "5213", False, None),   # Otros productos NCP
    # ─── Servicios generales y profesionales (51-79) ──────────────────────
    ("51", "5209", False, None),   # Servicios de mantenimiento y reparación
    ("52", "5209", False, None),   # Servicios de instalación
    ("55", "5209", False, None),   # Servicios de alojamiento y turismo
    ("56", "5209", False, None),   # Servicios de alimentación (catering)
    ("61", "5209", False, None),   # Servicios de salud humana
    ("62", "5209", False, None),   # Servicios veterinarios
    ("63", "5209", False, None),   # Servicios sociales y comunitarios
    ("69", "5209", False, None),   # Otros servicios de salud
    ("71", "5209", False, None),   # Servicios de educación y capacitación
    ("72", "5212", False, None),   # Servicios de I+D
    ("73", "5209", False, None),   # Servicios jurídicos y contables
    ("74", "5209", False, None),   # Servicios técnicos y consultoría
    ("75", "5206", False, None),   # Publicidad y mercadeo
    ("76", "5203", False, None),   # Servicios de arrendamiento (alquiler)
    ("77", "5209", False, None),   # Servicios de empleo / RR.HH.
    ("78", "5209", False, None),   # Servicios de agencias de viaje / transporte
    ("79", "5209", False, None),   # Servicios de seguridad y limpieza
    # ─── Telecomunicaciones, TI y servicios digitales (81-84) ─────────────
    ("81", "5204", False, None),   # Telecomunicaciones básicas (voz, datos)
    ("82", "5214", False, None),   # Servicios de TI / software / cloud
    ("83", "5214", False, None),   # Servicios de información y datos
    ("84", "5214", False, None),   # Servicios audiovisuales y entretenimiento
    # ─── Servicios financieros y seguros (85-89) ──────────────────────────
    ("85", "5301", False, None),   # Servicios financieros — intereses/comisiones
    ("86", "5208", False, None),   # Seguros (primas)
    ("87", "5301", False, None),   # Servicios de pensiones / fondos
    ("88", "5209", False, None),   # Servicios inmobiliarios (gestión)
    ("89", "5209", False, None),   # Otros servicios financieros
    # ─── Servicios públicos y misceláneos (91-99) ─────────────────────────
    ("91", "5204", False, None),   # Servicios públicos (agua, electricidad, ICE)
    ("92", "5209", False, None),   # Servicios culturales, recreacionales
    ("93", "5209", False, None),   # Deportes y recreación
    ("94", "5209", False, None),   # Servicios de membresías / afiliaciones
    ("95", "5207", False, None),   # Servicios de reparación de bienes del hogar
    ("96", "5209", False, None),   # Otros servicios personales
    ("97", "5209", False, None),   # Servicios domésticos
    ("98", "5209", False, None),   # Servicios prestados por organismos
    ("99", "5209", False, None),   # Servicios no clasificados en otra parte
]


def seed_cabys_rules_for_tenant(tenant_id: str, db: Session) -> int:
    """
    Siembra las reglas CABYS por prefijo para un tenant.
    Idempotente: ON CONFLICT (tenant_id, cabys_prefix) DO NOTHING.
    Retorna el número de filas insertadas (0 si ya existían todas).
    """
    inserted = 0
    for prefix, account_code, asset_flag, min_amount in CABYS_PREFIX_RULES:
        try:
            result = db.execute(text("""
                INSERT INTO cabys_account_rules
                    (id, tenant_id, cabys_code, cabys_prefix,
                     account_code, asset_flag, min_amount,
                     fuente, prioridad, created_at)
                VALUES
                    (:id, :tid, NULL, :prefix,
                     :account_code, :asset_flag, :min_amount,
                     'SEED_PREFIX', 5, NOW())
                ON CONFLICT (tenant_id, cabys_prefix) DO NOTHING
            """), {
                "id":           str(uuid.uuid4()),
                "tid":          tenant_id,
                "prefix":       prefix,
                "account_code": account_code,
                "asset_flag":   asset_flag,
                "min_amount":   min_amount,
            })
            inserted += (result.rowcount or 0)
        except Exception as ex:
            logger.warning(
                f"⚠️  seed_cabys_rules: error prefijo {prefix} para {tenant_id[:8]}: {ex}"
            )
    db.commit()
    if inserted:
        logger.info(
            f"✅ seed_cabys_rules: {inserted} reglas CABYS sembradas para tenant {tenant_id[:8]}"
        )
    return inserted


def seed_cabys_rules_all_tenants(db: Session) -> dict:
    """
    Siembra reglas CABYS para TODOS los tenants activos con catálogo existente.
    Usado en la migración M_CABYS_SEED del startup.

    Retorna: {"tenants": N, "reglas": M}
    """
    try:
        rows = db.execute(text(
            "SELECT DISTINCT tenant_id FROM accounts WHERE is_active = TRUE"
        )).fetchall()
    except Exception as ex:
        logger.warning(f"⚠️  seed_cabys_rules_all_tenants: no pudo leer accounts: {ex}")
        return {"tenants": 0, "reglas": 0}

    total_tenants = 0
    total_reglas  = 0
    for row in rows:
        tid = row[0]
        n = seed_cabys_rules_for_tenant(tid, db)
        total_tenants += 1
        total_reglas  += n

    return {"tenants": total_tenants, "reglas": total_reglas}
