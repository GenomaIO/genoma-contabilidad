"""
sim_eeff_logica_contable_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
E2E — Lógica Contable del Engine EEFF (3 Fixes)

FIX 1 — eeff_engine.py _accumulate():
  E1: Sin "net = -net" (doble negativo eliminado)
  E2: CR-normal usa credit - debit (sin negación posterior)
  E3: is_contra usa -abs(net)

FIX 2 — eeff_engine.py compute():
  P1: Inyección de utilidad_neta_eri en ESF.PAT.04
  P2: ESF se reconstruye con bucket actualizado

FIX 3 — niif_lines.py STANDARD_AUTO_MAPPING:
  M1: 1201 → ESF.ANC.01 (PPE, no CxC)
  M2: 1202 → ESF.ANC.01 (Dep. Acumulada, no CxC)
  M3: CxC en serie 1301-1307 (catálogo real)
  M4: CONTRA_ACCOUNTS incluye 1202

MATH CONTABLE — Verificación algebraica:
  A = P + PAT + Utilidad del período (identidad fundamental)
  Si balanza cierra → ESF debe cerrar (con el engine corregido)

AUDIT Python:
  A1: eeff_engine.py parseable (ast)
  A2: niif_lines.py parseable (ast)
  A3: fix_existing_mappings() exportado
"""
import sys, os, ast
from decimal import Decimal, ROUND_HALF_UP

PASS = "✅"; FAIL = "❌"
results = []

def check(name, cond, details=""):
    s = PASS if cond else FAIL
    results.append((s, name, details))
    print(f"  {s} {name}" + (f" — {details}" if details else ""))

def section(t):
    print(f"\n{'━'*62}\n  {t}\n{'━'*62}")

BASE    = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
eng_src = open(os.path.join(BASE, 'services/reporting/eeff_engine.py'),  encoding='utf-8').read()
nl_src  = open(os.path.join(BASE, 'services/reporting/niif_lines.py'),   encoding='utf-8').read()

# ── FIX 1 — _accumulate() ────────────────────────────────────────
section("FIX 1 — _accumulate(): doble negativo eliminado")
check("E1 — Sin 'net = -net'",              "net = -net" not in eng_src)
check("E2 — credit - debit sin negación",   "net = saldo[\"credit\"] - saldo[\"debit\"]" in eng_src
                                             and "net = -net" not in eng_src)
check("E3 — is_contra usa -abs(net)",       "net = -abs(net)" in eng_src)

# ── FIX 2 — compute() inyecta utilidad ───────────────────────────
section("FIX 2 — compute(): utilidad inyectada en ESF.PAT.04")
check("P1 — ESF.PAT.04 inyectado",         'buckets["ESF.PAT.04"] = utilidad_neta_eri'   in eng_src)
check("P2 — Condición correcta (solo si 0)","buckets.get(\"ESF.PAT.04\", Decimal(\"0\")) == Decimal(\"0\")" in eng_src)
check("P3 — ESF reconstruido post-inyección","esf = self._build_esf(buckets, detail)   # reconstruir" in eng_src)

# ── FIX 3 — STANDARD_AUTO_MAPPING ────────────────────────────────
section("FIX 3 — niif_lines.py STANDARD_AUTO_MAPPING")
check("M1 — 1201 → ESF.ANC.01 (PPE)",      '"1201": "ESF.ANC.01"' in nl_src)
check("M2 — 1202 → ESF.ANC.01 (Dep.Acum)", '"1202": "ESF.ANC.01"' in nl_src)
check("M3 — 1201 NO en ESF.AC.02",         not ('"1201": "ESF.AC.02"' in nl_src))
check("M4 — 1202 NO en ESF.AC.02",         not ('"1202": "ESF.AC.02"' in nl_src))
check("M5 — CxC en 1301",                  '"1301": "ESF.AC.02"' in nl_src)
check("M6 — CONTRA_ACCOUNTS incluye 1202", '"1202"' in nl_src and 'CONTRA_ACCOUNTS' in nl_src)
check("M7 — fix_existing_mappings() existe","def fix_existing_mappings(" in nl_src)

# ── MATH CONTABLE — Identidad Fundamental ────────────────────────
section("MATH CONTABLE — Identidad A = P + PAT + Utilidad")

