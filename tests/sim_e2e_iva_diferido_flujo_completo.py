"""
SIM-E2E-IVA — Flujo Completo: FE Condición 11 → IVA Diferido → Vencimiento 90d → Asiento Auto
═══════════════════════════════════════════════════════════════════════════════════════════════
Verifica el ciclo COMPLETO de vida de un documento con condición de venta 11:

  E2E-01: FE cond=11 → mapper_v2 genera IVA en cuenta 2108 (NO 2102)
  E2E-02: Asiento del doc con cond=11 queda balanceado
  E2E-03: Se puede registrar el IVA diferido con vencimiento correcto (+90d)
  E2E-04: El mismo día NO hay vencimientos (registro no ha vencido)
  E2E-05: Al día 90 exacto → el worker detecta el vencimiento
  E2E-06: El asiento de cierre generado está balanceado
  E2E-07: El asiento de cierre usa las cuentas correctas (2108 → 2102)
  E2E-08: El registro queda EJECUTADO (no se reprocesa)
  E2E-09: FE cond=02 (crédito normal) → IVA en 2102, sin tracking de diferido
  E2E-10: Asiento de cierre tiene source correcto (SISTEMA_IVA_DIFERIDO)
  E2E-11: Total fiscal: DR 2108 = CR 2102 (IVA es exactamente el registrado)
  E2E-12: Dos docs cond=11 en el mismo tenant → ambos rastreados y cerrados
"""
import sys, os
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.journal_mapper_v2 import _build_entry_lines_from_doc
from services.integration.iva_diferido_worker import (
    registrar_iva_diferido,
    run_iva_diferido_check,
)

PASS = 0; FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond: print(f"  ✅ PASS: {label}"); PASS += 1
    else:    print(f"  ❌ FAIL: {label}"); FAIL += 1

HOY        = date(2026, 3, 13)
FECHA_DOC  = "2026-01-01"   # Emitido el 1 de enero
VENC_90    = date(2026, 4, 1)   # enero 1 + 90 días = 1er abril

MONTO_NETO = 50_000.0
MONTO_IVA  = 6_500.0
TOTAL_DOC  = MONTO_NETO + MONTO_IVA  # 56_500

print("=" * 72)
print("SIM-E2E-IVA — Flujo Completo Condición 11 (Art.17 Ley IVA 9635)")
print("=" * 72)

# ─── E2E-01 / E2E-02: mapper_v2 genera IVA en 2108 y asiento balanceado ─────
print("\nE2E-01/02: FE cond=11 → IVA en 2108, asiento balanceado")
doc_c11 = {
    "tipo_doc":        "01",
    "condicion_venta": "11",
    "total_doc":       TOTAL_DOC,
    "receptor_nombre": "Cliente Venta a Plazo SA",
    "fecha_doc":       FECHA_DOC,
    "lineas": [{
        "descripcion":   "Consultoría Especializada",
        "monto_total":   MONTO_NETO,
        "tarifa_codigo": "08",
        "monto_iva":     MONTO_IVA,
    }],
}
lines_c11 = _build_entry_lines_from_doc(doc_c11, "tenant_A", "entry-c11-001", {})

dr_c11 = round(sum(l["debit"]  for l in lines_c11), 2)
cr_c11 = round(sum(l["credit"] for l in lines_c11), 2)

check("E2E-01: IVA en cuenta 2108 (Diferido)",
      any(l["account_code"] == "2108" for l in lines_c11))
check("E2E-01: SIN cuenta 2102 (IVA Débito normal)",
      not any(l["account_code"] == "2102" for l in lines_c11))
check("E2E-01: Role IVA_DIFERIDO en línea IVA",
      any(l.get("account_role") == "IVA_DIFERIDO" for l in lines_c11))
check("E2E-02: Asiento balanceado (DR=CR)",
      abs(dr_c11 - cr_c11) < 0.02)
check("E2E-02: Base legal Art.17",
      any(l.get("legal_basis", "").startswith("Art. 17") for l in lines_c11))

# ─── E2E-03: Registrar IVA diferido → vencimiento correcto ───────────────────
print("\nE2E-03: Registrar IVA diferido → vencimiento correcto (+90d)")
reg = registrar_iva_diferido(
    db=None, tenant_id="tenant_A",
    entry_id="entry-c11-001", source_ref="FE-A-001",
    fecha_doc=FECHA_DOC, monto_iva=MONTO_IVA,
)
check("E2E-03: Estado = PENDIENTE",        reg["estado"] == "PENDIENTE")
check("E2E-03: Vencimiento = 2026-04-01",  reg["vencimiento"] == str(VENC_90))
check("E2E-03: Monto IVA = 6500",          reg["monto_iva"] == 6500.0)
check("E2E-03: Cuenta origen = 2108",      reg["cuenta_origen"] == "2108")
check("E2E-03: Cuenta destino = 2102",     reg["cuenta_destino"] == "2102")

# ─── E2E-04: Antes del vencimiento → nada procesado ─────────────────────────
print("\nE2E-04: El mismo día del doc → sin vencimientos")
db_iva = [reg]
antes = date(2026, 1, 15)   # 15 días después del doc
res04 = run_iva_diferido_check(db_iva, today=antes)
check("E2E-04: Vencidos = 0 (no maduró aún)", res04["vencidos"] == 0)
check("E2E-04: Estado sigue PENDIENTE",        reg["estado"] == "PENDIENTE")

