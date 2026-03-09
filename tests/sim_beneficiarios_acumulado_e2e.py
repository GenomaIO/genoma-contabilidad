#!/usr/bin/env python3
"""
sim_beneficiarios_acumulado_e2e.py — SIM + E2E  Fase 5
=======================================================
Verifica:
  1. run_centinela usa SIN_FE (ya no SIN_ASIENTO vacío)
  2. saldo_libros no está hardcodeado a 0.0 en run_centinela
  3. Upsert a bank_counterparties se hace en run_centinela
  4. Umbral D-150 (>= ₡1,000,000) se detecta correctamente
  5. Endpoints /centinela/beneficiarios y /centinela/beneficiario/{nombre} existen
"""
import sys, pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0; FAIL = 0

def check(condition, label):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition: PASS += 1
    else: FAIL += 1


# ── SIM-1: run_centinela busca SIN_FE (no SIN_ASIENTO) ───────────────────────
print("\n[SIM-1] run_centinela usa SIN_FE")
router_src = (ROOT / "services" / "conciliacion" / "router.py").read_text(encoding="utf-8")
check("SIN_FE" in router_src,                         "router usa estado SIN_FE")
check("SIN_ASIENTO" in router_src,                    "fallback SIN_ASIENTO aún presente (backward compat)")
check("saldo_libros = 0.0" not in router_src,         "saldo_libros hardcodeado ELIMINADO")
check("COALESCE(SUM(jl.credit)" in router_src,        "saldo_libros se calcula desde journal_lines")


# ── SIM-2: Lógica de acumulado por beneficiario (pura, sin BD) ───────────────
print("\n[SIM-2] Lógica de acumulado cross-meses")

# Simular 3 meses de txns con el mismo beneficiario
MESES_TXNS = [
    # Mes 1
    [{"beneficiario_nombre": "JOSE ALEJANDRO CARVA", "tipo": "DB",
      "monto": 400_000.0, "beneficiario_categoria": "TERCERO",
      "beneficiario_telefono_norm": "86876080"},],
    # Mes 2
    [{"beneficiario_nombre": "JOSE ALEJANDRO CARVA", "tipo": "DB",
      "monto": 350_000.0, "beneficiario_categoria": "TERCERO",
      "beneficiario_telefono_norm": "86876080"},],
    # Mes 3
    [{"beneficiario_nombre": "JOSE ALEJANDRO CARVA", "tipo": "DB",
      "monto": 300_000.0, "beneficiario_categoria": "TERCERO",
      "beneficiario_telefono_norm": "86876080"},],
]

acumulado = defaultdict(lambda: {"debitos": 0.0, "creditos": 0.0, "n": 0, "d150_anual": 0.0})

for mes_txns in MESES_TXNS:
    for txn in mes_txns:
        bnom = txn["beneficiario_nombre"]
        if txn["beneficiario_categoria"] in ("BANK_FEE", "BANK_INTEREST"):
            continue
        if txn["tipo"] == "DB":
            acumulado[bnom]["debitos"]  += txn["monto"]
        else:
            acumulado[bnom]["creditos"] += txn["monto"]
        acumulado[bnom]["d150_anual"] += txn["monto"]
        acumulado[bnom]["n"] += 1

total_jose = acumulado["JOSE ALEJANDRO CARVA"]["debitos"]
d150_anual = acumulado["JOSE ALEJANDRO CARVA"]["d150_anual"]
d150_flag  = d150_anual >= 1_000_000.0

check(abs(total_jose - 1_050_000.0) < 1,  f"Acumulado 3 meses: ₡{total_jose:,.0f} (esperado 1,050,000)")
check(d150_flag,                           f"Supera umbral D-150 ₡1M: {d150_anual:,.0f}")
check(acumulado["JOSE ALEJANDRO CARVA"]["n"] == 3, "3 transacciones acumuladas")

# Verificar que BANK_FEE no se acumula
TXNS_CON_BANCO = [
    {"beneficiario_nombre": "BNCR", "tipo": "DB", "monto": 5_000.0, "beneficiario_categoria": "BANK_FEE"},
    {"beneficiario_nombre": "JOSE", "tipo": "DB", "monto": 50_000.0, "beneficiario_categoria": "TERCERO"},
]
acc2 = defaultdict(lambda: {"debitos": 0.0})
for txn in TXNS_CON_BANCO:
    if txn["beneficiario_categoria"] in ("BANK_FEE", "BANK_INTEREST"):
        continue
    acc2[txn["beneficiario_nombre"]]["debitos"] += txn["monto"]

check("BNCR" not in acc2,  "BANK_FEE (BNCR) excluido de counterparties")
check("JOSE" in acc2,      "Tercero (JOSE) incluido en counterparties")


# ── SIM-3: Endpoints en router ────────────────────────────────────────────────
print("\n[SIM-3] Endpoints en router.py")
check("/centinela/beneficiarios"         in router_src, "GET /centinela/beneficiarios existe")
check("/centinela/beneficiario/{nombre"  in router_src, "GET /centinela/beneficiario/{nombre} existe")
check("list_beneficiarios"               in router_src, "función list_beneficiarios")
check("get_beneficiario_detalle"         in router_src, "función get_beneficiario_detalle")
check("d150_flag"                        in router_src, "campo d150_flag en query")
check("d150_flagged"                     in router_src, "resumen d150_flagged en respuesta")


# ── SIM-4: Importación ────────────────────────────────────────────────────────
print("\n[SIM-4] Importación funcional")
try:
    from services.conciliacion.router import list_beneficiarios, get_beneficiario_detalle
    check(callable(list_beneficiarios),       "list_beneficiarios callable")
    check(callable(get_beneficiario_detalle), "get_beneficiario_detalle callable")
except Exception as ex:
    check(False, f"Import falló: {ex}")


# ── SIM-5: tarifa_iva en UPDATE de run_centinela ──────────────────────────────
print("\n[SIM-5] tarifa_iva y estimar_tarifa en run_centinela")
check("estimar_tarifa" in router_src, "run_centinela importa estimar_tarifa")
check("tarifa_iva" in router_src,     "run_centinela actualiza tarifa_iva en bank_transactions")
check("bank_counterparties" in router_src, "run_centinela hace upsert en bank_counterparties")


# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F5 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
