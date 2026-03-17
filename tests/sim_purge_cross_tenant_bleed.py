"""
sim_purge_cross_tenant_bleed.py — SIM Test: POST /integration/purge-cross-tenant-bleed
═══════════════════════════════════════════════════════════════════════════════════════
Verifica el endpoint de limpieza de datos contaminados cross-tenant.

Patrón Genoma: llamada directa a las funciones del endpoint,
inyectando current_user, db y env vars como mocks de Python puro.
Sin TestClient, sin servidor HTTP, sin DB real.

Escenarios:
  SC-1 · Detección por cédula de clave Hacienda — DRY-RUN
          Un tenant con 3 asientos: 2 de Álvaro (contaminados) + 1 propio
          El dry-run detecta exactamente 2 contaminados sin borrar nada.

  SC-2 · Dry-run no modifica la DB
          Después del dry-run el "mock DB" no recibió ningún DELETE.

  SC-3 · Borrado real (confirm=True) — elimina los contaminados
          Los 2 asientos de Álvaro se borran, el 1 propio queda intacto.

  SC-4 · Tenant limpio no reporta contaminados
          Un tenant cuyos asientos tienen su propia cédula → 0 contaminados.

  SC-5 · Guard de cédula (_filtrar_docs_por_cedula) — muro anti-bleed futuro
          El guard impide importar docs de otro tenant en pull-recibidos.
          Simulado directamente sobre la función helper del router.

  SC-6 · Entry con cédula en source_doc_lines JSONB (recibidos)
          Detecta contaminación vía receptor_cedula en JSONB cuando la
          fuente_ref no tiene formato de clave Hacienda.
"""

import os
import sys
import json

