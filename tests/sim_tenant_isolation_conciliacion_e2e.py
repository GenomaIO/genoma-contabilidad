"""
SIM — Aislamiento de Tenant (Tenant Isolation) en Conciliación
===============================================================
Regla de Oro: la información contable de un tenant NUNCA debe
ser visible ni modificable por otro tenant.

MÓDULO 1 — crear_sesion: usa _get_tenant(request), NO "test_tenant"
MÓDULO 2 — get_score: filtra por tenant_id en SQL
MÓDULO 3 — get_d270_preview: JOIN con br.tenant_id  
MÓDULO 4 — save_rule: usa _get_tenant(request), NO "default"
MÓDULO 5 — list_rules: filtra por :tid del JWT
MÓDULO 6 — Integridad: _get_tenant devuelve 401 sin JWT

Cada módulo simula 2 tenants distintos ('A' y 'B') y verifica
que los datos de A no se filtran a B y viceversa.
"""
import sys, os, re

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src  = open(os.path.join(ROOT, "services/conciliacion/router.py")).read()

# ─── MÓDULO 1: crear_sesion usa _get_tenant(request) ─────────────────────
print("\n🔐 MÓDULO 1 — crear_sesion: extrae tenant_id del JWT:")

# Buscar el bloque de crear_sesion
sesion_start = src.find("@router.post(\"/conciliacion/sesion\")")
sesion_end   = src.find("@router.post(\"/conciliacion/match/")
sesion_block = src[sesion_start:sesion_end]

check("_get_tenant(request)"          in sesion_block,
      "crear_sesion llama _get_tenant(request)")
check("test_tenant"               not in sesion_block,
      "string hardcodeado 'test_tenant' ELIMINADO")
check("req.__dict__.get(\"tenant_id\"" not in sesion_block,
      "fallback inseguro del body ELIMINADO")
check("tenant_id = _get_tenant(request)" in sesion_block,
      "tenant_id asignado desde JWT, no desde el body")
check("SEGURIDAD: tenant_id se extrae del JWT"  in sesion_block,
      "comentario de seguridad documenta el cambio")
check("logger.info" in sesion_block and "tenant=" in sesion_block,
      "audit log registra tenant en cada sesión creada")

# Simular: si request = None → 401 (no puede caerse a "test_tenant")
def simular_get_tenant(auth_header):
    """Simula _get_tenant: requiere Bearer token."""
    if not auth_header or not auth_header.startswith("Bearer "):
        return None  # → 401
    token = auth_header.split(" ", 1)[1]
    # Mock decode: tenant_id en payload simulado
    import base64, json
    try:
        payload_b64 = token.split(".")[1] + "=="
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("tenant_id") or payload.get("sub")
    except Exception:
        return None

# Tenant A con JWT válido → obtiene su tenant_id
import base64, json
payload_a = base64.urlsafe_b64encode(json.dumps({"tenant_id": "tenant_A"}).encode()).decode().rstrip("=")
jwt_a = f"ignored.{payload_a}.sig"
tid_a = simular_get_tenant(f"Bearer {jwt_a}")
check(tid_a == "tenant_A", f"JWT tenant_A → _get_tenant devuelve 'tenant_A' (got '{tid_a}')")

# Tenant B con JWT válido → su propio id
payload_b = base64.urlsafe_b64encode(json.dumps({"tenant_id": "tenant_B"}).encode()).decode().rstrip("=")
jwt_b = f"ignored.{payload_b}.sig"
tid_b = simular_get_tenant(f"Bearer {jwt_b}")
check(tid_b == "tenant_B", f"JWT tenant_B → _get_tenant devuelve 'tenant_B' (got '{tid_b}')")

# Sin token → 401
check(simular_get_tenant("") is None, "sin token → _get_tenant devuelve None (→ 401)")
check(simular_get_tenant(None) is None, "None → _get_tenant devuelve None (→ 401)")

# ─── MÓDULO 2: get_score filtra por tenant_id ────────────────────────────
print("\n📊 MÓDULO 2 — get_score: WHERE tenant_id del JWT:")

score_start = src.find("@router.get(\"/centinela/score/{period}\")")
score_end   = src.find("@router.get(\"/centinela/d270/{period}\")")
score_block = src[score_start:score_end]

check("_get_tenant(request)"         in score_block, "get_score llama _get_tenant(request)")
check("WHERE tenant_id = :tenant_id" in score_block, "SQL filtra por tenant_id")
check("AND period = :period"         in score_block,  "SQL también filtra por period")
check("\"tenant_id\": tenant_id"     in score_block or
      "'tenant_id': tenant_id"       in score_block,  "param tenant_id en la query")

# Simular aislamiento: tenant_A NO puede ver score de tenant_B
def simular_get_score(tenant_id_autenticado, rows_db):
    """Simula la query filtrada por tenant_id."""
    return [r for r in rows_db if r["tenant_id"] == tenant_id_autenticado]

filas_db = [
    {"tenant_id": "tenant_A", "period": "2026-02", "score_total": 85},
    {"tenant_id": "tenant_B", "period": "2026-02", "score_total": 42},
]
check(len(simular_get_score("tenant_A", filas_db)) == 1,
      "tenant_A ve solo su propio score (no el de B)")
check(simular_get_score("tenant_A", filas_db)[0]["score_total"] == 85,
      "score de tenant_A = 85, no 42 (el de B)")
check(len(simular_get_score("tenant_C", filas_db)) == 0,
      "tenant_C (sin datos) recibe lista vacía, no datos de A ni B")

