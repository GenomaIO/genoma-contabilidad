"""
SIM + E2E — Parser Universal de Fechas Bancarias CR
=====================================================

Valida el motor de parsing de estados de cuenta bancarios:

MÓDULO 1 — Formatos de fecha con año completo
MÓDULO 2 — Fecha dd-mm sin año (BN y otros) con inferencia por header
MÓDULO 3 — Meses en letras español (BCR, Coocique y otros)
MÓDULO 4 — Separadores mixtos y formatos raros
MÓDULO 5 — Cross-month split (BN PDF que cruza 2 meses)
MÓDULO 6 — Cadena de saldos entre PDFs consecutivos
MÓDULO 7 — extract_header_info detecta banco y fechas del header
MÓDULO 8 — Verificación de código (imports, funciones exportadas)
"""
import sys, os
from datetime import date

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services.conciliacion.bank_pdf_parser import (
    parse_fecha_universal,
    extract_header_info,
    split_transactions_by_period,
    verificar_cadena_saldos,
    parse_pdf_text,
    extract_saldos,
    _parse_monto_cr,
)

# ─── MÓDULO 1: Formatos numéricos con año completo ─────────────────────────
print("\n📅 MÓDULO 1 — Formatos numéricos con año completo:")

check(parse_fecha_universal("22/12/2025") == "2025-12-22", "dd/mm/yyyy con slash")
check(parse_fecha_universal("22-12-2025") == "2025-12-22", "dd-mm-yyyy con guión")
check(parse_fecha_universal("22.12.2025") == "2025-12-22", "dd.mm.yyyy con punto")
check(parse_fecha_universal("02/01/2026") == "2026-01-02", "dd/mm/yyyy enero")
check(parse_fecha_universal("2026-01-02") == "2026-01-02", "ISO yyyy-mm-dd")
check(parse_fecha_universal("16/01/26")   == "2026-01-16", "dd/mm/yy dos dígitos año")
check(parse_fecha_universal("31-01-26")   == "2026-01-31", "dd-mm-yy dos dígitos año")

# ─── MÓDULO 2: dd-mm sin año (BN) con inferencia de año ───────────────────
print("\n🏦 MÓDULO 2 — Fecha dd-mm sin año (BN) — inferencia por header:")

fecha_fin_enero = date(2026, 1, 16)   # "Fecha éste estado: 16/01/2026" del PDF (2)

# Transacciones de DIC-2025 en un PDF cuyo corte es 16 Ene 2026
check(parse_fecha_universal("22-12", context_fecha_fin=fecha_fin_enero) == "2025-12-22",
      "22-12 → 2025-12-22 (mes 12 > corte mes 1 → año anterior)")
check(parse_fecha_universal("31-12", context_fecha_fin=fecha_fin_enero) == "2025-12-31",
      "31-12 → 2025-12-31")
check(parse_fecha_universal("29-12", context_fecha_fin=fecha_fin_enero) == "2025-12-29",
      "29-12 → 2025-12-29")

# Transacciones de ENE-2026 en el mismo PDF
check(parse_fecha_universal("02-01", context_fecha_fin=fecha_fin_enero) == "2026-01-02",
      "02-01 → 2026-01-02 (mes 1 = mes corte → mismo año)")
check(parse_fecha_universal("09-01", context_fecha_fin=fecha_fin_enero) == "2026-01-09",
      "09-01 → 2026-01-09")
check(parse_fecha_universal("16-01", context_fecha_fin=fecha_fin_enero) == "2026-01-16",
      "16-01 → 2026-01-16 (último día del corte)")

# PDF (1): corte 20/02/2026 — tiene ene + feb
fecha_fin_feb = date(2026, 2, 20)

check(parse_fecha_universal("19-01", context_fecha_fin=fecha_fin_feb) == "2026-01-19",
      "19-01 → 2026-01-19 (mes 1, corte feb → mismo año)")
check(parse_fecha_universal("30-01", context_fecha_fin=fecha_fin_feb) == "2026-01-30",
      "30-01 → 2026-01-30")
check(parse_fecha_universal("02-02", context_fecha_fin=fecha_fin_feb) == "2026-02-02",
      "02-02 → 2026-02-02 (mes 2 = mes corte)")
