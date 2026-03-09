"""
SIM E2E PASO 4 — Verifica Conciliacion.jsx, Centinela.jsx y rutas en App.jsx
"""
import os, sys, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else: print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, "frontend", "src")

CONCILIACION = os.path.join(SRC, "pages", "Conciliacion.jsx")
CENTINELA    = os.path.join(SRC, "pages", "Centinela.jsx")
APP          = os.path.join(SRC, "App.jsx")

def read(p):
    with open(p) as f: return f.read()

# ── Conciliacion.jsx ─────────────────────────────────────────────────────────
print("\n🏦 PASO 4A — Conciliacion.jsx:")
check(os.path.exists(CONCILIACION), "Existe Conciliacion.jsx")
cc = read(CONCILIACION)
check("FileUploader"       in cc, "Componente FileUploader")
check("TxnTable"           in cc, "Componente TxnTable")
check("StatsBar"           in cc, "Componente StatsBar")
check("Badge"              in cc, "Componente Badge (semáforo)")
check("/conciliacion/entidades" in cc, "GET /conciliacion/entidades")
check("/conciliacion/parse"     in cc, "POST /conciliacion/parse")
check("/conciliacion/match/"    in cc, "POST /conciliacion/match/")
check("CONCILIADO"         in cc, "Estado CONCILIADO en UI")
check("SIN_ASIENTO"        in cc, "Estado SIN_ASIENTO en UI")
check("CSV"                in cc, "Mención CSV")
check("XLSX"               in cc, "Mención XLSX")
check("PDF"                in cc, "Mención PDF")
check("monto_orig_usd"     in cc, "Soporte visual USD (monto_orig_usd)")
check("tc_bccr"            in cc, "Soporte visual TC BCCR")
check("useApp"             in cc, "useApp (token del contexto)")
check("optgroup"           in cc, "Entidades agrupadas por tipo (optgroup)")
check("step"               in cc, "State 'step' para flujo 3 pasos")
check("CENTINELA"          in cc, "Enlace a CENTINELA en resultado")

# ── Centinela.jsx ─────────────────────────────────────────────────────────────
print("\n🛡️  PASO 4B — Centinela.jsx:")
check(os.path.exists(CENTINELA), "Existe Centinela.jsx")
ce = read(CENTINELA)
check("ScoreGauge"         in ce, "Componente ScoreGauge (SVG circular)")
check("FugaCard"           in ce, "Componente FugaCard")
check("D270Preview"        in ce, "Componente D270Preview")
check("/centinela/score/"  in ce, "GET /centinela/score/{period}")
check("/centinela/d270/"   in ce, "GET /centinela/d270/{period}")
check("/centinela/d270/"   in ce and "export" in ce, "Exportación CSV D-270")
check("SALUDABLE"          in ce, "Nivel SALUDABLE")
check("MODERADO"           in ce, "Nivel MODERADO")
check("EN_RIESGO"          in ce, "Nivel EN_RIESGO")
check("CRITICO"            in ce, "Nivel CRITICO")
check("fuga_tipo"          in ce, "Tipos de fuga A/B/C")
check("exposicion_iva"     in ce, "Métricas exposición IVA")
check("exposicion_renta"   in ce, "Métricas exposición renta")
check("d270_regs"          in ce, "Conteo registros D-270")
check("Decreto 44739-H"    in ce, "Normativa Decreto 44739-H en UI")
check("linearGradient"     in ce, "Degradado SVG en gauge")
check("tab"                in ce, "State 'tab' para pestañas")
check("periodLabel"        in ce, "periodLabel (YYYYMM → nombre mes)")

# ── App.jsx ───────────────────────────────────────────────────────────────────
print("\n📱 PASO 4C — App.jsx:")
ap = read(APP)
check("import Conciliacion" in ap, "Import Conciliacion")
check("import Centinela"    in ap, "Import Centinela")
check('path=\"/conciliacion\"' in ap or "path='/conciliacion'" in ap or '/conciliacion' in ap, "Ruta /conciliacion")
check('path=\"/centinela\"'    in ap or "path='/centinela'"    in ap or '/centinela' in ap,    "Ruta /centinela")
check("<Conciliacion />" in ap, "Componente <Conciliacion /> en rutas")
check("<Centinela />"    in ap, "Componente <Centinela /> en rutas")

# ── Sidebar.jsx ───────────────────────────────────────────────────────────────
print("\n🗂️  PASO 4D — Sidebar.jsx:")
sid_path = os.path.join(SRC, "components", "Sidebar.jsx")
sid = read(sid_path)
check("Conciliación Bancaria" in sid and "/conciliacion" in sid, "Conciliación en sidebar Generadores")
check("CENTINELA Fiscal"      in sid and "/centinela"    in sid, "CENTINELA en sidebar Generadores")

print("\n" + "="*60)
if errors:
    print(f"{FAIL} PASO 4 FALLIDO — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print(f"{OK} PASO 4 VERDE — Frontend Conciliacion.jsx + Centinela.jsx verificados")
    sys.exit(0)
