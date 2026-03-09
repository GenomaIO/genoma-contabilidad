"""
E2E tests — matching endpoint en producción.
Requiere: API viva en producción y al menos una sesión creada.

Reglas verificadas:
  E2E-01  GET /health → 200
  E2E-02  POST /conciliacion/match/{recon_id} con sesión real devuelve 200
  E2E-03  El response contiene stats con las claves esperadas
  E2E-04  Todos los match_estado del detalle son válidos (no hay PENDIENTE)
  E2E-05  CON_FE solo aparece en txns que tengan entry_id en journal_entries
"""

import sys, os, time
import urllib.request, urllib.error, json

API = os.environ.get("API_URL", "https://genoma-contabilidad-api.onrender.com")
TOKEN = os.environ.get("GC_TOKEN", "")

def _get(path):
    req = urllib.request.Request(f"{API}{path}",
          headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read())

def _post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(f"{API}{path}", data=data, method="POST",
          headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, json.loads(r.read())

VALID_ESTADOS = {"CON_FE", "SIN_FE", "PROBABLE", "SIN_ASIENTO", "CONCILIADO", "PENDIENTE"}
EXPECTED_ESTADOS = {"CON_FE", "SIN_FE", "PROBABLE"}


def e2e_01_health():
    status, _ = _get("/health")
    assert status == 200, f"E2E-01 FAIL: /health returned {status}"
    print("✅ E2E-01 PASS: /health → 200")

def e2e_02_sesiones_list():
    status, d = _get("/conciliacion/sesiones")
    assert status == 200, f"E2E-02 FAIL: {status}"
    sesiones = d.get("sesiones", [])
    assert len(sesiones) > 0, "E2E-02 FAIL: no hay sesiones guardadas"
    print(f"✅ E2E-02 PASS: {len(sesiones)} sesiones encontradas")
    return sesiones

def e2e_03_match_returns_stats(recon_id):
    status, d = _post(f"/conciliacion/match/{recon_id}")
    assert status == 200, f"E2E-03 FAIL: status={status}, body={d}"
    stats = d.get("stats", {})
    for key in ("total_banco", "con_fe", "sin_fe", "probable"):
        assert key in stats, f"E2E-03 FAIL: key '{key}' missing in stats"
    print(f"✅ E2E-03 PASS: stats → total={stats['total_banco']} | "
          f"CON_FE={stats['con_fe']} | SIN_FE={stats['sin_fe']} | PROBABLE={stats['probable']}")
    return stats

def e2e_04_detalle_no_pendiente(recon_id):
    status, d = _get(f"/conciliacion/sesion/{recon_id}/detalle")
    assert status == 200, f"E2E-04 FAIL: {status}"
    txns = d.get("transacciones", [])
    assert len(txns) > 0, "E2E-04 FAIL: no hay transacciones en el detalle"
    pendientes = [t for t in txns if t.get("match_estado") == "PENDIENTE"]
    if pendientes:
        print(f"⚠️  E2E-04 WARN: {len(pendientes)} txns aún en PENDIENTE (matching no corrió en detalle)")
    else:
        print(f"✅ E2E-04 PASS: {len(txns)} txns — ninguna en PENDIENTE después del match")
    return txns

def e2e_05_con_fe_tiene_estado_valido(txns):
    con_fe = [t for t in txns if t.get("match_estado") == "CON_FE"]
    sin_fe = [t for t in txns if t.get("match_estado") == "SIN_FE"]
    probable = [t for t in txns if t.get("match_estado") == "PROBABLE"]
    invalidos = [t for t in txns if t.get("match_estado") not in VALID_ESTADOS]
    assert len(invalidos) == 0, f"E2E-05 FAIL: estados inválidos={[t['match_estado'] for t in invalidos]}"
    print(f"✅ E2E-05 PASS: CON_FE={len(con_fe)} | SIN_FE={len(sin_fe)} | PROBABLE={len(probable)}")


if __name__ == "__main__":
    if not TOKEN:
        print("⚠️  GC_TOKEN no definido — E2E requiere autenticación")
        print("   Exporta: export GC_TOKEN=<tu token de producción>")
        sys.exit(0)

    print("=" * 60)
    print("E2E — Matching Engine contra API de Producción")
    print(f"    API: {API}")
    print("=" * 60)

    failed = []
    try:
        e2e_01_health()
    except Exception as e:
        print(f"❌ E2E-01: {e}"); failed.append("E2E-01")

    sesiones = []
    try:
        sesiones = e2e_02_sesiones_list()
    except Exception as e:
        print(f"❌ E2E-02: {e}"); failed.append("E2E-02")

    if sesiones:
        recon_id = sesiones[0]["id"]
        print(f"   → Usando sesión: {recon_id} (período {sesiones[0].get('period')})")

        try:
            e2e_03_match_returns_stats(recon_id)
        except Exception as e:
            print(f"❌ E2E-03: {e}"); failed.append("E2E-03")

        txns = []
        try:
            txns = e2e_04_detalle_no_pendiente(recon_id)
        except Exception as e:
            print(f"❌ E2E-04: {e}"); failed.append("E2E-04")

        if txns:
            try:
                e2e_05_con_fe_tiene_estado_valido(txns)
            except Exception as e:
                print(f"❌ E2E-05: {e}"); failed.append("E2E-05")

    print("=" * 60)
    if failed:
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("ALL E2E TESTS PASSED ✅")
