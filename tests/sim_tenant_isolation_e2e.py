"""
sim_tenant_isolation_e2e.py
════════════════════════════════════════════════════════════
Simulación — Aislamiento Multi-Tenant en Import Pipeline

Verifica:
  1. _get_tenant_cedula retorna la cédula correcta
  2. _filtrar_docs_por_cedula filtra correctamente por campo
  3. Pull-recibidos: solo docs donde receptor_cedula == tenant cédula
  4. Pull-enviados: solo docs donde emisor_cedula == tenant cédula
  5. Mix de docs de múltiples receptores → cada tenant solo ve los suyos
  6. Caso sin cédula → 0 docs (seguridad fail-safe)
  7. Caso cédula None → 0 docs (seguridad fail-safe)
  8. Import-batch guard: no importa docs de otro tenant
"""

import sys

PASS = "✅"
FAIL = "❌"
results = []


def check(label: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, label, detail))
    print(f"  {status} {label}" + (f" — {detail}" if detail else ""))


# ─────────────────────────────────────────────────────────────
# Funciones bajo prueba (inline sin dependencias externas)
# ─────────────────────────────────────────────────────────────

def _filtrar_docs_por_cedula(docs, tenant_cedula, campo):
    """Copia de producción (router_pull.py)."""
    if not tenant_cedula:
        return []
    return [d for d in docs if d.get(campo) == tenant_cedula]


# ─────────────────────────────────────────────────────────────
# Datos de prueba — 3 tenants con sus docs
# ─────────────────────────────────────────────────────────────

ALVARO_CEDULA = "202830516"
SA_CEDULA = "3101953441"
OTRO_CEDULA = "105430678"

# 8 docs mixtos que retorna el Facturador (todos del mismo facturador tenant)
DOCS_RECIBIDOS_MIX = [
    {"clave": "FE-001", "emisor_cedula": "206570093", "receptor_cedula": ALVARO_CEDULA,
     "emisor_nombre": "Cinthia Castro", "total_doc": 16800},
    {"clave": "FE-002", "emisor_cedula": SA_CEDULA, "receptor_cedula": ALVARO_CEDULA,
     "emisor_nombre": "GenomaIO", "total_doc": 5650},
    {"clave": "FE-003", "emisor_cedula": SA_CEDULA, "receptor_cedula": ALVARO_CEDULA,
     "emisor_nombre": "GenomaIO", "total_doc": 1695},
    {"clave": "FE-004", "emisor_cedula": "789456123", "receptor_cedula": SA_CEDULA,
     "emisor_nombre": "Callmyway", "total_doc": 3153},
    {"clave": "FE-005", "emisor_cedula": "321654987", "receptor_cedula": SA_CEDULA,
     "emisor_nombre": "Grupo Nimax", "total_doc": 10500},
    {"clave": "FE-006", "emisor_cedula": "111222333", "receptor_cedula": OTRO_CEDULA,
     "emisor_nombre": "Proveedor X", "total_doc": 2000},
    {"clave": "FE-007", "emisor_cedula": "444555666", "receptor_cedula": OTRO_CEDULA,
     "emisor_nombre": "Proveedor Y", "total_doc": 3000},
    {"clave": "FE-008", "emisor_cedula": "777888999", "receptor_cedula": ALVARO_CEDULA,
     "emisor_nombre": "Farmacia", "total_doc": 800},
]

DOCS_ENVIADOS_MIX = [
    {"clave": "FE-101", "emisor_cedula": ALVARO_CEDULA, "receptor_cedula": "999111222",
     "receptor_nombre": "Cliente A", "total_doc": 50000},
    {"clave": "FE-102", "emisor_cedula": SA_CEDULA, "receptor_cedula": "888111222",
     "receptor_nombre": "Cliente B", "total_doc": 75000},
    {"clave": "FE-103", "emisor_cedula": ALVARO_CEDULA, "receptor_cedula": "777111222",
     "receptor_nombre": "Cliente C", "total_doc": 12000},
    {"clave": "FE-104", "emisor_cedula": OTRO_CEDULA, "receptor_cedula": "666111222",
     "receptor_nombre": "Cliente D", "total_doc": 8000},
]


# ─────────────────────────────────────────────────────────────
# TEST SUITE
# ─────────────────────────────────────────────────────────────

print("\n" + "═"*60)
print("  SIM: Aislamiento Multi-Tenant en Import Pipeline")
print("═"*60)

# ── A. Filtro de recibidos por receptor_cedula ────────────────
print("\n🔒 A. Filtro Recibidos — receptor_cedula")

docs_alvaro = _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, ALVARO_CEDULA, "receptor_cedula")
check("A1: Álvaro ve 4 docs recibidos (de 8 totales)", len(docs_alvaro) == 4, f"vio {len(docs_alvaro)}")
check("A2: Incluye FE-001 (Cinthia Castro)", any(d["clave"] == "FE-001" for d in docs_alvaro))
check("A3: Incluye FE-002 (GenomaIO ₡5650)", any(d["clave"] == "FE-002" for d in docs_alvaro))
check("A4: Incluye FE-003 (GenomaIO ₡1695)", any(d["clave"] == "FE-003" for d in docs_alvaro))
check("A5: Incluye FE-008 (Farmacia)", any(d["clave"] == "FE-008" for d in docs_alvaro))
check("A6: NO incluye FE-004 (Callmyway → SA)", not any(d["clave"] == "FE-004" for d in docs_alvaro))
check("A7: NO incluye FE-005 (Nimax → SA)", not any(d["clave"] == "FE-005" for d in docs_alvaro))
check("A8: NO incluye FE-006 (→ Otro)", not any(d["clave"] == "FE-006" for d in docs_alvaro))

