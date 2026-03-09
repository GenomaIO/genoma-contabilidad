"""
SIM tests — CENTINELA por período (sin DB, sin servidor)
Reglas verificadas:
  SIM-01  Una cuenta, 3 SIN_FE → score calculado, fugas clasificadas
  SIM-02  Dos cuentas, SIN_FE combinados → consolidación correcta
  SIM-03  Período sin sesiones → error controlado (no 500)
  SIM-04  Safe Fallback: una cuenta falla → la otra se procesa
  SIM-05  Agrupación de responses por cuenta en cuentas_analizadas
"""

import sys, re, json
sys.path.insert(0, '.')


# ── Stubs mínimos de los engines (sin DB) ─────────────────────────────────────

def _mock_clasificar_fuga(txn, fe_emitidas, fe_recibidas):
    """Stub: todas las txns SIN_FE se convierten en fuga tipo A."""
    return {
        "fuga_tipo":  "A",
        "score_pts":  10,
        "d270_codigo": None,
        "accion":     "Regularizar",
        "iva_riesgo": abs(float(txn.get("monto", 0))) * 0.13,
        "base_riesgo": abs(float(txn.get("monto", 0))),
    }

def _mock_calcular_score(fugas, diff, ingresos, fe_total):
    """Stub: score = suma de puntos de fugas."""
    pts = sum(f.get("score_pts", 0) for f in fugas)
    return {
        "score_total":    pts,
        "fugas_tipo_a":   sum(1 for f in fugas if f.get("fuga_tipo") == "A"),
        "fugas_tipo_b":   sum(1 for f in fugas if f.get("fuga_tipo") == "B"),
        "fugas_tipo_c":   sum(1 for f in fugas if f.get("fuga_tipo") == "C"),
        "exposicion_iva":   sum(f.get("iva_riesgo", 0) for f in fugas),
        "exposicion_renta": 0,
        "exposicion_total": sum(f.get("base_riesgo", 0) for f in fugas),
        "d270_regs":      0,
        "detalle":        [],
    }

def _mock_estimar_tarifa(desc, cat):
    return 0.13

def _mock_calcular_iva(monto, tarifa):
    base = abs(float(monto))
    return {"base": base, "iva": round(base * tarifa, 2)}


# ── Lógica del endpoint (portada sin DB) ──────────────────────────────────────

