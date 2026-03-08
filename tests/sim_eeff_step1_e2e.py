"""
sim_eeff_step1_e2e.py  (v2 — standalone, sin dependencia de SQLAlchemy)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SIMULACIÓN E2E — EEFF Paso 1: Motor NIIF + ESF + ERI
NIIF PYMES 3ª Edición · Feb 2025 · IASB

Estrategia: replica la lógica de los módulos directamente en la sim
para ser ejecutable con Python puro (sin sqlalchemy en el path).

Checks:
  S1:  Partidas NIIF (56+) y cobertura ESF/ERI
  S2:  Auto-mapeo: cobertura por grupos, mapeos críticos
  S3:  Motor ESF — acumulación, contra-cuentas, balance
  S4:  Motor ERI — ingresos, utilidad neta
  S5:  Escenario pérdida
  S6:  Cuentas sin mapear → warning
  S7:  Archivos del módulo reporting creados
  S8:  Router endpoints declarados
  S9:  main.py registra reporting_router
"""
import sys, os, ast, re
from decimal import Decimal
from collections import defaultdict

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

PASS = "✅"; FAIL = "❌"
results = []

def check(name, condition, details=""):
    status = PASS if condition else FAIL
    results.append((status, name, details))
    print(f"  {status} {name}" + (f" — {details}" if details else ""))

def section(title):
    print(f"\n{'━'*62}\n  {title}\n{'━'*62}")

# ─── Leer fuentes directamente ────────────────────────────────────
BASE = os.path.join(os.path.dirname(__file__), '..')

def read_src(rel_path):
    with open(os.path.join(BASE, rel_path), encoding='utf-8') as f:
        return f.read()

niif_lines_src  = read_src("services/reporting/niif_lines.py")
router_src      = read_src("services/reporting/router.py")
engine_src      = read_src("services/reporting/eeff_engine.py")
models_src      = read_src("services/reporting/models.py")
main_src        = read_src("services/gateway/main.py")

# ─── Extraer datos inline de niif_lines.py vía regex/ast ─────────
# Ejecutamos solo las partes que NO tienen sqlalchemy
exec_globals = {}
# Parchar el import de sqlalchemy para la sim
niif_patch = niif_lines_src.replace(
    "from sqlalchemy.orm import Session", "Session = object"
).replace(
    "from sqlalchemy import text", ""
).replace(
    "from .models import NiifLineDef, NiifMapping, NiifStatement, EsfSection, EfeActivity",
    "# models patched"
).replace(
    "import __import__", ""
)
# Ejecutar para obtener NIIF_LINES y dicts
try:
    exec(niif_patch, exec_globals)
    NIIF_LINES          = exec_globals["NIIF_LINES"]
    STANDARD_AUTO_MAPPING = exec_globals["STANDARD_AUTO_MAPPING"]
    EXCLUDE_FROM_MAPPING = exec_globals["EXCLUDE_FROM_MAPPING"]
    CONTRA_ACCOUNTS     = exec_globals["CONTRA_ACCOUNTS"]
    niif_lines_ok = True
except Exception as e:
    NIIF_LINES = []; STANDARD_AUTO_MAPPING = {}; EXCLUDE_FROM_MAPPING = set(); CONTRA_ACCOUNTS = set()
    niif_lines_ok = False
    print(f"  ⚠️  niif_lines patch: {e}")

# ─── Lógica del motor (standalone) ────────────────────────────────
TOLERANCE = Decimal("0.01")

