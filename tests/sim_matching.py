"""
SIM tests — matching engine (sin DB, sin servidor)
Reglas verificadas:
  SIM-01  txn con asiento FE misma fecha/monto/desc → CON_FE
  SIM-02  txn con asiento MANUAL misma fecha/monto/desc → PROBABLE
  SIM-03  txn SIN asiento en libros → SIN_FE (siempre)
  SIM-04  BANK_FEE sin asiento en libros → SIN_FE (ya no auto-CON_FE)
  SIM-05  Dos txns misma fecha: matching 1-a-1, la segunda queda SIN_FE
  SIM-06  Monto fuera de ±2% no matchea aunque fecha/desc coincidan
"""

import sys, re
sys.path.insert(0, '.')


# ── Helper extraído del router (duplicado para test) ──────────────────────────
FUENTES_FE = {'FE', 'TE', 'NC', 'ND'}
TOLERANCIA  = 0.02

def _tokens(s):
    return {t.upper() for t in re.split(r'[\s/\-_.,]+', str(s or '')) if len(t) > 2}

def _descriptions_match(bank_desc, asiento_desc):
    STOP = {'DEL', 'LAS', 'LOS', 'CON', 'POR', 'PAGO', 'TXN', 'TRANS', 'BANCO', 'BNCR'}
    t1 = _tokens(bank_desc) - STOP
    t2 = _tokens(asiento_desc) - STOP
    return bool(t1 & t2)

def run_matching(bank_txns, asientos_periodo):
    """Replica exacta de la lógica del router (sin DB)."""
    usados = set()
    resultado = []

    for txn in bank_txns:
        txn_fecha = str(txn.get("fecha", ""))[:10]
        txn_monto = abs(float(txn.get("monto", 0)))
        txn_tipo  = txn.get("tipo", "DB")
        txn_desc  = str(txn.get("descripcion", ""))

        best_asiento = None
        best_diff    = 1.0
        best_conf    = 0.0

        for asi in asientos_periodo:
            if str(asi["fecha"])[:10] != txn_fecha:
                continue
            asi_monto = float(asi.get("credit" if txn_tipo == "CR" else "debit", 0) or 0)
            if asi_monto <= 0:
                continue
            diff = abs(txn_monto - asi_monto) / max(asi_monto, 1)
            if diff > TOLERANCIA:
                continue
            desc_ok = _descriptions_match(txn_desc, asi.get("desc_asiento", ""))
            conf = round((1.0 - diff) * 100, 1)
            if desc_ok:
                conf = min(conf + 10, 100.0)
            if diff < best_diff and asi["entry_id"] not in usados:
                best_diff = diff; best_conf = conf; best_asiento = asi

        if best_asiento:
            usados.add(best_asiento["entry_id"])
            tiene_fe = best_asiento["source"] in FUENTES_FE
            resultado.append({**txn,
                "match_estado":    "CON_FE" if tiene_fe else "PROBABLE",
                "match_confianza": best_conf,
                "tiene_fe":        tiene_fe})
        else:
            resultado.append({**txn,
                "match_estado":    "SIN_FE",
                "match_confianza": 0.0,
                "tiene_fe":        False})
    return resultado


# ── Tests ─────────────────────────────────────────────────────────────────────

def sim_01_con_fe():
    """txn con asiento fuente FE, misma fecha/monto → CON_FE"""
    txns = [{"id": "T1", "fecha": "2026-02-16", "monto": 150000, "tipo": "DB",
              "descripcion": "14-02-26 BNCR/COMISION 86020644"}]
    asientos = [{"entry_id": "A1", "fecha": "2026-02-16", "source": "FE",
                 "debit": 150000, "credit": 0,
                 "desc_asiento": "Comision 86020644 gastos bancarios"}]
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] == "CON_FE", f"SIM-01 FAIL: {r[0]['match_estado']}"
    print("✅ SIM-01 PASS: asiento FE → CON_FE")

