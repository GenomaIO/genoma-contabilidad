"""
fiscal_engine.py — Motor CENTINELA: Detector de Fugas Fiscales

Analiza las transacciones bancarias contra la normativa CR vigente y genera:
- Score de riesgo fiscal (0-100)
- Clasificación de fugas Tipo A/B/C
- Estimación de IVA y renta en riesgo
- Pre-llenado del D-270

Normativa base:
  - Decreto 44739-H: SINPE comercial debe tener FE con código 06
  - D-270: Declarar mensualmente gastos sin FE (vigente enero 2026)
  - Ley 7092 Art. 8: Gastos deducibles solo con FE o D-270
"""
from __future__ import annotations
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

IVA_RATE = 0.13

# ── Diccionario de keywords CR ───────────────────────────────────────────────
# Mapa: keyword → {tipo_transaccion, d270_codigo, clasificacion, nota}
CR_KEYWORDS: dict[str, dict] = {
    # Instituciones públicas (exentas de FE pero van en D-270)
    "CCSS":          {"tipo": "DB", "d270": "C",  "clasificacion": "CARGA_SOCIAL",    "nota": "Pago CCSS — puede ir en D-270"},
    "INS":           {"tipo": "DB", "d270": "C",  "clasificacion": "SEGURO",          "nota": "Seguro INS — verificar FE o D-270"},
    "AYA":           {"tipo": "DB", "d270": "C",  "clasificacion": "SERVICIO_PUBLICO", "nota": "Agua AyA — exenta, verificar documento"},
    "ICE":           {"tipo": "DB", "d270": "C",  "clasificacion": "SERVICIO_PUBLICO", "nota": "Servicio ICE — verificar FE"},
    "RECOPE":        {"tipo": "DB", "d270": "C",  "clasificacion": "COMBUSTIBLE",     "nota": "Combustible RECOPE"},
    "HACIENDA":      {"tipo": "DB", "d270": None, "clasificacion": "PAGO_IMPUESTO",   "nota": "Pago a Hacienda — no deducible como gasto"},
    "MUNICIPALIDAD": {"tipo": "DB", "d270": "C",  "clasificacion": "IMPUESTO_LOCAL",  "nota": "Pago municipalidad — verificar D-270"},
    "CONAVI":        {"tipo": "DB", "d270": "C",  "clasificacion": "SERVICIO_PUBLICO", "nota": "CONAVI — entidad pública"},
    "COSEVI":        {"tipo": "DB", "d270": None, "clasificacion": "MULTA",           "nota": "COSEVI — posible multa, no deducible"},
    # Servicios de telecomunicaciones (emiten FE)
    "KOLBI":         {"tipo": "DB", "d270": None, "clasificacion": "TELEFONO",        "nota": "KOLBI — verificar FE recibida"},
    "CLARO":         {"tipo": "DB", "d270": None, "clasificacion": "TELEFONO",        "nota": "CLARO — verificar FE recibida"},
    "MOVISTAR":      {"tipo": "DB", "d270": None, "clasificacion": "TELEFONO",        "nota": "MOVISTAR — verificar FE recibida"},
    "LIBERTY":       {"tipo": "DB", "d270": None, "clasificacion": "INTERNET",        "nota": "Liberty — verificar FE"},
    "CABLETICA":     {"tipo": "DB", "d270": None, "clasificacion": "INTERNET",        "nota": "Cabletica — verificar FE"},
    # Gastos laborales
    "PLANILLA":      {"tipo": "DB", "d270": None, "clasificacion": "SALARIO",         "nota": "Pago planilla — requiere comprobante patronal"},
    "SALARIO":       {"tipo": "DB", "d270": None, "clasificacion": "SALARIO",         "nota": "Salario — verificar planilla CCSS"},
    "NOMINA":        {"tipo": "DB", "d270": None, "clasificacion": "SALARIO",         "nota": "Nómina — verificar planilla CCSS"},
    # Alquileres y préstamos
    "ALQUILER":      {"tipo": "DB", "d270": "A",  "clasificacion": "ALQUILER",        "nota": "Alquiler — si no hay FE, incluir en D-270 (A)"},
    "ARRENDAMIENTO": {"tipo": "DB", "d270": "A",  "clasificacion": "ALQUILER",        "nota": "Arrendamiento — D-270 tipo A"},
    "CUOTA":         {"tipo": "DB", "d270": "I",  "clasificacion": "PRESTAMO",        "nota": "Cuota préstamo — intereses en D-270 (I)"},
    "INTERES":       {"tipo": "DB", "d270": "I",  "clasificacion": "INTERES",         "nota": "Interés bancario — D-270 tipo I"},
    "CREDITO":       {"tipo": "DB", "d270": "I",  "clasificacion": "PRESTAMO",        "nota": "Crédito — verificar capital vs intereses"},
    # Profesionales (requieren FE o van en D-270 SP)
    "HONORARIO":     {"tipo": "DB", "d270": "SP", "clasificacion": "SERV_PROF",       "nota": "Honorario — si sin FE, incluir en D-270 (SP)"},
    "ABOGADO":       {"tipo": "DB", "d270": "SP", "clasificacion": "SERV_PROF",       "nota": "Abogado — D-270 tipo SP si sin FE"},
    "CONTADOR":      {"tipo": "DB", "d270": "SP", "clasificacion": "SERV_PROF",       "nota": "Contador — D-270 tipo SP si sin FE"},
    "MEDICO":        {"tipo": "DB", "d270": "SP", "clasificacion": "SERV_PROF",       "nota": "Médico — D-270 tipo SP si sin FE"},
    "CONSULTOR":     {"tipo": "DB", "d270": "SP", "clasificacion": "SERV_PROF",       "nota": "Consultor — D-270 tipo SP si sin FE"},
    # Comisiones
    "COMISION":      {"tipo": "DB", "d270": "M",  "clasificacion": "COMISION",        "nota": "Comisión — D-270 tipo M si sin FE"},
    # Ingresos típicos
    "SINPE":         {"tipo": "CR", "d270": None, "clasificacion": "INGRESO_SINPE",   "nota": "SINPE — verificar FE emitida (Decreto 44739-H)"},
    "DEPOSITO":      {"tipo": "CR", "d270": None, "clasificacion": "INGRESO",         "nota": "Depósito — verificar origen y FE"},
    "TRANSFERENCIA": {"tipo": "CR", "d270": None, "clasificacion": "TRANSFERENCIA",   "nota": "Transferencia — verificar si es ingreso gravable"},
}