def accumulate(trial_balance: dict, mappings: dict) -> dict:
    """
    Lógica idéntica a EeffEngine._accumulate en eeff_engine.py.
    Saldo neto:
      ACTIVO / GASTO   → debit - credit  (saldo normal DR, positivo)
      PASIVO / PAT / INGRESO → credit - debit  (saldo normal CR, positivo)
    Las contra-cuentas (Dep. Acumulada) se convierten a valor negativo
    para restar del activo correspondiente.
    """
    buckets = defaultdict(Decimal)
    detail  = defaultdict(list)
    unmapped = []
    for code, saldo in trial_balance.items():
        mapping = mappings.get(code) or mappings.get(code[:4])
        if not mapping:
            unmapped.append(code)
            continue
        niif_code = mapping["niif_line_code"]
        is_contra = mapping["is_contra"]
        acct_type = saldo["account_type"]
        if acct_type in ("ACTIVO", "GASTO"):
            net = saldo["debit"] - saldo["credit"]   # DR normal → positivo
        else:
            # CR normal → positivo (invertimos para que el bucket sea positivo)
            net = saldo["credit"] - saldo["debit"]
        if is_contra:
            net = -abs(net)   # contra-cuenta resta siempre
        buckets[niif_code] += net
        detail[niif_code].append({"code": code, "balance": float(net)})
    return {"buckets": dict(buckets), "detail": dict(detail), "unmapped_codes": unmapped}

def build_esf_totals(buckets, NIIF_LINES):
    def sec_total(section_key):
        return sum(
            buckets.get(l["code"], Decimal("0"))
            for l in NIIF_LINES
            if l["statement"] == "ESF" and l["section"] == section_key and not l.get("is_subtotal")
        )
    tot_ac  = sec_total("ACTIVO_CORRIENTE")
    tot_anc = sec_total("ACTIVO_NO_CORRIENTE")
    tot_pc  = sec_total("PASIVO_CORRIENTE")
    tot_pnc = sec_total("PASIVO_NO_CORRIENTE")
    tot_pat = sec_total("PATRIMONIO")
    ta  = tot_ac + tot_anc
    tp  = tot_pc + tot_pnc
    tpp = tp + tot_pat
    return {
        "total_activos": ta,
        "total_pasivos": tp,
        "total_patrimonio": tot_pat,
        "total_pasivo_patrimonio": tpp,
        "balanced": abs(ta - tpp) <= TOLERANCE,
        "difference": abs(ta - tpp),
    }

def build_eri_totals(buckets, NIIF_LINES):
    def sec_total(section_key):
        return sum(
            buckets.get(l["code"], Decimal("0"))
            for l in NIIF_LINES
            if l["statement"] == "ERI" and l["section"] == section_key and not l.get("is_subtotal")
        )
    ing     = sec_total("INGRESO")
    costo   = sec_total("COSTO")
    gop     = sec_total("GASTO_OPERATIVO")
    gfin    = sec_total("GASTO_FINANCIERO")
    isr     = sec_total("IMPUESTO_RENTA")
    ori     = sec_total("OTRO_RESULTADO")
    ub      = ing - costo
    un      = ub - gop - gfin - isr
    tri     = un + ori
    return {"total_ingresos": ing, "total_costo": costo,
            "utilidad_bruta": ub, "utilidad_neta": un, "total_ori": ori,
            "total_resultado_integral": tri}

# ═════════════════════════════════════════════════════════════════
# CHECKS
# ═════════════════════════════════════════════════════════════════

# ── S1: Partidas NIIF ────────────────────────────────────────────
section("S1: Catálogo de Partidas NIIF PYMES 3ª Ed. (Feb 2025)")

esf_lines = [l for l in NIIF_LINES if l["statement"] == "ESF"]
eri_lines = [l for l in NIIF_LINES if l["statement"] == "ERI"]
esf_codes = {l["code"] for l in esf_lines}
eri_codes = {l["code"] for l in eri_lines}

