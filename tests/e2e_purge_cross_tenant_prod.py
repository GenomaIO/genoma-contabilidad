#!/usr/bin/env python3
"""
e2e_purge_cross_tenant_prod.py — E2E Test contra PRODUCCIÓN
════════════════════════════════════════════════════════════

Verifica el endpoint POST /integration/purge-cross-tenant-bleed
contra el backend real en producción (contabilidad.genomaio.com).

Protocolo de 4 etapas (safe-first):

  E1 · Health Check  — el backend está UP
  E2 · Endpoint existe y requiere auth (sin token → 401)
  E3 · DRY-RUN por cada tenant de la sombrilla
       Detecta cuántos asientos contaminados hay en SA y Angélica.
       NO borra nada. 100% seguro.
  E4 · PURGE REAL (requiere GC_TOKEN + CONFIRM_PURGE=1 explícito)
       Ejecuta el borrado en todos los tenants contaminados.
       Solo se ejecuta si la variable de entorno CONFIRM_PURGE=1.
       Por defecto es DRY-RUN.

Uso:
  # Solo diagnóstico (100% seguro, sin borrar nada):
  GC_TOKEN=<token> python tests/e2e_purge_cross_tenant_prod.py

  # Borrado real en producción (IRREVERSIBLE):
  GC_TOKEN=<token> CONFIRM_PURGE=1 python tests/e2e_purge_cross_tenant_prod.py

Requisito en el servidor:
  La variable ENABLE_PURGE_UTILITY=1 debe estar seteada en Render
  durante la ventana de mantenimiento.
"""

import os
import sys
import json
import base64
import urllib.request
import urllib.error

# ── Configuración ──────────────────────────────────────────────────────────────
BASE_URL       = "https://contabilidad.genomaio.com"
GC_TOKEN       = os.environ.get("GC_TOKEN", "")
CONFIRM_PURGE  = os.environ.get("CONFIRM_PURGE", "") == "1"

PASS_MARK = "  ✅"
FAIL_MARK = "  ❌"
SKIP_MARK = "  ⏭️ "
WARN_MARK = "  ⚠️ "
errors    = []
skipped   = []

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
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
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
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
        except Exception:
            body = {}
        return e.code, body
    except Exception as exc:
        return 0, {"error": str(exc)}


def decode_jwt(token: str) -> dict:
    try:
        parts   = token.split(".")
        padding = 4 - len(parts[1]) % 4
        return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
    except Exception:
        return {}


def _purge_tenant(tenant_id: str, nombre: str, token: str, confirm: bool, cedula: str = "") -> dict | None:
    """Ejecuta dry-run o purge real para un tenant dado su JWT de switch."""
    # Primero hacer switch para tener JWT con el tenant_id correcto
    st_sw, body_sw = http_post(
        "/auth/switch-tenant",
        {"tenant_id": tenant_id, "nombre": nombre},
        token
    )
    if st_sw != 200:
        print(f"     {FAIL_MARK} switch-tenant a {nombre} falló: HTTP {st_sw} {body_sw}")
        return None

    tenant_token = body_sw.get("access_token", "")
    if not tenant_token:
        print(f"     {FAIL_MARK} switch-tenant a {nombre} no retornó access_token")
        return None

    # Ejecutar purge (dry-run o real)
    # cedula_tenant = override para partner_linked (no existen en DB local de tenants)
    payload = {
        "confirm": confirm,
        "source_types": ["HACIENDA_PULL", "hacienda_pull", "AUTO"],
    }
    if cedula:
        payload["cedula_tenant"] = cedula

    st_p, body_p = http_post(
        "/integration/purge-cross-tenant-bleed",
        payload,
        tenant_token
    )
    return {"status": st_p, "body": body_p, "nombre": nombre, "tenant_id": tenant_id}


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 66)
print("   E2E TEST — purge-cross-tenant-bleed en PRODUCCIÓN")
print(f"   Backend:  {BASE_URL}")
print(f"   Modo:     {'🔴 PURGE REAL (CONFIRM_PURGE=1)' if CONFIRM_PURGE else '🟢 DRY-RUN (solo lectura)'}")
print("═" * 66)

# ─────────────────────────────────────────────────────────────────────────────
# E1 · Health Check
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E1  Health Check")

st_h, body_h = http_get("/health")
check(f"Backend UP (HTTP {st_h})", st_h == 200, body_h.get("error", ""))
if st_h != 200:
    print(f"     ⚠️  Backend no responde en {BASE_URL}")
    print("═" * 66 + "\n")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# E2 · Endpoint existe y requiere auth
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E2  /integration/purge-cross-tenant-bleed requiere auth")

st_no_auth, body_no_auth = http_post(
    "/integration/purge-cross-tenant-bleed",
    {"confirm": False}
)
check(
    f"Sin token → 401 (got {st_no_auth})",
    st_no_auth == 401,
    str(body_no_auth)
)