# ── Tarifas IVA vigentes (Ley 9635 y Decreto 43855-H) ───────────────────────
# Tarifa 0%: bienes exentos (art. 8 Ley 9635)
# Tarifa 1%: canasta básica (art. 11)
# Tarifa 2%: medicamentos y seguros (art. 11)
# Tarifa 4%: servicios profesionales (transitorio V) + educación privada
# Tarifa 8%: salud privada, seguros generales (art. 11)
# Tarifa 13%: general (art. 10)

# Mapa semántico: keyword → tasa decimal
# Aplicado en orden: la primera coincidencia gana
_TARIFA_SEMANTICA: list[tuple[str, float]] = [
    # Exentos 0%
    ("GASOLINA",         0.00),
    ("DIESEL",           0.00),
    ("COMBUSTIBLE",      0.00),
    ("RECOPE",           0.00),
    ("MEDICINA",         0.00),
    ("MEDICAMENTO",      0.00),
    ("FARMACIA",         0.00),
    ("HOSPITAL",         0.00),
    ("CLINICA",          0.00),
    ("LABORATORIO",      0.00),
    ("SEGURO",           0.02),  # Seguros → 2%
    ("INS",              0.02),
    ("CCSS",             0.00),  # Cargas sociales → exento
    ("HACIENDA",         0.00),  # Impuestos → exento
    ("MUNICIPALIDAD",    0.00),  # Impuestos locales → exento
    ("AYA",              0.00),  # Servicios AyA → exento art. 8
    ("AGUA",             0.00),
    ("EDUCACION",        0.04),  # Educación privada → 4%
    ("COLEGIO",          0.04),
    ("UNIVERSIDAD",      0.04),
    ("CAPACITACION",     0.04),
    ("MEDICO",           0.04),  # Servicios médicos → 4% (transitorio)
    ("DENTISTA",         0.04),
    ("ODONTOLOGO",       0.04),
    ("PSICOLOGO",        0.04),
    ("HONORARIO",        0.04),  # Servicios profesionales → 4%
    ("ABOGADO",          0.04),
    ("CONTADOR",         0.04),
    ("CONSULTOR",        0.04),
    ("NOTARIO",          0.04),
    ("ALQUILER",         0.13),  # Alquileres inmuebles → 13%
    ("ARRENDAMIENTO",    0.13),
    # Resto → 13% default
]


