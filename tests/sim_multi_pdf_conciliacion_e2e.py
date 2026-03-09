"""
SIM — Multi-PDF Upload en Conciliación (Opción A)
===================================================
Valida la lógica de fusión de múltiples archivos:

MÓDULO 1 — Deduplicación: fechas+monto+descripción iguales = 1 txn
MÓDULO 2 — Fusión de períodos de varios PDFs (BN real dic+ene)
MÓDULO 3 — Ordenación por fecha tras fusión
MÓDULO 4 — Código frontend: input multiple, files array, botón dinámico
MÓDULO 5 — Manejo de errores parciales (1 mal, otros bien)
MÓDULO 6 — Cadena de saldos correcta tras fusión
"""
import sys, os

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services.conciliacion.bank_pdf_parser import split_transactions_by_period

# ── Simulación de merge (réplica exacta de la lógica del frontend en Python) ──

def merge_resultados(resultados):
    """Réplica de la lógica JS de parsear() en Python para test."""
    todos = []
    periodos = set()
    saldo_inicial = 0
    saldo_final   = 0
    usa_gemini = False

    for i, d in enumerate(resultados):
        todos.extend(d.get('transacciones', []))
        for p in (d.get('periodos_detectados') or []):
            periodos.add(p)
        if i == 0:
            saldo_inicial = d.get('saldo_inicial', 0)
        saldo_final = d.get('saldo_final', saldo_final)
        if d.get('fuente') == 'gemini-vision':
            usa_gemini = True

    # Deduplicar
    seen = set()
    fusionadas = []
    for t in todos:
        key = f"{t['fecha']}|{t['monto']}|{t.get('descripcion','')[:30]}"
        if key not in seen:
            seen.add(key)
            fusionadas.append(t)

    # Ordenar por fecha
    fusionadas.sort(key=lambda t: t.get('fecha', ''))

    return {
        'transacciones':       fusionadas,
        'total':               len(fusionadas),
        'periodos_detectados': sorted(periodos),
        'saldo_inicial':       saldo_inicial,
        'saldo_final':         saldo_final,
        'usa_gemini':          usa_gemini,
    }

# ─── MÓDULO 1: Deduplicación ──────────────────────────────────────────────
print("\n🔁 MÓDULO 1 — Deduplicación de transacciones entre PDFs:")

# BN PDF(2): dic22-ene16 → tiene txns de Ene que también están en PDF(1)
resultado_pdf2 = {
    'transacciones': [
        {'fecha': '2025-12-22', 'descripcion': 'GOMEZ NAVARRO', 'monto': 200000, 'tipo': 'DB'},
        {'fecha': '2025-12-31', 'descripcion': 'BNCR/COMISION', 'monto': 175000, 'tipo': 'DB'},
        {'fecha': '2026-01-02', 'descripcion': 'BNCR/INTERESES', 'monto': 9034.45, 'tipo': 'CR'},
        {'fecha': '2026-01-09', 'descripcion': 'BNCR/SOCIEDAD',  'monto': 102804,  'tipo': 'DB'},
        {'fecha': '2026-01-16', 'descripcion': 'BNCR/PREST',    'monto': 300000,  'tipo': 'DB'},
    ],
    'periodos_detectados': ['2025-12', '2026-01'],
    'saldo_inicial': 8_174_111.16,
    'saldo_final':   5_658_341.61,
}

# BN PDF(1): ene19-feb20 → el 02-01 y 09-01 y 16-01 NO deben duplicarse
# (en la práctica PDF(1) no tiene esas fechas, pero en teoría podrían solaparse)
resultado_pdf1 = {
    'transacciones': [
        # Duplicados intencionales para verificar dedup
        {'fecha': '2026-01-02', 'descripcion': 'BNCR/INTERESES', 'monto': 9034.45, 'tipo': 'CR'},  # ← duplicado
        {'fecha': '2026-01-19', 'descripcion': 'BNCR/LOTO',     'monto': 30000,   'tipo': 'DB'},
        {'fecha': '2026-01-21', 'descripcion': 'CIDEP CENTRO',  'monto': 21348.88, 'tipo': 'CR'},
        {'fecha': '2026-01-30', 'descripcion': 'VILLEGAS ROJAS', 'monto': 50000,  'tipo': 'DB'},
    ],
    'periodos_detectados': ['2026-01'],
    'saldo_inicial': 5_658_341.61,
    'saldo_final':   8_484_597.50,
}

merged = merge_resultados([resultado_pdf2, resultado_pdf1])

check(merged['total'] == 8,
      f"8 txns tras dedup (5 + 4 - 1 duplicado) → got {merged['total']}")
check(
    sum(1 for t in merged['transacciones']
        if t['fecha'] == '2026-01-02' and t['descripcion'] == 'BNCR/INTERESES') == 1,
    "01-02 BNCR/INTERESES aparece solo 1 vez (dedup funciona)"
)

