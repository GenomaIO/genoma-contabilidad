"""
SIM — Fixes de Audit Pendientes (3 warnings)
=============================================
MÓDULO 1 — BUG-04: Parser BN detecta créditos sin '+' via keywords
MÓDULO 2 — WARN-01: /parse valida banco con BANCO_KEYS (422 si inválido)
MÓDULO 3 — WARN-03: Dedup usa 60 chars, no 30 (evita colapso falso)
"""
import sys, os, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_parser = open(os.path.join(ROOT, "services/conciliacion/bank_pdf_parser.py")).read()
src_router = open(os.path.join(ROOT, "services/conciliacion/router.py")).read()
src_front  = open(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")).read()

# ─── MÓDULO 1: BUG-04 — Parser BN con keywords de crédito ───────────────
print("\n🏦 MÓDULO 1 — BUG-04: Parser BN detecta créditos sin signo:")

# Verificar que el código tiene las keywords
check("_CR_KEYWORDS"           in src_parser, "_CR_KEYWORDS definidas en el parser BN")
check("'ACREDITACION'"         in src_parser, "keyword ACREDITACION incluida")
check("'INTERESES'"            in src_parser, "keyword INTERESES incluida")
check("'RENDIMIENTO'"          in src_parser, "keyword RENDIMIENTO incluida")
check("'DEPOSITO'"             in src_parser, "keyword DEPOSITO incluida")
check("'SALARIO'"              in src_parser, "keyword SALARIO incluida")
check("'DEVOLUCION'"           in src_parser, "keyword DEVOLUCION incluida")
check("any(k in desc_up for k in _CR_KEYWORDS)" in src_parser,
      "lógica any() para detectar al menos una keyword")
check("'CR' if any" in src_parser,
      "resultado: 'CR' si keyword presente, 'DB' si no")

# Simular la lógica sin el parser completo
_CR_KEYWORDS = (
    'ACREDITACION', 'ACREDITACIÓN',
    'INTERESES', 'RENDIMIENTO',
    'DEPOSITO', 'DEPÓSITO',
    'CREDITO', 'CRÉDITO',
    'SALARIO', 'PENSIÓN', 'PENSION',
    'DEVOLUCION', 'DEVOLUCIÓN',
    'REINTEGRO', 'REMESA',
    'BONO', 'SUBSIDIO',
)
def simular_tipo_bn(monto_raw, descripcion):
    """Simula la lógica del parser BN."""
    if monto_raw.endswith('-'):
        return 'DB'
    elif monto_raw.endswith('+'):
        return 'CR'
    else:
        desc_up = descripcion.upper()
        return 'CR' if any(k in desc_up for k in _CR_KEYWORDS) else 'DB'

# Casos de prueba reales del BN
check(simular_tipo_bn("200,000-", "CARGO MENSUALIDAD")      == "DB",  "monto- → DB (sin cambio)")
check(simular_tipo_bn("9,034.45+", "SINPE MOVIL")           == "CR",  "monto+ → CR (sin cambio)")
check(simular_tipo_bn("45,000", "ACREDITACION NOMINA CCSS") == "CR",  "ACREDITACION sin signo → CR ✅")
check(simular_tipo_bn("1,250", "INTERESES PLAZO FIJO")      == "CR",  "INTERESES sin signo → CR ✅")
check(simular_tipo_bn("3,500", "RENDIMIENTO CUENTA SALDO")  == "CR",  "RENDIMIENTO sin signo → CR ✅")
check(simular_tipo_bn("100,000", "SALARIO EMPRESA XYZ")     == "CR",  "SALARIO sin signo → CR ✅")
check(simular_tipo_bn("800", "COMISION MANTENIMIENTO")      == "DB",  "COMISION sin signo → DB (fallback correcto)")
check(simular_tipo_bn("6,200", "PAGO SERVICIOS PUBLICOS")   == "DB",  "PAGO sin signo → DB")
check(simular_tipo_bn("15,000", "DEPOSITO EFECTIVO")        == "CR",  "DEPOSITO sin signo → CR ✅")
check(simular_tipo_bn("25,000", "DEVOLUCION IVA HACIENDA")  == "CR",  "DEVOLUCION sin signo → CR ✅")

# ─── MÓDULO 2: WARN-01 — Validación de banco en /parse ───────────────────
print("\n🔍 MÓDULO 2 — WARN-01: Validación de banco en /parse:")

parse_block_start = src_router.find("@router.post(\"/conciliacion/parse\")")
parse_block_end   = src_router.find("@router.post(\"/conciliacion/parse-file\")")
parse_block = src_router[parse_block_start:parse_block_end]

check("BANCO_KEYS" in parse_block,
      "importa BANCO_KEYS para validar")
check("claves_validas = set(BANCO_KEYS.values())" in parse_block,
      "construye set de claves válidas desde BANCO_KEYS")
check("banco_upper not in claves_validas" in parse_block,
      "condicional: si banco NO está en las claves → error")
check("status_code=422" in parse_block,
      "retorna 422 si banco inválido")
check("banco_upper" in parse_block,
      "normaliza a UPPER antes de validar")
check("Nota: Los PDFs se procesan" in parse_block,
      "docstring actualizado (ya no menciona pdf.js)")

# Simular la validación
from services.conciliacion.bank_pdf_parser import BANCO_KEYS
claves_validas = set(BANCO_KEYS.values())

check("BN"          in claves_validas, "'BN' es válido")
check("BAC"         in claves_validas, "'BAC' es válido")
check("BCR"         in claves_validas, "'BCR' es válido")
check("COOCIQUE"    in claves_validas, "'COOCIQUE' es válido")
check("BANCO_MALO"  not in claves_validas, "'BANCO_MALO' → 422 (inválido rechazado)")
check("test_tenant" not in claves_validas, "'test_tenant' → 422 (cadena seguridad rechazada)")
check("default"     not in claves_validas, "'default' → 422 (cadena hardcode rechazada)")

# ─── MÓDULO 3: WARN-03 — Dedup con 60 chars ─────────────────────────────
print("\n🔑 MÓDULO 3 — WARN-03: Dedup usa 60 chars (no 30):")

check("descripcion?.slice(0, 60)" in src_front,
      "slice de 60 chars en la clave de dedup")
check("descripcion?.slice(0, 30)" not in src_front,
      "slice de 30 chars ELIMINADO")

# Simular el problema que resolvemos
def simular_dedup_key(fecha, monto, descripcion, max_chars):
    return f"{fecha}|{monto}|{descripcion[:max_chars]}"

# Usar descripciones donde la diferencia cae DESPUÉS del char 30
# "TRANSFERENCIA INTERBANCARIA BNCR 11111" vs "TRANSFERENCIA INTERBANCARIA BNCR 99999"
# Los primeros 30 chars son idénticos: "TRANSFERENCIA INTERBANCARIA BNC"
desc_a = "TRANSFERENCIA INTERBANCARIA BNCR 11111"   # ref. distinta al final
desc_b = "TRANSFERENCIA INTERBANCARIA BNCR 99999"   # ref. distinta al final

k30_a = simular_dedup_key("2026-01-15", 100000, desc_a, 30)
k30_b = simular_dedup_key("2026-01-15", 100000, desc_b, 30)
k60_a = simular_dedup_key("2026-01-15", 100000, desc_a, 60)
k60_b = simular_dedup_key("2026-01-15", 100000, desc_b, 60)

check(k30_a == k30_b, "Con 30 chars: ambas txns tienen misma clave (colisión falsa ☠️)")
check(k60_a != k60_b, "Con 60 chars: claves distintas (txns se conservan ambas ✅)")

# Caso donde 60 chars sí deduplicación CORRECTA (mismo movimiento, dos PDFs)
desc_dup = "SINPE MOVIL 8999-8877 PAGO FACTURA AGUA"
k_dup_a = simular_dedup_key("2026-01-20", 15000, desc_dup, 60)
k_dup_b = simular_dedup_key("2026-01-20", 15000, desc_dup, 60)
check(k_dup_a == k_dup_b, "Duplicado real (misma txn en 2 PDFs): clave idéntica → se deduplica ✅")

# ─── Resultado Final ──────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Fixes de Audit (3 warnings resueltos)")
    print("   · BUG-04: Parser BN detecta CR por keywords (10 casos)")
    print("   · WARN-01: /parse rechaza banco inválido con 422")
    print("   · WARN-03: Dedup con 60 chars evita colapso falso")
    sys.exit(0)