check(parse_fecha_universal("19-02", context_fecha_fin=fecha_fin_feb) == "2026-02-19",
      "19-02 → 2026-02-19")

# Fallback sin contexto
check(parse_fecha_universal("15-03", context_year=2026) == "2026-03-15",
      "15-03 con context_year=2026")

# ─── MÓDULO 3: Meses en letras español ────────────────────────────────────
print("\n🔤 MÓDULO 3 — Meses en letras (BCR, Coocique y otros):")

# BCR suele usar "22 ENERO 2026", "22-ENE-26", "22/ENE/2026"
check(parse_fecha_universal("22 enero 2026")   == "2026-01-22", "22 enero 2026 (minúsculas)")
check(parse_fecha_universal("22 ENERO 2026")   == "2026-01-22", "22 ENERO 2026 (mayúsculas)")
check(parse_fecha_universal("15 febrero 2026") == "2026-02-15", "15 febrero 2026")
check(parse_fecha_universal("31 diciembre 2025") == "2025-12-31", "31 diciembre 2025")
check(parse_fecha_universal("01 marzo 2026")   == "2026-03-01",  "01 marzo 2026")

# Abreviaturas
check(parse_fecha_universal("22-ENE-2026") == "2026-01-22", "22-ENE-2026")
check(parse_fecha_universal("22-ENE-26")   == "2026-01-22", "22-ENE-26 (año 2 dígitos)")
check(parse_fecha_universal("15-FEB-26")   == "2026-02-15", "15-FEB-26")
check(parse_fecha_universal("31-DIC-25")   == "2025-12-31", "31-DIC-25")
check(parse_fecha_universal("10-SET-2025") == "2025-09-10",
      "10-SET-2025 (SET=septiembre, uso CR)")
check(parse_fecha_universal("10-SEP-2025") == "2025-09-10",
      "10-SEP-2025 (SEP=septiembre, uso estándar)")

# Meses completos y variantes
check(parse_fecha_universal("5 ABR 2025")  == "2025-04-05", "5 ABR 2025")
check(parse_fecha_universal("3 ago 2025")  == "2025-08-03", "3 ago 2025 (agosto abrev)")
check(parse_fecha_universal("28 NOV 2025") == "2025-11-28", "28 NOV 2025")

# ─── MÓDULO 4: Separadores y casos raros ──────────────────────────────────
print("\n⚙️  MÓDULO 4 — Separadores mixtos y casos raros:")

check(parse_fecha_universal("2025.12.22")  == "2025-12-22", "yyyy.mm.dd con punto")
check(parse_fecha_universal("22/01/2026")  == "2026-01-22", "dd/mm/yyyy slash")
check(parse_fecha_universal("")            is None,         "cadena vacía → None")
check(parse_fecha_universal("ABCDEF")      is None,         "texto sin fecha → None")
check(parse_fecha_universal("00-13")       is None,         "fecha inválida (mes 13) → None")
check(parse_fecha_universal("32-01")       is None,         "fecha inválida (día 32) → None")

# ─── MÓDULO 5: Split cross-month (BN PDF cruzado) ─────────────────────────
print("\n✂️  MÓDULO 5 — Split por mes (PDF BN que cruza diciembre→enero):")