def estimar_tarifa(descripcion: str, categoria: str = "TERCERO") -> float:
    """
    Estima la tarifa IVA correcta para una transacción bancaria.

    Base legal: Ley 9635 (IVA Costa Rica) vigente.
    Trabaja por semántica de la descripción — la primera coincidencia gana.

    Casos especiales:
    - BANK_FEE / BANK_INTEREST → 0% (servicios financieros exentos, art. 8)
    - SINPE sin descripción → 13% (ingreso gravable por defecto)
    - Descripción vacía → 13% (máxima prudencia fiscal)

    Args:
        descripcion: Texto crudo de la transacción
        categoria:   beneficiario_categoria (BANK_FEE, BANK_INTEREST, SINPE, TERCERO)

    Returns:
        Tasa decimal: 0.0, 0.01, 0.02, 0.04, 0.08, 0.13
    """
    if categoria in ("BANK_FEE", "BANK_INTEREST"):
        return 0.00   # Servicios financieros exentos art. 8 inc. g

    desc_up = (descripcion or "").upper()
    for keyword, tasa in _TARIFA_SEMANTICA:
        if keyword in desc_up:
            return tasa
    return 0.13   # Default: tarifa general


def calcular_iva_incluido(monto_bruto: float, tarifa: float = IVA_RATE) -> dict:
    """
    Desglosa un monto que ya incluye IVA según la tarifa indicada.

    monto_bruto = base * (1 + tarifa)
    base  = monto_bruto / (1 + tarifa)
    IVA   = monto_bruto - base

    Args:
        monto_bruto: Monto total del banco (ya incluye IVA)
        tarifa:      Tasa decimal. Default 0.13. Usar estimar_tarifa() para detectar.

    Returns:
        dict con base, iva, bruto, tarifa_pct
    """
    if tarifa <= 0:
        return {"base": monto_bruto, "iva": 0.0, "bruto": monto_bruto, "tarifa_pct": 0}
    base = round(monto_bruto / (1 + tarifa), 2)
    iva  = round(monto_bruto - base, 2)
    return {
        "base":       base,
        "iva":        iva,
        "bruto":      monto_bruto,
        "tarifa_pct": int(tarifa * 100),
    }




# ── Clasificación de fugas ───────────────────────────────────────────────────

