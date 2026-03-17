#!/usr/bin/env python3
"""
e2e_switch_tenant_prod.py — E2E Test contra PRODUCCIÓN
══════════════════════════════════════════════════════

Verifica el flujo completo del fix de aislamiento multi-tenant
contra el backend real en producción (contable.genomaio.com).

Etapas:
  E1 · Health Check — el backend está UP
  E2 · /auth/clients — el endpoint existe y responde
  E3 · /auth/switch-tenant — el endpoint existe y responde
  E4 · JWT válido con tenant_id correcto al hacer switch
  E5 · Aislamiento: dos switches producen JWTs con tenant_ids distintos

Nota: Los tests E4 y E5 requieren un gc_token real.
Si no hay token disponible, se marcan como SKIP con aviso.

Uso:
  python tests/e2e_switch_tenant_prod.py
  GC_TOKEN=<token> python tests/e2e_switch_tenant_prod.py
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error
import urllib.parse

# ── Configuración ──────────────────────────────────────────────────────────────
BASE_URL  = "https://contabilidad.genomaio.com"  # Backend Contabilidad en producción
GC_TOKEN  = os.environ.get("GC_TOKEN", "")    # JWT del partner (opcional)

PASS_MARK  = "  ✅"
FAIL_MARK  = "  ❌"
SKIP_MARK  = "  ⏭️"
errors     = []
skipped    = []

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"{PASS_MARK} {label}")
    else:
        msg = f"{FAIL_MARK} {label}" + (f" — {detail}" if detail else "")
        print(msg)
        errors.append(label)


def skip(label: str, reason: str = ""):
    msg = f"{SKIP_MARK} {label}" + (f" — {reason}" if reason else "")
    print(msg)
    skipped.append(label)


def http_get(path: str, token: str = "") -> tuple[int, dict]:
    url = f"{BASE_URL}{path}"
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            return r.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception as exc:
        return 0, {"error": str(exc)}


def http_post(path: str, payload: dict, token: str = "") -> tuple[int, dict]:
    url  = f"{BASE_URL}{path}"
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode())
            return r.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception as exc:
        return 0, {"error": str(exc)}


def decode_jwt_payload(token: str) -> dict:
    """Decodifica el payload del JWT sin verificar la firma (solo para E2E)."""
    try:
        parts   = token.split(".")
        padding = 4 - len(parts[1]) % 4
        decoded = base64.urlsafe_b64decode(parts[1] + "=" * padding)
        return json.loads(decoded)
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 62)
print("   E2E TEST — switch-tenant en PRODUCCIÓN")
print(f"   Backend: {BASE_URL}")
print("═" * 62)

# ─────────────────────────────────────────────────────────────────────────────
# E1 · Health Check
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E1  Health Check")

status, body = http_get("/health")
check(f"Backend UP (HTTP {status})", status == 200, body.get("error", ""))
if status != 200:
    print(f"     Backend URL: {BASE_URL}")
    print(f"     Respuesta:   {body}")

# ─────────────────────────────────────────────────────────────────────────────
# E2 · /auth/clients existe y requiere auth
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E2  /auth/clients requiere auth (endpoint existe)")

status_cl, body_cl = http_get("/auth/clients")
check(
    f"/auth/clients retorna 401 sin token (HTTP {status_cl})",
    status_cl == 401,
    f"got {status_cl}: {body_cl}"
)

# ─────────────────────────────────────────────────────────────────────────────
# E3 · /auth/switch-tenant existe y requiere auth
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E3  /auth/switch-tenant requiere auth (endpoint existe)")

status_sw, body_sw = http_post("/auth/switch-tenant", {"tenant_id": "test-tenant-id"})
check(
    f"/auth/switch-tenant retorna 401 sin token (HTTP {status_sw})",
    status_sw == 401,
    f"got {status_sw}: {body_sw}"
)

# ─────────────────────────────────────────────────────────────────────────────
# E4 · Con GC_TOKEN real: switch emite JWT con tenant_id correcto
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E4  Con GC_TOKEN: switch-tenant emite JWT con tenant_id correcto")

if not GC_TOKEN:
    skip("E4 (requiere GC_TOKEN)", "Pasar GC_TOKEN=<token> para ejecutar este test")
else:
    # Primero obtener lista de clientes disponibles
    status_list, body_list = http_get("/auth/clients", GC_TOKEN)
    if status_list != 200 or not body_list.get("clients"):
        check("E4 — obtener lista de clientes", False, f"HTTP {status_list}: {body_list}")
    else:
        clients = body_list["clients"]
        old_payload  = decode_jwt_payload(GC_TOKEN)
        current_tid  = str(old_payload.get("tenant_id", ""))

        # Elegir un tenant DIFERENTE al actual para que la comparación sea válida
        target = next(
            (c for c in clients if str(c["tenant_id"]) != current_tid),
            clients[0]
        )
        target_tenant_id = str(target["tenant_id"])
        target_nombre    = target.get("nombre", "")

        print(f"     → Tenants disponibles: {[c.get('nombre', '?') for c in clients]}")
        print(f"     → JWT actual tenant_id: {current_tid!r}")
        print(f"     → Haciendo switch a: {target_nombre} ({target_tenant_id})")

        status_sw4, body_sw4 = http_post(
            "/auth/switch-tenant",
            {"tenant_id": target_tenant_id, "nombre": target_nombre},
            GC_TOKEN
        )
        check(f"HTTP 200 al hacer switch a {target_nombre}", status_sw4 == 200, str(body_sw4))

        if status_sw4 == 200:
            new_token   = body_sw4.get("access_token", "")
            new_payload = decode_jwt_payload(new_token)

            check(
                f"JWT.tenant_id = {target_tenant_id}",
                new_payload.get("tenant_id") == target_tenant_id,
                f"got: {new_payload.get('tenant_id')!r}"
            )
            check(
                f"JWT nuevo ({target_tenant_id}) != JWT original ({current_tid})",
                new_payload.get("tenant_id") != current_tid,
                f"Ambos tienen tenant_id={current_tid!r}"
            )
            print(f"     → Original tenant_id: {current_tid!r}")
            print(f"     → Nuevo    tenant_id: {new_payload.get('tenant_id')!r}")

# ─────────────────────────────────────────────────────────────────────────────
# E5 · Con GC_TOKEN real: dos switches producen JWTs con tenant_ids distintos
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E5  Aislamiento — dos tenants = dos JWTs distintos")

if not GC_TOKEN:
    skip("E5 (requiere GC_TOKEN)", "Pasar GC_TOKEN=<token> para ejecutar este test")
else:
    status_list2, body_list2 = http_get("/auth/clients", GC_TOKEN)
    clients2 = body_list2.get("clients", []) if status_list2 == 200 else []

    if len(clients2) < 2:
        skip("E5 — necesita al menos 2 clientes disponibles", f"Solo hay {len(clients2)}")
    else:
        c_a = clients2[0]
        c_b = clients2[1]

        print(f"     → Tenant A: {c_a.get('nombre', '?')}")
        print(f"     → Tenant B: {c_b.get('nombre', '?')}")

        _, resp_a = http_post("/auth/switch-tenant",
                              {"tenant_id": str(c_a["tenant_id"]), "nombre": c_a.get("nombre", "")},
                              GC_TOKEN)
        _, resp_b = http_post("/auth/switch-tenant",
                              {"tenant_id": str(c_b["tenant_id"]), "nombre": c_b.get("nombre", "")},
                              GC_TOKEN)

        jwt_a = resp_a.get("access_token", "")
        jwt_b = resp_b.get("access_token", "")

        if not jwt_a or not jwt_b:
            check("E5 — ambos switches retornan token", False, f"A={bool(jwt_a)} B={bool(jwt_b)}")
        else:
            payload_a = decode_jwt_payload(jwt_a)
            payload_b = decode_jwt_payload(jwt_b)

            check("Token A ≠ Token B (JWTs distintos)", jwt_a != jwt_b)
            check(
                f"Tenant A.tenant_id = {str(c_a['tenant_id'])}",
                payload_a.get("tenant_id") == str(c_a["tenant_id"]),
                f"got: {payload_a.get('tenant_id')!r}"
            )
            check(
                f"Tenant B.tenant_id = {str(c_b['tenant_id'])}",
                payload_b.get("tenant_id") == str(c_b["tenant_id"]),
                f"got: {payload_b.get('tenant_id')!r}"
            )
            check(
                "tenant_ids distintos entre sí",
                payload_a.get("tenant_id") != payload_b.get("tenant_id")
            )

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 62)
total   = len(errors) + len(skipped) + (
    14 - len(errors) - len(skipped)  # approximation
)
if skipped:
    print(f"  ⏭️  Tests skipped (necesitan GC_TOKEN): {len(skipped)}")
    print("     Para correr todos: GC_TOKEN=<token> python tests/e2e_switch_tenant_prod.py")

if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    print("═" * 62 + "\n")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON")
    if not skipped:
        print("     → End-to-end verificado contra producción")
        print("     → Backend UP + switch-tenant funcionando")
        print("     → JWTs con tenant_id correcto + aislamiento completo")
    else:
        print("     → Checks de infraestructura (E1-E3) verificados")
        print("     → Para verificar E4-E5 pasar GC_TOKEN")
print("═" * 62 + "\n")