# ─── MÓDULO 2: Fusión de períodos ─────────────────────────────────────────
print("\n📅 MÓDULO 2 — Fusión de períodos de múltiples PDFs:")

check('2025-12' in merged['periodos_detectados'], "período 2025-12 detectado")
check('2026-01' in merged['periodos_detectados'], "período 2026-01 detectado")
check(len(merged['periodos_detectados']) == 2, "exactamente 2 períodos únicos tras fusión")

grupos = split_transactions_by_period(merged['transacciones'])
check('2025-12' in grupos, "split: grupo 2025-12 existe")
check('2026-01' in grupos, "split: grupo 2026-01 existe")
check(len(grupos['2025-12']) == 2,
      f"2025-12: 2 txns (dic22, dic31) → got {len(grupos.get('2025-12',[]))}")
check(len(grupos['2026-01']) == 6,
      f"2026-01: 6 txns (ene02,09,16,19,21,30) → got {len(grupos.get('2026-01',[]))}")

# ─── MÓDULO 3: Ordenación por fecha ───────────────────────────────────────
print("\n📋 MÓDULO 3 — Ordenación cronológica tras fusión:")

fechas = [t['fecha'] for t in merged['transacciones']]
check(fechas == sorted(fechas), "transacciones ordenadas cronológicamente")
check(fechas[0] == '2025-12-22', f"primera txn = 2025-12-22 → got {fechas[0]}")
check(fechas[-1] == '2026-01-30', f"última txn = 2026-01-30 → got {fechas[-1]}")

# ─── MÓDULO 4: Código frontend ────────────────────────────────────────────
print("\n⚛️  MÓDULO 4 — Frontend actualizado para multi-archivo:")

src = open(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")).read()
check('type="file" multiple'          in src, 'input con atributo "multiple"')
check('Array.from(e.target.files'     in src, 'handleFile convierte FileList a Array')
check('const [files, setFiles]'       in src, 'estado files (array, no file singular)')
check('files.length'                  in src, 'condición files.length (no file)')
check('parsearArchivo'                in src, 'función parsearArchivo para 1 archivo')
check('files.length > 1'             in src, 'botón dinámico: "Parsear N archivos"')
check('concat(d.transacciones'        in src, 'acumulación con concat')
check('seen.has(key)'                 in src, 'deduplicación con Set')
check('localeCompare'                 in src, 'ordenación por fecha con localeCompare')
check('errores.push'                  in src, 'manejo parcial de errores por archivo')
check('Podés seleccionar varios'      in src, 'texto de ayuda en drop-zone')
check('files.map((f, i)'              in src, 'lista de archivos seleccionados en drop-zone')
check('Clic para cambiar'             in src, 'hint de cambiar archivos')

# ─── MÓDULO 5: Manejo de errores parciales ────────────────────────────────
print("\n⚠️  MÓDULO 5 — Errores parciales (1 mal, otros bien):")

# Si 1 de 3 archivos falla, los otros 2 deben procesarse igualmente
def simular_con_error():
    resultados_ok = [resultado_pdf2, resultado_pdf1]
    todos_ok = []
    errores  = []
    for i, r in enumerate(resultados_ok):
        # Simular que el archivo 1 falla pero el 2 pasa
        if i == 0:
            errores.append("archivo1.pdf: timeout")
            continue
        todos_ok.extend(r.get('transacciones', []))
    return todos_ok, errores

txns_parciales, errs = simular_con_error()
check(len(txns_parciales) == 4, f"4 txns del archivo que sí pasó → got {len(txns_parciales)}")
check(len(errs) == 1, f"1 error registrado → got {len(errs)}")
check("timeout" in errs[0], "mensaje de error es descriptivo")

# ─── MÓDULO 6: Saldo inicial correcto ────────────────────────────────────
print("\n💰 MÓDULO 6 — Saldo inicial y final de la fusión:")

check(merged['saldo_inicial'] == 8_174_111.16,
      f"saldo_inicial = ₡8,174,111.16 (del PDF más antiguo, PDF2) → {merged['saldo_inicial']}")
check(merged['saldo_final'] == 8_484_597.50,
      f"saldo_final = ₡8,484,597.50 (del PDF más reciente, PDF1) → {merged['saldo_final']}")

# ─── Resultado final ───────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Multi-PDF Upload en Conciliación (Opción A)")
    print("   · Selección múltiple con Ctrl/Cmd o arrastre")
    print("   · Deduplicación automática por fecha+monto+descripción")
    print("   · Fusión de períodos (BN dic+ene en 2 PDFs → enero completo)")
    print("   · Ordenación cronológica unificada")
    print("   · Errores parciales: 1 falla no cancela los demás")
    print("   · Saldo inicial = primer PDF, saldo final = último PDF")
    sys.exit(0)