def clasificar_fuga(txn: dict, fe_emitidas: list[dict], fe_recibidas: list[dict]) -> dict:
    """
    Determina el tipo de fuga fiscal de una transacción sin match en libros.

    Tipo A: INGRESO sin FE emitida correspondiente
    Tipo B: GASTO sin FE recibida (y sin D-270)
    Tipo C: SINPE sin código 06 en FE emitida
    """
    monto  = float(txn.get("monto", 0))
    tipo   = txn.get("tipo", "")
    desc   = (txn.get("descripcion") or "").upper()

    calc = calcular_iva_incluido(monto)

    if tipo == "CR":
        # Buscar FE emitida por monto similar en el período
        fecha = txn.get("fecha", "")
        period = str(fecha)[:7].replace("-", "") if fecha else ""
        fe_match = _find_fe_match(monto, period, fe_emitidas)

        if "SINPE" in desc:
            if fe_match and fe_match.get("medio_pago") != "06":
                return {
                    "fuga_tipo":   "C",
                    "descripcion": "SINPE cobrado pero FE tiene medio de pago incorrecto (no es código 06)",
                    "accion":      "Corregir FE: cambiar medio de pago a SINPE Móvil (código 06)",
                    "iva_riesgo":  0.0,
                    "base_riesgo": 0.0,
                    "d270_codigo": None,
                    "score_pts":   5,
                }
            elif not fe_match:
                return {
                    "fuga_tipo":   "A",
                    "descripcion": "SINPE recibido sin FE emitida correspondiente — Decreto 44739-H",
                    "accion":      "Emitir FE con medio de pago SINPE Móvil (código 06)",
                    "iva_riesgo":  calc["iva"],
                    "base_riesgo": calc["base"],
                    "d270_codigo": None,
                    "score_pts":   15,
                }
        else:
            if not fe_match:
                return {
                    "fuga_tipo":   "A",
                    "descripcion": "Ingreso recibido (no SINPE) sin FE correspondiente",
                    "accion":      "Emitir FE o justificar como ingreso no gravable",
                    "iva_riesgo":  calc["iva"],
                    "base_riesgo": calc["base"],
                    "d270_codigo": None,
                    "score_pts":   15,
                }
        return {}  # OK — tiene FE

    elif tipo == "DB":
        # Buscar FE recibida por monto similar
        fecha = txn.get("fecha", "")
        period = str(fecha)[:7].replace("-", "") if fecha else ""
        fe_match = _find_fe_match(monto, period, fe_recibidas)

        if fe_match:
            return {}  # OK — tiene FE de respaldo

        # Determinar código D-270 por keyword
        d270_codigo = _detectar_d270_codigo(desc)

        if d270_codigo:
            return {
                "fuga_tipo":   "B",
                "descripcion": f"Gasto sin FE recibida — debe incluirse en D-270 como tipo {d270_codigo}",
                "accion":      f"Incluir en D-270 mensual (código {d270_codigo}) antes del día 10",
                "iva_riesgo":  calc["iva"],  # IVA acreditable perdido
                "base_riesgo": calc["base"],
                "d270_codigo": d270_codigo,
                "score_pts":   12,
            }
        else:
            return {
                "fuga_tipo":   "B",
                "descripcion": "Gasto sin FE recibida — tipo D-270 por determinar",
                "accion":      "Verificar si aplica D-270 y bajo qué código",
                "iva_riesgo":  calc["iva"],
                "base_riesgo": calc["base"],
                "d270_codigo": None,
                "score_pts":   10,
            }

    return {}


def _find_fe_match(monto: float, period: str, fe_list: list[dict]) -> Optional[dict]:
    """Busca una FE con monto similar (±2%) en el período dado."""
    for fe in fe_list:
        fe_period = str(fe.get("period", fe.get("periodo", "")))
        if period and fe_period and fe_period[:6] != period[:6]:
            continue
        fe_monto = float(fe.get("total", fe.get("monto_total", 0)) or 0)
        if fe_monto > 0 and abs(fe_monto - monto) / max(fe_monto, 1) <= 0.02:
            return fe
    return None


def _detectar_d270_codigo(descripcion: str) -> Optional[str]:
    """Detecta el código D-270 apropiado por keywords en la descripción."""
    desc = descripcion.upper()
    for kw, info in CR_KEYWORDS.items():
        if kw in desc and info.get("d270"):
            return info["d270"]
    return None


# ── Motor de scoring CENTINELA ───────────────────────────────────────────────

REGLAS_SCORE = [
    # (id, descripción, puntos_max, función_evaluadora)
    ("R01", "SINPE sin FE emitida",                    40),
    ("R02", "Gasto por transfer sin FE recibida",       30),
    ("R03", "Gasto sin FE y sin D-270",                 30),
    ("R04", "Depósito ≥ ₡500K sin FE",                 40),
    ("R05", "Diferencia saldo banco vs libros > ₡50K",   8),
    ("R06", "Mismo teléfono ≥3 pagos sin FE emitida",   15),
    ("R07", "Cuotas bancarias sin D-270 (I)",             5),
    ("R10", "Ingresos banco > FE emitidas × 1.10",      25),
]