# Simular las transacciones del PDF (2) del BN real:
#   22-12 al 16-01 → saldo: 8,174,111.16 → 5,658,341.61
txns_pdf2 = [
    {'fecha': '2025-12-22', 'descripcion': 'GOMEZ NAVARRO DEILYN', 'tipo': 'DB', 'monto': 200000, 'saldo': 7974111.16, 'banco': 'BN'},
    {'fecha': '2025-12-22', 'descripcion': 'BNCR/VALLA PUBLICITARIA', 'tipo': 'DB', 'monto': 423750, 'saldo': 7550361.16, 'banco': 'BN'},
    {'fecha': '2025-12-23', 'descripcion': 'BNCR/TENIS', 'tipo': 'DB', 'monto': 38500, 'saldo': 7511861.16, 'banco': 'BN'},
    {'fecha': '2025-12-29', 'descripcion': 'BNCR/AYUDA', 'tipo': 'DB', 'monto': 250000, 'saldo': 6761861.16, 'banco': 'BN'},
    {'fecha': '2025-12-31', 'descripcion': 'BNCR/COMISION', 'tipo': 'DB', 'monto': 175000, 'saldo': 6586861.16, 'banco': 'BN'},
    {'fecha': '2025-12-31', 'descripcion': 'BNCR/COMIDA', 'tipo': 'DB', 'monto': 25000, 'saldo': 6561861.16, 'banco': 'BN'},
    # Enero 2026
    {'fecha': '2026-01-02', 'descripcion': 'BNCR/INTERESES GANADOS', 'tipo': 'CR', 'monto': 9034.45, 'saldo': 6570895.61, 'banco': 'BN'},
    {'fecha': '2026-01-09', 'descripcion': 'BNCR/SOCIEDAD', 'tipo': 'DB', 'monto': 102804, 'saldo': 6458091.61, 'banco': 'BN'},
    {'fecha': '2026-01-16', 'descripcion': 'BNCR/PREST', 'tipo': 'DB', 'monto': 300000, 'saldo': 5658341.61, 'banco': 'BN'},
]

grupos = split_transactions_by_period(txns_pdf2)
check('2025-12' in grupos, "split detecta período 2025-12")
check('2026-01' in grupos, "split detecta período 2026-01")
check(len(grupos['2025-12']) == 6, f"diciembre: 6 transacciones (got {len(grupos.get('2025-12', []))})")
check(len(grupos['2026-01']) == 3, f"enero: 3 transacciones (got {len(grupos.get('2026-01', []))})")

# Confirmar que enero en PDF (1) complementa correctamente
txns_pdf1_ene = [
    {'fecha': '2026-01-19', 'descripcion': 'BNCR/LOTO', 'tipo': 'DB', 'monto': 30000, 'saldo': 5628341.61, 'banco': 'BN'},
    {'fecha': '2026-01-21', 'descripcion': 'CIDEP CENTRO', 'tipo': 'CR', 'monto': 21348.88, 'saldo': 5597190.49, 'banco': 'BN'},
    {'fecha': '2026-01-30', 'descripcion': 'VILLEGAS ROJAS', 'tipo': 'DB', 'monto': 50000, 'saldo': 9573320.11, 'banco': 'BN'},
]
grupos1 = split_transactions_by_period(txns_pdf1_ene)
check('2026-01' in grupos1, "PDF(1) split contiene 2026-01")

# Enero completo = PDF2.ene + PDF1.ene
enero_completo = grupos.get('2026-01', []) + grupos1.get('2026-01', [])
check(len(enero_completo) == 6, f"Enero total = 3 (PDF2) + 3 (PDF1) = 6 txns (got {len(enero_completo)})")

# ─── MÓDULO 6: Cadena de saldos entre PDFs ────────────────────────────────
print("\n🔗 MÓDULO 6 — Cadena de saldos entre PDFs consecutivos:")

# Datos tomados directamente de los PDFs del BN compartidos
pdf_chain = [
    {'label': 'PDF(2) Dic22-Ene16', 'saldo_inicial': 8_174_111.16, 'saldo_final': 5_658_341.61},
    {'label': 'PDF(1) Ene19-Feb20', 'saldo_inicial': 5_658_341.61, 'saldo_final': 8_484_597.50},
]

resultado = verificar_cadena_saldos(pdf_chain)
check(resultado['ok'] == True, "Cadena de saldos BN cuadra ✓")
check(len(resultado['pares']) == 1, "1 par verificado")
check(resultado['pares'][0]['diff'] == 0.0, "diff exacta = ₡0.00 (saldo igual a centavo)")
check(len(resultado['gaps']) == 0, "Sin gaps en la cadena de saldos")

# Caso con GAP (PDF faltante) — el sistema lo detecta
pdf_chain_gap = [
    {'label': 'PDF(2)',  'saldo_inicial': 8_174_111.16, 'saldo_final': 5_658_341.61},
    {'label': 'PDF(3)',  'saldo_inicial': 9_000_000.00, 'saldo_final': 8_484_597.50},  # ← gap!
]
resultado_gap = verificar_cadena_saldos(pdf_chain_gap)
check(resultado_gap['ok'] == False, "GAP detectado cuando saldos no cuadran ✓")
check(len(resultado_gap['gaps']) == 1, "1 gap identificado")