# ─── E2E-05 / E2E-06 / E2E-07: Al día 90 → asiento de cierre ────────────────
print("\nE2E-05/06/07: Al día 90 → worker genera asiento DR 2108 → CR 2102")
res05 = run_iva_diferido_check(db_iva, today=VENC_90)
check("E2E-05: Vencidos = 1", res05["vencidos"] == 1)
check("E2E-05: Generados = 1", res05["generados"] == 1)

if res05["generados"] == 1:
    entry_cierre = res05["detalle"][0]["entry"]
    ln = entry_cierre["lines"]
    dr_c = round(sum(l["debit"]  for l in ln), 2)
    cr_c = round(sum(l["credit"] for l in ln), 2)
    check("E2E-06: Asiento cierre balanceado",              abs(dr_c - cr_c) < 0.02)
    check("E2E-06: Monto = IVA original (6500)",            dr_c == 6500.0)
    check("E2E-07: DR en 2108 (rebaja IVA Diferido)",       any(l["account_code"]=="2108" and l["debit"]>0 for l in ln))
    check("E2E-07: CR en 2102 (IVA por Pagar exigible)",    any(l["account_code"]=="2102" and l["credit"]>0 for l in ln))
    check("E2E-07: Base legal Art.17 en líneas cierre",     any("90 días" in l.get("legal_basis","") for l in ln))

# ─── E2E-08: Registro queda EJECUTADO → idempotente ─────────────────────────
print("\nE2E-08: Registro queda EJECUTADO (idempotencia)")
check("E2E-08: Estado = EJECUTADO", reg["estado"] == "EJECUTADO")
check("E2E-08: entry_id_cierre seteado", reg.get("entry_id_cierre") is not None)
res08b = run_iva_diferido_check(db_iva, today=VENC_90 + timedelta(1))
check("E2E-08: 2do run → 0 generados (idempotente)", res08b["generados"] == 0)

# ─── E2E-09: FE cond=02 → IVA en 2102, sin tracking diferido ────────────────
print("\nE2E-09: FE cond=02 (crédito normal) → IVA en 2102, sin 2108")
doc_c02 = {**doc_c11, "condicion_venta": "02"}
lines_c02 = _build_entry_lines_from_doc(doc_c02, "tenant_A", "entry-c02-001", {})
check("E2E-09: IVA en 2102 (normal)", any(l["account_code"]=="2102" for l in lines_c02))
check("E2E-09: SIN cuenta 2108",     not any(l["account_code"]=="2108" for l in lines_c02))

# ─── E2E-10: Source del asiento de cierre ────────────────────────────────────
print("\nE2E-10: Asiento de cierre tiene source correcto")
if res05["generados"] == 1:
    check("E2E-10: source = SISTEMA_IVA_DIFERIDO",
          entry_cierre["source"] == "SISTEMA_IVA_DIFERIDO")
    check("E2E-10: status = DRAFT (contador aprueba)",
          entry_cierre["status"] == "DRAFT")

# ─── E2E-11: Exactitud fiscal — DR 2108 = CR 2102 = MONTO_IVA ────────────────
print("\nE2E-11: Exactitud fiscal (IVA = MONTO_IVA registrado)")
if res05["generados"] == 1:
    l2108 = [l for l in entry_cierre["lines"] if l["account_code"] == "2108"]
    l2102 = [l for l in entry_cierre["lines"] if l["account_code"] == "2102"]
    check("E2E-11: DR 2108 = 6500",  round(sum(l["debit"]  for l in l2108), 2) == 6500.0)
    check("E2E-11: CR 2102 = 6500",  round(sum(l["credit"] for l in l2102), 2) == 6500.0)

# ─── E2E-12: Dos docs cond=11 → ambos rastreados y cerrados ─────────────────
print("\nE2E-12: Dos docs cond=11 en mismo tenant → ambos cerrados")
f2 = str(HOY - timedelta(days=95))   # ya vencidos
db_dual = [
    registrar_iva_diferido(None, "tenant_B", "e-D1", "FE-B-001", f2, 3000.0),
    registrar_iva_diferido(None, "tenant_B", "e-D2", "FE-B-002", f2, 4500.0),
]
res12 = run_iva_diferido_check(db_dual, today=HOY)
check("E2E-12: Vencidos = 2",   res12["vencidos"] == 2)
check("E2E-12: Generados = 2",  res12["generados"] == 2)
check("E2E-12: Ambos EJECUTADOS",
      all(r["estado"] == "EJECUTADO" for r in db_dual))

# Total IVA cerrado = 3000 + 4500
total_dr = sum(
    round(sum(l["debit"] for l in d["entry"]["lines"]), 2)
    for d in res12["detalle"]
)
check("E2E-12: Total DR cerrado = 7500",  total_dr == 7500.0)

print("\n" + "=" * 72)
if FAIL == 0: print(f"ALL {PASS} SIM-E2E-IVA TESTS PASSED ✅")
else:         print(f"{PASS} passed, {FAIL} FAILED ❌"); sys.exit(1)
print("=" * 72)
