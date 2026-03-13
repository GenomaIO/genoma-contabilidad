"""
SIM-IVA90 — Worker IVA Diferido (Condición 11, 90 días)
═══════════════════════════════════════════════════════════
Verifica el worker de vencimiento de IVA diferido:

  IVA90-01: registrar_iva_diferido() calcula vencimiento = fecha + 90d
  IVA90-02: run_iva_diferido_check() no genera nada si no hay vencidos
  IVA90-03: Genera asiento DR 2108 → CR 2102 al llegar el día 90
  IVA90-04: Asiento generado es balanceado (DR = CR)
  IVA90-05: Registro queda en estado EJECUTADO tras el run
  IVA90-06: No procesa dos veces el mismo registro (idempotencia)
  IVA90-07: Múltiples vencidos en mismo run → todos procesados
  IVA90-08: Un error en un registro no bloquea los demás
  IVA90-09: auto_post=True → entry queda POSTED; False → DRAFT
  IVA90-10: Condición 11 en mapper_v2 → IVA va a cuenta 2108
"""
import sys, os
from datetime import date, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.iva_diferido_worker import (
    registrar_iva_diferido,
    run_iva_diferido_check,
    DIAS_VENCIMIENTO,
)
from services.integration.journal_mapper_v2 import _build_entry_lines_from_doc

PASS = 0; FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond: print(f"  ✅ PASS: {label}"); PASS += 1
    else:    print(f"  ❌ FAIL: {label}"); FAIL += 1

HOY = date(2026, 3, 13)

print("=" * 65)
print("SIM-IVA90 — Worker IVA Diferido (Condición 11, 90 días)")
print("=" * 65)

# ─── IVA90-01: registrar_iva_diferido → vencimiento correcto ────────
print("\nIVA90-01: registrar_iva_diferido() calcula vencimiento +90d")
reg = registrar_iva_diferido(
    db=None,           # No se usa en la función pura
    tenant_id="t1",
    entry_id="e-001",
    source_ref="50601011900310061007070000000062400010000",
    fecha_doc="2026-01-01",
    monto_iva=6500.0,
)
expected_venc = "2026-04-01"   # enero 1 + 90 días
check("Estado = PENDIENTE",         reg["estado"] == "PENDIENTE")
check("Vencimiento = fecha + 90d",  reg["vencimiento"] == expected_venc)
check("Monto IVA correcto",         reg["monto_iva"] == 6500.0)
check("cuenta_origen = 2108",       reg["cuenta_origen"] == "2108")
check("cuenta_destino = 2102",      reg["cuenta_destino"] == "2102")

# ─── IVA90-02: Sin vencidos → sin generados ─────────────────────────
print("\nIVA90-02: Sin vencidos en la fecha → cero generados")
db_sim = [registrar_iva_diferido(None, "t1", "e-002", "REF002", "2026-03-01", 1300.0)]
# Vence el 2026-05-30, consultamos hoy 2026-03-13
result = run_iva_diferido_check(db_sim, today=HOY)
check("Vencidos = 0",   result["vencidos"] == 0)
check("Generados = 0",  result["generados"] == 0)

# ─── IVA90-03: Al día 90 → genera asiento ───────────────────────────
print("\nIVA90-03: Al llegar el día 90 → genera asiento cierre")
fecha_90 = str(HOY - timedelta(days=DIAS_VENCIMIENTO))   # hace 90 días
db_sim2 = [registrar_iva_diferido(None, "t1", "e-003", "REF003", fecha_90, 5200.0)]
result2 = run_iva_diferido_check(db_sim2, today=HOY)
check("Vencidos = 1",    result2["vencidos"] == 1)
check("Generados = 1",   result2["generados"] == 1)

# ─── IVA90-04: Asiento balanceado (DR = CR) ─────────────────────────
print("\nIVA90-04: Asiento generado está balanceado")
if result2["generados"] == 1:
    entry = result2["detalle"][0]["entry"]
    lines = entry["lines"]
    dr = round(sum(l["debit"]  for l in lines), 2)
    cr = round(sum(l["credit"] for l in lines), 2)
    check("DR = CR (balanceado)",            abs(dr - cr) < 0.01)
    check("DR en cuenta 2108",               any(l["account_code"]=="2108" and l["debit"]>0 for l in lines))
    check("CR en cuenta 2102",               any(l["account_code"]=="2102" and l["credit"]>0 for l in lines))
    check("Monto IVA = 5200",                dr == 5200.0)
else:
    check("Asiento generado (prereq fallido)", False)