def calcular_score(
    fugas: list[dict],
    saldo_diff: dict,
    ingresos_banco: float,
    total_fe_emitidas: float,
) -> dict:
    """
    Calcula el score de riesgo CENTINELA (0-100).

    Args:
        fugas: Lista de fugas detectadas (output de clasificar_fuga)
        saldo_diff: Output de calcular_diferencia_saldo
        ingresos_banco: Total de créditos (ingresos) en banco
        total_fe_emitidas: Total de FE emitidas en el período

    Returns:
        dict con score_total, detalle, exposicion_iva, exposicion_total
    """
    score = 0
    detalle = []
    exposicion_iva   = 0.0
    exposicion_renta = 0.0
    fugas_a = fugas_b = fugas_c = 0
    d270_items = []

    for fuga in fugas:
        if not fuga:
            continue
        pts = min(fuga.get("score_pts", 0), 40)
        score += pts
        tipo = fuga.get("fuga_tipo", "")
        if tipo == "A": fugas_a += 1
        if tipo == "B": fugas_b += 1
        if tipo == "C": fugas_c += 1
        exposicion_iva   += float(fuga.get("iva_riesgo", 0))
        base = float(fuga.get("base_riesgo", 0))
        exposicion_renta += base * 0.15  # tasa estimada conservadora

        detalle.append({
            "regla":  f"R0{1 if tipo=='A' else 2 if tipo=='B' else 3}",
            "tipo":   tipo,
            "puntos": pts,
            "desc":   fuga.get("descripcion", ""),
        })

        # Si tiene código D-270, va al borrador
        if fuga.get("d270_codigo") and tipo == "B":
            d270_items.append({
                "descripcion":  fuga.get("txn_descripcion", "Sin descripción"),
                "monto":        fuga.get("base_riesgo", 0),
                "d270_codigo":  fuga["d270_codigo"],
                "observacion":  fuga.get("accion", ""),
            })

    # R05 — diferencia saldo
    if saldo_diff.get("estado") == "DIFERENCIA_SIGNIFICATIVA":
        score += 8
        detalle.append({"regla": "R05", "puntos": 8, "desc": saldo_diff.get("observacion")})

    # R10 — ingresos banco >> FE emitidas
    if total_fe_emitidas > 0 and ingresos_banco > total_fe_emitidas * 1.10:
        score += 25
        detalle.append({
            "regla": "R10", "puntos": 25,
            "desc": f"Ingresos banco ₡{ingresos_banco:,.0f} > FE ₡{total_fe_emitidas:,.0f} × 1.10"
        })

    score = min(score, 100)

    if score <= 30:
        nivel, emoji = "SALUDABLE", "🟢"
    elif score <= 60:
        nivel, emoji = "MODERADO",  "🟡"
    elif score <= 80:
        nivel, emoji = "EN_RIESGO", "🟠"
    else:
        nivel, emoji = "CRITICO",   "🔴"

    return {
        "score_total":      score,
        "nivel":            nivel,
        "emoji":            emoji,
        "fugas_tipo_a":     fugas_a,
        "fugas_tipo_b":     fugas_b,
        "fugas_tipo_c":     fugas_c,
        "exposicion_iva":   round(exposicion_iva, 2),
        "exposicion_renta": round(exposicion_renta, 2),
        "exposicion_total": round(exposicion_iva + exposicion_renta, 2),
        "d270_regs":        len(d270_items),
        "d270_items":       d270_items,
        "detalle":          detalle,
    }


# ── Generador D-270 ──────────────────────────────────────────────────────────

D270_CODIGOS = {
    "V":  "Ventas a clientes sin comprobante electrónico",
    "C":  "Compras a proveedores sin comprobante electrónico",
    "SP": "Servicios profesionales sin comprobante electrónico",
    "A":  "Alquileres sin comprobante electrónico",
    "M":  "Comisiones sin comprobante electrónico",
    "I":  "Intereses a entidades financieras",
}

# Palabras clave para detectar ingresos por intereses bancarios
_PALABRAS_INTERES = [
    "INTERES", "INTERÉS", "RDTO", "RENDIMIENTO", "RENTA FIJA",
    "CAPITALIZACION", "CAPITALIZACIÓN",
]


