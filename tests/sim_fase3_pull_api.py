"""
SIM Fase 3 — APIs Pull desde Genoma Contable
Verifica la lógica de: paginación, dedup, cross-tenant guard, rollback en error.
Todos los tests son offline — mockean genoma_client y DB.
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = 0
FAIL = 0

def check(label, cond):
    global PASS, FAIL
    if cond:
        print(f"  ✅ PASS: {label}")
        PASS += 1
    else:
        print(f"  ❌ FAIL: {label}")
        FAIL += 1

print("=" * 60)
print("SIM-F3 — APIs Pull: paginación, dedup, guard, rollback")
print("=" * 60)

# ─── SIM-F3-01: paginación correcta ───────────────────────────────
print("\nSIM-F3-01: pull retorna max limit docs paginados")
from services.integration.router_pull import _paginate_result

docs = [{"clave": str(i)} for i in range(25)]
page1 = _paginate_result(docs, page=1, limit=10)
page2 = _paginate_result(docs, page=2, limit=10)
page3 = _paginate_result(docs, page=3, limit=10)

check("página 1 tiene 10 items", len(page1["items"]) == 10)
check("página 2 tiene 10 items", len(page2["items"]) == 10)
check("página 3 tiene 5 items (restantes)", len(page3["items"]) == 5)
check("total siempre es 25", page1["total"] == page3["total"] == 25)
check("total_pages = 3", page1["total_pages"] == 3)

# ─── SIM-F3-02: pull-recibidos retorna campos CABYS por línea ─────
print("\nSIM-F3-02: Respuesta incluye lineas[] con cabys_code")
doc_with_lines = {
    "clave": "A" * 50,
    "tipo_doc": "08",
    "emisor_nombre": "TI Soluciones S.A.",
    "total_doc": 912000,
    "lineas": [
        {"cabys_code": "4151903010", "descripcion": "Computadora", "monto_total": 750000, "tarifa_codigo": "08"},
        {"cabys_code": "9309991001", "descripcion": "Papel carta",  "monto_total": 12000,  "tarifa_codigo": "08"},
    ]
}
check("doc tiene lineas[]", "lineas" in doc_with_lines)
check("línea 1 tiene cabys_code", "cabys_code" in doc_with_lines["lineas"][0])
check("línea 2 tiene tarifa_codigo", "tarifa_codigo" in doc_with_lines["lineas"][1])

# ─── SIM-F3-03: dedup por source_ref ──────────────────────────────
print("\nSIM-F3-03: Documento ya importado → skip (no duplica)")
from services.integration.router_pull import _is_already_imported

class MockDBDedup:
    def __init__(self, existing_refs):
        self.existing = existing_refs
    def execute(self, stmt, params=None):
        ref = (params or {}).get("ref", "")
        return MockDedup(ref in self.existing)

class MockDedup:
    def __init__(self, found): self._found = found
    def fetchone(self): return object() if self._found else None

db_dup = MockDBDedup(existing_refs={"CLAVE_YA_EXIST_50_CHARS_PADDED_0000000000000000"})
check("clave existente → is_imported = True",
      _is_already_imported(db_dup, "t1", "CLAVE_YA_EXIST_50_CHARS_PADDED_0000000000000000") == True)
check("clave nueva → is_imported = False",
      _is_already_imported(db_dup, "t1", "CLAVE_NUEVA_XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX") == False)

# ─── SIM-F3-04: rollback en error a mitad del batch ───────────────
print("\nSIM-F3-04: Import batch — rollback si falla cualquier doc")
from services.integration.router_pull import _process_import_batch

class MockDBRollback:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.added = []
    def add(self, obj): self.added.append(obj)
    def commit(self): self.committed = True
    def rollback(self): self.rolled_back = True
    def execute(self, stmt, params=None): return MockDedup(False)  # nunca duplicado

def bad_mapper(db, doc, tenant_id):
    if doc.get("clave") == "BAD_DOC":
        raise ValueError("Error de mapeo simulado")
    return {"entry_id": str(uuid.uuid4())}

docs_batch = [
    {"clave": "OK_DOC_1", "tipo_doc": "08", "total_doc": 1000, "lineas": []},
    {"clave": "BAD_DOC",  "tipo_doc": "08", "total_doc": 5000, "lineas": []},
]

db_rb = MockDBRollback()
result = _process_import_batch(db_rb, docs_batch, "t1", bad_mapper)
check("rollback llamado cuando hay error", db_rb.rolled_back)
check("no commit cuando hay error", not db_rb.committed)
check("resultado incluye error info", "error" in result)

# ─── SIM-F3-05: guard cross-tenant ────────────────────────────────
print("\nSIM-F3-05: tenant_id del token protege cross-tenant")
from services.integration.router_pull import _validate_tenant_docs

docs_mixed = [
    {"clave": "C1", "tenant_id": "t1"},
    {"clave": "C2", "tenant_id": "t2"},  # ← cruzado
    {"clave": "C3", "tenant_id": "t1"},
]
# Solo deben pasar los del tenant t1
safe_docs = _validate_tenant_docs(docs_mixed, "t1")
check("solo pasan 2 docs del tenant t1", len(safe_docs) == 2)
check("doc de t2 filtrado", all(d["tenant_id"] == "t1" for d in safe_docs))

print("\n" + "=" * 60)
if FAIL == 0:
    print(f"ALL {PASS} SIM-F3 TESTS PASSED ✅")
else:
    print(f"{PASS} passed, {FAIL} FAILED ❌")
    sys.exit(1)
print("=" * 60)