# ─── IVA90-05: Registro queda EJECUTADO ─────────────────────────────
print("\nIVA90-05: Registro queda en estado EJECUTADO")
if result2["generados"] == 1:
    check("Estado = EJECUTADO", db_sim2[0]["estado"] == "EJECUTADO")
    check("entry_id_cierre seteado", db_sim2[0]["entry_id_cierre"] is not None)

# ─── IVA90-06: Idempotencia — segundo run no reprocesa ──────────────
print("\nIVA90-06: Idempotencia — segundo run no reprocesa")
result3 = run_iva_diferido_check(db_sim2, today=HOY)
check("Vencidos en 2do run = 0",    result3["vencidos"] == 0)
check("Generados en 2do run = 0",   result3["generados"] == 0)

# ─── IVA90-07: Múltiples vencidos → todos procesados ────────────────
print("\nIVA90-07: Múltiples vencidos → todos generados")
f = str(HOY - timedelta(days=95))   # ya vencidos
db_multi = [
    registrar_iva_diferido(None, "t1", "e-010", "REF010", f, 1000.0),
    registrar_iva_diferido(None, "t1", "e-011", "REF011", f, 2000.0),
    registrar_iva_diferido(None, "t1", "e-012", "REF012", f, 500.0),
]
result_multi = run_iva_diferido_check(db_multi, today=HOY)
check("Vencidos = 3",   result_multi["vencidos"] == 3)
check("Generados = 3",  result_multi["generados"] == 3)
check("Todos EJECUTADOS", all(r["estado"] == "EJECUTADO" for r in db_multi))

# ─── IVA90-08: Error en un registro → continúa con los demás ────────
print("\nIVA90-08: Error en registro no bloquea resto")
db_error = [
    {"id": "bad-id", "estado": "PENDIENTE", "vencimiento": str(HOY - timedelta(1)),
     "monto_iva": "NOT_A_NUMBER", "tenant_id": "t1", "source_ref": "BAD"},   # error
    # El registro bueno también debe tener vencimiento pasado para aparecer en _get_vencidos
    registrar_iva_diferido(None, "t1", "e-020", "REF020",
                           str(HOY - timedelta(days=91)),  # hace 91 días → ya vencido
                           800.0),
]
result_err = run_iva_diferido_check(db_error, today=HOY)
check("Continúa tras error (generados >= 1)", result_err["generados"] >= 1)
check("Registra el error",                    result_err["errores"] >= 1)

# ─── IVA90-09: auto_post=True → POSTED; False → DRAFT ───────────────
print("\nIVA90-09: auto_post controla el status del entry")
db_ap = [registrar_iva_diferido(None, "t2", "e-030", "REF030", str(HOY - timedelta(91)), 300.0)]
res_posted = run_iva_diferido_check(db_ap, today=HOY, auto_post=True)
check("auto_post=True → POSTED", res_posted["detalle"][0]["entry"]["status"] == "POSTED")

db_ap2 = [registrar_iva_diferido(None, "t2", "e-031", "REF031", str(HOY - timedelta(91)), 300.0)]
res_draft = run_iva_diferido_check(db_ap2, today=HOY, auto_post=False)
check("auto_post=False → DRAFT", res_draft["detalle"][0]["entry"]["status"] == "DRAFT")

# ─── IVA90-10: mapper_v2 cond=11 → IVA a cuenta 2108 ───────────────
print("\nIVA90-10: mapper_v2 con condicion=11 → IVA en cuenta 2108")
doc_cond11 = {
    "tipo_doc":       "01",
    "condicion_venta": "11",
    "total_doc":      56500.0,
    "receptor_nombre": "Cliente Plazo",
    "lineas": [
        {"descripcion": "Consultoría", "monto_total": 50000.0,
         "tarifa_codigo": "08", "monto_iva": 6500.0}
    ],
}
lines_c11 = _build_entry_lines_from_doc(doc_cond11, "t1", "e-c11", {})
dr = round(sum(l["debit"]  for l in lines_c11), 2)
cr = round(sum(l["credit"] for l in lines_c11), 2)
check("Asiento balanceado",           abs(dr - cr) < 0.02)
check("IVA en cuenta 2108 (diferido)", any(l["account_code"] == "2108" for l in lines_c11))
check("NO usa cuenta 2102 (normal)", not any(l["account_code"] == "2102" for l in lines_c11))
check("Role=IVA_DIFERIDO en líneas",  any(l.get("account_role") == "IVA_DIFERIDO" for l in lines_c11))

print("\n" + "=" * 65)
if FAIL == 0: print(f"ALL {PASS} SIM-IVA90 TESTS PASSED ✅")
else:         print(f"{PASS} passed, {FAIL} FAILED ❌"); sys.exit(1)
print("=" * 65)