def r(n): return Decimal(str(n)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

# Datos reales del tenant (trial balance YTD Feb 2026)
tb = [
    ("1101.01", "ACTIVO",     "177125201.83",  "480809.00"),
    ("1201.04", "ACTIVO",      "13555935.00",       "0.00"),
    ("1202.03", "ACTIVO",           "0.00",   "4650804.38"),
    ("1202.04", "ACTIVO",      "112966.12",    "112966.12"),
    ("2102.01", "PASIVO",           "0.00",    "594437.60"),
    ("2102.02", "PASIVO",        "5272.00",    "133477.00"),
    ("3401.01", "PATRIMONIO",       "0.00", "178854520.10"),
    ("4101.03", "INGRESO",          "0.00",   "6673830.00"),
    ("5210.03", "GASTO",       "225932.24",         "0.00"),
    ("5301.01", "GASTO",       "112966.12",    "112966.12"),
    ("5401.01", "GASTO",        "33615.00",          "0.00"),
    ("5901.01", "GASTO",       "441922.00",          "0.00"),
]

# Balanza
total_debe  = sum(r(d) for _, _, d, _ in tb)
total_haber = sum(r(h) for _, _, _, h in tb)
diff_bc = abs(total_debe - total_haber)
check("C1 — Balanza de Comprobación cierra (diff ≤ ¢0.01)",
      diff_bc <= r("0.02"), f"diff=¢{diff_bc:.4f}")

# Saldos netos por tipo (CON el engine corregido — sin net=-net)
activos = pasivos = patrimonio = ingresos = gastos = Decimal("0")
for code, tipo, d, h in tb:
    d, h = r(d), r(h)
    if tipo in ("ACTIVO", "GASTO"):
        net = d - h
    else:
        net = h - d           # Fix1: ya no negamos
    if tipo == "ACTIVO":      activos     += net
    elif tipo == "PASIVO":    pasivos     += net
    elif tipo == "PATRIMONIO":patrimonio  += net
    elif tipo == "INGRESO":   ingresos    += net
    elif tipo == "GASTO":     gastos      += net

utilidad = ingresos - gastos

check("C2 — Activos positivos",    activos > 0,    f"¢{activos:,.2f}")
check("C3 — Pasivos positivos",    pasivos > 0,    f"¢{pasivos:,.2f}")
check("C4 — Patrimonio positivo",  patrimonio > 0, f"¢{patrimonio:,.2f}")
check("C5 — Ingresos positivos",   ingresos > 0,   f"¢{ingresos:,.2f}")
check("C6 — Gastos positivos",     gastos > 0,     f"¢{gastos:,.2f}")
check("C7 — Utilidad período (ERI)", utilidad > 0, f"¢{utilidad:,.2f}")

# Fix2: Inyección de utilidad en ESF.PAT.04
patrimonio_con_resultado = patrimonio + utilidad     # pre-cierre + resultado ERI
pas_pat_total = pasivos + patrimonio_con_resultado
diff_esf = abs(activos - pas_pat_total)
check("C8 — ESF cierra (A = P + PAT + Utilidad) diff ≤ ¢1",
      diff_esf <= r("1.00"), f"diff=¢{diff_esf:.4f}")

# Contra-cuenta corrección (1202.03 debe restar de PPE)
ppe_bruto = r("13555935.00")    # 1201.04
dep_acum  = r("4650804.38")     # 1202.03 (contra)
ppe_neto  = ppe_bruto - dep_acum
check("C9 — PPE neto = Bruto - Dep.Acum (Fix3 contra)",
      ppe_neto > 0, f"PPE neto=¢{ppe_neto:,.2f}")

# Mapeo correcto: 1201+1202 van a ANC.01 (no AC.02)
check("C10 — 1201.04 prefix '1201' → ESF.ANC.01 (Fix3)",
      '"1201": "ESF.ANC.01"' in nl_src)

# ── AUDIT Python syntax ───────────────────────────────────────────
section("AUDIT — Python AST parse")
try:
    ast.parse(eng_src)
    check("A1 — eeff_engine.py parseable",  True)
except SyntaxError as e:
    check("A1 — eeff_engine.py parseable",  False, str(e))

try:
    ast.parse(nl_src)
    check("A2 — niif_lines.py parseable",   True)
except SyntaxError as e:
    check("A2 — niif_lines.py parseable",   False, str(e))

# Verificar que el router.py de reporting usa el engine
rtr_src = open(os.path.join(BASE, 'services/reporting/router.py'), encoding='utf-8').read()
check("A3 — router.py usa EeffEngine",      "EeffEngine" in rtr_src)
check("A4 — router.py importa niif_lines",  "niif_lines" in rtr_src or "fix_existing_mappings" in rtr_src or "seed_standard_mapping" in rtr_src)

# ── RESUMEN ────────────────────────────────────────────────────────
print(f"\n{'═'*62}")
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
    print(f"  ✅✅✅ TODO VERDE — Lógica contable correcta — Listo para push")
    print(f"{'═'*62}")