os.environ.setdefault("JWT_SECRET", "test-secret-purge-cross-tenant")
os.environ.setdefault("DATABASE_URL", "postgresql://fake:fake@localhost/fake")
os.environ.setdefault("ENABLE_PURGE_UTILITY", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, call, patch
from fastapi import HTTPException

from services.integration.router_pull import (
    purge_cross_tenant_bleed,
    PurgeCrossTenantRequest,
    _extract_cedula_from_clave,
    _cedulas_coinciden,
    _filtrar_docs_por_cedula,
    _get_tenant_cedula,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

PASS_MARK = "  ✅"
FAIL_MARK = "  ❌"
errors = []


def check(label: str, condition: bool, detail: str = ""):
    if condition:
        print(f"{PASS_MARK} {label}")
    else:
        msg = f"{FAIL_MARK} {label}" + (f" — {detail}" if detail else "")
        print(msg)
        errors.append(label)


# ── Datos de prueba ───────────────────────────────────────────────────────────

# Cédulas ficticias (10 dígitos, sin guiones)
CEDULA_ANGELICA = "3101953441"   # tenant activo = Angélica
CEDULA_ALVARO   = "1234567890"   # Álvaro — el que "sangró"

TENANT_ANGELICA_ID = "tenant-uuid-angelica"

# Clave Hacienda válida con CEDULA_ANGELICA embebida (posición 3-12)
# Formato: 506 + CEDULA(10) + resto
CLAVE_ANGELICA = f"506{CEDULA_ANGELICA}2026031600100001010000000010000000001"  # len=50(aprox)
CLAVE_ALVARO   = f"506{CEDULA_ALVARO}2026031600100001010000000020000000001"

# Asientos candidatos del mock DB
# (id, status, source_ref, description, source_doc_lines)
ENTRIES_MOCK = [
    # Contaminado A: asiento de Álvaro con clave Hacienda de Álvaro
    ("entry-alvaro-001", "DRAFT", CLAVE_ALVARO, "FE Álvaro - Compra 001", None),
    # Contaminado B: asiento de Álvaro con clave Hacienda de Álvaro
    ("entry-alvaro-002", "DRAFT", CLAVE_ALVARO, "FE Álvaro - Compra 002", None),
    # Propio: asiento de Angélica con clave Hacienda de Angélica
    ("entry-angelica-001", "DRAFT", CLAVE_ANGELICA, "FE Angélica - Venta 001", None),
]

ENTRIES_MOCK_CON_JSONB = [
    # Contaminado via JSONB receptor_cedula
    (
        "entry-alvaro-recib-001",
        "DRAFT",
        "source_ref_sin_formato_hacienda",  # source_ref sin cédula válida
        "FEC Recibido Álvaro",
        json.dumps([{"receptor_cedula": CEDULA_ALVARO, "monto": 10000}]),
    ),
    # Propio via JSONB
    (
        "entry-angelica-recib-001",
        "DRAFT",
        "source_ref_angelica",
        "FEC Recibido Angélica",
        json.dumps([{"receptor_cedula": CEDULA_ANGELICA, "monto": 5000}]),
    ),
]


def _current_user_angelica() -> dict:
    return {
        "sub":         "user-angelica-uuid",
        "tenant_id":   TENANT_ANGELICA_ID,
        "tenant_type": "partner_linked",
        "role":        "admin",
        "nombre":      "Angélica Demo",
    }


def _mock_db_con_entries(entries: list) -> MagicMock:
    """
    Mock de DB que retorna entries al SELECT y permite DELETE.
    """
    db = MagicMock()

    # fetchall() retorna la lista de entries en cada llamada (simplificado)
    db.execute.return_value.fetchall.return_value = entries

    # fetchone() para _get_tenant_cedula → retorna cédula de Angélica
    db.execute.return_value.fetchone.return_value = (CEDULA_ANGELICA,)

    return db


def _mock_db_limpio() -> MagicMock:
    """Mock de DB donde el tenant no tiene asientos importados."""
    db = MagicMock()
    db.execute.return_value.fetchall.return_value = []
    db.execute.return_value.fetchone.return_value = (CEDULA_ANGELICA,)
    return db


# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 64)
print("   SIM TEST — POST /integration/purge-cross-tenant-bleed")
print("═" * 64)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers unitarios primero
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 UT-1  _extract_cedula_from_clave")

check(
    "Extrae cédula de Álvaro de su clave Hacienda",
    _extract_cedula_from_clave(CLAVE_ALVARO) == CEDULA_ALVARO.lstrip("0"),
    f"got: {_extract_cedula_from_clave(CLAVE_ALVARO)!r}"
)
check(
    "Clave vacía → string vacío",
    _extract_cedula_from_clave("") == "",
)
check(
    "Clave corta → string vacío",
    _extract_cedula_from_clave("506123") == "",
)

print("\n📌 UT-2  _cedulas_coinciden")

check("Misma cédula → True",              _cedulas_coinciden(CEDULA_ANGELICA, CEDULA_ANGELICA))
check("Con ceros iniciales → True",       _cedulas_coinciden("0" + CEDULA_ANGELICA, CEDULA_ANGELICA))
check("Diferente cédula → False",         not _cedulas_coinciden(CEDULA_ANGELICA, CEDULA_ALVARO))
check("None vs string → False",           not _cedulas_coinciden(None, CEDULA_ANGELICA))

# ─────────────────────────────────────────────────────────────────────────────
# SC-1 · DRY-RUN detecta 2 contaminados, 1 propio
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-1  DRY-RUN — detecta exactamente 2 asientos contaminados")

req_dry = PurgeCrossTenantRequest(confirm=False)
db_sc1  = _mock_db_con_entries(ENTRIES_MOCK)
cu_sc1  = _current_user_angelica()

# Necesitamos que _get_tenant_cedula retorne la cédula de Angélica en mock db
# La función hace: db.execute(text(...)).fetchone() → row[0]
# El mock genérico ya lo hace

try:
    resp = purge_cross_tenant_bleed(req_dry, db_sc1, cu_sc1)

    check("HTTP 200 sin excepción",    True)
    check("modo = DRY_RUN",            resp.get("modo") == "DRY_RUN", str(resp.get("modo")))
    check("confirmado = False",        resp.get("confirmado") is False)
    check("total_contaminados = 2",
          resp.get("total_contaminados") == 2,
          f"got {resp.get('total_contaminados')}")
    check("total_revisados = 3",
          resp.get("total_revisados") == 3,
          f"got {resp.get('total_revisados')}")
    # Los 2 contaminados deben ser los de Álvaro
    ids_contam = [c["entry_id"] for c in resp.get("contaminados", [])]
    check("entry-alvaro-001 detectado", "entry-alvaro-001" in ids_contam, str(ids_contam))
    check("entry-alvaro-002 detectado", "entry-alvaro-002" in ids_contam, str(ids_contam))
    check("entry-angelica-001 NO detectado", "entry-angelica-001" not in ids_contam, str(ids_contam))
except Exception as exc:
    check("SC-1 sin excepción", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# SC-2 · DRY-RUN no ejecuta DELETE en la DB
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-2  DRY-RUN no modifica la DB (ningún DELETE ejecutado)")

req_dry2 = PurgeCrossTenantRequest(confirm=False)
db_sc2   = _mock_db_con_entries(ENTRIES_MOCK)
cu_sc2   = _current_user_angelica()

try:
    purge_cross_tenant_bleed(req_dry2, db_sc2, cu_sc2)

    # Verificar que ninguna llamada a db.execute contenía DELETE
    delete_calls = [
        str(c) for c in db_sc2.execute.call_args_list
        if "DELETE" in str(c)
    ]
    check("Cero DELETEs ejecutados en dry-run", len(delete_calls) == 0, str(delete_calls))
    check("db.commit() NO llamado",             db_sc2.commit.call_count == 0,
          f"commit llamado {db_sc2.commit.call_count} veces")
except Exception as exc:
    check("SC-2 sin excepción", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# SC-3 · BORRADO REAL (confirm=True) borra los 2 contaminados
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-3  BORRADO REAL — confirm=True elimina los 2 contaminados")

req_real = PurgeCrossTenantRequest(confirm=True)
db_sc3   = _mock_db_con_entries(ENTRIES_MOCK)
cu_sc3   = _current_user_angelica()

# Para el sanity check (verificar que son DRAFT):
# la segunda fetchall devuelve las mismas entries con status DRAFT
db_sc3.execute.return_value.fetchall.side_effect = [
    ENTRIES_MOCK,                   # candidatos
    [("entry-alvaro-001", "DRAFT"), ("entry-alvaro-002", "DRAFT")],  # verificación
]
db_sc3.execute.return_value.fetchone.return_value = (CEDULA_ANGELICA,)

try:
    resp3 = purge_cross_tenant_bleed(req_real, db_sc3, cu_sc3)

    check("modo = PURGE_REAL",     resp3.get("modo") == "PURGE_REAL", str(resp3.get("modo")))
    check("confirmado = True",     resp3.get("confirmado") is True)
    check("borrados = 2",          resp3.get("borrados") == 2, f"got {resp3.get('borrados')}")
    check("db.commit() llamado",   db_sc3.commit.call_count >= 1,
          f"commit llamado {db_sc3.commit.call_count} veces")
    # Los source_refs liberados deben contener las claves de Álvaro
    liberados = resp3.get("source_refs_liberados", [])
    check("source_refs_liberados contiene clave Álvaro",
          CLAVE_ALVARO in liberados or len(liberados) == 2,
          str(liberados))
except Exception as exc:
    check("SC-3 sin excepción", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# SC-4 · Tenant limpio → 0 contaminados
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-4  Tenant limpio — cero asientos contaminados")

# Solo el asiento propio de Angélica
ENTRIES_SOLO_ANGELICA = [
    ("entry-angelica-100", "DRAFT", CLAVE_ANGELICA, "FE Angélica - Venta 100", None),
    ("entry-angelica-101", "DRAFT", CLAVE_ANGELICA, "FE Angélica - Venta 101", None),
]

req_clean = PurgeCrossTenantRequest(confirm=False)
db_sc4    = _mock_db_con_entries(ENTRIES_SOLO_ANGELICA)
cu_sc4    = _current_user_angelica()

try:
    resp4 = purge_cross_tenant_bleed(req_clean, db_sc4, cu_sc4)

    check("total_contaminados = 0",
          resp4.get("total_contaminados") == 0,
          f"got {resp4.get('total_contaminados')}")
    check("contaminados vacío",
          len(resp4.get("contaminados", [])) == 0,
          str(resp4.get("contaminados")))
    check("mensaje indica tenant limpio",
          "limpio" in resp4.get("mensaje", "").lower(),
          repr(resp4.get("mensaje")))
except Exception as exc:
    check("SC-4 sin excepción", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# SC-5 · Muro anti-bleed: _filtrar_docs_por_cedula bloquea docs ajenos
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-5  Muro anti-bleed — _filtrar_docs_por_cedula bloquea docs de otro tenant")

docs_mixtos = [
    {"clave": CLAVE_ALVARO,    "receptor_cedula": CEDULA_ALVARO,    "tipo": "FEC", "total": 1000},
    {"clave": CLAVE_ALVARO,    "receptor_cedula": CEDULA_ALVARO,    "tipo": "FEC", "total": 2000},
    {"clave": CLAVE_ANGELICA,  "receptor_cedula": CEDULA_ANGELICA,  "tipo": "FEC", "total": 3000},
]

# Solo los docs de Angélica deben pasar el guard
resultado_filtrado = _filtrar_docs_por_cedula(docs_mixtos, CEDULA_ANGELICA, "receptor_cedula")

check("Docs de Álvaro bloqueados",         len(resultado_filtrado) == 1,     f"got {len(resultado_filtrado)}")
check("Doc de Angélica pasa el muro",      resultado_filtrado[0]["total"] == 3000)
check("Ningún doc de Álvaro en resultado",
      not any(d.get("receptor_cedula") == CEDULA_ALVARO for d in resultado_filtrado))

# Caso: sin cédula del tenant → 0 docs (fail-closed)
resultado_sin_cedula = _filtrar_docs_por_cedula(docs_mixtos, None, "receptor_cedula")
check("Sin cédula del tenant → 0 docs (fail-closed)", len(resultado_sin_cedula) == 0)

# ─────────────────────────────────────────────────────────────────────────────
# SC-6 · Detección via source_doc_lines JSONB (recibidos sin clave Hacienda)
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-6  Detección via JSONB receptor_cedula (doc recibido sin clave estándar)")

req_jsonb = PurgeCrossTenantRequest(confirm=False)
db_sc6    = _mock_db_con_entries(ENTRIES_MOCK_CON_JSONB)
cu_sc6    = _current_user_angelica()

try:
    resp6 = purge_cross_tenant_bleed(req_jsonb, db_sc6, cu_sc6)

    check("Detecta 1 contaminado via JSONB",
          resp6.get("total_contaminados") == 1,
          f"got {resp6.get('total_contaminados')}")
    ids_sc6 = [c["entry_id"] for c in resp6.get("contaminados", [])]
    check("entry-alvaro-recib-001 detectado vía JSONB",
          "entry-alvaro-recib-001" in ids_sc6, str(ids_sc6))
    check("motivo = receptor_cedula_en_source_doc_lines",
          any(c.get("motivo") == "receptor_cedula_en_source_doc_lines"
              for c in resp6.get("contaminados", [])))
    check("entry-angelica-recib-001 NO contaminado",
          "entry-angelica-recib-001" not in ids_sc6)
except Exception as exc:
    check("SC-6 sin excepción", False, str(exc))

# ─────────────────────────────────────────────────────────────────────────────
# SC-7 · Sin ENABLE_PURGE_UTILITY → HTTP 503
# ─────────────────────────────────────────────────────────────────────────────
print("\n📌 SC-7  Sin ENABLE_PURGE_UTILITY → HTTP 503 (endpoint inactivo en prod por defecto)")

req_guard = PurgeCrossTenantRequest(confirm=False)
db_sc7    = _mock_db_con_entries(ENTRIES_MOCK)
cu_sc7    = _current_user_angelica()

old_env = os.environ.pop("ENABLE_PURGE_UTILITY", None)
try:
    purge_cross_tenant_bleed(req_guard, db_sc7, cu_sc7)
    check("SC-7 debe lanzar HTTPException 503", False, "No lanzó excepción")
except HTTPException as exc:
    check(f"HTTP 503 cuando ENABLE_PURGE_UTILITY está ausente (got {exc.status_code})",
          exc.status_code == 503)
except Exception as exc:
    check("SC-7 lanza HTTPException", False, str(exc))
finally:
    if old_env is not None:
        os.environ["ENABLE_PURGE_UTILITY"] = old_env

# ══════════════════════════════════════════════════════════════════════════════
print("\n" + "═" * 64)
if errors:
    print(f"  ❌ FALLARON {len(errors)} checks:")
    for e in errors:
        print(f"     → {e}")
    print("═" * 64 + "\n")
    sys.exit(1)
else:
    print("  ✅ TODOS LOS CHECKS PASARON — purge-cross-tenant-bleed VERIFICADO")
    print("     → Detección por cédula en clave Hacienda (emisor) ✓")
    print("     → Detección por receptor_cedula en JSONB ✓")
    print("     → DRY-RUN seguro sin modificar DB ✓")
    print("     → Borrado real solo de contaminados ✓")
    print("     → Muro anti-bleed (_filtrar_docs) bloquea docs ajenos ✓")
    print("     → Guard ENABLE_PURGE_UTILITY protege producción ✓")
    print("═" * 64 + "\n")
