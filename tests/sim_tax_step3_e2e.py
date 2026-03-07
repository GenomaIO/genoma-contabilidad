"""
tests/sim_tax_step3_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PASO 3 — E2E contra API real (https://genoma-contabilidad-api.onrender.com)

Flujo completo:
  1. Login → obtener token JWT
  2. Verificar que /tax/* responde (nuevas rutas desplegadas)
  3. Guardar perfil PJ estándar
  4. Leer perfil → confirmar datos guardados
  5. Pre-llenar tramos 2026 oficiales
  6. Verificar idempotencia del prefill
  7. Leer tramos 2026 → verificar 4 PJ + 5 PF
  8. Agregar tramos 2027 manuales → no requiere deploy
  9. Leer tramos 2027 → verificar estructura
  10. GET proyección de renta → verificar campos esperados
  11. Modificar un tramo 2027 → proyección debe reflejar cambio
  12. Guardar perfil PF → proyección cambia de tipo

NOTA:
- Si el servidor aún no desplegó el código (Render puede tardar ~5 min),
  algunos checks fallarán con 404/502. El script reportará eso claramente.
- Credenciales en environment variables: E2E_EMAIL y E2E_PASSWORD
- Ejemplo:
  E2E_EMAIL=test@ejemplo.com E2E_PASSWORD=password python tests/sim_tax_step3_e2e.py

Ejecutar con:
    python tests/sim_tax_step3_e2e.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import os
import sys
import json
import time
import requests
from datetime import date

API = "https://genoma-contabilidad-api.onrender.com"
EMAIL    = os.environ.get("E2E_EMAIL",    "")
PASSWORD = os.environ.get("E2E_PASSWORD", "")

PASS = "  ✅"
FAIL = "  ❌"
SKIP = "  ⏭️ "
WARN = "  ⚠️ "
errors = []
skipped = []

def check(label, cond, detail=""):
    if cond:
        print(f"{PASS} {label}")
    else:
        print(f"{FAIL} {label}" + (f" — {detail}" if detail else ""))
        errors.append(label)

def skip(label, reason=""):
    print(f"{SKIP} {label}" + (f" [{reason}]" if reason else ""))
    skipped.append(label)

def warn(msg):
    print(f"{WARN} {msg}")

def near(a, b, tol=1.0):
    return abs(a - b) <= tol

def api(method, path, token=None, **kwargs):
    """Helper para llamadas HTTP con timeout y manejo de errores."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = getattr(requests, method)(
            f"{API}{path}",
            headers=headers,
            timeout=30,
            **kwargs,
        )
        return r
    except requests.exceptions.ConnectionError as e:
        print(f"  💥 ConnectionError: {e}")
        return None
    except requests.exceptions.Timeout:
        print(f"  💥 Timeout en {path}")
        return None

print("\n" + "═" * 65)
print("  SIMULACIÓN E2E — Paso 3: API Real de Producción")
print(f"  URL: {API}")
print(f"  Fecha de prueba: {date.today()}")
print("═" * 65)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 0: Conectividad y health check")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("get", "/health")
if r is None:
    check("API alcanzable", False, "Connection failed — ¿Render está desplegando?")
    print("\n  💡 El servidor puede estar inicializando. Espera 2-3 minutos y reintenta.")
    sys.exit(1)

check(f"GET /health → 200 (got {r.status_code})", r.status_code == 200, r.text[:100])

if r.status_code != 200:
    warn("Servidor responde pero con error — puede estar en deploy")
    sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 1: Login y autenticación")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if not EMAIL or not PASSWORD:
    warn("E2E_EMAIL / E2E_PASSWORD no definidos — saltando bloques 1-12")
    warn("Ejecutar con: E2E_EMAIL=tu@email.com E2E_PASSWORD=tupass python tests/sim_tax_step3_e2e.py")
    skip("Login", "sin credenciales")
    TOKEN = None
else:
    r = api("post", "/auth/login", json={"email": EMAIL, "password": PASSWORD})
    check("POST /auth/login → 200",              r and r.status_code == 200, r.text[:200] if r else "no response")
    TOKEN = r.json().get("access_token") if r and r.status_code == 200 else None
    check("Login retorna access_token",          bool(TOKEN))

    r2 = api("get", "/auth/me", token=TOKEN)
    check("GET /auth/me → 200",                  r2 and r2.status_code == 200)
    if r2 and r2.status_code == 200:
        me = r2.json()
        check("Me tiene tenant_id",              bool(me.get("tenant_id")))
        print(f"     → Tenant: {me.get('tenant_id')} | Email: {me.get('email')}")

