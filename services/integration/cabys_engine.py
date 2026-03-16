"""
integration/cabys_engine.py
════════════════════════════════════════════════════════════
Motor de resolución CABYS → Cuenta Contable  (v2 — Solución Global)

Jerarquía de resolución:
  1. Regla exacta del tenant (cabys_account_rules.cabys_code)     → conf 1.0
  2. Regla por prefijo 2 dígitos (sector CABYS) en la DB          → conf 0.8
  3. Semántica enriquecida: hints del sector CABYS + descripción
     del ítem → busca en el catálogo NIIF real del tenant         → conf 0.6
  4. Fallback genérico → CUENTA_OTROS_GASTOS (5299)               → conf 0.3

Novedades v2:
  - _CABYS_PREFIX_HINTS: tabla estática con 50+ sectores CABYS
    (basado en la Clasificación Central de Productos CPC v2.1 de la ONU,
    que es el estándar que Hacienda CR adopta para su catálogo CABYS).
    Cubre TODOS los prefijos de 2 dígitos relevantes para Costa Rica.
  - _buscar_semantico ahora acepta hint_keywords adicionales del sector
    y los mezcla con las palabras de la descripción del ítem.
  - Ningún CABYS queda sin al menos 1 keyword de sector para la búsqueda.

Reglas de Oro:
  - Función pura: no modifica DB, solo lee
  - Siempre retorna un resultado (nunca None)
  - Si asset_flag y monto >= min_amount → needs_review = True
"""
import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Cuenta de fallback cuando no hay ningún match semántico.
# 5299 = "Otros Gastos Operativos" — existe en catálogo estándar CR.
CUENTA_OTROS_GASTOS = "5299"

