#!/usr/bin/env python3
"""
sim_historial_sesiones_e2e.py — SIM + E2E  Fase 2
==================================================
Verifica:
  1. Migración M_CENTINELA_V2 en main.py (tabla bank_counterparties)
  2. Endpoints GET /conciliacion/sesiones y /sesion/{id}/detalle
  3. Estructura de bank_counterparties correcta
"""
import sys, pathlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0; FAIL = 0

def check(condition, label):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition: PASS += 1
    else: FAIL += 1


# ── SIM-1: Migración M_CENTINELA_V2 en main.py ───────────────────────────────
print("\n[SIM-1] Migración M_CENTINELA_V2 — bank_counterparties")
main_src = (ROOT / "services" / "gateway" / "main.py").read_text(encoding="utf-8")

check("M_CENTINELA_V2"          in main_src, "main.py contiene M_CENTINELA_V2")
check("bank_counterparties"     in main_src, "tabla bank_counterparties en migración")
check("tenant_id"               in main_src, "campo tenant_id (Regla de Oro)")
check("nombre_norm"             in main_src, "campo nombre_norm")
check("total_debitos"           in main_src, "campo total_debitos")
check("total_creditos"          in main_src, "campo total_creditos")
check("d150_monto_anual"        in main_src, "campo d150_monto_anual (umbral D-150)")
check("d150_flag"               in main_src, "campo d150_flag")
check("riesgo_nivel"            in main_src, "campo riesgo_nivel")
check("UNIQUE (tenant_id, nombre_norm)" in main_src, "UNIQUE constraint multi-tenant")
check("idx_counterparties_tenant" in main_src, "índice de performance tenant")

# ── SIM-2: Endpoints en el router ────────────────────────────────────────────
print("\n[SIM-2] Endpoints de historial en router.py")
router_src = (ROOT / "services" / "conciliacion" / "router.py").read_text(encoding="utf-8")

check("/conciliacion/sesiones"              in router_src, "endpoint GET /conciliacion/sesiones existe")
check("/conciliacion/sesion/{recon_id}/detalle" in router_src, "endpoint GET /sesion/{id}/detalle existe")
check("list_sesiones"                       in router_src, "función list_sesiones definida")
check("get_sesion_detalle"                  in router_src, "función get_sesion_detalle definida")
check("ORDER BY created_at DESC"            in router_src, "sesiones ordenadas por fecha desc")
check("LIMIT 50"                            in router_src, "límite de 50 sesiones (performance)")
check("beneficiario_nombre"                 in router_src, "detalle incluye beneficiario_nombre")
check("tiene_fe"                            in router_src, "detalle incluye tiene_fe")

# ── SIM-3: Importación funcional del router ──────────────────────────────────
print("\n[SIM-3] Importación sanitaria del router")
try:
    from services.conciliacion.router import list_sesiones, get_sesion_detalle
    check(callable(list_sesiones),     "list_sesiones es callable")
    check(callable(get_sesion_detalle), "get_sesion_detalle es callable")
except Exception as ex:
    check(False, f"Import falló: {ex}")

# ── SIM-4: class BulkTransactionItem intacta ─────────────────────────────────
print("\n[SIM-4] Integridad de BulkTransactionItem")
check("class BulkTransactionItem" in router_src, "class BulkTransactionItem existe")
check("class BulkTransactionRequest" in router_src, "class BulkTransactionRequest existe")

# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F2 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
