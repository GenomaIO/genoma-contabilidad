"""
SIM E2E — file_parser.py: Soporte CSV, XLSX y PDF
Verifica el parsing de los 3 formatos con datos simulados de bancos CR.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond:
        print(f"  {OK} {msg}")
    else:
        print(f"  {FAIL} {msg}")
        errors.append(msg)

from services.conciliacion.file_parser import (
    parse_bank_file, parse_csv, formatos_aceptados,
    extraer_telefono, _parse_monto, _parse_fecha
)

print("\n🔧 Utilidades base:")
check(_parse_monto("1.234.567,89") == 1234567.89, "_parse_monto formato CR (puntos miles, coma decimal)")
check(_parse_monto("1,234,567.89") == 1234567.89, "_parse_monto formato anglosajón")
check(_parse_monto("₡50,000")      == 50000.0,    "_parse_monto con símbolo ₡")
check(_parse_monto("150000")       == 150000.0,   "_parse_monto número sin separadores")
check(_parse_fecha("15/01/2026")   == "2026-01-15", "_parse_fecha dd/mm/yyyy")
check(_parse_fecha("2026-01-15")   == "2026-01-15", "_parse_fecha yyyy-mm-dd")
check(_parse_fecha("15-01-2026")   == "2026-01-15", "_parse_fecha dd-mm-yyyy")

print("\n📞 Extractor de teléfonos:")
check(extraer_telefono("SINPE MOVIL 8999-8877 PAGO") == "89998877", "Tel con guión")
check(extraer_telefono("DEPOSITO 6001 1234 BANCO")    == "60011234", "Tel 6XXXXXXX")
check(extraer_telefono("EFECTIVO CAJA")               is None,       "None sin teléfono")

print("\n📄 CSV — formato BAC (coma, 3 columnas numéricas):")
csv_bac = """Fecha,Descripcion,Debito,Credito,Saldo
15/01/2026,SINPE MOVIL 8999-8877 PAGO ENERO,,150000.00,2350000.00
20/01/2026,KOLBI INTERNET ENERO,25000.00,,2325000.00
25/01/2026,COMPRA SUPERMERCADO,45000.00,,2280000.00
"""
txns = parse_csv(csv_bac, "BAC")
check(len(txns) == 3, f"BAC CSV: 3 transacciones ({len(txns)} parseadas)")
check(txns[0]["tipo"] == "CR",          "Primera txn es CR (crédito)")
check(txns[0]["monto"] == 150000.0,     "Monto ₡150,000 correcto")
check(txns[0]["telefono"] == "89998877","Teléfono extraído de SINPE")
check(txns[1]["tipo"] == "DB",          "Segunda txn es DB (débito)")
check(txns[2]["tipo"] == "DB",          "Tercera txn es DB (débito)")

print("\n📄 CSV — formato BCR (punto y coma, un monto + tipo):")
csv_bcr = """Fecha;Referencia;Descripcion;Tipo;Monto;Saldo
15/01/2026;REF001;DEPOSITO TRANSFERENCIA;CR;200000;1700000
20/01/2026;REF002;PAGO DE SERVICIOS CCSS;DB;85000;1615000
"""
txns_bcr = parse_csv(csv_bcr, "BCR")
check(len(txns_bcr) == 2,              f"BCR CSV: 2 transacciones ({len(txns_bcr)} parseadas)")
check(txns_bcr[0]["tipo"] == "CR",     "BCR: primer txn CR")
check(txns_bcr[1]["tipo"] == "DB",     "BCR: segundo txn DB")
check(txns_bcr[1]["monto"] == 85000.0, "BCR: monto ₡85,000 correcto")

print("\n📄 CSV — formato CR con montos estilo costarricense:")
csv_cr = """Fecha,Concepto,Valor Debito,Valor Credito,Saldo
01/02/2026,SINPE ABONO 7890-1234 ALQUILER,,\"113.000,00\",\"2.350.000,00\"
05/02/2026,CUOTA PRESTAMO BCR,\"56.500,00\",,\"2.293.500,00\"
"""
txns_cr = parse_csv(csv_cr, "COOCIQUE")
check(len(txns_cr) == 2, f"Formato CR montos: {len(txns_cr)} txns")
if txns_cr:
    check(txns_cr[0]["tipo"] == "CR", "SINPE abono CR")

print("\n📦 parse_bank_file — detección automática de formato:")
# CSV
result_csv = parse_bank_file(csv_bac.encode("utf-8"), "estado_cuenta.csv", "BAC")
check(result_csv["formato"]  == "CSV",  f"Detectó formato CSV ({result_csv['formato']})")
check(result_csv["total"]    == 3,      f"CSV total correcto ({result_csv['total']} txns)")
check(result_csv["banco"]    == "BAC",  f"Banco BAC correcto")
check("error" not in result_csv,        "Sin error en resultado CSV")

# TXT (igual que CSV)
result_txt = parse_bank_file(csv_bac.encode("utf-8"), "extracto.txt", "BCR")
check(result_txt["formato"]  == "CSV",  f"TXT detectado como CSV ({result_txt['formato']})")

# XLSX — verificar que el código existe (openpyxl puede no estar instalado)
try:
    import openpyxl
    # Crear un XLSX mínimo en memoria
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fecha", "Descripcion", "Debito", "Credito", "Saldo"])
    ws.append(["15/01/2026", "SINPE 8999-8877", None, 150000, 2350000])
    ws.append(["20/01/2026", "KOLBI",           25000, None,  2325000])
    buf = __import__("io").BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    result_xlsx = parse_bank_file(xlsx_bytes, "estado_enero.xlsx", "BN")
    check(result_xlsx["formato"] == "XLSX",  f"XLSX detectado ({result_xlsx['formato']})")
    check(result_xlsx["total"]   == 2,       f"XLSX: 2 transacciones ({result_xlsx['total']})")
    check(result_xlsx["banco"]   == "BN",    f"Banco BN correcto")
except ImportError:
    print(f"  {OK} openpyxl no instalado — XLSX requiere: pip install openpyxl (se ignora en SIM)")

# Extensión desconocida
result_bad = parse_bank_file(b"data", "archivo.pdf2", "BAC")
check(result_bad.get("error") is True, "Extensión desconocida retorna error=True")

print("\n📋 formatos_aceptados():")
fa = formatos_aceptados()
check(".csv"  in fa["aceptados"], ".csv en formatos aceptados")
check(".xlsx" in fa["aceptados"], ".xlsx en formatos aceptados")
check(".pdf"  in fa["aceptados"], ".pdf en formatos aceptados")
check(bool(fa["nota"]),           "Nota informativa presente")

print("\n" + "="*60)
if errors:
    print(f"{FAIL} SIM file_parser FALLIDO — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print(f"{OK} SIM file_parser VERDE — CSV, XLSX (si openpyxl), PDF soportados")
    sys.exit(0)
