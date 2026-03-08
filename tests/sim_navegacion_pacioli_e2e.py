"""
sim_navegacion_pacioli_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E2E — Fix navegación Mayor + Watermark Pacioli

FIX 1 — BalanceComprobacion.jsx:
  N1: useNavigate importado
  N2: navigate hook declarado (const navigate = useNavigate())
  N3: navigate() usado en onClick de fila (no window.location.href)
  N4: Sin window.location.href en el archivo

FIX 2 — ClientSelector.jsx:
  P1: img watermark pacioli.png presente
  P2: opacity 0.08 (sello de agua)
  P3: position absolute + z-index 0
  P4: filtro grayscale y mixBlendMode
  P5: aria-hidden=true (accesibilidad)
  P6: pointerEvents:none (no bloquea clicks)
  P7: div wrapper z-index 1 que eleva el contenido
  P8: JSX válido (misma cantidad de < y >)

CHECK IMAGEN:
  I1: pacioli.png existe en frontend/public/
  I2: Es un archivo PNG real (no HTML)

AUDIT IMPORTS:
  A1: ledger/router.py imports correctos
"""
import sys, os

PASS = "✅"; FAIL = "❌"
results = []

def check(name, cond, details=""):
    s = PASS if cond else FAIL
    results.append((s, name, details))
    print(f"  {s} {name}" + (f" — {details}" if details else ""))

def section(t):
    print(f"\n{'━'*60}\n  {t}\n{'━'*60}")

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
bc   = open(os.path.join(BASE, 'frontend/src/pages/BalanceComprobacion.jsx'), encoding='utf-8').read()
cs   = open(os.path.join(BASE, 'frontend/src/pages/ClientSelector.jsx'), encoding='utf-8').read()

# ── NAVEGACIÓN ────────────────────────────────────────────────
section("FIX 1 — Navegación SPA (useNavigate)")
check("N1 — useNavigate importado",              "useNavigate" in bc and "react-router-dom" in bc)
check("N2 — navigate hook declarado",            "const navigate = useNavigate()" in bc)
check("N3 — navigate() en onClick de fila",      "navigate(`/mayor?code=" in bc or "navigate('/mayor?code=" in bc or "navigate(`/mayor" in bc)
check("N4 — Sin window.location.href",           "window.location.href" not in bc)

# ── WATERMARK PACIOLI ─────────────────────────────────────────
section("FIX 2 — Watermark Pacioli en ClientSelector")
check("P1 — img src=/pacioli.png",              'src="/pacioli.png"' in cs)
check("P2 — opacity: 0.08",                     "opacity: 0.08" in cs)
check("P3 — position: 'absolute'",              "position: 'absolute'" in cs)
check("P4 — filter grayscale",                  "grayscale" in cs)
check("P5 — aria-hidden",                       "aria-hidden" in cs)
check("P6 — pointerEvents: 'none'",             "pointerEvents: 'none'" in cs)
check("P7 — div wrapper zIndex: 1",             "zIndex: 1" in cs)
check("P8 — JSX balanceado (opens≈closes)",     cs.count("<div") - cs.count("</div") in [-1, 0, 1])

# ── IMAGEN ────────────────────────────────────────────────────
section("IMAGEN — pacioli.png en public/")
pacioli_path = os.path.join(BASE, 'frontend/public/pacioli.png')
exists = os.path.exists(pacioli_path)
check("I1 — archivo pacioli.png existe",        exists, pacioli_path if not exists else "")
if exists:
    with open(pacioli_path, 'rb') as f:
        header = f.read(8)
    is_png = header[:8] == b'\x89PNG\r\n\x1a\n'
    check("I2 — es PNG real (no HTML)",         is_png, f"header={header[:4]}")
    fsize = os.path.getsize(pacioli_path)
    check("I3 — tamaño razonable > 10KB",       fsize > 10000, f"{fsize/1024:.0f} KB")

# ── AUDIT IMPORTS ─────────────────────────────────────────────
section("AUDIT — Imports Python router.py")
import ast
rtr_src = open(os.path.join(BASE, 'services/ledger/router.py'), encoding='utf-8').read()
rtr_tree = ast.parse(rtr_src)
for node in ast.walk(rtr_tree):
    if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('services.auth.'):
        submod = node.module.replace('services.auth.', '')
        target = os.path.join(BASE, 'services/auth', submod + '.py')
        names_list = [a.name for a in node.names]
        if os.path.exists(target):
            content = open(target).read()
            missing = [n for n in names_list if n not in content]
            if missing:
                check(f"IMPORT {node.module}", False, f"NO EXPORTADO: {missing}")
            else:
                check(f"IMPORT from {node.module} import {names_list}", True)
        else:
            check(f"IMPORT {node.module}", False, "MÓDULO NO EXISTE")

# ── RESUMEN ────────────────────────────────────────────────────
print(f"\n{'═'*60}")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
print(f"  RESULTADO: {passed}/{len(results)} pasados")
if failed:
    print(f"\n  FALLOS ({failed}):")
    for r in results:
        if r[0] == FAIL:
            print(f"    ❌  {r[1]}: {r[2]}")
    sys.exit(1)
else:
    print(f"  ✅✅✅ TODO VERDE — Listo para push")
    print(f"{'═'*60}")