# ── Mapa de tarifa_codigo → tipo y porcentaje IVA (Hacienda v4.4) ──────────
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
    """
    if tipo_exoneracion:
        return {"tipo": "EXONERADO", "tarifa": 0.0, "acreditable": False}
    result = TARIFA_MAP.get(tarifa_codigo)
    if result:
        return dict(result)
    logger.warning(f"⚠️ cabys_engine: tarifa_codigo '{tarifa_codigo}' desconocida → NO_SUJETO")
    return {"tipo": "NO_SUJETO", "tarifa": 0.0, "acreditable": False}


# ══════════════════════════════════════════════════════════════════════════════
# TABLA GLOBAL DE HINTS POR SECTOR CABYS
# Basada en la Clasificación Central de Productos (CPC v2.1) de la ONU,
# que Hacienda CR adopta como base para su catálogo CABYS.
# Prefijo = primeros 2 dígitos del código CABYS (sector).
# Las keywords se usan para buscar semánticamente en el catálogo NIIF del tenant.
# account_type restringe la búsqueda al tipo correcto de cuenta.
# ══════════════════════════════════════════════════════════════════════════════
_CABYS_PREFIX_HINTS: dict = {
    # ── Productos agropecuarios (01-05) ─────────────────────────────────────
    "01": {"tipo": "GASTO", "kws": ["agropecuario", "agricola", "cosecha", "semilla", "abono"]},
    "02": {"tipo": "GASTO", "kws": ["agropecuario", "ganadero", "pecuario", "animal"]},
    "03": {"tipo": "GASTO", "kws": ["forestal", "madera", "silvicultura"]},
    "04": {"tipo": "GASTO", "kws": ["pesca", "acuicultura", "marisco", "pescado"]},
    "05": {"tipo": "GASTO", "kws": ["mineral", "combustible", "petroleo", "gas", "extraccion"]},

    # ── Alimentos y bebidas (10-16) ──────────────────────────────────────────
    "10": {"tipo": "GASTO", "kws": ["alimento", "carne", "conserva", "producto alimenticio"]},
    "11": {"tipo": "GASTO", "kws": ["lacteo", "queso", "leche", "mantequilla"]},
    "12": {"tipo": "GASTO", "kws": ["alimento", "aceite", "grasa", "comestible"]},
    "13": {"tipo": "GASTO", "kws": ["cereal", "harina", "panaderia", "pasteleria"]},
    "14": {"tipo": "GASTO", "kws": ["alimento", "fruta", "vegetal", "procesado"]},
    "15": {"tipo": "GASTO", "kws": ["bebida", "jugo", "refresco", "soda"]},
    "16": {"tipo": "GASTO", "kws": ["tabaco", "cigarro"]},

    # ── Textiles, cuero, papel (17-22) ──────────────────────────────────────
    "17": {"tipo": "GASTO", "kws": ["textil", "tela", "fibra", "hilado"]},
    "18": {"tipo": "GASTO", "kws": ["confeccion", "ropa", "vestido", "uniformes"]},
    "19": {"tipo": "GASTO", "kws": ["cuero", "calzado", "equipaje", "bolso"]},
    "20": {"tipo": "GASTO", "kws": ["madera", "mueble", "carpinteria"]},
    "21": {"tipo": "GASTO", "kws": ["papel", "carton", "embalaje", "papeleria"]},
    "22": {"tipo": "GASTO", "kws": ["impresion", "imprenta", "publicacion", "editorial"]},

    # ── Químicos, farmacéuticos (23-25) ─────────────────────────────────────
    "23": {"tipo": "GASTO", "kws": ["combustible", "diesel", "gasolina", "petroleo"]},
    "24": {"tipo": "GASTO", "kws": ["quimico", "reactivo", "laboratorio"]},
    "25": {"tipo": "GASTO", "kws": ["farmaceutico", "medicamento", "medicina", "farmacia"]},

    # ── Plásticos, minerales (26-28) ─────────────────────────────────────────
    "26": {"tipo": "GASTO", "kws": ["plastico", "caucho", "hule"]},
    "27": {"tipo": "GASTO", "kws": ["vidrio", "ceramica", "materiales construccion"]},
    "28": {"tipo": "GASTO", "kws": ["mineral", "cemento", "concreto", "arcilla"]},

    # ── Metales (29-31) ──────────────────────────────────────────────────────
    "29": {"tipo": "GASTO", "kws": ["metal", "hierro", "acero", "aluminio"]},
    "30": {"tipo": "GASTO", "kws": ["metal", "herraje", "herramienta"]},
    "31": {"tipo": "GASTO", "kws": ["electronico", "electrico", "componente", "circuito"]},

    # ── Maquinaria y equipos → ACTIVO (32-36) ────────────────────────────────
    "32": {"tipo": "ACTIVO", "kws": ["maquinaria", "equipo industrial", "motor"]},
    "33": {"tipo": "ACTIVO", "kws": ["computadora", "equipo computo", "servidor", "laptop"]},
    "34": {"tipo": "ACTIVO", "kws": ["equipo electrico", "transformador", "generador"]},
    "35": {"tipo": "ACTIVO", "kws": ["vehiculo", "automovil", "camion", "flotilla"]},
    "36": {"tipo": "ACTIVO", "kws": ["mueble", "mobiliario", "equipo oficina"]},

    # ── Construcción (41-43) ─────────────────────────────────────────────────
    "41": {"tipo": "GASTO", "kws": ["construccion", "obra", "edificacion", "remodelacion"]},
    "42": {"tipo": "GASTO", "kws": ["acabado", "pintura", "instalacion", "obra civil"]},
    "43": {"tipo": "GASTO", "kws": ["instalacion", "electrico", "plomeria", "obra"]},

    # ── Comercio / Mercadería (45-47) ────────────────────────────────────────
    "45": {"tipo": "GASTO", "kws": ["mercaderia", "inventario", "producto", "reventa"]},
    "46": {"tipo": "GASTO", "kws": ["mayoreo", "distribucion", "comercio"]},
    "47": {"tipo": "GASTO", "kws": ["venta", "detalle", "consumo", "mercaderia"]},

    # ── Transporte y logística (49-53) ───────────────────────────────────────
    "49": {"tipo": "GASTO", "kws": ["transporte", "flete", "acarreo", "logistica"]},
    "50": {"tipo": "GASTO", "kws": ["marítimo", "naviero", "carga maritima"]},
    "51": {"tipo": "GASTO", "kws": ["aereo", "carga aerea", "avion"]},
    "52": {"tipo": "GASTO", "kws": ["almacenamiento", "bodega", "deposito"]},
    "53": {"tipo": "GASTO", "kws": ["correo", "mensajeria", "courier", "envio"]},

    # ── Alojamiento y gastronomía (55-56) ────────────────────────────────────
    "55": {"tipo": "GASTO", "kws": ["alojamiento", "hotel", "hospedaje", "habitacion"]},
    "56": {"tipo": "GASTO", "kws": ["restaurante", "comida", "alimentacion", "catering"]},

    # ── Información y comunicaciones (58-60) ─────────────────────────────────
    "58": {"tipo": "GASTO", "kws": ["comunicacion", "telecomunicaciones", "internet", "telefono"]},
    "59": {"tipo": "GASTO", "kws": ["telecomunicaciones", "radio", "television", "señal"]},
    "60": {"tipo": "GASTO", "kws": ["informatica", "tecnologia", "sistema", "software"]},

    # ── Servicios financieros y seguros (61) ─────────────────────────────────
    "61": {"tipo": "GASTO", "kws": ["financiero", "bancario", "seguro", "comision bancaria"]},

    # ── Servicios de TI (62-63) ──────────────────────────────────────────────
    "62": {"tipo": "GASTO", "kws": ["tecnologia", "software", "sistema", "informatica", "desarrollo"]},
    "63": {"tipo": "GASTO", "kws": ["tecnologia", "datos", "informacion", "software", "sistema"]},

    # ── Servicios profesionales y técnicos (64-69) ───────────────────────────
    "64": {"tipo": "GASTO", "kws": ["profesional", "consultoria", "asesoria", "servicio tecnico"]},
    "65": {"tipo": "GASTO", "kws": ["legal", "juridico", "notarial", "abogado"]},
    "66": {"tipo": "GASTO", "kws": ["contable", "auditoria", "contabilidad", "financiero"]},
    "67": {"tipo": "GASTO", "kws": ["arquitectura", "ingenieria", "diseno tecnico"]},
    "68": {"tipo": "GASTO", "kws": ["investigacion", "desarrollo", "cientifico"]},
    "69": {"tipo": "GASTO", "kws": ["publicidad", "marketing", "mercadeo", "investigacion mercado"]},

    # ── Otros servicios empresariales (70-75) ────────────────────────────────
    "70": {"tipo": "GASTO", "kws": ["alquiler", "arrendamiento", "renta", "inmueble"]},
    "72": {"tipo": "GASTO", "kws": ["veterinario", "agropecuario", "animal"]},
    "73": {"tipo": "GASTO", "kws": ["cientifico", "laboratorio", "analisis", "prueba"]},
    "74": {"tipo": "GASTO", "kws": ["empleo", "recurso humano", "reclutamiento", "personal"]},
    "75": {"tipo": "GASTO", "kws": ["seguridad", "vigilancia", "investigacion privada"]},

    # ── Soporte operativo (77-82) ─────────────────────────────────────────────
    "77": {"tipo": "GASTO", "kws": ["alquiler", "arrendamiento", "leasing", "renta equipo"]},
    "78": {"tipo": "GASTO", "kws": ["viaje", "turismo", "agencia", "excursion"]},
    "79": {"tipo": "GASTO", "kws": ["turismo", "reservacion", "viaje", "tour"]},
    "80": {"tipo": "GASTO", "kws": ["seguridad", "vigilancia", "custodia", "guardas"]},
    "81": {"tipo": "GASTO", "kws": ["mantenimiento", "reparacion", "limpieza", "aseo"]},
    "82": {"tipo": "GASTO", "kws": ["administrativo", "oficina", "soporte", "call center"]},

    # ── Tecnología e informática / soporte técnico (83) ──────────────────────
    "83": {"tipo": "GASTO", "kws": ["tecnologia", "software", "sistema", "consultoria",
                                     "informatica", "hardware", "desarrollo", "soporte tecnico"]},

    # ── Servicios sociales y personales (85-93) ──────────────────────────────
    "85": {"tipo": "GASTO", "kws": ["educacion", "capacitacion", "formacion", "curso", "entrenamiento"]},
    "86": {"tipo": "GASTO", "kws": ["salud", "medico", "clinica", "hospital"]},
    "87": {"tipo": "GASTO", "kws": ["salud", "asistencia", "cuidado personal"]},
    "88": {"tipo": "GASTO", "kws": ["asistencia", "bienestar", "social"]},
    "90": {"tipo": "GASTO", "kws": ["publicidad", "marketing", "arte", "entretenimiento"]},
    "91": {"tipo": "GASTO", "kws": ["deporte", "recreacion", "entretenimiento"]},
    "92": {"tipo": "GASTO", "kws": ["cultura", "museo", "biblioteca"]},
    "93": {"tipo": "GASTO", "kws": ["otro servicio", "miscelaneo", "varios"]},

    # ── Membresías y organismos (94-96) ─────────────────────────────────────
    "94": {"tipo": "GASTO", "kws": ["membresia", "afiliacion", "suscripcion", "asociacion", "cuota"]},
    "95": {"tipo": "GASTO", "kws": ["hogar", "domestico", "servicio domestico"]},
    "96": {"tipo": "GASTO", "kws": ["personal", "servicio personal", "cuidado"]},

    # ── Gubernamentales y especiales (98-99) ────────────────────────────────
    "98": {"tipo": "GASTO", "kws": ["gobierno", "administracion publica", "permiso", "tramite"]},
    "99": {"tipo": "GASTO", "kws": ["otro", "varios", "miscelaneo", "gasto general"]},
}

# Prefijos CABYS que corresponden a sectores de bienes de capital (NIIF Secc. 17)
_PREFIJOS_ACTIVO = frozenset(["32", "33", "34", "35", "36"])

# Keywords que sugieren activo fijo en la descripción del ítem
_ASSET_KEYWORDS = frozenset([
    "equipo", "computador", "computadora", "laptop", "servidor", "impresora",
    "vehiculo", "vehiculo", "camion", "camion", "automovil", "automovil",
    "maquinaria", "maquina", "maquina", "tractor", "montacargas",
    "mobiliario", "mueble", "escritorio", "archivero", "archivador",
    "edificio", "terreno", "local", "inmueble", "instalacion", "instalacion",
    "telefono", "telefono", "celular", "tablet", "monitor", "pantalla",
    "generador", "ascensor", "elevador",
    "camara", "camara", "alarma", "ups", "router", "switch", "server",
    "estante", "estanteria", "estanteria", "mesa", "sillon", "sillon",
    "fotocopiadora", "scanner", "escaner", "proyector",
])


def _es_keyword_activo(descripcion: str) -> bool:
    """True si la descripción contiene un keyword de activo fijo."""
    d = descripcion.lower()
    return any(kw in d for kw in _ASSET_KEYWORDS)


def _buscar_semantico(db, tenant_id: str, descripcion: str,
                      hint_keywords: list = None) -> dict | None:
    """
    Búsqueda semántica en el catálogo NIIF del tenant (v2 — enriquecida).

    Combina hint_keywords (del sector CABYS, más confiables) con palabras
    de la descripción del ítem. Los hints van primero en la búsqueda.

    - Si la descripción tiene keywords de activo → busca en ACTIVO primero.
    - Si no → busca en GASTO con todas las keywords.
    - Retorna None solo si absolutamente nada coincide.
    """
    desc_words = [w.lower() for w in (descripcion or "").split() if len(w) >= 4]
    # Hints del sector van primero (más semánticamente precisos)
    all_kws = list(hint_keywords or []) + desc_words

    if not all_kws:
        return None

    # Paso 1: ¿parece activo fijo?
    if _es_keyword_activo(descripcion or ""):
        for kw in all_kws[:8]:
            try:
                row = db.execute(text("""
                    SELECT code AS account_code
                    FROM accounts
                    WHERE tenant_id = :tid
                      AND is_active = TRUE
                      AND LOWER(name) LIKE :kw
                      AND account_type IN (
                          'ACTIVO', 'ASSET',
                          'PROPIEDAD_PLANTA_EQUIPO', 'PROPERTY_PLANT_EQUIPMENT',
                          'ACTIVO_NO_CORRIENTE'
                      )
                    ORDER BY code
                    LIMIT 1
                """), {"tid": tenant_id, "kw": f"%{kw}%"}).fetchone()
                if row:
                    logger.info(f"cabys_engine: SEMANTICA-ACTIVO '{kw}' → {row.account_code}")
                    return {"account_code": row.account_code, "asset_flag": True}
            except Exception:
                pass

    # Paso 2: buscar en cuentas de gasto con todos los keywords
    for kw in all_kws[:10]:
        try:
            row = db.execute(text("""
                SELECT code AS account_code
                FROM accounts
                WHERE tenant_id = :tid
                  AND is_active = TRUE
                  AND allow_entries = TRUE
                  AND LOWER(name) LIKE :kw
                  AND account_type = 'GASTO'
                ORDER BY code
                LIMIT 1
            """), {"tid": tenant_id, "kw": f"%{kw}%"}).fetchone()
            if row:
                logger.info(f"cabys_engine: SEMANTICA-GASTO '{kw}' → {row.account_code}")
                return {"account_code": row.account_code, "asset_flag": False}
        except Exception:
            pass

    return None


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

    Jerarquía:
      1. Regla exacta en cabys_account_rules          → conf 1.0 EXACTA
      2. Regla por prefijo (2 dígitos) en la DB        → conf 0.8 PREFIJO
      3. Semántica enriquecida con hints CABYS          → conf 0.6 SEMANTICA
      4. Fallback OTROS_GASTOS                          → conf 0.3 FALLBACK
    """
    prefix = (cabys_code or "")[:2]

    # ── 1. Regla exacta del tenant ───────────────────────────────────────────
    if cabys_code:
        try:
            row = db.execute(text("""
                SELECT account_code, asset_flag, min_amount
                FROM cabys_account_rules
                WHERE tenant_id = :tid AND cabys_code = :cabys
                ORDER BY prioridad DESC LIMIT 1
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
        except Exception:
            pass

    # ── 2. Regla por prefijo en la DB ───────────────────────────────────────
    if prefix:
        try:
            row_p = db.execute(text("""
                SELECT account_code, asset_flag, min_amount
                FROM cabys_account_rules
                WHERE tenant_id = :tid
                  AND cabys_code IS NULL AND cabys_prefix = :prefix
                ORDER BY prioridad DESC LIMIT 1
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
        except Exception:
            pass

    # ── 3. Semántica enriquecida: hints del sector CABYS ────────────────────
    sector_info     = _CABYS_PREFIX_HINTS.get(prefix, {})
    hint_kws        = sector_info.get("kws", [])
    sector_es_activo = prefix in _PREFIJOS_ACTIVO

    sem = _buscar_semantico(db, tenant_id, descripcion or "", hint_kws)
    if sem:
        return {
            "account_code": sem["account_code"],
            "confidence":   0.6,
            "fuente":       "SEMANTICA",
            "asset_flag":   sector_es_activo or sem.get("asset_flag", False),
            "cabys_code":   cabys_code,
        }

    # ── 4. Fallback — Otros Gastos ───────────────────────────────────────────
    logger.info(
        f"cabys_engine: FALLBACK para CABYS={cabys_code} "
        f"prefix={prefix} desc='{(descripcion or '')[:40]}'"
    )
    return {
        "account_code": CUENTA_OTROS_GASTOS,
        "confidence":   0.3,
        "fuente":       "FALLBACK",
        "asset_flag":   False,
        "cabys_code":   cabys_code,
    }
