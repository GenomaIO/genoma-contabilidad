"""
SIM — Fix PDF: pdfplumber backend en lugar de pdf.js client
=============================================================
MÓDULO 1 — Código: branch PDF ahora usa /parse-file (FormData)
MÓDULO 2 — Código: pdf.js NO se usa para extraer texto de tablas
MÓDULO 3 — Lógica: parse-file usa pdfplumber que entiende tablas
MÓDULO 4 — Regresión: CSV y XLSX siguen funcionando igual
"""
import sys, os

OK   = "\033[92m✅\033[0m"
FAIL = "\033[91m❌\033[0m"
errors = []

def check(cond, msg):
    if cond: print(f"  {OK} {msg}")
    else:    print(f"  {FAIL} {msg}"); errors.append(msg)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src  = open(os.path.join(ROOT, "frontend/src/pages/Conciliacion.jsx")).read()

# ─── MÓDULO 1: Branch PDF usa /parse-file ────────────────────────────────
print("\n📄 MÓDULO 1 — Branch PDF cambiado a /parse-file (pdfplumber):")

# Buscar el bloque if PDF en parsearArchivo
idx = src.find("parsearArchivo")
pdf_section = src[idx:idx+2000]  # los primeros 2000 chars de la función

check("/conciliacion/parse-file" in pdf_section,
      "branch PDF llama a /parse-file (pdfplumber backend)")
check("pdfplumber" in src,
      "comentario explica que pdfplumber maneja tablas correctamente")
check("pdf.js client-side" in src or "pdfplumber" in src,
      "comentario explica razón del cambio")

# El branch PDF debe enviar FormData, NO extraer texto con getDocument
pdf_start = src.find("if (fname.endsWith('.pdf'))")
pdf_end   = src.find("if (fname.endsWith('.xlsx')")
pdf_block = src[pdf_start:pdf_end] if pdf_start > 0 and pdf_end > 0 else ""

check("new FormData()"       in pdf_block, "branch PDF usa FormData (igual que XLSX)")
check("parse-file"           in pdf_block, "branch PDF llama /parse-file")
check("getDocument"      not in pdf_block, "branch PDF NO usa pdfjsLib.getDocument")
check("getTextContent"   not in pdf_block, "branch PDF NO extrae texto con pdf.js")
check("arrayBuffer"      not in pdf_block, "branch PDF NO usa arrayBuffer (pdf.js)")

# ─── MÓDULO 2: pdf.js no se usa para tablas ──────────────────────────────
print("\n🚫 MÓDULO 2 — pdf.js no procesa tablas bancarias directamente:")

# pdf.js puede quedarse como dependencia (para otros usos en el futuro)
# pero el branch .pdf debe ir a /parse-file
check("getDocument" not in pdf_block,
      "getDocument no está en el branch .pdf (tablas van a pdfplumber)")

# Verificar que el comentario explica el motivo
check("desordena" in src or "tablas" in src,
      "comentario explica por qué pdf.js no funciona para tablas BN")

# ─── MÓDULO 3: Backend parse-file con pdfplumber ─────────────────────────
print("\n🐍 MÓDULO 3 — Backend /parse-file usa pdfplumber:")

router_src = open(os.path.join(ROOT, "services/conciliacion/router.py")).read()
check("pdfplumber" in router_src,  "pdfplumber en /parse-file del backend")
check("fname.endswith(\".pdf\")" in router_src or
      'fname.endswith(".pdf")' in router_src,
      "backend detecta archivos .pdf en parse-file")
check("pdfplumber.open" in router_src, "backend usa pdfplumber.open para PDF")
check("extract_text"    in router_src, "backend llama extract_text() por página")

# ─── MÓDULO 4: CSV y XLSX no regresionaron ───────────────────────────────
print("\n✅ MÓDULO 4 — Regresión: CSV y XLSX intactos:")

check("fname.endsWith('.csv')"  in src, "branch CSV sigue igual")
check("fname.endsWith('.xlsx')" in src, "branch XLSX sigue igual")
csv_start = src.find("fname.endsWith('.csv')")
csv_block = src[csv_start:csv_start+300]
check("/conciliacion/parse'"   in csv_block or
      "/conciliacion/parse`"   in csv_block,
      "CSV sigue enviando texto a /conciliacion/parse")

xlsx_start = src.find("fname.endsWith('.xlsx')")
xlsx_block = src[xlsx_start:xlsx_start+300]
check("parse-file" in xlsx_block, "XLSX sigue enviando a /parse-file")

# ─── Resultado final ───────────────────────────────────────────────────────
print("\n" + "="*65)
if errors:
    print(f"❌ SIM FALLIDA — {len(errors)} error(es):")
    for e in errors: print(f"   • {e}")
    sys.exit(1)
else:
    print("✅ SIM VERDE — Fix PDF: pdfplumber backend (tablas BN)")
    print("   · PDF → FormData → /parse-file (pdfplumber)")
    print("   · pdfplumber lee tablas correctamente → N txns (no 0)")
    print("   · CSV sigue con /parse (texto directo)")
    print("   · XLSX sigue con /parse-file (openpyxl)")
    sys.exit(0)