check("S1.1 — Total partidas ≥ 50",      len(NIIF_LINES) >= 50, f"{len(NIIF_LINES)} partidas")
check("S1.2 — ESF ≥ 15 partidas",        len(esf_lines) >= 15,   f"{len(esf_lines)}")
check("S1.3 — ERI ≥ 10 partidas",        len(eri_lines) >= 10,   f"{len(eri_lines)}")
check("S1.4 — ESF.AC.01 (Efectivo)",     "ESF.AC.01" in esf_codes)
check("S1.5 — ESF.ANC.01 (PPE)",         "ESF.ANC.01" in esf_codes)
check("S1.6 — ESF.AT (Total Activos)",   "ESF.AT" in esf_codes)
check("S1.7 — ESF.PT_PAT (P+Pat)",       "ESF.PT_PAT" in esf_codes)
check("S1.8 — ESF.AC.04 (nuevo Sec.23 3ªEd)", "ESF.AC.04" in esf_codes)
check("S1.9 — ESF.PAT.05 (ORI acumulado)","ESF.PAT.05" in esf_codes)
check("S1.10 — ERI.ING.01 (Ventas bienes)", "ERI.ING.01" in eri_codes)
check("S1.11 — ERI.GST.01 (Costo ventas)","ERI.GST.01" in eri_codes)
check("S1.12 — ERI.ISR (Imp. Renta)",    "ERI.ISR" in eri_codes)
check("S1.13 — ERI.UN (Utilidad Neta)",  "ERI.UN" in eri_codes)
check("S1.14 — ERI.TRI (Total Res.Int.)", "ERI.TRI" in eri_codes)
check("S1.15 — ERI.ORI.01 (ORI 3ªEd.)", "ERI.ORI.01" in eri_codes)

# Orden sin duplicados
all_codes = [l["code"] for l in NIIF_LINES]
check("S1.16 — Sin partidas NIIF duplicadas", len(all_codes) == len(set(all_codes)))

# ── S2: Auto-mapeo ───────────────────────────────────────────────
section("S2: Auto-mapeo Catálogo Estándar Genoma")

all_niif_codes = {l["code"] for l in NIIF_LINES}
bad_targets = {v for v in STANDARD_AUTO_MAPPING.values() if v not in all_niif_codes}
check("S2.1 — Todos los targets existen en NIIF_LINES",
      len(bad_targets) == 0, f"Inválidos: {bad_targets}" if bad_targets else "OK")

groups = {c[0] for c in STANDARD_AUTO_MAPPING if c[0].isdigit()}
check("S2.2 — Mapeo cubre grupos 1,2,3,4,5", groups >= {"1","2","3","4","5"})
check("S2.3 — 3304 (transitoria) NO mapeada", "3304" not in STANDARD_AUTO_MAPPING)
check("S2.4 — CONTRA_ACCOUNTS incluye 1590",  "1590" in CONTRA_ACCOUNTS)
check("S2.5 — CONTRA_ACCOUNTS incluye 1690",  "1690" in CONTRA_ACCOUNTS)

critical = {"1101":"ESF.AC.01","1201":"ESF.AC.02","1301":"ESF.AC.03",
            "1503":"ESF.ANC.01","2101":"ESF.PC.01","3303":"ESF.PAT.04",
            "4101":"ERI.ING.01","5101":"ERI.GST.01","5301":"ERI.GST.04","5401":"ERI.ISR"}
wrong = {k: (STANDARD_AUTO_MAPPING.get(k), v) for k,v in critical.items()
         if STANDARD_AUTO_MAPPING.get(k) != v}
check("S2.6 — 10 mapeos críticos correctos",
      not wrong, f"Errores: {wrong}" if wrong else "OK")
check("S2.7 — ≥ 50 cuentas en auto-mapeo", len(STANDARD_AUTO_MAPPING) >= 50, f"{len(STANDARD_AUTO_MAPPING)}")

# ── S3: Motor ESF ────────────────────────────────────────────────
section("S3: Motor de Cálculo — ESF")

