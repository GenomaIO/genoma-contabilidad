#!/usr/bin/env python3
"""
sim_beneficiario_extractor_e2e.py — SIM + E2E  Fase 1
======================================================
Verifica que el extractor de beneficiario funciona correctamente
con 15 casos reales de descripciones bancarias BNCR/BCR/Davivienda.
"""
import sys, pathlib

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0; FAIL = 0

def check(condition, label):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition: PASS += 1
    else: FAIL += 1


# ── Importar módulo ───────────────────────────────────────────────────────────
print("\n[SIM-0] Importación del módulo")
try:
    from services.conciliacion.beneficiario_extractor import (
        extraer_beneficiario, CAT_BANK_FEE, CAT_BANK_INTEREST, CAT_SINPE, CAT_TERCERO
    )
    check(True, "beneficiario_extractor importado OK")
except Exception as ex:
    check(False, f"Import falló: {ex}")
    sys.exit(1)


# ── Casos de prueba reales ────────────────────────────────────────────────────
CASOS = [
    # (descripcion, telefono_raw, nombre_esperado_contains, categoria_esperada)
    ("01-02-26 MAXIMO MENDEZ VALERIO/CO...",    None,       "MAXIMO MENDEZ VALERIO",  CAT_TERCERO),
    ("31-01-26 JOSE ALEJANDRO CARVA/COM...",    "86876080", "JOSE ALEJANDRO CARVA",   CAT_TERCERO),
    ("31-01-26 ZUNIGA PEREZ EFREN/COMBUS...",   "88232093", "ZUNIGA PEREZ EFREN",     CAT_TERCERO),
    ("14-02-26 BNCR/AYUDA 88443928",            "88443928", "BANCO",                  CAT_BANK_FEE),
    ("14-02-26 BNCR/COMISION 86020644",         "86020644", "BANCO",                  CAT_BANK_FEE),
    ("31-01-26 BNCR/INTERESES GANADOS EN SU CUENTA DE AH", None, "BANCO",            CAT_BANK_INTEREST),
    ("12-02-26 SODA RUTA 35 ALAJUELA CRI",      None,       "SODA RUTA 35",           CAT_TERCERO),
    ("14-02-26 BNCR/COMISION 86020644",         None,       "BANCO",                  CAT_BANK_FEE),
    ("15-02-26 QUESADA RODRIGUEZ OMER/L...",    "60106802", "QUESADA RODRIGUEZ OMER", CAT_TERCERO),
    ("05-02-26 CIDEP CENTRO IBEROAMER./CIDEP REINT...", None, "CIDEP CENTRO IBEROAMER", CAT_TERCERO),
    ("09-02-26 JOSE PABLO ROMERO VILLEG/PAGO SOCI...", "88636618", "JOSE PABLO ROMERO VILLEG", CAT_TERCERO),
    ("11-02-26 MARCOS VINICIO JIMENEZ V/LOTO 61980...", "61980261", "MARCOS VINICIO JIMENEZ", CAT_TERCERO),
    ("SINPE MOVIL/TRANSFERENCIA 87654321",      "87654321", None,                     CAT_SINPE),
    ("BCR/MANEJO DE CUENTA",                    None,       "BANCO",                  CAT_BANK_FEE),
    ("DAVIVIENDA/COMISION ATM",                 None,       "BANCO",                  CAT_BANK_FEE),
]

print(f"\n[SIM-1] {len(CASOS)} casos de extracción")
for desc, tel, nombre_exp, cat_exp in CASOS:
    result = extraer_beneficiario(desc, tel)
    nombre_ok = (nombre_exp is None) or (nombre_exp.upper() in (result["nombre_norm"] or ""))
    cat_ok    = result["categoria"] == cat_exp
    check(nombre_ok and cat_ok,
          f"'{desc[:45]}...' → {result['nombre_norm']!r} [{result['categoria']}]")

# ── Verificar teléfono normal ─────────────────────────────────────────────────
print("\n[SIM-2] Normalización de teléfonos")
r = extraer_beneficiario("01-02-26 JUAN PEREZ/CO", "8867-4321")
check(r["telefono_norm"] == "88674321", f"Teléfono con guión normalizado: {r['telefono_norm']!r}")

r2 = extraer_beneficiario("01-02-26 MARIO SOTO/CO", None)
check(r2["telefono_norm"] is None, "Sin teléfono → None")

# ── Verificar migración en main.py ────────────────────────────────────────────
print("\n[SIM-3] Migración M_CENTINELA_V1 en main.py")
main_src = (ROOT / "services" / "gateway" / "main.py").read_text(encoding="utf-8")
check("M_CENTINELA_V1"               in main_src, "main.py contiene M_CENTINELA_V1")
check("beneficiario_nombre"          in main_src, "columna beneficiario_nombre en migración")
check("beneficiario_telefono_norm"   in main_src, "columna beneficiario_telefono_norm en migración")
check("beneficiario_categoria"       in main_src, "columna beneficiario_categoria en migración")
check("tiene_fe"                     in main_src, "columna tiene_fe en migración")
check("tarifa_iva"                   in main_src, "columna tarifa_iva en migración")

# ── Verificar integración en router ──────────────────────────────────────────
print("\n[SIM-4] Integración en bulk_insert_transactions")
router_src = (ROOT / "services" / "conciliacion" / "router.py").read_text(encoding="utf-8")
check("extraer_beneficiario"         in router_src, "router importa extraer_beneficiario")
check("beneficiario_nombre"          in router_src, "router inserta beneficiario_nombre")
check("beneficiario_categoria"       in router_src, "router inserta beneficiario_categoria")

# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F1 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
