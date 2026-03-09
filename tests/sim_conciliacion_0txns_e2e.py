"""
SIM — Fix: 0 txns silencioso en Conciliacion.jsx
=================================================
Verifica que:
  M1. API devuelve 0 txns, 0 errores → NO avanza al Paso 2 + muestra advertencia
  M2. API devuelve 0 txns, CON errores → NO avanza + muestra errores del archivo
  M3. API devuelve N txns normales     → SÍ avanza al Paso 2 (happy path sin cambio)
  M4. API parcial: 1 archivo ok + 1 archivo con error → avanza con las txns del ok
  M5. Mensaje de advertencia menciona el banco incorrecto (ayuda al usuario a diagnosticar)
  M6. La logica de dedup preserva txns unicas al fusionar multiples archivos
"""
import sys, os, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src  = open(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")).read()

# ─── Helpers que replican la logica de Conciliacion.jsx ──────────────────────

def simular_parsear(archivos_resultado, banco, period):
    """
    Simula el bloque parsear() en Conciliacion.jsx.

    archivos_resultado: list de dicts (uno por archivo simulado), cada uno con:
        {'transacciones': [...], 'error': None | str,
         'periodos_detectados': [], 'saldo_inicial': 0, 'saldo_final': 0}

    Retorna: {'avanza': bool, 'step_destino': 'upload'|'review', 'msg': dict, 'txns': list}
    """
    todos_txns   = []
    todos_periodos = set()
    saldo_inicial = 0
    saldo_final   = 0
    errores       = []

    for i, resultado in enumerate(archivos_resultado):
        if resultado.get('error'):
            errores.append(f"archivo_{i+1}.pdf: {resultado['error']}")
        else:
            todos_txns.extend(resultado.get('transacciones', []))
            for p in resultado.get('periodos_detectados', []):
                todos_periodos.add(p)
            if i == 0:
                saldo_inicial = resultado.get('saldo_inicial', 0)
            saldo_final = resultado.get('saldo_final', saldo_final)

    # Dedup (replica la logica de slice(0,60))
    seen = set()
    txns_fusionadas = []
    for t in todos_txns:
        key = f"{t.get('fecha')}|{t.get('monto')}|{str(t.get('descripcion',''))[:60]}"
        if key not in seen:
            seen.add(key)
            txns_fusionadas.append(t)

    # Sort por fecha
    txns_fusionadas.sort(key=lambda t: t.get('fecha', ''))

    periodos_str = ', '.join(sorted(todos_periodos))
    error_str    = f" | ⚠ {len(errores)} error(es)" if errores else ''

    # ─── LOGICA DEL FIX ───────────────────────────────────────────────────────
    if len(txns_fusionadas) == 0:
        # Fix aplicado: nunca avanzar si hay 0 txns, con o sin errores
        if errores:
            err_msg = f"Error procesando archivos: {'; '.join(errores)}"
        else:
            err_msg = (
                f"⚠️ Se procesaron {len(archivos_resultado)} archivo(s) pero no se encontraron transacciones. "
                f"Verifica que el banco seleccionado ({banco}) coincide con el archivo cargado."
            )
        return {
            'avanza': False,
            'step_destino': 'upload',
            'txns': [],
            'msg': {'ok': False, 'text': err_msg},
        }
    else:
        ok_text = (
            f"✅ {len(txns_fusionadas)} transacciones de {len(archivos_resultado)} archivo(s)"
            f" | Períodos: {periodos_str or period}{error_str}"
        )
        return {
            'avanza': True,
            'step_destino': 'review',
            'txns': txns_fusionadas,
            'msg': {'ok': True, 'text': ok_text},
        }

# Muestra de txns de prueba
TXN_A = {'fecha': '2026-01-15', 'monto': 150000, 'descripcion': 'SINPE MOVIL 8888-9999', 'tipo': 'CR'}
TXN_B = {'fecha': '2026-01-20', 'monto': 75000,  'descripcion': 'PAGO SERVICIOS BCR',    'tipo': 'DB'}
TXN_C = {'fecha': '2026-01-22', 'monto': 75000,  'descripcion': 'PAGO SERVICIOS BCR',    'tipo': 'DB'}  # igual a B → dup

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 1: 0 txns, 0 errores → NO avanza + advertencia con banco
# ─────────────────────────────────────────────────────────────────────────────
print("\n🚫 MÓDULO 1 — 0 txns, 0 errores → NO avanza al Paso 2:")

res1 = simular_parsear(
    archivos_resultado=[{'transacciones': [], 'periodos_detectados': [], 'error': None}],
    banco='BN',
    period='202601',
)
check(res1['avanza'] is False,           "NO llama onTransacciones (no avanza al Paso 2)")
check(res1['step_destino'] == 'upload',  "step se queda en 'upload' (Paso 1)")
check(res1['msg']['ok'] is False,        "mensaje de tipo error (ok=False)")
check('BN' in res1['msg']['text'],       "mensaje menciona el banco 'BN' para diagnosticar")
check('⚠️' in res1['msg']['text'],       "mensaje incluye emoji de advertencia ⚠️")
check('transacciones' in res1['msg']['text'].lower(), "mensaje dice 'transacciones'")

# Verificar que el código fuente tiene la logica correcta
check("if (txnsFusionadas.length === 0)" in src,
      "JSX: condicion unificada 'if (txnsFusionadas.length === 0)'")
check("if (txnsFusionadas.length === 0 && errores.length)" not in src,
      "JSX: condicion antigua '&& errores.length' ELIMINADA")

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 2: 0 txns, CON errores → NO avanza + muestra errores del archivo
# ─────────────────────────────────────────────────────────────────────────────
print("\n❌ MÓDULO 2 — 0 txns CON errores de parsing:")

res2 = simular_parsear(
    archivos_resultado=[
        {'transacciones': [], 'error': 'pdfplumber no pudo leer el archivo', 'periodos_detectados': []},
        {'transacciones': [], 'error': 'Formato Excel no reconocido',         'periodos_detectados': []},
    ],
    banco='BAC',
    period='202601',
)
check(res2['avanza'] is False,                    "NO avanza con errores y 0 txns")
check('pdfplumber' in res2['msg']['text'],         "mensaje incluye detalle del error del archivo")
check('Formato Excel' in res2['msg']['text'],      "mensaje incluye segundo error")
check(res2['msg']['ok'] is False,                  "msg.ok=False (color rojo en el UI)")

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 3: Happy path — N txns → SÍ avanza al Paso 2 (sin cambio)
# ─────────────────────────────────────────────────────────────────────────────
print("\n✅ MÓDULO 3 — Happy path: N txns → avanza al Paso 2:")

res3 = simular_parsear(
    archivos_resultado=[{
        'transacciones': [TXN_A, TXN_B],
        'periodos_detectados': ['2026-01'],
        'saldo_inicial': 1000000,
        'saldo_final':   1075000,
        'error': None,
    }],
    banco='BCR',
    period='202601',
)
check(res3['avanza'] is True,              "SÍ llama onTransacciones (avanza al Paso 2)")
check(res3['step_destino'] == 'review',    "step cambia a 'review'")
check(len(res3['txns']) == 2,              "2 transacciones preservadas")
check(res3['msg']['ok'] is True,           "mensaje de éxito (ok=True, color verde)")
check('✅' in res3['msg']['text'],          "mensaje incluye ✅")
check('Períodos' in res3['msg']['text'],   "mensaje incluye períodos detectados")

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 4: Parcial — 1 archivo ok + 1 con error → avanza con txns del ok
# ─────────────────────────────────────────────────────────────────────────────
print("\n⚠️  MÓDULO 4 — Parcial: 1 ok + 1 con error → avanza con txns parciales:")

res4 = simular_parsear(
    archivos_resultado=[
        {'transacciones': [TXN_A, TXN_B], 'periodos_detectados': ['2026-01'], 'error': None},
        {'transacciones': [],             'error': 'formato no reconocido',    'periodos_detectados': []},
    ],
    banco='BCR',
    period='202601',
)
check(res4['avanza'] is True,           "SÍ avanza porque hay txns del primer archivo")
check(len(res4['txns']) == 2,           "2 txns del archivo ok preservadas")
check('error(es)' in res4['msg']['text'],'mensaje indica que hubo errores parciales (⚠)')
check(res4['msg']['ok'] is True,        "msg.ok=True porque hay txns correctas")

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 5: Mensaje de advertencia incluye banco para diagnosticar
# ─────────────────────────────────────────────────────────────────────────────
print("\n🔍 MÓDULO 5 — Advertencia menciona banco para diagnóstico:")

for banco_test in ['BN', 'BCR', 'BAC', 'BPDC']:
    res = simular_parsear(
        archivos_resultado=[{'transacciones': [], 'periodos_detectados': [], 'error': None}],
        banco=banco_test,
        period='202601',
    )
    check(banco_test in res['msg']['text'],
          f"Banco '{banco_test}' aparece en mensaje de advertencia")

# ─────────────────────────────────────────────────────────────────────────────
# MÓDULO 6: Dedup preserva txns distintas y elimina duplicados reales
# ─────────────────────────────────────────────────────────────────────────────
print("\n🔑 MÓDULO 6 — Dedup con 60 chars: correcto para distintas y duplicadas:")

# Dos archivos con las mismas txns (escenario: mismo PDF subido 2 veces)
res6_dup = simular_parsear(
    archivos_resultado=[
        {'transacciones': [TXN_A, TXN_B], 'periodos_detectados': ['2026-01'], 'error': None},
        {'transacciones': [TXN_A, TXN_B], 'periodos_detectados': ['2026-01'], 'error': None},
    ],
    banco='BCR', period='202601'
)
check(len(res6_dup['txns']) == 2, "Duplicados reales (mismo PDF x2) se deduplican → 2 txns")

# Dos archivos con txns distintas (escenario: dos meses distintos)
res6_dist = simular_parsear(
    archivos_resultado=[
        {'transacciones': [TXN_A],        'periodos_detectados': ['2026-01'], 'error': None},
        {'transacciones': [TXN_B, TXN_C], 'periodos_detectados': ['2026-01'], 'error': None},
    ],
    banco='BCR', period='202601'
)
# TXN_B y TXN_C son iguales (descripcion identica), pero TXN_A es distinto
# TXN_A (15 ene) + TXN_B (20 ene, ₡75k) + TXN_C (22 ene, ₡75k misma desc)
# La clave dedup incluye FECHA → fechas distintas → NO son duplicados → 3 txns únicas
check(len(res6_dist['txns']) == 3, "TXN_B y TXN_C tienen fechas distintas (20 vs 22 ene) → 3 txns únicas (no dedup por fecha)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Fix 0 txns silencioso")
    print("   · 0 txns sin errores → Paso 1 + advertencia con banco")
    print("   · 0 txns con errores → Paso 1 + detalle del error archivo")
    print("   · N txns normales    → Paso 2 (happy path sin cambio) ✅")
    print("   · Parcial (1 ok + 1 error) → Paso 2 con txns parciales ✅")
    print("   · Advertencia siempre menciona el banco seleccionado")
    print("   · Dedup 60 chars: elimina dups reales, preserva txns distintas")
    sys.exit(0)
