"""
SIM-PURGE — purge-bad-drafts + re-importacion de FE Recibidas
═══════════════════════════════════════════════════════════════════
Simula el flujo completo:

  PURGE-01: Detecta DRAFTs con 4xxx importados como recibidos
  PURGE-02: confirm=False retorna error sin borrar nada
  PURGE-03: confirm=True borra los DRAFTs malos
  PURGE-04: source_refs quedan liberados
  PURGE-05: DRAFTs POSTED no son tocados (guard)
  PURGE-06: Sin candidatos → retorna mensaje claro
  PURGE-07: Re-importacion con logica corregida genera 5xxx (Gasto), no 4xxx
  PURGE-08: Re-importacion genera CxP (2101), no CxC (1102)
  PURGE-09: Re-importacion genera IVA Credito, no IVA Debito
  PURGE-10: ICE Telecomunicaciones (cond en doc) -> asiento correcto
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.integration.journal_mapper_v2 import _build_entry_lines_from_doc

PASS = 0; FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond: print(f"  PASS: {label}"); PASS += 1
    else:    print(f"  FAIL: {label}"); FAIL += 1

print("=" * 65)
print("SIM-PURGE — purge-bad-drafts + re-importacion FE Recibidas")
print("=" * 65)

# ─── Simular base de datos en memoria ─────────────────────────────
class MockEntry:
    def __init__(self, eid, status, source_ref, source, lines):
        self.id         = eid
        self.status     = status
        self.source_ref = source_ref
        self.source     = source
        self.lines      = lines   # list de dicts con account_code

class MockDB:
    def __init__(self, entries):
        self.entries      = entries   # list[MockEntry]
        self.deleted_ids  = []

    def is_imported(self, source_ref):
        return any(e.source_ref == source_ref for e in self.entries
                   if e.id not in self.deleted_ids)

def _auto_detect_bad(db):
    """Simula la query de purge: DRAFT con linea 4xxx + source HACIENDA_PULL."""
    return [
        e for e in db.entries
        if e.id not in db.deleted_ids
        and e.status == "DRAFT"
        and e.source in ("HACIENDA_PULL", "hacienda_pull", "AUTO")
        and any(l["account_code"].startswith("4") for l in e.lines)
    ]

def _purge(db, entry_ids=None, confirm=False):
    """Simula el endpoint purge-bad-drafts."""
    if not confirm:
        return {"error": "confirm=True requerido"}

    candidates = (
        [e for e in db.entries if e.id in entry_ids]
        if entry_ids
        else _auto_detect_bad(db)
    )
    if not candidates:
        return {"ok": True, "borrados": 0, "liberados": [], "mensaje": "Sin candidatos"}

    bad = [e for e in candidates if e.status != "DRAFT"]
    if bad:
        return {"error": f"POSTED encontrado: {[e.id for e in bad]}"}

    liberados = []
    for e in candidates:
        db.deleted_ids.append(e.id)
        if e.source_ref:
            liberados.append(e.source_ref)

    return {"ok": True, "borrados": len(candidates), "liberados": liberados}

# ── DATOS DE PRUEBA ────────────────────────────────────────────────
BAD_ENTRY_1 = MockEntry(
    "e-bad-001", "DRAFT", "FE-CINTHIA-001", "HACIENDA_PULL",
    [{"account_code": "1102"}, {"account_code": "4101"}, {"account_code": "2102"}]
)
BAD_ENTRY_2 = MockEntry(
    "e-bad-002", "DRAFT", "FE-SA-001", "HACIENDA_PULL",
    [{"account_code": "1102"}, {"account_code": "4101"}, {"account_code": "2102"}]
)
GOOD_POSTED = MockEntry(
    "e-good-001", "POSTED", "FE-OK-001", "MANUAL",
    [{"account_code": "5101"}, {"account_code": "2101"}]
)

db = MockDB([BAD_ENTRY_1, BAD_ENTRY_2, GOOD_POSTED])

# ─── PURGE-01: Detecta DRAFTs con 4xxx ────────────────────────────
print("\nPURGE-01: Auto-deteccion de DRAFTs malos (4xxx)")
bad = _auto_detect_bad(db)
check("Detecta 2 candidatos malos", len(bad) == 2)
check("No incluye el POSTED", all(e.id != "e-good-001" for e in bad))

# ─── PURGE-02: confirm=False → error sin borrar ───────────────────
print("\nPURGE-02: confirm=False -> error sin borrar nada")
res = _purge(db, confirm=False)
check("Retorna error", "error" in res)
check("No borro nada", len(db.deleted_ids) == 0)

# ─── PURGE-03: confirm=True → borra los malos ────────────────────
print("\nPURGE-03: confirm=True -> borra DRAFTs malos")
res = _purge(db, confirm=True)
check("ok=True", res.get("ok") is True)
check("Borrados = 2", res["borrados"] == 2)

# ─── PURGE-04: source_refs liberados ─────────────────────────────
print("\nPURGE-04: source_refs quedan liberados")
check("FE-CINTHIA-001 liberado", "FE-CINTHIA-001" in res["liberados"])
check("FE-SA-001 liberado",      "FE-SA-001"      in res["liberados"])
check("e-bad-001 ya no existe",  not db.is_imported("FE-CINTHIA-001"))
check("e-bad-002 ya no existe",  not db.is_imported("FE-SA-001"))

# ─── PURGE-05: POSTED protegido ───────────────────────────────────
print("\nPURGE-05: POSTED no es tocado")
db2 = MockDB([GOOD_POSTED])
res2 = _purge(db2, entry_ids=["e-good-001"], confirm=True)
check("Retorna error POSTED", "error" in res2)
check("POSTED sigue en DB", db2.is_imported("FE-OK-001"))

# ─── PURGE-06: Sin candidatos ─────────────────────────────────────
print("\nPURGE-06: Sin candidatos -> mensaje claro")
db3 = MockDB([])
res3 = _purge(db3, confirm=True)
check("borrados = 0", res3["borrados"] == 0)
check("liberados vacio", res3["liberados"] == [])

# ─── PURGE-07/08/09: Re-importacion correcta de FE Recibidas ──────
print("\nPURGE-07/08/09: Re-importacion con logica corregida")

def make_doc_recibido(clave, emisor, total, iva, condicion="02"):
    return {
        "tipo_doc":        "01",
        "condicion_venta": condicion,
        "_es_recibido":    True,
        "total_doc":       total,
        "receptor_nombre": "PROVEEDOR SA",
        "fecha_doc":       "2026-03-01",
        "clave":           clave,
        "lineas": [{
            "descripcion":   "Servicio",
            "monto_total":   total - iva,
            "tarifa_codigo": "08",
            "monto_iva":     iva,
        }],
    }

# Cinthia Castro (¢16,800 total, ¢1,932.74 IVA aprox)
doc_cinthia = make_doc_recibido("FE-CINTHIA-001", "CINTHIA CASTRO", 16800, 1800.0)
entry_c = _build_entry_lines_from_doc(doc_cinthia, "tenant_X", "e-c-001", {})

dr = round(sum(l["debit"]  for l in entry_c), 2)
cr = round(sum(l["credit"] for l in entry_c), 2)

check("PURGE-07: Gasto en 5xxx (no 4xxx)",
      any(l["account_code"].startswith("5") for l in entry_c))
check("PURGE-07: SIN cuenta 4xxx (no ingreso)",
      not any(l["account_code"].startswith("4") for l in entry_c))
check("PURGE-08: CxP en 2101 (no CxC 1102)",
      any(l["account_code"] == "2101" for l in entry_c))
check("PURGE-08: SIN CxC 1102",
      not any(l["account_code"] == "1102" for l in entry_c))
check("PURGE-09: Asiento balanceado", abs(dr - cr) < 0.02)

# IVA en recibidos: va a cuenta 1105 (IVA Credito/Acreditable) — no 2102
iva_lines = [l for l in entry_c if "IVA" in (l.get("account_role",""))]
check("PURGE-09: IVA en cuenta activo (credito fiscal — NO 2102)",
      all(l["account_code"] != "2102" for l in iva_lines))

# ─── PURGE-10: ICE Telecomunicaciones ────────────────────────────
print("\nPURGE-10: ICE Telecomunicaciones - FE Recibida ¢25,290,533 + IVA ¢2,883,354")
doc_ice = {
    "tipo_doc":        "01",
    "condicion_venta": "01",   # contado (pago immediato)
    "_es_recibido":    True,
    "total_doc":       25_290_533 + 2_883_354,
    "receptor_nombre": "CLIENTE",
    "fecha_doc":       "2026-02-27",
    "clave":           "1000000004000042139...",
    "lineas": [{
        "descripcion":   "COSTO POR DISPONIBILIDAD DE LA RED",
        "monto_total":   25_290_533.0,
        "tarifa_codigo": "08",
        "monto_iva":     2_883_354.0,
    }],
}
entry_ice = _build_entry_lines_from_doc(doc_ice, "tenant_X", "e-ice-001", {})
dr_i = round(sum(l["debit"]  for l in entry_ice), 2)
cr_i = round(sum(l["credit"] for l in entry_ice), 2)

check("PURGE-10: Gasto ICE en 5xxx",
      any(l["account_code"].startswith("5") for l in entry_ice))
check("PURGE-10: Banco en 1101 (contado cond=01)",
      any(l["account_code"] == "1101" for l in entry_ice))
check("PURGE-10: Asiento balanceado",          abs(dr_i - cr_i) < 1.0)
check("PURGE-10: Monto ~¢28,173,887",          abs(dr_i - 28_173_887) < 10)

print("\n" + "=" * 65)
if FAIL == 0: print(f"ALL {PASS} SIM-PURGE TESTS PASSED")
else:         print(f"{PASS} passed, {FAIL} FAILED"); sys.exit(1)
print("=" * 65)