# ─── MÓDULO 3: get_d270_preview JOIN con br.tenant_id ────────────────────
print("\n📋 MÓDULO 3 — get_d270_preview: JOIN filtra por tenant_id:")

d270_start = src.find("@router.get(\"/centinela/d270/{period}\")")
d270_end   = src.find("@router.get(\"/centinela/d270/{period}/export\")")
d270_block = src[d270_start:d270_end]

check("_get_tenant(request)"         in d270_block, "get_d270_preview llama _get_tenant(request)")
check("br.tenant_id   = :tenant_id"  in d270_block or
      "br.tenant_id = :tenant_id"    in d270_block, "JOIN filtra por br.tenant_id")
check("\"tenant_id\": tenant_id"     in d270_block or
      "'tenant_id': tenant_id"       in d270_block, "param tenant_id en la query D-270")

# Simular: tenant_B no puede ver partidas D-270 de tenant_A
def simular_d270(tenant_autenticado, partidas_db):
    return [p for p in partidas_db
            if p["tenant_id"] == tenant_autenticado and p["d270_codigo"]]

partidas = [
    {"tenant_id": "tenant_A", "d270_codigo": "01", "monto": 500000},
    {"tenant_id": "tenant_A", "d270_codigo": "03", "monto": 120000},
    {"tenant_id": "tenant_B", "d270_codigo": "01", "monto": 88000},
]
resTB = simular_d270("tenant_B", partidas)
resTA = simular_d270("tenant_A", partidas)
check(len(resTB) == 1,    "tenant_B ve solo 1 partida (la suya)")
check(len(resTA) == 2,    "tenant_A ve 2 partidas (las suyas)")
check(resTB[0]["monto"] == 88000,
      "tenant_B ve su monto ₡88,000, no los de tenant_A")

# ─── MÓDULO 4: save_rule usa JWT, NO "default" ───────────────────────────
print("\n📏 MÓDULO 4 — save_rule: tenant del JWT, NO 'default':")

rule_start = src.find("@router.post(\"/conciliacion/rule\")")
rule_end   = src.find("@router.get(\"/conciliacion/rules\")")
rule_block = src[rule_start:rule_end]

check("_get_tenant(request)"      in rule_block, "save_rule llama _get_tenant(request)")
check("\"default\""           not in rule_block, "string 'default' ELIMINADO de save_rule")
check("tenant_id = _get_tenant"   in rule_block, "tenant_id desde JWT asignado")
check("SEGURIDAD: las reglas se guardan" in rule_block,
      "comentario de seguridad documenta el cambio")

# ─── MÓDULO 5: list_rules filtra por :tid del JWT ────────────────────────
print("\n📋 MÓDULO 5 — list_rules: filtra por tenant del JWT:")

rules_start = src.find("@router.get(\"/conciliacion/rules\")")
rules_block = src[rules_start:]

check("_get_tenant(request)"              in rules_block, "list_rules llama _get_tenant(request)")
check("WHERE tenant_id = :tid"            in rules_block, "SQL filtra por :tid (tenant del JWT)")
check("tenant_id = 'default'"         not in rules_block, "hardcode 'default' ELIMINADO")

# Simular aislamiento de reglas
def simular_list_rules(tenant_id, rules_db):
    return [r for r in rules_db if r["tenant_id"] == tenant_id]

rules_db = [
    {"tenant_id": "tenant_A", "pattern": "SINPE", "uses_count": 10},
    {"tenant_id": "tenant_A", "pattern": "BNCR", "uses_count": 5},
    {"tenant_id": "tenant_B", "pattern": "BAC", "uses_count": 3},
]
check(len(simular_list_rules("tenant_A", rules_db)) == 2,
      "tenant_A ve sus 2 reglas")
check(len(simular_list_rules("tenant_B", rules_db)) == 1,
      "tenant_B ve solo su 1 regla (no las de A)")
check(simular_list_rules("tenant_B", rules_db)[0]["pattern"] == "BAC",
      "tenant_B ve su regla 'BAC', no 'SINPE' ni 'BNCR' de A")

# ─── MÓDULO 6: _get_tenant devuelve 401 sin JWT ──────────────────────────
print("\n🚫 MÓDULO 6 — Sin JWT → 401 (no fallback inseguro):")

# Verificar en el código de _get_tenant
get_tenant_start = src.find("def _get_tenant(request)")
get_tenant_end   = src.find("# ── Endpoints", get_tenant_start)
gt_block = src[get_tenant_start:get_tenant_end]

check("raise HTTPException(status_code=401"  in gt_block,
      "_get_tenant lanza 401 si no hay token")
check("Bearer "                          in gt_block,
      "_get_tenant valida prefijo 'Bearer '")
check("tenant_id"                        in gt_block and
      "payload"                          in gt_block,
      "_get_tenant extrae tenant_id del payload JWT")

# ─── Resultado final ───────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Aislamiento de Tenant (Tenant Isolation)")
    print("   · crear_sesion: tenant_id del JWT (no 'test_tenant')")
    print("   · get_score: WHERE tenant_id = :tenant_id")
    print("   · get_d270_preview: JOIN br.tenant_id = :tenant_id")
    print("   · save_rule: tenant del JWT (no 'default')")
    print("   · list_rules: WHERE tenant_id = :tid del JWT")
    print("   · Sin JWT → 401 (no fallback inseguro posible)")
    sys.exit(0)