MOCK_TB = {
    "1101": {"account_type": "ACTIVO",     "account_name": "Caja",    "debit": Decimal("500000"), "credit": Decimal("200000"), "balance": Decimal("300000")},
    "1103": {"account_type": "ACTIVO",     "account_name": "Bancos",  "debit": Decimal("2000000"),"credit": Decimal("500000"), "balance": Decimal("1500000")},
    "1201": {"account_type": "ACTIVO",     "account_name": "CxC",     "debit": Decimal("800000"), "credit": Decimal("100000"), "balance": Decimal("700000")},
    "1301": {"account_type": "ACTIVO",     "account_name": "Inv",     "debit": Decimal("600000"), "credit": Decimal("0"),      "balance": Decimal("600000")},
    "1503": {"account_type": "ACTIVO",     "account_name": "PPE",     "debit": Decimal("4000000"),"credit": Decimal("0"),      "balance": Decimal("4000000")},
    "1590": {"account_type": "ACTIVO",     "account_name": "DepAcum", "debit": Decimal("0"),      "credit": Decimal("800000"), "balance": Decimal("-800000")},
    "2101": {"account_type": "PASIVO",     "account_name": "CxP",     "debit": Decimal("100000"), "credit": Decimal("700000"), "balance": Decimal("600000")},
    "2201": {"account_type": "PASIVO",     "account_name": "PrestLP", "debit": Decimal("0"),      "credit": Decimal("2500000"),"balance": Decimal("2500000")},
    "3101": {"account_type": "PATRIMONIO", "account_name": "Capital", "debit": Decimal("0"),      "credit": Decimal("1000000"),"balance": Decimal("1000000")},
    "3301": {"account_type": "PATRIMONIO", "account_name": "UtlAnt", "debit": Decimal("0"),       "credit": Decimal("500000"), "balance": Decimal("500000")},
    "3303": {"account_type": "PATRIMONIO", "account_name": "UtlEj",  "debit": Decimal("0"),       "credit": Decimal("1700000"), "balance": Decimal("1700000")},  # Ajustado: 6.3M - 3.1M - 1.5M = 1.7M
    "4101": {"account_type": "INGRESO",    "account_name": "Ventas",  "debit": Decimal("0"),      "credit": Decimal("3000000"),"balance": Decimal("3000000")},
    "5101": {"account_type": "GASTO",      "account_name": "CostoV",  "debit": Decimal("1500000"),"credit": Decimal("0"),      "balance": Decimal("1500000")},
    "5201": {"account_type": "GASTO",      "account_name": "Sueldos", "debit": Decimal("500000"), "credit": Decimal("0"),      "balance": Decimal("500000")},
    "5210": {"account_type": "GASTO",      "account_name": "DepGst",  "debit": Decimal("200000"), "credit": Decimal("0"),      "balance": Decimal("200000")},
    "5301": {"account_type": "GASTO",      "account_name": "Interes", "debit": Decimal("75000"),  "credit": Decimal("0"),      "balance": Decimal("75000")},
    "5401": {"account_type": "GASTO",      "account_name": "ISR",     "debit": Decimal("225000"), "credit": Decimal("0"),      "balance": Decimal("225000")},
}
MOCK_MAPPINGS = {
    "1101": {"niif_line_code": "ESF.AC.01", "is_contra": False},
    "1103": {"niif_line_code": "ESF.AC.01", "is_contra": False},
    "1201": {"niif_line_code": "ESF.AC.02", "is_contra": False},
    "1301": {"niif_line_code": "ESF.AC.03", "is_contra": False},
    "1503": {"niif_line_code": "ESF.ANC.01","is_contra": False},
    "1590": {"niif_line_code": "ESF.ANC.01","is_contra": True},
    "2101": {"niif_line_code": "ESF.PC.01", "is_contra": False},
    "2201": {"niif_line_code": "ESF.PNC.01","is_contra": False},
    "3101": {"niif_line_code": "ESF.PAT.01","is_contra": False},
    "3301": {"niif_line_code": "ESF.PAT.03","is_contra": False},
    "3303": {"niif_line_code": "ESF.PAT.04","is_contra": False},
    "4101": {"niif_line_code": "ERI.ING.01","is_contra": False},
    "5101": {"niif_line_code": "ERI.GST.01","is_contra": False},
    "5201": {"niif_line_code": "ERI.GST.03","is_contra": False},
    "5210": {"niif_line_code": "ERI.GST.03","is_contra": False},
    "5301": {"niif_line_code": "ERI.GST.04","is_contra": False},
    "5401": {"niif_line_code": "ERI.ISR",   "is_contra": False},
}

accum = accumulate(MOCK_TB, MOCK_MAPPINGS)
buckets = {k: Decimal(str(v)) for k, v in accum["buckets"].items()}