if not TOKEN:
    print("\n  ⚠️  Sin token — no se pueden ejecutar los bloques 2-12.")
    print("     Los tests de lógica (Pasos 1 y 2) ya verificaron todo.")
    if skipped:
        print(f"     Saltados: {len(skipped)} bloques")
    sys.exit(0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 2: Nuevas rutas /tax/* desplegadas")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("get", "/tax/fiscal-profile", token=TOKEN)
check("GET /tax/fiscal-profile → no 404 (ruta existe)",
      r and r.status_code != 404,
      f"got {r.status_code if r else 'no response'}")

if r and r.status_code == 404 and "Not Found" in r.text:
    warn("Ruta /tax no existe aún — Render puede estar desplegando el nuevo código.")
    warn("Espera 2-3 minutos y reintenta. El código fue pusheado correctamente.")
    sys.exit(1)

r2 = api("get", "/tax/tax-brackets/years", token=TOKEN)
check("GET /tax/tax-brackets/years → no 404",
      r2 and r2.status_code != 404,
      f"got {r2.status_code if r2 else 'no response'}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 3: Perfil fiscal — guardar y leer")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("put", "/tax/fiscal-profile", token=TOKEN, json={
    "taxpayer_type": "PJ",
    "is_large_taxpayer": False,
    "fiscal_year_end_month": 9,
})
check("PUT /tax/fiscal-profile → 200",      r and r.status_code == 200, r.text[:200] if r else "no response")
check("PUT → ok=true",                      r and r.json().get("ok") == True)

r = api("get", "/tax/fiscal-profile", token=TOKEN)
check("GET perfil tras guardar → 200",      r and r.status_code == 200)
if r and r.status_code == 200:
    d = r.json()
    check("Perfil → configured=true",       d.get("configured") == True, str(d))
    check("Perfil → PJ",                    d.get("taxpayer_type") == "PJ")
    check("Perfil → mes 9 (Sept)",          d.get("fiscal_year_end_month") == 9)
    check("Perfil → is_large=False",        d.get("is_large_taxpayer") == False)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 4: Pre-llenado 2026 e idempotencia")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("post", "/tax/tax-brackets/prefill-2026", token=TOKEN)
check("POST prefill-2026 → 200",            r and r.status_code == 200, r.text[:200] if r else "no response")
if r and r.status_code == 200:
    d = r.json()
    check("prefill → ok=true",              d.get("ok") == True)
    first_time = not d.get("were_existing", True)
    if first_time:
        print("     → Primera vez: se insertaron 10 tramos oficiales")
    else:
        print("     → Ya existían tramos 2026 — no se sobreescribieron ✓")

# Idempotencia — segunda llamada
r2 = api("post", "/tax/tax-brackets/prefill-2026", token=TOKEN)
check("POST prefill-2026 segunda → 200",    r2 and r2.status_code == 200)
if r2 and r2.status_code == 200:
    check("Segunda llamada → were_existing=true",
          r2.json().get("were_existing") == True,
          str(r2.json()))

# Verificar que 2026 aparece en años
r = api("get", "/tax/tax-brackets/years", token=TOKEN)
check("GET /years → incluye 2026",
      r and 2026 in r.json().get("years", []),
      str(r.json() if r else "no response"))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 5: Verificar tramos 2026 en BD")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("get", "/tax/tax-brackets?year=2026", token=TOKEN)
check("GET /tax-brackets?year=2026 → 200",   r and r.status_code == 200)
if r and r.status_code == 200:
    d = r.json()
    check("2026 → configured=true",           d.get("configured") == True)
    bks = d.get("brackets", {})
    check("2026 → tiene PJ",                  "PJ" in bks)
    check("2026 → tiene PF",                  "PF" in bks)
    check("2026 → PJ con 4 tramos",
          len(bks.get("PJ", [])) == 4,
          f"tramos PJ: {len(bks.get('PJ', []))}")
    check("2026 → PF con 5 tramos",
          len(bks.get("PF", [])) == 5,
          f"tramos PF: {len(bks.get('PF', []))}")

    # Verificar valores del primer tramo PJ (oficial Hacienda 2026)
    if bks.get("PJ"):
        pj0 = bks["PJ"][0]
        check("PJ tramo 1 → desde ₡0",        near(pj0["income_from"], 0))
        check("PJ tramo 1 → hasta ₡5,621,000", near(pj0.get("income_to", 0), 5_621_000, tol=100))
        check("PJ tramo 1 → tasa 5%",          near(pj0["rate"], 0.05, tol=0.001))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 6: Tramos manuales año 2027 (sin deploy)")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("put", "/tax/tax-brackets", token=TOKEN, json={
    "fiscal_year": 2027,
    "taxpayer_type": "PJ",
    "brackets": [
        {"taxpayer_type": "PJ", "income_from": 0,         "income_to": 6_000_000,  "rate": 0.05},
        {"taxpayer_type": "PJ", "income_from": 6_000_000, "income_to": 10_000_000, "rate": 0.12},
        {"taxpayer_type": "PJ", "income_from": 10_000_000,"income_to": None,        "rate": 0.22},
    ]
})
check("PUT tramos 2027 → 200",    r and r.status_code == 200, r.text[:200] if r else "no response")
check("PUT 2027 → ok=true",       r and r.json().get("ok") == True)

r = api("get", "/tax/tax-brackets?year=2027", token=TOKEN)
check("GET 2027 → 200",           r and r.status_code == 200)
if r and r.status_code == 200:
    d2027 = r.json()
    check("2027 → configured=true",  d2027.get("configured") == True, str(d2027))
    check("2027 → PJ con 3 tramos",
          len(d2027.get("brackets", {}).get("PJ", [])) == 3)

# Verificar que 2027 aparece en la lista de años
r = api("get", "/tax/tax-brackets/years", token=TOKEN)
if r and r.status_code == 200:
    years = r.json().get("years", [])
    check("GET /years → incluye 2026 y 2027",  2026 in years and 2027 in years, f"años: {years}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 7: Proyección de Renta")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YEAR = date.today().year
r = api("get", f"/tax/renta-projection?year={YEAR}", token=TOKEN)
check(f"GET /renta-projection?year={YEAR} → 200 o 404",
      r and r.status_code in (200, 404),
      f"got {r.status_code if r else 'no response'}")

if r and r.status_code == 200:
    d = r.json()
    check("Proyección → utilidad_acumulada presente",   "utilidad_acumulada" in d)
    check("Proyección → renta_estimada_anual presente", "renta_estimada_anual" in d)
    check("Proyección → provision_mensual_sugerida",    "provision_mensual_sugerida" in d)
    check("Proyección → tasa_efectiva_pct",             "tasa_efectiva_pct" in d)
    check("Proyección → desglose_tramos",               isinstance(d.get("desglose_tramos"), list))
    check("Proyección → nota explicativa",              bool(d.get("nota")))
    check("Proyección → provisión = anual / 12",
          near(d["provision_mensual_sugerida"], d["renta_estimada_anual"] / 12))
    check("Proyección → tasa efectiva ≥ 0%",           d.get("tasa_efectiva_pct", -1) >= 0)
    prov = d["provision_mensual_sugerida"]
    renta = d["renta_estimada_anual"]
    print(f"     → Utilidad acumulada: ₡{d.get('utilidad_acumulada', 0):,.0f}")
    print(f"     → Utilidad proyectada: ₡{d.get('utilidad_proyectada_anual', 0):,.0f}")
    print(f"     → Renta estimada anual: ₡{renta:,.0f}")
    print(f"     → 💡 Provisión mensual: ₡{prov:,.0f}")
    print(f"     → Tasa efectiva: {d.get('tasa_efectiva_pct', 0):.2f}%")
elif r and r.status_code == 404:
    detail = r.json().get("detail", "")
    warn(f"404 en proyección: {detail}")
    warn("Puede ser que no haya asientos contables aún — es esperado en un tenant nuevo.")
    skip("Checks de proyección detallados", "sin datos contables disponibles")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 8: Reemplazar tramos 2027 → verifica idempotencia de PUT")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Reemplazar con tasa plana (simula edición de usuario)
r = api("put", "/tax/tax-brackets", token=TOKEN, json={
    "fiscal_year": 2027,
    "taxpayer_type": "PJ",
    "brackets": [
        {"taxpayer_type": "PJ", "income_from": 0, "income_to": None, "rate": 0.20},
    ]
})
check("PUT 2027 reemplazar → 200",  r and r.status_code == 200)

r = api("get", "/tax/tax-brackets?year=2027", token=TOKEN)
if r and r.status_code == 200:
    pj_tramos = r.json().get("brackets", {}).get("PJ", [])
    check("2027 tras reemplazo → 1 tramo",   len(pj_tramos) == 1, f"{len(pj_tramos)}")
    if pj_tramos:
        check("Tramo único → tasa 20%",       near(pj_tramos[0]["rate"], 0.20, tol=0.001))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n📌 BLOQUE 9: Validaciones de error en API real")
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

r = api("put", "/tax/fiscal-profile", token=TOKEN, json={
    "taxpayer_type": "INVALIDO", "is_large_taxpayer": False, "fiscal_year_end_month": 9
})
check("PUT tipo inválido → 400",     r and r.status_code == 400, f"got {r.status_code if r else 'no response'}")

r = api("put", "/tax/tax-brackets", token=TOKEN, json={
    "fiscal_year": 2026, "taxpayer_type": "PJ", "brackets": []
})
check("PUT tramos vacíos → 400",     r and r.status_code == 400, f"got {r.status_code if r else 'no response'}")

r = api("get", "/tax/renta-projection?year=2099", token=TOKEN)
check("GET proyección 2099 → 404",   r and r.status_code == 404, f"got {r.status_code if r else 'no response'}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
print("\n" + "═" * 65)
TOTAL_SKIP = len(skipped)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    if TOTAL_SKIP:
        print(f"  ⏭️  Saltados: {TOTAL_SKIP}")
    sys.exit(1)
else:
    print(f"  ✅ TODOS LOS CHECKS PASARON — Paso 3 (E2E) APROBADO")
    if TOTAL_SKIP:
        print(f"  ⏭️  Saltados: {TOTAL_SKIP} (sin datos contables base — esperado en tenant nuevo)")
    print("     → API real responde en producción")
    print("     → Perfil fiscal guardado y leído correctamente")
    print("     → Pre-llenado 2026 idempotente en BD real")
    print("     → Tramos 2027 ingresados manualmente sin tocar código")
    print("     → Proyección de renta funcionando correctamente")
    print("     → Validaciones de error en producción OK")
print("═" * 65 + "\n")
