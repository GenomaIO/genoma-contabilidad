"""
beneficiario_extractor.py — Extractor de beneficiario desde descripción bancaria CR

Convierte la descripción cruda del banco en un nombre normalizado y categoría.

Ejemplos de entrada (BNCR, BCR, BAC, Davivienda):
  "01-02-26 MAXIMO MENDEZ VALERIO/CO..."   → "MAXIMO MENDEZ VALERIO"
  "31-01-26 JOSE ALEJANDRO CARVA/COM..."   → "JOSE ALEJANDRO CARVA"
  "14-02-26 BNCR/AYUDA 88443928"          → categoría: BANK_FEE
  "31-01-26 BNCR/INTERESES GANADOS..."    → categoría: BANK_INTEREST
  "12-02-26 SODA RUTA 35 ALAJUELA CRI"    → "SODA RUTA 35"
  "15-02-26 CIDEP CENTRO IBEROAMER./..."  → "CIDEP CENTRO IBEROAMER"

Reglas de Oro:
- No modifica datos; devuelve un dict nuevo
- Sin efectos secundarios; función pura testeable
"""
from __future__ import annotations
import re

# ─── Patrones de entidades bancarias CR (SUGEF) ───────────────────────────────
_BANK_KEYWORDS = re.compile(
    r'\b(BNCR|BCR|BAC|DAVIVIENDA|LAFISE|SCOTIABANK|PROMERICA|BANCREDITO|'
    r'BN VITAL|MUCAP|COOPENAE|COOPEMEP|COOPEAMISTAD|COOPECAJA|COOPESANMARCOS|'
    r'CATHAY|IMPROSA|BANCRECEN|CMB|SERVIBANCA|ATH|REDIBAN)\b',
    re.IGNORECASE,
)

# Palabras que indican cargo del propio banco (no un tercero)
_BANK_FEE_HINTS = re.compile(
    r'\b(COMISION|AYUDA|MANEJO|COSTO DE SERVICIO|CARGO|'
    r'ITF|TIMBRE|IMPUESTO|SEGURO|MEMBRESIA|CUOTA)\b',
    re.IGNORECASE,
)

_BANK_INTEREST_HINTS = re.compile(
    r'\b(INTERES(ES)? GANADOS?|RENDIMIENTOS?|CAPITALIZACION)\b',
    re.IGNORECASE,
)

# Fecha al inicio de la descripción: "DD-MM-YY " o "DDMMYY "
_DATE_PREFIX = re.compile(r'^\d{2}[-/]\d{2}[-/]\d{2,4}\s*')

# Separador que suele delimitar el nombre del beneficiario en BNCR/BCR/Davivienda
_NAME_SEPARATOR = re.compile(r'/[A-Z]{1,4}\.?\s*$|/CO[A-Z]*\.?$', re.IGNORECASE)

# Palabras ruido al final (lugar, tipo de op)
_NOISE_SUFFIX = re.compile(
    r'\s+(S\.?A\.?|CRI|CRIT|COSTA RICA|DE C\.?R\.?\s*|SA DE CV|S\.R\.L\.?|LTDA\.?)$',
    re.IGNORECASE,
)

# Teléfono al final: 8 dígitos seguidos (CR) o 7 dígitos
_PHONE_SUFFIX = re.compile(r'\s+(\d{7,8})\s*$')

# Categorías
CAT_BANK_FEE      = "BANK_FEE"        # comisión / cargo bancario
CAT_BANK_INTEREST = "BANK_INTEREST"   # intereses ganados
CAT_SINPE         = "SINPE"           # SINPE móvil / transferencia electrónica
CAT_TERCERO       = "TERCERO"         # proveedor / cliente normal
CAT_DESCONOCIDO   = "DESCONOCIDO"     # no se pudo determinar