def asignar_d270_auto(txns: list[dict]) -> list[dict]:
    """
    Asigna código D-270 automáticamente a transacciones SIN_FE/SIN_ASIENTO.
    No modifica las que ya tienen código asignado ni las CON_FE.

    Reglas:
      CR + palabras de interés en descripción → I (Intereses)
      CR genérico SIN_FE                     → V (Ventas sin comprobante)
      DB SIN_FE con monto ≥ 1                → C (Compras sin comprobante)
      CON_FE / CONCILIADO / PROBABLE         → sin código (None)
    """
    estados_sin_fe = {"SIN_FE", "SIN_ASIENTO"}

    for txn in txns:
        if txn.get("match_estado") not in estados_sin_fe:
            continue                          # CON_FE / CONCILIADO → skip
        if txn.get("d270_codigo"):
            continue                          # ya tiene código → respetar

        desc  = (txn.get("descripcion") or "").upper()
        tipo  = (txn.get("tipo") or "DB").upper()
        monto = abs(float(txn.get("monto", 0)))

        if tipo == "CR":
            if any(k in desc for k in _PALABRAS_INTERES):
                txn["d270_codigo"] = "I"
            else:
                txn["d270_codigo"] = "V"
        else:  # DB
            if monto >= 1:
                txn["d270_codigo"] = "C"

    return txns



def generar_d270_csv(
    tenant_id: str,
    identificacion: str,
    nombre: str,
    period: str,          # YYYYMM
    items: list[dict],    # {d270_codigo, monto, descripcion, contact_name}
) -> str:
    """
    Genera el CSV de la D-270 en el formato esperado por Tribu-CR.
    period: YYYYMM (ej: 202602 para febrero 2026)

    Formato CSV:
    periodo,tipo_id_contraparte,num_id_contraparte,nombre_contraparte,tipo_txn,monto
    """
    lines = ["periodo,tipo_id_contraparte,num_id_contraparte,nombre_contraparte,tipo_transaccion,monto_total"]

    totales = {cod: 0.0 for cod in D270_CODIGOS}

    for item in items:
        codigo = item.get("d270_codigo", "C")
        monto  = float(item.get("monto", 0))
        nombre_cp = item.get("contact_name") or item.get("descripcion", "SIN IDENTIFICAR")
        id_cp     = item.get("id_contraparte", "000000000")
        tipo_id   = "01"  # 01=cédula física, 02=cédula jurídica, 03=DIMEX

        if monto <= 0:
            continue

        totales[codigo] = totales.get(codigo, 0) + monto
        lines.append(f"{period},{tipo_id},{id_cp},{nombre_cp},{codigo},{monto:.2f}")

    return "\n".join(lines)


def generar_d270_resumen(items: list[dict]) -> dict:
    """Genera el resumen por tipo para mostrar en el frontend."""
    totales = {cod: 0.0 for cod in D270_CODIGOS}
    conteos = {cod: 0    for cod in D270_CODIGOS}

    for item in items:
        cod = item.get("d270_codigo", "C")
        if cod in totales:
            totales[cod] += float(item.get("monto", 0))
            conteos[cod] += 1

    return {
        "totales": totales,
        "conteos": conteos,
        "total_registros": sum(conteos.values()),
        "total_monto": sum(totales.values()),
        "codigos": D270_CODIGOS,
    }


# ── Score Fiscal V2 — 5 indicadores DGT reales ──────────────────────────────
# Score 0-100 invertido: 0=máximo riesgo, 100=sin riesgo fiscal
# Metodología: ponderación por importancia de control fiscal DGT CR