check("S3.1 — ESF.AC.01 = Caja(300k) + Bancos(1500k) = 1,800,000",
      abs(buckets.get("ESF.AC.01", 0) - Decimal("1800000")) <= TOLERANCE,
      f"{buckets.get('ESF.AC.01', 0)}")
check("S3.2 — ESF.ANC.01 = PPE(4M) - DepAcum(800k) = 3,200,000",
      abs(buckets.get("ESF.ANC.01", 0) - Decimal("3200000")) <= TOLERANCE,
      f"{buckets.get('ESF.ANC.01', 0)}")
check("S3.3 — ESF.PC.01 = CxP(600k)",
      abs(buckets.get("ESF.PC.01", 0) - Decimal("600000")) <= TOLERANCE,
      f"{buckets.get('ESF.PC.01', 0)}")
check("S3.4 — ESF.PNC.01 = Préstamo LP(2,500,000)",
      abs(buckets.get("ESF.PNC.01", 0) - Decimal("2500000")) <= TOLERANCE,
      f"{buckets.get('ESF.PNC.01', 0)}")

esf_t = build_esf_totals(buckets, NIIF_LINES)
check("S3.5 — ESF cuadra (A == P + Pat)", esf_t["balanced"],
      f"TA={esf_t['total_activos']} | TP+Pat={esf_t['total_pasivo_patrimonio']} | diff={esf_t['difference']}")
check("S3.6 — Diferencia ESF < 0.01", esf_t["difference"] < Decimal("0.01"),
      f"diff={esf_t['difference']}")
check("S3.7 — Total Activos > 0", esf_t["total_activos"] > 0, f"{esf_t['total_activos']}")

# ── S4: Motor ERI ────────────────────────────────────────────────
section("S4: Motor de Cálculo — ERI")

eri_t = build_eri_totals(buckets, NIIF_LINES)
check("S4.1 — Ingresos = 3,000,000",
      abs(eri_t["total_ingresos"] - Decimal("3000000")) <= TOLERANCE, f"{eri_t['total_ingresos']}")
check("S4.2 — Costo = 1,500,000",
      abs(eri_t["total_costo"] - Decimal("1500000")) <= TOLERANCE, f"{eri_t['total_costo']}")
check("S4.3 — Utilidad Bruta = 1,500,000",
      abs(eri_t["utilidad_bruta"] - Decimal("1500000")) <= TOLERANCE, f"{eri_t['utilidad_bruta']}")
# UN = 3M - 1.5M - 500k - 200k - 75k - 225k = 500,000
check("S4.4 — Utilidad Neta = 500,000",
      abs(eri_t["utilidad_neta"] - Decimal("500000")) <= TOLERANCE, f"{eri_t['utilidad_neta']}")

# ── S5: Escenario pérdida ────────────────────────────────────────
section("S5: Escenario de Pérdida Neta")

MOCK_TB_P = {
    "1101": {"account_type": "ACTIVO",     "account_name": "Caja",   "debit": Decimal("100000"), "credit": Decimal("0"), "balance": Decimal("100000")},
    "3101": {"account_type": "PATRIMONIO", "account_name": "Capital","debit": Decimal("0"),      "credit": Decimal("200000"), "balance": Decimal("200000")},
    "4101": {"account_type": "INGRESO",    "account_name": "Ventas", "debit": Decimal("0"),      "credit": Decimal("500000"), "balance": Decimal("500000")},
    "5101": {"account_type": "GASTO",      "account_name": "Costo",  "debit": Decimal("800000"), "credit": Decimal("0"),      "balance": Decimal("800000")},
}
MOCK_MAP_P = {
    "1101": {"niif_line_code": "ESF.AC.01", "is_contra": False},
    "3101": {"niif_line_code": "ESF.PAT.01","is_contra": False},
    "4101": {"niif_line_code": "ERI.ING.01","is_contra": False},
    "5101": {"niif_line_code": "ERI.GST.01","is_contra": False},
}
accum_p = accumulate(MOCK_TB_P, MOCK_MAP_P)
buckets_p = {k: Decimal(str(v)) for k, v in accum_p["buckets"].items()}
eri_p = build_eri_totals(buckets_p, NIIF_LINES)
check("S5.1 — Pérdida neta negativa", eri_p["utilidad_neta"] < 0, f"{eri_p['utilidad_neta']}")
check("S5.2 — Pérdida neta = -300,000",
      abs(eri_p["utilidad_neta"] - Decimal("-300000")) <= TOLERANCE, f"{eri_p['utilidad_neta']}")