def extraer_beneficiario(descripcion: str, telefono_raw: str | None = None) -> dict:
    """
    Extrae el beneficiario normalizado desde la descripción de una txn bancaria.

    Args:
        descripcion:   Texto crudo del estado de cuenta (ej: "01-02-26 MAXIMO MENDEZ/CO...")
        telefono_raw:  Teléfono ya extraído por el parser (puede ser None)

    Returns:
        dict con:
            nombre_norm:      str  — nombre normalizado en MAYÚSCULAS
            categoria:        str  — CAT_BANK_FEE | CAT_BANK_INTEREST | CAT_SINPE | CAT_TERCERO
            telefono_norm:    str | None — teléfono limpio 8 dígitos
            es_banco:         bool — True si el movimiento es del propio banco
    """
    desc = (descripcion or "").strip()

    # 1. Quitar fecha inicial
    desc_clean = _DATE_PREFIX.sub("", desc).strip()

    # 2. Detectar categoría por banco
    es_banco = bool(_BANK_KEYWORDS.match(desc_clean.split("/")[0].strip()))

    if es_banco:
        if _BANK_INTEREST_HINTS.search(desc_clean):
            return _result("BANCO", CAT_BANK_INTEREST, telefono_raw, True)
        if _BANK_FEE_HINTS.search(desc_clean):
            return _result("BANCO", CAT_BANK_FEE, telefono_raw, True)
        # BNCR con nombre de tercero: "BNCR/NOMBRE" → extraer nombre
        parts = desc_clean.split("/", 1)
        if len(parts) == 2 and parts[1].strip():
            nombre = _limpiar_nombre(parts[1])
            # Si el "nombre" tras / es numérico → es cargo bancario
            if nombre.replace(" ", "").isdigit():
                return _result("BANCO", CAT_BANK_FEE, telefono_raw, True)
            return _result(nombre, CAT_TERCERO, telefono_raw, False)
        return _result("BANCO", CAT_BANK_FEE, telefono_raw, True)

    # 3. Detectar SINPE
    if re.search(r'\bSINPE\b', desc_clean, re.IGNORECASE):
        nombre = _limpiar_nombre(re.sub(r'\bSINPE\b', '', desc_clean, flags=re.IGNORECASE))
        return _result(nombre or "SINPE", CAT_SINPE, telefono_raw, False)

    # 4. Extraer nombre separado por "/"
    if "/" in desc_clean:
        partes = desc_clean.split("/", 1)
        nombre = _limpiar_nombre(partes[0])
    else:
        nombre = _limpiar_nombre(desc_clean)

    # 5. Quitar teléfono si está pegado al nombre
    tel_match = _PHONE_SUFFIX.search(nombre)
    tel_extraido = None
    if tel_match:
        tel_extraido = tel_match.group(1)
        nombre = nombre[:tel_match.start()].strip()

    telefono_final = _normalizar_tel(telefono_raw or tel_extraido)
    cat = CAT_TERCERO if nombre else CAT_DESCONOCIDO

    return _result(nombre or desc_clean[:40].upper(), cat, telefono_final, False)


# ─── Helpers internos ─────────────────────────────────────────────────────────

def _limpiar_nombre(s: str) -> str:
    """Limpia ruido del nombre: sufijos geográficos, siglas societarias, etc."""
    s = s.strip().upper()
    s = _NOISE_SUFFIX.sub("", s).strip()
    # Quitar punto final y comas sueltas
    s = re.sub(r'[,.\s]+$', '', s).strip()
    # Comprimir espacios múltiples
    s = re.sub(r'\s{2,}', ' ', s)
    return s[:80]  # max 80 chars


def _normalizar_tel(tel: str | None) -> str | None:
    if not tel:
        return None
    digits = re.sub(r'\D', '', tel)
    if 7 <= len(digits) <= 8:
        return digits
    return None


def _result(nombre: str, categoria: str, tel_raw: str | None, es_banco: bool) -> dict:
    return {
        "nombre_norm":   nombre.strip().upper()[:80] if nombre else None,
        "categoria":     categoria,
        "telefono_norm": _normalizar_tel(tel_raw),
        "es_banco":      es_banco,
    }