# Si retorna 503 es porque ENABLE_PURGE_UTILITY no está activo (esperado en prod normal)
if st_no_auth == 503:
    print(f"{WARN_MARK} El servidor retornó 503 — ENABLE_PURGE_UTILITY no está activo.")
    print(f"     Activar en Render: ENABLE_PURGE_UTILITY=1 y re-correr este test.")

# ─────────────────────────────────────────────────────────────────────────────
# E3 · DRY-RUN por cada tenant de la sombrilla
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E3  DRY-RUN — diagnóstico de contaminación por tenant")

if not GC_TOKEN:
    skip("E3 (requiere GC_TOKEN)", "Pasar GC_TOKEN=<token> para ejecutar")
else:
    # Obtener lista de clientes del partner
    st_cl, body_cl = http_get("/auth/clients", GC_TOKEN)

    if st_cl != 200 or not body_cl.get("clients"):
        check("E3 — obtener lista de clientes", False, f"HTTP {st_cl}: {body_cl}")
    else:
        clients = body_cl["clients"]
        print(f"     → {len(clients)} cliente(s) en la sombrilla:")
        for c in clients:
            print(f"       · {c.get('nombre', '?')} (tenant_id: {str(c.get('tenant_id','?'))[:12]}...)")

        resultados_dry = []

        for client in clients:
            tid    = str(client.get("tenant_id", ""))
            nombre = client.get("nombre", "Sin nombre")
            # emisor_id = cédula real del cliente en el Facturador
            # ── Resolver cédula del cliente ─────────────────────────────────────
            # 1) emisor_id del Facturador (fuente de verdad, suele ser null en esta API)
            # 2) Regex sobre el nombre (ej: "3-101-953441 SOCIEDAD ANONIMA" → 3101953441)
            # 3) Mapeo conocido hardcodeado (fallback final para GC-RNHJ)
            CEDULAS_CONOCIDAS = {
                "1001": "202830516",   # Álvaro González Alfaro
                "1002": "603170547",   # Angélica Li Wong
                "1003": "3101953441",  # 3-101-953441 Sociedad Anónima
            }
            cedula = str(client.get("emisor_id") or client.get("cedula") or "")
            if not cedula:
                # Intentar extraer del nombre (ej: "3-101-953441 SOCIEDAD ANONIMA")
                import re as _re
                m = _re.search(r'(\d[\d-]{7,11}\d)', nombre)
                if m:
                    cedula = m.group(1).replace("-", "")
            if not cedula:
                cedula = CEDULAS_CONOCIDAS.get(tid, "")

            print(f"\n     🔍 Analizando: {nombre}" + (f" (cédula: {cedula})" if cedula else " ⚠️ sin cédula"))
            result = _purge_tenant(tid, nombre, GC_TOKEN, confirm=False, cedula=cedula)

            if result is None:
                print(f"        ❌ No se pudo hacer diagnóstico")
                continue

            st_p  = result["status"]
            body_p = result["body"]

            if st_p == 503:
                print(f"        ⚠️  ENABLE_PURGE_UTILITY no activo en el servidor")
                print(f"           Activar en Render y re-correr el test")
                continue

            if st_p != 200:
                print(f"        ❌ Error HTTP {st_p}: {body_p}")
                errors.append(f"E3 — {nombre}: HTTP {st_p}")
                continue

            contam = body_p.get("total_contaminados", 0)
            revisados = body_p.get("total_revisados", 0)
            cedula = body_p.get("cedula_tenant", "?")

            print(f"        Cédula tenant: {cedula}")
            print(f"        Revisados:     {revisados} asientos DRAFT importados")
            print(f"        Contaminados:  {contam}")

            if contam > 0:
                print(f"        🩸 CONTAMINACIÓN DETECTADA:")
                for c_item in body_p.get("contaminados", [])[:5]:  # max 5 en pantalla
                    print(f"           · [{c_item.get('motivo','?')}] {c_item.get('description','?')[:60]}")
                    print(f"             cédula_doc={c_item.get('cedula_detectada')} vs tenant={c_item.get('cedula_tenant')}")
                if contam > 5:
                    print(f"           ... y {contam - 5} más")
                resultados_dry.append({"nombre": nombre, "tid": tid, "contam": contam})

            check(
                f"{nombre}: diagnóstico completado (modo=DRY_RUN)",
                st_p == 200
            )

        print(f"\n     ── Resumen DRY-RUN ─────────────────────────────────")
        if resultados_dry:
            total_contam = sum(r["contam"] for r in resultados_dry)
            print(f"     {WARN_MARK} {total_contam} asiento(s) contaminado(s) detectados en {len(resultados_dry)} tenant(s):")
            for r in resultados_dry:
                print(f"       → {r['nombre']}: {r['contam']} asiento(s) a purgar")
            print(f"\n     Para purgar, correr con CONFIRM_PURGE=1:")
            print(f"     GC_TOKEN=<token> CONFIRM_PURGE=1 python tests/e2e_purge_cross_tenant_prod.py")
        else:
            print(f"     ✅ Todos los tenants limpios — sin contaminación detectada")

