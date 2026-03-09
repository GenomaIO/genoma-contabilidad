"""
services/reporting/niif_lines.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Catálogo de Partidas NIIF — NIIF PYMES 3ª Edición (Feb 2025)
Seeder idempotente para niif_line_defs + mapeo automático
para el Catálogo Estándar Genoma.

Funciones:
  seed_niif_lines(db)        → Inserta las partidas NIIF globales
  seed_standard_mapping(tenant_id, db) → Mapea el catálogo standard_cr al NIIF
  get_unmapped_accounts(tenant_id, db) → Cuentas activas sin mapear (para wizard)
"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from .models import NiifLineDef, NiifMapping, NiifStatement, EsfSection, EfeActivity
import uuid
from datetime import datetime, timezone


# ─────────────────────────────────────────────────────────────────
# Catálogo de partidas NIIF PYMES 3ª Ed. — mínimos Sec. 4 y Sec. 5
# ─────────────────────────────────────────────────────────────────
NIIF_LINES = [
    # ── ESF — ACTIVO CORRIENTE (Sec. 4.4a-d) ────────────────────
    {"code": "ESF.AC.01", "label": "Efectivo y equivalentes al efectivo",       "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 10, "efe_activity": "OPERACION",    "niif_ref": "Sec.4/7"},
    {"code": "ESF.AC.02", "label": "Deudores comerciales y otras CxC (neto)",  "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 20, "efe_activity": "OPERACION",    "niif_ref": "Sec.4"},
    {"code": "ESF.AC.03", "label": "Inventarios",                               "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 30, "efe_activity": "OPERACION",    "niif_ref": "Sec.13"},
    {"code": "ESF.AC.04", "label": "Activos por contratos (Sec.23 3ªEd.)",     "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 40, "efe_activity": "OPERACION",    "niif_ref": "Sec.23"},
    {"code": "ESF.AC.05", "label": "Activos biológicos corrientes",             "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 50, "efe_activity": "OPERACION",    "niif_ref": "Sec.34"},
    {"code": "ESF.AC.06", "label": "Activo por impuesto corriente",             "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 55, "efe_activity": "NO_APLICA",   "niif_ref": "Sec.29"},
    {"code": "ESF.AC.07", "label": "Otros activos corrientes",                  "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 60, "efe_activity": "OPERACION",    "niif_ref": "Sec.4"},
    {"code": "ESF.AC.TOT","label": "Total Activo Corriente",                    "statement": "ESF", "section": "ACTIVO_CORRIENTE",    "order": 99, "is_subtotal": True,            "niif_ref": "Sec.4"},

    # ── ESF — ACTIVO NO CORRIENTE ────────────────────────────────
    {"code": "ESF.ANC.01","label": "Propiedades, planta y equipo (neto)",       "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 110,"efe_activity": "INVERSION",    "niif_ref": "Sec.17"},
    {"code": "ESF.ANC.02","label": "Propiedades de inversión",                  "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 120,"efe_activity": "INVERSION",    "niif_ref": "Sec.16"},
    {"code": "ESF.ANC.03","label": "Activos intangibles (excl. plusvalía)",     "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 130,"efe_activity": "INVERSION",    "niif_ref": "Sec.18"},
    {"code": "ESF.ANC.04","label": "Plusvalía",                                 "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 140,"efe_activity": "INVERSION",    "niif_ref": "Sec.19"},
    {"code": "ESF.ANC.05","label": "Inversiones en asociadas",                  "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 150,"efe_activity": "INVERSION",    "niif_ref": "Sec.14"},
    {"code": "ESF.ANC.06","label": "Activo por impuesto diferido",              "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 160,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.29"},
    {"code": "ESF.ANC.07","label": "Otros activos no corrientes",               "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 170,"efe_activity": "INVERSION",    "niif_ref": "Sec.4"},
    {"code": "ESF.ANC.TOT","label":"Total Activo No Corriente",                 "statement": "ESF", "section": "ACTIVO_NO_CORRIENTE", "order": 199,"is_subtotal": True,            "niif_ref": "Sec.4"},
    {"code": "ESF.AT",    "label": "TOTAL ACTIVOS",                             "statement": "ESF", "section": "ACTIVO_CORRIENTE",   "order": 200,"is_subtotal": True, "is_calculated": True, "niif_ref": "Sec.4"},

    # ── ESF — PASIVO CORRIENTE ───────────────────────────────────
    {"code": "ESF.PC.01", "label": "Acreedores comerciales y otras CxP",        "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 310,"efe_activity": "OPERACION",    "niif_ref": "Sec.4"},
    {"code": "ESF.PC.02", "label": "Pasivos financieros corrientes",            "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 320,"efe_activity": "FINANCIACION", "niif_ref": "Sec.11"},
    {"code": "ESF.PC.03", "label": "Pasivos por contratos (Sec.23 3ªEd.)",     "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 330,"efe_activity": "OPERACION",    "niif_ref": "Sec.23"},
    {"code": "ESF.PC.04", "label": "Provisiones corrientes",                    "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 340,"efe_activity": "OPERACION",    "niif_ref": "Sec.21"},
    {"code": "ESF.PC.05", "label": "Pasivo por impuesto corriente",             "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 350,"efe_activity": "OPERACION",    "niif_ref": "Sec.29"},
    {"code": "ESF.PC.06", "label": "Otros pasivos corrientes",                  "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 360,"efe_activity": "OPERACION",    "niif_ref": "Sec.4"},
    {"code": "ESF.PC.TOT","label": "Total Pasivo Corriente",                    "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 399,"is_subtotal": True,            "niif_ref": "Sec.4"},

    # ── ESF — PASIVO NO CORRIENTE ────────────────────────────────
    {"code": "ESF.PNC.01","label": "Préstamos y financiamiento largo plazo",    "statement": "ESF", "section": "PASIVO_NO_CORRIENTE", "order": 410,"efe_activity": "FINANCIACION", "niif_ref": "Sec.11"},
    {"code": "ESF.PNC.02","label": "Pasivo por impuesto diferido",              "statement": "ESF", "section": "PASIVO_NO_CORRIENTE", "order": 420,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.29"},
    {"code": "ESF.PNC.03","label": "Provisiones no corrientes",                 "statement": "ESF", "section": "PASIVO_NO_CORRIENTE", "order": 430,"efe_activity": "OPERACION",    "niif_ref": "Sec.21"},
    {"code": "ESF.PNC.04","label": "Otros pasivos no corrientes",               "statement": "ESF", "section": "PASIVO_NO_CORRIENTE", "order": 440,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.4"},
    {"code": "ESF.PNC.TOT","label":"Total Pasivo No Corriente",                 "statement": "ESF", "section": "PASIVO_NO_CORRIENTE", "order": 499,"is_subtotal": True,            "niif_ref": "Sec.4"},
    {"code": "ESF.PT",    "label": "TOTAL PASIVOS",                             "statement": "ESF", "section": "PASIVO_CORRIENTE",   "order": 500,"is_subtotal": True, "is_calculated": True, "niif_ref": "Sec.4"},

    # ── ESF — PATRIMONIO ─────────────────────────────────────────
    {"code": "ESF.PAT.01","label": "Capital social / Capital del propietario",  "statement": "ESF", "section": "PATRIMONIO",          "order": 610,"efe_activity": "FINANCIACION", "niif_ref": "Sec.22"},
    {"code": "ESF.PAT.02","label": "Reservas (legal, voluntaria)",              "statement": "ESF", "section": "PATRIMONIO",          "order": 620,"efe_activity": "FINANCIACION", "niif_ref": "Sec.6"},
    {"code": "ESF.PAT.03","label": "Resultados acumulados",                     "statement": "ESF", "section": "PATRIMONIO",          "order": 630,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.6"},
    {"code": "ESF.PAT.04","label": "Resultado del período (neto)",              "statement": "ESF", "section": "PATRIMONIO",          "order": 640,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.5"},
    {"code": "ESF.PAT.05","label": "Otro resultado integral acumulado (ORI)",   "statement": "ESF", "section": "PATRIMONIO",          "order": 650,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.5.4/3ªEd"},
    {"code": "ESF.PAT.TOT","label":"TOTAL PATRIMONIO",                          "statement": "ESF", "section": "PATRIMONIO",          "order": 699,"is_subtotal": True,            "niif_ref": "Sec.4"},
    {"code": "ESF.PT_PAT","label": "TOTAL PASIVO + PATRIMONIO",                 "statement": "ESF", "section": "PATRIMONIO",          "order": 700,"is_subtotal": True, "is_calculated": True, "niif_ref": "Sec.4"},

    # ── ERI — INGRESOS (Sec. 5 + Sec. 23 3ª Ed.) ────────────────
    {"code": "ERI.ING.01","label": "Ingresos por ventas de bienes",             "statement": "ERI", "section": "INGRESO",             "order": 10, "efe_activity": "OPERACION",    "niif_ref": "Sec.23"},
    {"code": "ERI.ING.02","label": "Ingresos por prestación de servicios",      "statement": "ERI", "section": "INGRESO",             "order": 20, "efe_activity": "OPERACION",    "niif_ref": "Sec.23"},
    {"code": "ERI.ING.03","label": "Ingresos financieros (intereses)",          "statement": "ERI", "section": "INGRESO",             "order": 30, "efe_activity": "OPERACION",    "niif_ref": "Sec.11"},
    {"code": "ERI.ING.04","label": "Diferencial cambiario favorable",           "statement": "ERI", "section": "INGRESO",             "order": 40, "efe_activity": "OPERACION",    "niif_ref": "Sec.30"},
    {"code": "ERI.ING.05","label": "Otros ingresos de actividades ordinarias",  "statement": "ERI", "section": "INGRESO",             "order": 50, "efe_activity": "OPERACION",    "niif_ref": "Sec.5"},
    {"code": "ERI.ING.TOT","label":"Total Ingresos",                            "statement": "ERI", "section": "INGRESO",             "order": 99, "is_subtotal": True,            "niif_ref": "Sec.5"},

    # ── ERI — COSTOS Y GASTOS ────────────────────────────────────
    {"code": "ERI.GST.01","label": "Costo de ventas / Costo de servicios",      "statement": "ERI", "section": "COSTO",               "order": 110,"efe_activity": "OPERACION",    "niif_ref": "Sec.5"},
    {"code": "ERI.GST.02","label": "Gastos de ventas y distribución",           "statement": "ERI", "section": "GASTO_OPERATIVO",     "order": 120,"efe_activity": "OPERACION",    "niif_ref": "Sec.5"},
    {"code": "ERI.GST.03","label": "Gastos de administración",                  "statement": "ERI", "section": "GASTO_OPERATIVO",     "order": 130,"efe_activity": "OPERACION",    "niif_ref": "Sec.5"},
    {"code": "ERI.GST.04","label": "Gastos financieros (intereses pagados)",    "statement": "ERI", "section": "GASTO_FINANCIERO",    "order": 140,"efe_activity": "FINANCIACION", "niif_ref": "Sec.7.14"},
    {"code": "ERI.GST.05","label": "Diferencial cambiario desfavorable",        "statement": "ERI", "section": "GASTO_FINANCIERO",    "order": 150,"efe_activity": "OPERACION",    "niif_ref": "Sec.30"},
    {"code": "ERI.GST.06","label": "Otros gastos",                              "statement": "ERI", "section": "GASTO_OPERATIVO",     "order": 160,"efe_activity": "OPERACION",    "niif_ref": "Sec.5"},
    {"code": "ERI.UAI",   "label": "Utilidad (Pérdida) antes de impuestos",    "statement": "ERI", "section": "GASTO_OPERATIVO",     "order": 199,"is_subtotal": True,            "niif_ref": "Sec.5"},
    {"code": "ERI.ISR",   "label": "Impuesto sobre la renta del período",       "statement": "ERI", "section": "IMPUESTO_RENTA",      "order": 200,"efe_activity": "OPERACION",    "niif_ref": "Sec.29"},
    {"code": "ERI.UN",    "label": "UTILIDAD (PÉRDIDA) NETA DEL PERÍODO",      "statement": "ERI", "section": "IMPUESTO_RENTA",      "order": 209,"is_subtotal": True, "is_calculated": True, "niif_ref": "Sec.5"},

    # ── ERI — OTRO RESULTADO INTEGRAL (ORI) 3ª Ed. Sec. 5.4 ─────
    {"code": "ERI.ORI.01","label": "Diferencias de cambio en operaciones ext.", "statement": "ERI", "section": "OTRO_RESULTADO",      "order": 310,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.5.4/3ªEd"},
    {"code": "ERI.ORI.02","label": "Ganancias/pérdidas actuariales",            "statement": "ERI", "section": "OTRO_RESULTADO",      "order": 320,"efe_activity": "NO_APLICA",   "niif_ref": "Sec.5.4/3ªEd"},
    {"code": "ERI.TRI",   "label": "TOTAL RESULTADO INTEGRAL DEL PERÍODO",     "statement": "ERI", "section": "OTRO_RESULTADO",      "order": 399,"is_subtotal": True, "is_calculated": True, "niif_ref": "Sec.5"},
]

# ─────────────────────────────────────────────────────────────────
# Mapeo automático: catálogo standard_cr.json → partidas NIIF
# ─────────────────────────────────────────────────────────────────
# Regla: prefix numérico de la cuenta → partida NIIF por defecto
# El contador puede refinarlo después desde el wizard.
STANDARD_AUTO_MAPPING = {
    # ── ACTIVOS CORRIENTES (Sec. 4 NIIF PYMES) ──
    # Efectivo y equivalentes — serie 11xx
    "1101": "ESF.AC.01",  # Caja General
    "1102": "ESF.AC.01",  # Caja Chica
    "1103": "ESF.AC.01",  # Bancos CRC
    "1104": "ESF.AC.01",  # Bancos USD
    "1105": "ESF.AC.01",  # Inversiones < 3 meses (equivalente efectivo)
    "1106": "ESF.AC.01",  # Otras disponibilidades
    # Deudores comerciales y CxC — serie 13xx (catálogo standard_cr Genoma)
    "1301": "ESF.AC.02",  # CxC Clientes
    "1302": "ESF.AC.02",  # CxC empleados (anticipos)
    "1303": "ESF.AC.02",  # Documentos por cobrar
    "1304": "ESF.AC.02",  # Otras CxC
    "1305": "ESF.AC.02",  # Provisión cuentas incobrables (contra-CxC)
    "1306": "ESF.AC.02",  # IVA Crédito Fiscal
    "1307": "ESF.AC.02",  # Impuesto renta anticipado
    # Inventarios — serie 14xx
    "1401": "ESF.AC.03",  # Inventario mercadería
    "1402": "ESF.AC.03",  # Producto en proceso
    "1403": "ESF.AC.03",  # Materia prima
    "1404": "ESF.AC.03",  # Material de empaque
    # Otros activos corrientes — serie 15xx
    "1501": "ESF.AC.07",  # Gastos pagados por adelantado
    "1502": "ESF.AC.07",  # Otros activos corrientes
    # ── ACTIVOS NO CORRIENTES (Sec. 17 NIIF PYMES) ──
    # PPE: Propiedad, Planta y Equipo — serie 12xx (catálogo standard_cr Genoma)
    # ⚠️ NOTA: En el catálogo Genoma standard_cr, la serie 12xx es PPE,
    #          no CxC. CxC está en 13xx. Verificado en standard_cr.json.
    "1201": "ESF.ANC.01", # PPE: Vehículos, Terrenos, Edificios, Maquinaria
    "1202": "ESF.ANC.01", # Depreciación Acumulada PPE (contra-cuenta)
    # Documentos financieros CP — serie 1107xx
    "1107": "ESF.AC.02",  # Documentos por Cobrar y Efectos CP → CxC
    # Intangibles LP — serie 1203xx (Software, Marcas, Goodwill)
    "1203": "ESF.ANC.03", # Intangibles adquiridos (Software, Marcas, Patentes, Goodwill)
    # Inversiones no corrientes — serie 1204xx
    "1204": "ESF.ANC.05", # Inversiones en asociadas (Acciones, Bonos, Fondos)
    # Documentos/CxC largo plazo — serie 1205xx
    "1205": "ESF.ANC.07", # Otros activos no corrientes (CxC LP, Efectos LP)
    # Intangibles — serie 16xx
    "1601": "ESF.ANC.03", # Software
    "1602": "ESF.ANC.03", # Marcas y patentes
    "1690": "ESF.ANC.03", # Amortización acumulada intangibles (contra)
    # Activo diferido — serie 17xx
    "1701": "ESF.ANC.06", # Activo por ISR diferido
    # ── PASIVOS ──
    "2101": "ESF.PC.01",  # CxP proveedores
    "2102": "ESF.PC.01",  # CxP varias
    "2103": "ESF.PC.05",  # IVA Débito Fiscal (corriente)
    "2104": "ESF.PC.05",  # Retenciones por pagar
    "2105": "ESF.PC.05",  # CCSS por pagar
    "2106": "ESF.PC.04",  # Aguinaldo por pagar
    "2107": "ESF.PC.04",  # Cesantía y preaviso CP
    "2108": "ESF.PC.06",  # Otros pasivos corrientes
    "2201": "ESF.PNC.01", # Préstamos bancarios LP
    "2202": "ESF.PNC.03", # Provisión aguinaldo/cesantía LP
    "2203": "ESF.PNC.04", # Otros pasivos no corrientes
    "2701": "ESF.PNC.02", # Pasivo por ISR diferido
    # ── PATRIMONIO ──
    "3101": "ESF.PAT.01", # Capital suscrito y pagado
    "3102": "ESF.PAT.01", # Capital adicional
    "3201": "ESF.PAT.02", # Reserva legal
    "3202": "ESF.PAT.02", # Reservas voluntarias
    "3301": "ESF.PAT.03", # Utilidades acumuladas
    "3302": "ESF.PAT.04", # Pérdida del ejercicio
    "3303": "ESF.PAT.04", # Utilidad del ejercicio
    # 3304 = Resumen de Resultado (transitoria, saldo 0 al cierre — no mapear)
    "3401": "ESF.PAT.01", # Capital del propietario (PE unipersonal)
    "3402": "ESF.PAT.03", # Resultados acumulados del propietario
    # ── INGRESOS ──
    "4101": "ERI.ING.01", # Ventas de mercancías
    "4102": "ERI.ING.02", # Ventas de servicios
    "4103": "ERI.ING.01", # Ventas exentas
    "4104": "ERI.ING.01", # Descuentos sobre ventas (contra)
    "4201": "ERI.ING.03", # Ingresos financieros / intereses ganados
    "4202": "ERI.ING.04", # Diferencial cambiario favorable
    "4203": "ERI.ING.05", # Otros ingresos no operativos
    "4901": "ERI.ING.05", # Ingresos misceláneos
    "4902": "ERI.ING.05", # Ganancias eventuales
    "4903": "ERI.ING.05", # Ingresos períodos anteriores
    # ── COSTOS Y GASTOS ──
    "5101": "ERI.GST.01", # Costo de mercancías vendidas
    "5102": "ERI.GST.01", # Costo de servicios prestados
    "5201": "ERI.GST.03", # Sueldos y salarios
    "5202": "ERI.GST.03", # Cargas sociales
    "5203": "ERI.GST.03", # Alquiler
    "5204": "ERI.GST.03", # Electricidad, agua, teléfono
    "5205": "ERI.GST.03", # Combustibles
    "5206": "ERI.GST.02", # Publicidad y mercadeo
    "5207": "ERI.GST.03", # Mantenimiento y reparaciones
    "5208": "ERI.GST.03", # Seguros
    "5209": "ERI.GST.03", # Honorarios profesionales
    "5210": "ERI.GST.03", # Depreciación del período
    "5211": "ERI.GST.03", # Amortización de intangibles
    "5212": "ERI.GST.03", # Viajes y representación
    "5213": "ERI.GST.03", # Materiales y suministros
    "5214": "ERI.GST.03", # Servicios tecnológicos (Cloud/SaaS)
    "5301": "ERI.GST.04", # Intereses bancarios pagados
    "5302": "ERI.GST.04", # Comisiones bancarias
    "5303": "ERI.GST.05", # Diferencial cambiario desfavorable
    "5401": "ERI.ISR",    # ISR corriente del período
    "5402": "ERI.ISR",    # ISR diferido
    "5901": "ERI.GST.06", # Gastos misceláneos
    "5902": "ERI.GST.06", # Gastos no deducibles
    "5903": "ERI.GST.06", # Pérdidas y ajustes contables
}

# Cuentas que NO deben mapearse (transitorias o de control)
EXCLUDE_FROM_MAPPING = {"3304", "3000", "4000", "5000", "1000", "2000", "1100", "1200",
                        "1300", "1400", "1500", "1600", "2100", "2200", "3100", "3200",
                        "3300", "3400", "4100", "4200", "4900", "5100", "5200", "5300",
                        "5400", "5900"}

# Cuentas complementarias (contra-cuentas = se restan de su partida NIIF)
# 1202: Depreciación Acumulada PPE (contra de 1201)
# 1305: Provisión incobrables (contra de CxC)
# 1690/1790: Amortización Acumulada Intangibles
# 4104: Descuentos sobre ventas (contra-ingreso)
CONTRA_ACCOUNTS = {"1202", "1305", "1590", "1690", "1790", "4104"}


def seed_niif_lines(db: Session) -> int:
    """Inserta el catálogo global de partidas NIIF. Idempotente."""
    inserted = 0
    for line in NIIF_LINES:
        existing = db.query(NiifLineDef).filter_by(code=line["code"]).first()
        if existing:
            continue
        obj = NiifLineDef(
            id=str(uuid.uuid4()),
            code=line["code"],
            label=line["label"],
            statement=NiifStatement(line["statement"]),
            section=EsfSection(line["section"]),
            order=line["order"],
            is_subtotal=line.get("is_subtotal", False),
            is_calculated=line.get("is_calculated", False),
            efe_activity=EfeActivity(line.get("efe_activity", "NO_APLICA")),
            niif_section_ref=line.get("niif_ref"),
        )
        db.add(obj)
        inserted += 1
    db.commit()
    return inserted


def seed_standard_mapping(tenant_id: str, db: Session) -> int:
    """
    Mapea automáticamente el catálogo estándar Genoma a partidas NIIF.
    Solo inserta cuentas que tengan mapeo definido en STANDARD_AUTO_MAPPING.
    """
    inserted = 0
    for acc_code, niif_code in STANDARD_AUTO_MAPPING.items():
        existing = db.query(NiifMapping).filter_by(
            tenant_id=tenant_id, account_code=acc_code
        ).first()
        if existing:
            continue
        mapping = NiifMapping(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            account_code=acc_code,
            niif_line_code=niif_code,
            is_contra=(acc_code in CONTRA_ACCOUNTS),
        )
        db.add(mapping)
        inserted += 1
    db.commit()
    return inserted


def fix_existing_mappings(tenant_id: str, db: Session) -> int:
    """
    Corrige mapeos NIIF existentes que pudieran haberse sembrado incorrectamente.

    El seeder usa `if existing: continue` (idempotente-solo-inserción), por lo tanto
    si la tabla STANDARD_AUTO_MAPPING tenía un valor incorrecto cuando se sembró,
    el registro en DB queda mal para siempre. Esta función los corrige al restart.

    Correcciones aplicadas (versión completa v2):
      ── Activo No Corriente ──
      1201 → ESF.ANC.01  (PPE: Vehículos, Terrenos, Edificios, Maquinaria)
      1202 → ESF.ANC.01  (Depreciación Acumulada PPE — contra-cuenta)
      1203 → ESF.ANC.03  (Intangibles: Software, Marcas, Patentes)
      1204 → ESF.ANC.05  (Inversiones en asociadas)
      1205 → ESF.ANC.07  (Otros activos no corrientes: CxC LP, Efectos LP)
      1601 → ESF.ANC.03  (Software / intangibles serie 16xx)
      1602 → ESF.ANC.03  (Marcas y patentes)
      1690 → ESF.ANC.03  (Amortización acumulada intangibles — contra)
      1701 → ESF.ANC.06  (Activo por ISR diferido)
      1107 → ESF.AC.02   (Documentos por Cobrar CP — corriente, no LP)
      ── Pasivo No Corriente ──
      2201 → ESF.PNC.01  (Préstamos bancarios LP)
      2202 → ESF.PNC.03  (Provisión aguinaldo/cesantía LP)
      2203 → ESF.PNC.04  (Otros pasivos no corrientes)
      2701 → ESF.PNC.02  (Pasivo por ISR diferido)
    """
    CORRECTIONS = [
        # (account_code, new_niif_line_code, is_contra)
        # ── Activo No Corriente (PPE y familia) ──────────────
        ("1201", "ESF.ANC.01", False),   # PPE: Vehículos, Terrenos, Edificios
        ("1202", "ESF.ANC.01", True),    # Depreciación Acumulada PPE (contra)
        ("1203", "ESF.ANC.03", False),   # Intangibles adquiridos
        ("1204", "ESF.ANC.05", False),   # Inversiones en asociadas
        ("1205", "ESF.ANC.07", False),   # Otros A. No Corrientes (CxC LP)
        ("1107", "ESF.AC.02",  False),   # Documentos por Cobrar CP
        # ── Intangibles serie 16xx ────────────────────────────
        ("1601", "ESF.ANC.03", False),   # Software
        ("1602", "ESF.ANC.03", False),   # Marcas y patentes
        ("1690", "ESF.ANC.03", True),    # Amortización acumulada intangibles
        # ── Activo diferido / ISR ─────────────────────────────
        ("1701", "ESF.ANC.06", False),   # Activo por ISR diferido
        # ── Pasivo No Corriente ───────────────────────────────
        ("2201", "ESF.PNC.01", False),   # Préstamos bancarios LP
        ("2202", "ESF.PNC.03", False),   # Provisión LP (aguinaldo/cesantía)
        ("2203", "ESF.PNC.04", False),   # Otros pasivos no corrientes
        ("2701", "ESF.PNC.02", False),   # Pasivo por ISR diferido
    ]
    updated = 0
    for acc_code, niif_code, is_contra in CORRECTIONS:
        existing = db.query(NiifMapping).filter_by(
            tenant_id=tenant_id, account_code=acc_code
        ).first()
        if existing and existing.niif_line_code != niif_code:
            existing.niif_line_code = niif_code
            existing.is_contra = is_contra
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
        elif not existing:
            # Crear si no existe
            db.add(NiifMapping(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                account_code=acc_code,
                niif_line_code=niif_code,
                is_contra=is_contra,
            ))
            updated += 1
    db.commit()
    return updated


def get_unmapped_accounts(tenant_id: str, db: Session) -> list[dict]:
    """
    Retorna las cuentas activas del tenant que NO tienen mapeo NIIF.
    Estas cuentas bloquean la generación de EEFF.
    """
    result = db.execute(
        __import__("sqlalchemy").text("""
            SELECT a.code, a.name, a.account_type
            FROM accounts a
            LEFT JOIN niif_mappings m
              ON m.tenant_id = a.tenant_id AND m.account_code = a.code
            WHERE a.tenant_id = :tenant_id
              AND a.is_active = TRUE
              AND a.allow_entries = TRUE
              AND m.id IS NULL
            ORDER BY a.code
        """),
        {"tenant_id": tenant_id}
    ).fetchall()
    return [{"code": r[0], "name": r[1], "type": r[2]} for r in result]