def sim_02_probable():
    """txn con asiento fuente MANUAL → PROBABLE"""
    txns = [{"id": "T2", "fecha": "2026-02-13", "monto": 3500, "tipo": "DB",
              "descripcion": "12-02-26 SODA RUTA 35 ALAJUELA"}]
    asientos = [{"entry_id": "A2", "fecha": "2026-02-13", "source": "MANUAL",
                 "debit": 3500, "credit": 0,
                 "desc_asiento": "Soda Ruta 35 almuerzo"}]
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] == "PROBABLE", f"SIM-02 FAIL: {r[0]['match_estado']}"
    print("✅ SIM-02 PASS: asiento MANUAL → PROBABLE")

def sim_03_sin_asiento():
    """txn SIN asiento en libros → SIN_FE siempre"""
    txns = [{"id": "T3", "fecha": "2026-02-09", "monto": 23000, "tipo": "DB",
              "descripcion": "JOSE PABLO ROMERO VILLEG/PAGO SOCI"}]
    asientos = []  # libro diario vacío
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] == "SIN_FE", f"SIM-03 FAIL: {r[0]['match_estado']}"
    print("✅ SIM-03 PASS: sin asiento en libros → SIN_FE")

def sim_04_bank_fee_sin_asiento():
    """BANK_FEE sin asiento en libros NO es CON_FE (regla estricta)"""
    txns = [{"id": "T4", "fecha": "2026-02-16", "monto": 150000, "tipo": "DB",
              "descripcion": "14-02-26 BNCR/COMISION 86020644",
              "beneficiario_categoria": "BANK_FEE"}]
    asientos = []  # no hay asiento para esta comisión
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] == "SIN_FE", f"SIM-04 FAIL: {r[0]['match_estado']}"
    print("✅ SIM-04 PASS: BANK_FEE sin asiento en libros → SIN_FE (no auto-CON_FE)")

def sim_05_one_to_one():
    """Dos txns misma fecha/monto: el asiento se usa solo para la primera"""
    txns = [
        {"id": "T5a", "fecha": "2026-02-16", "monto": 150000, "tipo": "DB",
         "descripcion": "14-02-26 BNCR/COMISION 86020644"},
        {"id": "T5b", "fecha": "2026-02-16", "monto": 150000, "tipo": "DB",
         "descripcion": "14-02-26 BNCR/COMISION 86020644"},
    ]
    asientos = [{"entry_id": "A5", "fecha": "2026-02-16", "source": "FE",
                 "debit": 150000, "credit": 0,
                 "desc_asiento": "Comision 86020644"}]
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] in ("CON_FE", "PROBABLE"), f"SIM-05a FAIL"
    assert r[1]["match_estado"] == "SIN_FE", f"SIM-05b FAIL: {r[1]['match_estado']}"
    print("✅ SIM-05 PASS: matching 1-a-1 — segunda txn queda SIN_FE")

def sim_06_monto_fuera_tolerancia():
    """Monto diferente >2% no matchea aunque fecha/desc coincidan"""
    txns = [{"id": "T6", "fecha": "2026-02-02", "monto": 200000, "tipo": "DB",
              "descripcion": "MAXIMO MENDEZ VALERIO"}]
    asientos = [{"entry_id": "A6", "fecha": "2026-02-02", "source": "FE",
                 "debit": 210000, "credit": 0,  # diferencia 5% > 2%
                 "desc_asiento": "Maximo Mendez Valerio pago"}]
    r = run_matching(txns, asientos)
    assert r[0]["match_estado"] == "SIN_FE", f"SIM-06 FAIL: {r[0]['match_estado']}"
    print("✅ SIM-06 PASS: monto >2% de diferencia → SIN_FE")


if __name__ == "__main__":
    print("=" * 56)
    print("SIM — Motor de Matching (regla fecha+monto+asiento)")
    print("=" * 56)
    failed = []
    for fn in [sim_01_con_fe, sim_02_probable, sim_03_sin_asiento,
               sim_04_bank_fee_sin_asiento, sim_05_one_to_one, sim_06_monto_fuera_tolerancia]:
        try:
            fn()
        except AssertionError as e:
            print(f"❌ {e}")
            failed.append(fn.__name__)
    print("=" * 56)
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL SIM TESTS PASSED ✅")