def run_centinela_period_logic(tenant_id: str, period: str, sesiones: list,
                                sin_fe_por_sesion: dict, all_txns_por_sesion: dict,
                                fe_emitidas: list = None):
    """
    Replica la lógica del endpoint sin acceso a DB.
    sesiones: [{id, banco, account_code, saldo_final}]
    sin_fe_por_sesion: {recon_id: [txn, ...]}
    all_txns_por_sesion: {recon_id: [txn, ...]}
    """
    if not sesiones:
        raise ValueError("No hay sesiones")

    sin_match_all = []
    all_txns_all  = []
    cuentas_procesadas = []
    cuentas_fallidas   = []

    for sesion in sesiones:
        rid = sesion["id"]
        try:
            sin_fe   = sin_fe_por_sesion.get(rid, [])
            all_txns = all_txns_por_sesion.get(rid, [])
            if sesion.get("_falla"):
                raise RuntimeError("Sesión simulada con falla")
            sin_match_all.extend(sin_fe)
            all_txns_all.extend(all_txns)
            cuentas_procesadas.append({
                "recon_id": rid, "banco": sesion.get("banco"),
                "sin_fe": len(sin_fe), "total_txns": len(all_txns),
            })
        except Exception as e:
            cuentas_fallidas.append({"recon_id": rid, "error": str(e)})

    fugas = []
    for txn in sin_match_all:
        desc   = txn.get("descripcion", "")
        cat    = txn.get("beneficiario_categoria", "TERCERO")
        tarifa = _mock_estimar_tarifa(desc, cat)
        calc   = _mock_calcular_iva(txn.get("monto", 0), tarifa)
        fuga   = _mock_clasificar_fuga(txn, fe_emitidas or [], [])
        fuga.update({
            "txn_id": txn["id"], "txn_monto": float(txn.get("monto", 0)),
            "iva_riesgo": calc["iva"], "base_riesgo": calc["base"],
        })
        fugas.append(fuga)

    ingresos_banco = sum(float(t.get("monto", 0)) for t in all_txns_all if t.get("tipo") == "CR")
    result = _mock_calcular_score(fugas, 0, ingresos_banco, 0)

    return {
        "ok": True, "period": period, "score": result, "fugas": fugas,
        "cuentas_analizadas": cuentas_procesadas,
        "cuentas_fallidas": cuentas_fallidas,
        "total_sin_fe": len(sin_match_all),
        "total_txns": len(all_txns_all),
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

def sim_01_una_cuenta():
    """Una cuenta, 3 SIN_FE → fugas clasificadas y score calculado."""
    sesiones = [{"id": "R1", "banco": "BNCR", "account_code": "1101.01", "saldo_final": 500000}]
    sin_fe   = {"R1": [
        {"id": "T1", "monto": 50000, "tipo": "DB", "descripcion": "Pago Jose", "beneficiario_categoria": "TERCERO"},
        {"id": "T2", "monto": 30000, "tipo": "DB", "descripcion": "Pago Maria", "beneficiario_categoria": "TERCERO"},
        {"id": "T3", "monto": 10000, "tipo": "DB", "descripcion": "Pago Pedro", "beneficiario_categoria": "TERCERO"},
    ]}
    all_txns = {"R1": sin_fe["R1"]}
    r = run_centinela_period_logic("T001", "202602", sesiones, sin_fe, all_txns)
    assert r["ok"]
    assert r["total_sin_fe"] == 3
    assert len(r["fugas"]) == 3
    assert r["score"]["score_total"] == 30   # 3 fugas × 10 pts
    assert len(r["cuentas_analizadas"]) == 1
    assert r["cuentas_fallidas"] == []
    print("✅ SIM-01 PASS: una cuenta, 3 SIN_FE → score=30")

def sim_02_dos_cuentas():
    """Dos cuentas, SIN_FE combinados → consolidación correcta."""
    sesiones = [
        {"id": "R1", "banco": "BNCR", "account_code": "1101.01", "saldo_final": 500000},
        {"id": "R2", "banco": "BCR",  "account_code": "1101.02", "saldo_final": 200000},
    ]
    sin_fe = {
        "R1": [{"id": "T1", "monto": 50000, "tipo": "DB", "descripcion": "A", "beneficiario_categoria": "TERCERO"}],
        "R2": [
            {"id": "T2", "monto": 30000, "tipo": "DB", "descripcion": "B", "beneficiario_categoria": "TERCERO"},
            {"id": "T3", "monto": 20000, "tipo": "DB", "descripcion": "C", "beneficiario_categoria": "TERCERO"},
        ],
    }
    all_txns = sin_fe.copy()
    r = run_centinela_period_logic("T001", "202602", sesiones, sin_fe, all_txns)
    assert r["ok"]
    assert r["total_sin_fe"] == 3         # 1 + 2
    assert len(r["fugas"]) == 3
    assert len(r["cuentas_analizadas"]) == 2
    assert r["cuentas_fallidas"] == []
    print("✅ SIM-02 PASS: dos cuentas consolidadas → total_sin_fe=3")

def sim_03_sin_sesiones():
    """Sin sesiones → ValueError controlado (no crash silencioso)."""
    try:
        run_centinela_period_logic("T001", "202601", [], {}, {})
        assert False, "Debería haber levantado ValueError"
    except ValueError as e:
        assert "No hay sesiones" in str(e)
        print("✅ SIM-03 PASS: sin sesiones → ValueError controlado")

def sim_04_safe_fallback():
    """Una sesión falla → la otra se procesa (Rule #1 Safe Fallback)."""
    sesiones = [
        {"id": "R1", "banco": "BNCR", "account_code": "1101.01", "saldo_final": 500000, "_falla": True},
        {"id": "R2", "banco": "BCR",  "account_code": "1101.02", "saldo_final": 200000},
    ]
    sin_fe   = {"R2": [{"id": "T1", "monto": 50000, "tipo": "DB", "descripcion": "X", "beneficiario_categoria": "TERCERO"}]}
    all_txns = {"R2": sin_fe["R2"]}
    r = run_centinela_period_logic("T001", "202602", sesiones, sin_fe, all_txns)
    assert r["ok"]
    assert len(r["cuentas_analizadas"]) == 1   # solo R2
    assert len(r["cuentas_fallidas"])   == 1   # R1 falló
    assert r["cuentas_fallidas"][0]["recon_id"] == "R1"
    assert r["total_sin_fe"] == 1
    print("✅ SIM-04 PASS: Safe Fallback — cuenta fallida omitida, R2 procesada")

def sim_05_breakdown_por_cuenta():
    """El resultado incluye breakdown correcto por cuenta."""
    sesiones = [
        {"id": "R1", "banco": "BNCR", "account_code": "1101.01", "saldo_final": 500000},
        {"id": "R2", "banco": "BCR",  "account_code": "1101.02", "saldo_final": 200000},
    ]
    sin_fe = {
        "R1": [{"id": "T1", "monto": 100000, "tipo": "DB", "descripcion": "Z", "beneficiario_categoria": "TERCERO"}],
        "R2": [],
    }
    all_txns = {"R1": sin_fe["R1"] + [{"id": "T2", "monto": 500000, "tipo": "CR", "descripcion": "Deposito", "beneficiario_categoria": "TERCERO"}], "R2": []}
    r = run_centinela_period_logic("T001", "202602", sesiones, sin_fe, all_txns)
    cuentas = {c["recon_id"]: c for c in r["cuentas_analizadas"]}
    assert cuentas["R1"]["sin_fe"] == 1
    assert cuentas["R2"]["sin_fe"] == 0
    assert cuentas["R1"]["banco"] == "BNCR"
    print("✅ SIM-05 PASS: breakdown correcto — R1:sin_fe=1, R2:sin_fe=0")


if __name__ == "__main__":
    print("=" * 60)
    print("SIM — CENTINELA por Período (consolidado multi-cuenta)")
    print("=" * 60)
    failed = []
    for fn in [sim_01_una_cuenta, sim_02_dos_cuentas, sim_03_sin_sesiones,
               sim_04_safe_fallback, sim_05_breakdown_por_cuenta]:
        try:
            fn()
        except AssertionError as e:
            print(f"❌ {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"❌ {fn.__name__}: {type(e).__name__}: {e}")
            failed.append(fn.__name__)
    print("=" * 60)
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL SIM TESTS PASSED ✅")