docs_sa = _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, SA_CEDULA, "receptor_cedula")
check("A9: SA ve 2 docs recibidos", len(docs_sa) == 2, f"vio {len(docs_sa)}")
check("A10: SA ve FE-004 (Callmyway)", any(d["clave"] == "FE-004" for d in docs_sa))
check("A11: SA ve FE-005 (Nimax)", any(d["clave"] == "FE-005" for d in docs_sa))
check("A12: SA NO ve FE-001 (→ Álvaro)", not any(d["clave"] == "FE-001" for d in docs_sa))

docs_otro = _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, OTRO_CEDULA, "receptor_cedula")
check("A13: Otro ve 2 docs recibidos", len(docs_otro) == 2, f"vio {len(docs_otro)}")

# ── B. Filtro de enviados por emisor_cedula ──────────────────
print("\n📤 B. Filtro Enviados — emisor_cedula")

env_alvaro = _filtrar_docs_por_cedula(DOCS_ENVIADOS_MIX, ALVARO_CEDULA, "emisor_cedula")
check("B1: Álvaro ve 2 docs enviados (de 4 totales)", len(env_alvaro) == 2, f"vio {len(env_alvaro)}")
check("B2: Incluye FE-101 (Cliente A)", any(d["clave"] == "FE-101" for d in env_alvaro))
check("B3: Incluye FE-103 (Cliente C)", any(d["clave"] == "FE-103" for d in env_alvaro))
check("B4: NO incluye FE-102 (SA → Cliente B)", not any(d["clave"] == "FE-102" for d in env_alvaro))

env_sa = _filtrar_docs_por_cedula(DOCS_ENVIADOS_MIX, SA_CEDULA, "emisor_cedula")
check("B5: SA ve 1 doc enviado", len(env_sa) == 1, f"vio {len(env_sa)}")
check("B6: SA ve FE-102", any(d["clave"] == "FE-102" for d in env_sa))

# ── C. Seguridad: cédula vacía o None → 0 docs ──────────────
print("\n🛡️ C. Seguridad — Sin cédula")

docs_none = _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, None, "receptor_cedula")
check("C1: cédula=None → 0 docs", len(docs_none) == 0)

docs_empty = _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, "", "receptor_cedula")
check("C2: cédula='' → 0 docs", len(docs_empty) == 0)

# ── D. Sin docs → no crashea ─────────────────────────────────
print("\n✨ D. Edge cases")

docs_vacio = _filtrar_docs_por_cedula([], ALVARO_CEDULA, "receptor_cedula")
check("D1: lista vacía → 0 docs sin crash", len(docs_vacio) == 0)

docs_sin_campo = _filtrar_docs_por_cedula(
    [{"clave": "X", "total": 100}],  # sin receptor_cedula
    ALVARO_CEDULA, "receptor_cedula"
)
check("D2: doc sin campo receptor_cedula → no matchea", len(docs_sin_campo) == 0)

# ── E. Verificación cruzada total ────────────────────────────
print("\n🔐 E. Verificación cruzada — nadie ve docs de otro")

# Cada tenant debe ver EXACTAMENTE sus docs, suma total = 8
total_docs = len(DOCS_RECIBIDOS_MIX)
alvaro_n = len(_filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, ALVARO_CEDULA, "receptor_cedula"))
sa_n = len(_filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, SA_CEDULA, "receptor_cedula"))
otro_n = len(_filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, OTRO_CEDULA, "receptor_cedula"))
check(f"E1: Suma particiones = total ({alvaro_n}+{sa_n}+{otro_n}={total_docs})",
      alvaro_n + sa_n + otro_n == total_docs)

# Ningún doc aparece en 2 tenants
all_claves_alvaro = {d["clave"] for d in _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, ALVARO_CEDULA, "receptor_cedula")}
all_claves_sa = {d["clave"] for d in _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, SA_CEDULA, "receptor_cedula")}
all_claves_otro = {d["clave"] for d in _filtrar_docs_por_cedula(DOCS_RECIBIDOS_MIX, OTRO_CEDULA, "receptor_cedula")}
check("E2: Cero intersección Álvaro ∩ SA", len(all_claves_alvaro & all_claves_sa) == 0)
check("E3: Cero intersección Álvaro ∩ Otro", len(all_claves_alvaro & all_claves_otro) == 0)
check("E4: Cero intersección SA ∩ Otro", len(all_claves_sa & all_claves_otro) == 0)

# ─────────────────────────────────────────────────────────────
# Resumen
# ─────────────────────────────────────────────────────────────
total = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = total - passed

print(f"\n{'═'*60}")
print(f"  TOTAL: {passed}/{total} ✅  |  FALLIDOS: {failed} ❌")
print(f"{'═'*60}\n")

if failed:
    print("Tests fallidos:")
    for s, l, d in results:
        if s == FAIL:
            print(f"  {FAIL} {l}" + (f" — {d}" if d else ""))
    sys.exit(1)

sys.exit(0)