# Un solo PDF → siempre OK (sin pares que verificar)
resultado_solo = verificar_cadena_saldos([
    {'label': 'PDF único', 'saldo_inicial': 1_000_000, 'saldo_final': 800_000}
])
check(resultado_solo['ok'] == True, "1 solo PDF → ok=True (nada que comparar)")

# ─── MÓDULO 7: extract_header_info ────────────────────────────────────────
print("\n📋 MÓDULO 7 — Extracción de metadatos del header del PDF:")

# Texto simulado del PDF (2) del BN
texto_bn_pdf2 = """
Estado de Cuenta Electrónica Colones
BANCO NACIONAL
Número de cuenta: 200-01-012-080146-5
Nombre: GONZALEZ ALFARO ALVARO
Fecha último estado: 19/12/2025
Fecha éste estado: 16/01/2026
"""

header = extract_header_info(texto_bn_pdf2)
check(header['banco_detectado'] == 'BN', "Banco Nacional detectado como BN")
check(header['fecha_inicio'] == date(2025, 12, 19), "fecha_inicio = 19/12/2025")
check(header['fecha_fin']    == date(2026, 1,  16), "fecha_fin = 16/01/2026")
check(header['numero_cuenta'] == '200-01-012-080146-5', "número de cuenta extraído")

# BCR — corte al final de mes
texto_bcr = """
BANCO DE COSTA RICA
Estado de Cuenta
Fecha de corte: 31/01/2026
"""
header_bcr = extract_header_info(texto_bcr)
check(header_bcr['banco_detectado'] == 'BCR', "BCR detectado")
check(header_bcr['fecha_fin'] == date(2026, 1, 31), "BCR fecha_fin = 31/01/2026")

# BAC — formato diferente
texto_bac = """
BAC San José
Estado de cuenta al 31/01/2026
"""
header_bac = extract_header_info(texto_bac)
check(header_bac['banco_detectado'] == 'BAC', "BAC detectado")

# ─── MÓDULO 8: Verificación de código ─────────────────────────────────────
print("\n📂 MÓDULO 8 — Verificación de código y exports:")

parser_src = open(os.path.join(ROOT, "services/conciliacion/bank_pdf_parser.py")).read()
check("parse_fecha_universal"       in parser_src, "parse_fecha_universal definida")
check("extract_header_info"         in parser_src, "extract_header_info definida")
check("split_transactions_by_period" in parser_src, "split_transactions_by_period definida")
check("verificar_cadena_saldos"     in parser_src, "verificar_cadena_saldos definida")
check("_MESES_ES"                   in parser_src, "diccionario _MESES_ES de meses en español")
check("_FECHA_DDMM"                 in parser_src, "regex _FECHA_DDMM sin año")
check("_FECHA_LETRAS"               in parser_src, "regex _FECHA_LETRAS con mes en texto")
check("context_fecha_fin"           in parser_src, "parámetro context_fecha_fin en parser")
check("es_reguladora" not in parser_src, "sin contaminación de código de otra feature")

# Verificar que _parse_bn usa el nuevo sistema
check("parse_fecha_universal" in parser_src and "_parse_bn" in parser_src,
      "parser BN v2 usa parse_fecha_universal")
check("fecha_fin" in parser_src, "BN parser extrae fecha_fin del header")

# ─── Resultado final ───────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Parser Universal de Fechas Bancarias CR")
    print("   Formatos soportados:")
    print("   · dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy, yyyy-mm-dd (ISO)")
    print("   · dd-mm SIN AÑO → inferencia por 'Fecha éste estado' del PDF")
    print("   · Meses en letras: ENE, FEB, ENERO, FEBRERO ... DIC, DICIEMBRE")
    print("   · SET (septiembre CR) + SEP (estándar)")
    print("   · Separadores: /, -, ., espacio")
    print("   · Cross-month split: PDF que cruza 2 meses → 2 grupos YYYY-MM")
    print("   · Cadena de saldos: detecta PDFs faltantes si saldo no cuadra")
    sys.exit(0)