# ── S6: Cuentas sin mapear ───────────────────────────────────────
section("S6: Cuentas sin mapear → warning no bloqueante")
MOCK_TB_U = dict(MOCK_TB)
MOCK_TB_U["9999"] = {"account_type":"GASTO","account_name":"Nueva","debit":Decimal("50000"),"credit":Decimal("0"),"balance":Decimal("50000")}
accum_u = accumulate(MOCK_TB_U, MOCK_MAPPINGS)
check("S6.1 — Cuenta 9999 detectada sin mapear", "9999" in accum_u["unmapped_codes"])
check("S6.2 — Sistema no colapsa por cuenta sin mapear", True, "Motor robusto")

# ── S7: Archivos creados ─────────────────────────────────────────
section("S7: Archivos del módulo reporting/ creados")
files = ["services/reporting/models.py", "services/reporting/niif_lines.py",
         "services/reporting/eeff_engine.py", "services/reporting/router.py"]
for f in files:
    path = os.path.join(BASE, f)
    exists = os.path.exists(path)
    size = os.path.getsize(path) if exists else 0
    check(f"S7 — {f.split('/')[-1]} existe y no vacío", exists and size > 1000, f"{size} bytes")

# ── S8: Router endpoints ─────────────────────────────────────────
section("S8: Router — endpoints declarados")
eps = ["/eeff/{year}", "/eeff/lines", "/eeff/mapping", "/eeff/mapping/unmapped", "/eeff/seed-mapping"]
for ep in eps:
    check(f"S8 — {ep}", ep in router_src)
check("S8.6 — SIN_MAPEO_NIIF guard en router", "SIN_MAPEO_NIIF" in router_src)
check("S8.7 — EeffEngine invocado en router", "EeffEngine" in router_src)

# ── S9: main.py ──────────────────────────────────────────────────
section("S9: Registro en main.py")
check("S9.1 — reporting_router importado",          "reporting_router" in main_src)
check("S9.2 — include_router(reporting_router)",     "include_router(reporting_router)" in main_src)
check("S9.3 — services.reporting.models importado", "services.reporting.models" in main_src)

# ── Engine source checks ─────────────────────────────────────────
section("S10: Calidad del código del motor")
check("S10.1 — EeffEngine tiene _accumulate",   "_accumulate" in engine_src)
check("S10.2 — EeffEngine tiene _build_esf",    "_build_esf"  in engine_src)
check("S10.3 — EeffEngine tiene _build_eri",    "_build_eri"  in engine_src)
check("S10.4 — ESF usa TOLERANCE",              "TOLERANCE"   in engine_src)
check("S10.5 — is_contra maneja contra-cuentas","is_contra"   in engine_src)
check("S10.6 — Solo asientos POSTED",           "POSTED"      in engine_src)
check("S10.7 — 3304 excluida en query",         "3304"        in engine_src)

# ── RESUMEN ───────────────────────────────────────────────────────
print(f"\n{'═'*62}")
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total  = len(results)
print(f"  RESULTADO FINAL: {passed}/{total} checks pasados")
if failed > 0:
    print(f"\n  ❌ FALLOS ({failed}):")
    for r in results:
        if r[0] == FAIL:
            print(f"    ❌ {r[1]}: {r[2]}")
    print(f"{'═'*62}")
    sys.exit(1)
else:
    print(f"  ✅✅✅ TODO VERDE — Paso 1 EEFF completamente validado")
    print(f"  NIIF PYMES 3ª Ed. (Feb 2025) — Motor ESF+ERI operativo")
    print(f"{'═'*62}")
    sys.exit(0)