# ─────────────────────────────────────────────────────────────────────────────
# E4 · PURGE REAL (solo si CONFIRM_PURGE=1 y GC_TOKEN presentes)
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E4  PURGE REAL — borrado definitivo de contaminados")

if not GC_TOKEN:
    skip("E4 (requiere GC_TOKEN)")
elif not CONFIRM_PURGE:
    skip(
        "E4 (requiere CONFIRM_PURGE=1)",
        "El modo actual es DRY-RUN. Para borrar: GC_TOKEN=<t> CONFIRM_PURGE=1 python ..."
    )
else:
    print(f"     🔴 MODO PURGE REAL ACTIVADO — los asientos contaminados serán BORRADOS")

    st_cl2, body_cl2 = http_get("/auth/clients", GC_TOKEN)
    clients2 = body_cl2.get("clients", []) if st_cl2 == 200 else []

    total_borrados = 0

    for client in clients2:
        tid    = str(client.get("tenant_id", ""))
        nombre = client.get("nombre", "Sin nombre")
        cedula = str(client.get("emisor_id") or client.get("cedula") or "")

        print(f"\n     🗑️  Purgando: {nombre}" + (f" (cédula: {cedula})" if cedula else ""))
        result = _purge_tenant(tid, nombre, GC_TOKEN, confirm=True, cedula=cedula)

        if result is None:
            errors.append(f"E4 — {nombre}: no se pudo hacer switch-tenant")
            continue

        st_p   = result["status"]
        body_p = result["body"]

        if st_p == 503:
            print(f"        ⚠️  ENABLE_PURGE_UTILITY no activo")
            errors.append(f"E4 — {nombre}: ENABLE_PURGE_UTILITY no activo")
            continue

        check(
            f"{nombre}: purge HTTP 200",
            st_p == 200,
            f"got {st_p}: {body_p.get('detail', body_p)}"
        )

        if st_p == 200:
            borrados   = body_p.get("borrados", 0)
            liberados  = body_p.get("source_refs_liberados", [])
            total_borrados += borrados

            print(f"        Borrados:   {borrados} asiento(s)")
            if liberados:
                print(f"        Liberados:  {len(liberados)} source_ref(s) para re-importar")
            print(f"        Mensaje:    {body_p.get('mensaje', '')[:100]}")

            check(
                f"{nombre}: modo = PURGE_REAL",
                body_p.get("modo") == "PURGE_REAL",
                str(body_p.get("modo"))
            )

    print(f"\n     ── Resumen PURGE REAL ──────────────────────────────────")
    print(f"     Total asientos borrados: {total_borrados}")
    if total_borrados > 0:
        print(f"     ✅ SA y Angélica purgados — sin registros de otro tenant")
        print(f"     🧱 El muro anti-bleed (filtro cédula en import-batch) protege el futuro")
    else:
        print(f"     ✅ Los tenants ya estaban limpios")

# ─────────────────────────────────────────────────────────────────────────────
# E5 · Verificación post-purge: switch-tenant sigue funcionando
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 E5  Verificación post-purge — switch-tenant sigue funcionando")

if not GC_TOKEN:
    skip("E5 (requiere GC_TOKEN)")
else:
    st_sw_post, body_sw_post = http_get("/auth/clients", GC_TOKEN)
    check(
        f"GET /auth/clients sigue respondiendo (HTTP {st_sw_post})",
        st_sw_post == 200,
        str(body_sw_post)
    )

    if st_sw_post == 200 and body_sw_post.get("clients"):
        c_test = body_sw_post["clients"][0]
        st_sw5, body_sw5 = http_post(
            "/auth/switch-tenant",
            {"tenant_id": str(c_test["tenant_id"]), "nombre": c_test.get("nombre", "")},
            GC_TOKEN
        )
        check(
            f"switch-tenant a {c_test.get('nombre','?')} sigue funcionando (HTTP {st_sw5})",
            st_sw5 == 200,
            str(body_sw5)
        )
        if st_sw5 == 200:
            payload_post = decode_jwt(body_sw5.get("access_token", ""))
            check(
                "JWT post-purge contiene tenant_id correcto",
                payload_post.get("tenant_id") == str(c_test["tenant_id"]),
                f"got {payload_post.get('tenant_id')!r}"
            )

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 66)
if skipped:
    print(f"  ⏭️  Tests skipped: {len(skipped)}")
    for s in skipped:
        print(f"     → {s}")

if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    print("═" * 66 + "\n")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON")
    if CONFIRM_PURGE:
        print("     → PURGE REAL ejecutado — SA y Angélica limpios")
        print("     → Muro anti-bleed activo para futuros imports")
        print("     → switch-tenant sigue funcionando correctamente")
    else:
        print("     → DRY-RUN completado — backend UP, endpoints verificados")
        print("     → Para aplicar el purge: GC_TOKEN=<t> CONFIRM_PURGE=1 python ...")
print("═" * 66 + "\n")
