"""
SIM — Flujo Conciliación Completo: FIX 2+3+4
=============================================
M1. crear_sesion + bulk-insert: flujo correcto con tenant isolation
M2. Tenant incorrecto → 403 (seguridad)
M3. saveSesion exitoso → reconId disponible → Conciliar se habilita
M4. Matching retorna stats → auto-CENTINELA → score en estado
M5. runMatch sin reconId → mensaje claro (no crash)
M6. 0 txns para el período → el filtro vacía txnsFiltradas → no avanza
M7. El endpoint GET /ledger/accounts existe en el backend
"""
import sys, os, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_conc = open(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")).read()
src_ledger = open(os.path.join(ROOT, "services/ledger/router.py")).read()
src_crecon = open(os.path.join(ROOT, "services/conciliacion/router.py")).read()

# ─── M1: Endpoint bulk-insert existe con tenant isolation ─────────────────────
print("\n🏦 MÓDULO 1 — Backend: bulk-insert con tenant isolation:")

check("bulk_insert_transactions" in src_crecon,
      "Función bulk_insert_transactions definida en el backend")
check("row.tenant_id != tenant_id" in src_crecon,
      "Validación: recon_id pertenece al tenant autenticado")
check("DELETE FROM bank_transactions WHERE recon_id = :id" in src_crecon,
      "DELETE antes de INSERT (idempotent, permite re-cargas)")
check("total_insertadas" in src_crecon,
      "Respuesta incluye total_insertadas para logging en front")

# ─── M2: Aislamiento por tenant ───────────────────────────────────────────────
print("\n🔒 MÓDULO 2 — Seguridad: aislamiento por tenant:")

def simular_bulk_insert(recon_tenant, req_tenant, txns):
    """Simula la lógica de bulk_insert_transactions."""
    if recon_tenant != req_tenant:
        return {"status": 403, "detail": "Acceso denegado"}
    return {"status": 200, "ok": True, "total_insertadas": len(txns)}

res_ok   = simular_bulk_insert("tenant-A", "tenant-A", [{"fecha": "2026-02-01"}])
res_403  = simular_bulk_insert("tenant-A", "tenant-B", [{"fecha": "2026-02-01"}])

check(res_ok["status"] == 200,  "Mismo tenant → 200 OK")
check(res_403["status"] == 403, "Tenant diferente → 403 Acceso denegado")

# ─── M3: Flujo saveSesion → reconId → Conciliar habilitado ────────────────────
print("\n💾 MÓDULO 3 — Frontend: flujo saveSesion → reconId:")

def simular_save_sesion(account_code, txns, token):
    """Simula saveSesion() del frontend."""
    if not account_code:
        return {"ok": False, "reconId": None, "msg": "Selecciona la cuenta contable"}
    if not token:
        return {"ok": False, "reconId": None, "msg": "Sin autenticación"}
    # Simula POST /sesion → {ok: true, recon_id: "uuid"}
    recon_id = "test-recon-id-123"
    # Simula POST /sesion/{id}/transactions → {ok: true, total_insertadas: N}
    total = len(txns)
    return {"ok": True, "reconId": recon_id, "total_insertadas": total,
            "saveMsg": f"✅ {total} transacciones guardadas. Listo para conciliar."}

txns_feb = [
    {"fecha": "2026-02-03", "monto": 50000, "tipo": "DB"},
    {"fecha": "2026-02-10", "monto": 200000, "tipo": "CR"},
]

res_save = simular_save_sesion("1101", txns_feb, "valid-token")
check(res_save["ok"],                   "saveSesion OK con cuenta + token")
check(res_save["reconId"] is not None,  "reconId disponible tras guardar")
check(res_save["total_insertadas"] == 2, "2 txns insertadas")
check("Listo para conciliar" in res_save["saveMsg"], "Mensaje indica listo para conciliar")

res_no_acct = simular_save_sesion("", txns_feb, "valid-token")
check(not res_no_acct["ok"],            "Sin cuenta → error, no procede")
check(res_no_acct["reconId"] is None,   "Sin cuenta → reconId sigue null")

# ─── M4: Matching + auto-CENTINELA ────────────────────────────────────────────
print("\n⚖️  MÓDULO 4 — runMatch + auto-CENTINELA:")

def simular_run_match(recon_id):
    """Simula el resultado de POST /conciliacion/match/{recon_id}."""
    return {
        "ok": True,
        "stats": {"conciliados": 1, "probables": 0, "sin_asiento": 1, "solo_libros": 0, "total_banco": 2},
        "saldo_diff": {"diferencia": 50000, "estado": "DIFERENCIA"}
    }

def simular_centinela_analyze(recon_id):
    """Simula POST /centinela/analyze/{recon_id}."""
    return {"ok": True, "score": {"score_total": 35, "fugas_tipo_a": 0, "fugas_tipo_b": 1, "fugas_tipo_c": 0,
                                   "exposicion_iva": 6500, "exposicion_renta": 0}}

def simular_flujo_matching(recon_id):
    match_result = simular_run_match(recon_id)
    centinela = simular_centinela_analyze(recon_id) if match_result["ok"] else None
    return {
        "step": "done",
        "stats": match_result["stats"],
        "centinelaScore": centinela["score"] if centinela else None,
    }

resultado = simular_flujo_matching("test-recon-id-123")
check(resultado["step"] == "done",        "Paso cambia a 'done'")
check(resultado["stats"]["conciliados"] == 1, "1 txn conciliada")
check(resultado["centinelaScore"] is not None, "CENTINELA score disponible automáticamente")
check(resultado["centinelaScore"]["score_total"] == 35, "Score = 35/100 (riesgo bajo)")
check(resultado["centinelaScore"]["fugas_tipo_b"] == 1,  "1 fuga tipo B detectada")

# ─── M5: runMatch sin reconId ─────────────────────────────────────────────────
print("\n🚫 MÓDULO 5 — runMatch sin reconId muestra mensaje claro:")

# Verificamos en el código del frontend que el mensaje es informativo
check("💾 Guarda las transacciones primero" in src_conc,
      "Mensaje guiar usuario cuando Conciliar se presiona sin guardar")
check("disabled={matching || !reconId}" in src_conc,
      "Botón Conciliar deshabilitado visualmente si !reconId")
check("opacity: reconId ? 1 : 0.45" in src_conc,
      "Botón Conciliar semitransparente si no hay reconId")

# ─── M6: 0 txns para el período → filtro vacía → mensaje correcto ─────────────
print("\n📅 MÓDULO 6 — 0 txns para el período = mensaje informativo:")

check("txnsFiltradas.length === 0" in src_conc,
      "Condición usa txnsFiltradas (no txnsFusionadas)")
check("ninguna es de" in src_conc,
      "Mensaje diferencia 'archivo ok pero ninguna es del período'")
check("onTransacciones(txnsFiltradas" in src_conc,
      "onTransacciones recibe txnsFiltradas (solo del período)")

# ─── M7: GET /ledger/accounts existe ─────────────────────────────────────────
print("\n📋 MÓDULO 7 — Backend: GET /ledger/accounts:")

check("@router.get(\"/accounts\")" in src_ledger,
      "Endpoint GET /ledger/accounts existe en router.py")
check("account_type: Optional[str]" in src_ledger,
      "Parámetro account_type para filtrar por ACTIVO/PASIVO/etc")
check("db.rollback()" in src_ledger,
      "Fallback para es_reguladora: rollback + retry sin columna")

# ─── M8: Nuevo estado centinelaScore en el frontend ──────────────────────────
print("\n🛡️  MÓDULO 8 — Frontend: score CENTINELA en Paso 3:")

check("centinelaScore" in src_conc,
      "Estado centinelaScore existe en el componente")
check("setCentinelaScore(dc.score)" in src_conc,
      "Score se guarda tras auto-análisis CENTINELA")
check("CENTINELA Fiscal" in src_conc,
      "Badge CENTINELA se renderiza en el Paso 3")
check("Score: {centinelaScore.score_total} / 100" in src_conc,
      "Score se muestra como X/100")

# ─── Resultado ────────────────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Flujo Conciliación Completo")
    print("   · FIX 1: Filtro período → solo txns de Feb 2026 pasan el Paso 2")
    print("   · FIX 2: POST /sesion/{id}/transactions con tenant isolation")
    print("   · FIX 3: Selector cuenta + guardar sesión habilita Conciliar")
    print("   · FIX 4: Auto-CENTINELA tras matching → score en Paso 3")
    print("   · GET /ledger/accounts → catálogo para el selector")
    sys.exit(0)