def calcular_score_v2(
    bank_txns: list[dict],
    fe_emitidas: list[dict],
    fe_recibidas: list[dict],
    saldo_banco: float,
    saldo_libros: float,
) -> dict:
    """
    Motor de score CENTINELA V2 — 5 indicadores reales DGT Costa Rica.

    Score 0-100 (invertido): 100 = sin riesgo, 0 = riesgo máximo.

    Indicadores:
      I1 (30%): Cobertura documental = txns CON_FE / total_txns
      I2 (25%): Exposición IVA = sum(iva_estimado SIN_FE) / total_ingresos
      I3 (20%): Concentración sin FE = top3_beneficiarios_sinFE / total_debitos
      I4 (15%): Operaciones sin referencia trazable (SINPE/transf sin FE)
      I5 (10%): Discrepancia banco vs FE-D101 proyectada

    Args:
        bank_txns:    lista con 'match_estado', 'tipo', 'monto', 'iva_estimado',
                      'beneficiario_nombre', 'beneficiario_categoria'
        fe_emitidas:  lista de FE emitidas del período
        fe_recibidas: lista de FE recibidas del período (puede estar vacía)
        saldo_banco:  saldo final banco (del PDF)
        saldo_libros: saldo calculado desde journal_lines

    Returns:
        dict con score_total (0-100), nivel, indicadores, exposicion_iva, exposicion_renta
    """
    if not bank_txns:
        return _score_vacio()

    total = len(bank_txns)
    con_fe  = sum(1 for t in bank_txns if t.get("match_estado") == "CON_FE")
    sin_fe  = [t for t in bank_txns if t.get("match_estado") == "SIN_FE"]
    total_ingresos = sum(float(t.get("monto", 0)) for t in bank_txns if t.get("tipo") == "CR")

    # ── I1: Cobertura documental (30%) ────────────────────────────────────────
    i1_ratio = con_fe / total if total else 1.0
    i1_score = i1_ratio * 100  # 100 si todos tienen FE

    # ── I2: Exposición IVA (25%) ──────────────────────────────────────────────
    iva_total   = sum(abs(float(t.get("iva_estimado", 0) or 0)) for t in sin_fe if t.get("tipo") == "CR")
    if total_ingresos > 0:
        i2_ratio = min(iva_total / total_ingresos, 1.0)
    else:
        i2_ratio = 0.0
    i2_score = (1.0 - i2_ratio) * 100  # 100 si no hay IVA en riesgo

    # ── I3: Concentración beneficiarios sin FE (20%) ──────────────────────────
    # Top-3 beneficiarios en débitos SIN_FE vs total débitos
    from collections import Counter
    debitos_sinfe_por_ben: Counter = Counter()
    for t in sin_fe:
        if t.get("tipo") == "DB":
            bnom = t.get("beneficiario_nombre", "DESCONOCIDO")
            debitos_sinfe_por_ben[bnom] += float(t.get("monto", 0))
    total_debitos = sum(float(t.get("monto", 0)) for t in bank_txns if t.get("tipo") == "DB")
    top3_sinfe = sum(v for _, v in debitos_sinfe_por_ben.most_common(3))
    if total_debitos > 0:
        i3_ratio = min(top3_sinfe / total_debitos, 1.0)
    else:
        i3_ratio = 0.0
    i3_score = (1.0 - i3_ratio) * 100

    # ── I4: Operaciones sin referencia (15%) ──────────────────────────────────
    # SINPE/transferencias sin FE → menor trazabilidad
    sin_ref = [
        t for t in sin_fe
        if any(kw in (t.get("descripcion") or "").upper()
               for kw in ("SINPE", "TRANSFER", "TRASLADO"))
    ]
    i4_ratio = len(sin_ref) / total if total else 0.0
    i4_score = (1.0 - i4_ratio) * 100

    # ── I5: Discrepancia banco vs D-101 proyectado (10%) ─────────────────────
    total_fe_ingresos = sum(abs(float(fe.get("monto", fe.get("total_amount", 0)) or 0))
                            for fe in fe_emitidas)
    if total_ingresos > 0 and total_fe_ingresos > 0:
        brecha = abs(total_ingresos - total_fe_ingresos) / total_ingresos
        i5_score = max(0.0, (1.0 - brecha) * 100)
    else:
        i5_score = 50.0  # Sin FE emitidas → riesgo medio

    # ── Score ponderado ───────────────────────────────────────────────────────
    score = (
        i1_score * 0.30 +
        i2_score * 0.25 +
        i3_score * 0.20 +
        i4_score * 0.15 +
        i5_score * 0.10
    )
    score = round(min(max(score, 0.0), 100.0), 1)

    # Nivel de riesgo (invertido: score bajo = riesgo alto)
    if score >= 91:
        nivel, emoji = "VERDE",    "🟢"
    elif score >= 71:
        nivel, emoji = "BAJO",     "🟡"
    elif score >= 41:
        nivel, emoji = "MODERADO", "🟠"
    else:
        nivel, emoji = "CRITICO",  "🔴"

    # ── Exposición fiscal real (metodología Hacienda CR) ─────────────────────
    # INGRESOS sin FE (créditos bancarios SIN_FE):
    #   Hacienda presume son ventas → cobra IVA 13/113 + Renta 30% sobre base
    ingresos_sin_fe_cr  = sum(abs(float(t.get("monto", 0)))
                              for t in sin_fe if t.get("tipo") == "CR")
    iva_presunto_cr     = round(ingresos_sin_fe_cr * 13 / 113, 2)
    renta_presunta_cr   = round((ingresos_sin_fe_cr - iva_presunto_cr) * 0.25, 2)

    # GASTOS sin FE (débitos bancarios SIN_FE):
    #   Hacienda rechaza crédito IVA + rechaza deducción de renta
    gastos_sin_fe_db    = sum(abs(float(t.get("monto", 0)))
                              for t in sin_fe if t.get("tipo") == "DB")
    iva_no_acreditable  = round(gastos_sin_fe_db * 13 / 113, 2)
    escudo_renta_perdido= round(gastos_sin_fe_db * 0.25, 2)

    exposicion_iva   = round(iva_presunto_cr + iva_no_acreditable, 2)
    exposicion_renta = round(renta_presunta_cr + escudo_renta_perdido, 2)

    return {
        "score_total":      score,
        "nivel":            nivel,
        "emoji":            emoji,
        "version":          "v2",
        "indicadores": {
            "I1_cobertura_documental": round(i1_score, 1),
            "I2_exposicion_iva":       round(i2_score, 1),
            "I3_concentracion_sinfe":  round(i3_score, 1),
            "I4_sin_referencia":       round(i4_score, 1),
            "I5_discrepancia_d101":    round(i5_score, 1),
        },
        "totales": {
            "total_txns":    total,
            "con_fe":        con_fe,
            "sin_fe":        len(sin_fe),
            "total_ingresos": total_ingresos,
            "total_debitos": total_debitos,
        },
        "exposicion_iva":   exposicion_iva,
        "exposicion_renta": exposicion_renta,
        "exposicion_total": round(exposicion_iva + exposicion_renta, 2),
        "saldo_diff":       round(saldo_banco - saldo_libros, 2),
        # Desglose granular para el layout "INGRESOS vs GASTOS sin FE"
        "desglose": {
            "ingresos_sin_fe":      round(ingresos_sin_fe_cr, 2),
            "iva_presunto_cr":      iva_presunto_cr,
            "renta_presunta_cr":    renta_presunta_cr,
            "gastos_sin_fe":        round(gastos_sin_fe_db, 2),
            "iva_no_acreditable":   iva_no_acreditable,
            "escudo_renta_perdido": escudo_renta_perdido,
            "multa_estimada_50pct": round((exposicion_iva + exposicion_renta) * 0.50, 2),
            "riesgo_maximo":        round((exposicion_iva + exposicion_renta) * 1.50, 2),
        },
    }


def _score_vacio() -> dict:
    """Score vacío cuando no hay transacciones."""
    return {
        "score_total": 100.0, "nivel": "VERDE", "emoji": "🟢",
        "version": "v2",
        "indicadores": {k: 100.0 for k in
                        ["I1_cobertura_documental","I2_exposicion_iva",
                         "I3_concentracion_sinfe","I4_sin_referencia","I5_discrepancia_d101"]},
        "totales": {"total_txns":0,"con_fe":0,"sin_fe":0,"total_ingresos":0,"total_debitos":0},
        "exposicion_iva": 0.0, "exposicion_renta": 0.0, "exposicion_total": 0.0, "saldo_diff": 0.0,
    }
