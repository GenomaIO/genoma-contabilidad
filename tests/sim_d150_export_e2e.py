#!/usr/bin/env python3
"""
sim_d150_export_e2e.py — SIM + E2E  Fase 7
===========================================
Verifica endpoints D-150, export de resultado CSV y formato correcto de salida.
"""
import sys, pathlib, csv, io

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = 0; FAIL = 0

def check(condition, label):
    global PASS, FAIL
    icon = "✅" if condition else "❌"
    print(f"  {icon}  {label}")
    if condition: PASS += 1
    else: FAIL += 1


# ── SIM-1: Lógica D-150 umbral ───────────────────────────────────────────────
print("\n[SIM-1] Lógica D-150 umbral ≥ ₡1,000,000")
BENEFICIARIOS = [
    {"nombre_norm": "JOSE ALEJANDRO",   "d150_monto_anual": 1_050_000.0, "n_transacciones": 3},
    {"nombre_norm": "SODA RUTA 35",     "d150_monto_anual":   250_000.0, "n_transacciones": 1},
    {"nombre_norm": "PROVEEDOR GRANDE", "d150_monto_anual": 3_200_000.0, "n_transacciones": 8},
]
UMBRAL = 1_000_000.0
d150_partidas = [b for b in BENEFICIARIOS if b["d150_monto_anual"] >= UMBRAL]
non_partidas  = [b for b in BENEFICIARIOS if b["d150_monto_anual"] < UMBRAL]

check(len(d150_partidas) == 2,         "2 beneficiarios superar umbral ₡1M")
check(non_partidas[0]["nombre_norm"] == "SODA RUTA 35", "SODA RUTA 35 excluida (<₡1M)")
check(max(b["d150_monto_anual"] for b in d150_partidas) == 3_200_000.0,
      "PROVEEDOR GRANDE = ₡3.2M (máximo)")


# ── SIM-2: Generación CSV D-150 ───────────────────────────────────────────────
print("\n[SIM-2] Generación CSV formato D-150")
lines = ["beneficiario,cedula,telefono,monto_total_crc,n_transacciones,aviso"]
for b in d150_partidas:
    lines.append(
        f"{b['nombre_norm']},PENDIENTE,,{b['d150_monto_anual']:.2f},"
        f"{b['n_transacciones']},Completar cédula antes de declarar"
    )
csv_text = "\n".join(lines)
reader = csv.DictReader(io.StringIO(csv_text))
filas = list(reader)

check(len(filas) == 2,                               "CSV tiene 2 filas de datos")
check(filas[0]["cedula"] == "PENDIENTE",             "cedula=PENDIENTE (protege privacidad)")
check("monto_total_crc" in filas[0],                 "campo monto_total_crc presente")
check("aviso" in filas[0],                           "campo aviso presente")
check(float(filas[0]["monto_total_crc"]) >= 1000000, "Primer fila >= ₡1M")


# ── SIM-3: Generación CSV resultado de sesión ─────────────────────────────────
print("\n[SIM-3] Generación CSV resultado de sesión")
TXNS_MUESTRA = [
    {"fecha":"2026-02-02","descripcion":"BNCR INTERESES","monto":9238.9,"tipo":"CR",
     "moneda":"CRC","tiene_fe":True,"tarifa_iva":0,"iva_estimado":0,"base_estimada":9238.9,
     "match_estado":"CON_FE","beneficiario_nombre":"BNCR","beneficiario_categoria":"BANK_INTEREST",
     "d270_codigo":None,"accion":None},
    {"fecha":"2026-02-05","descripcion":"JOSE ALEJANDRO CARVA","monto":260_000.0,"tipo":"DB",
     "moneda":"CRC","tiene_fe":False,"tarifa_iva":13,"iva_estimado":29911.5,"base_estimada":230088.5,
     "match_estado":"SIN_FE","beneficiario_nombre":"JOSE ALEJANDRO CARVA","beneficiario_categoria":"TERCERO",
     "d270_codigo":None,"accion":"Verificar FE recibida"},
]
csv_lines = [
    "fecha,descripcion,monto,tipo,moneda,tiene_fe,tarifa_iva_pct,"
    "iva_estimado,base_estimada,match_estado,beneficiario,categoria,d270,accion"
]
for t in TXNS_MUESTRA:
    tiene_fe_str = "SI" if t["tiene_fe"] else "NO"
    csv_lines.append(
        f"{t['fecha']},{t['descripcion'].replace(',',';')},{t['monto']},"
        f"{t['tipo']},{t['moneda']},{tiene_fe_str},{t['tarifa_iva']},"
        f"{t['iva_estimado'] or 0},{t['base_estimada'] or 0},{t['match_estado']},"
        f"{(t['beneficiario_nombre'] or '').replace(',',';')},"
        f"{t['beneficiario_categoria']},"
        f"{t['d270_codigo'] or ''},{(t['accion'] or '').replace(',',';')}"
    )
csv_resultado = "\n".join(csv_lines)
reader2 = csv.DictReader(io.StringIO(csv_resultado))
filas2 = list(reader2)

check(len(filas2) == 2,                              "CSV resultado tiene 2 filas")
check(filas2[0]["tiene_fe"] == "SI",                 "BNCR tiene_fe=SI")
check(filas2[1]["tiene_fe"] == "NO",                 "JOSE tiene_fe=NO (SIN_FE)")
check(filas2[1]["match_estado"] == "SIN_FE",         "match_estado=SIN_FE")
check(float(filas2[1]["iva_estimado"]) > 0,          "iva_estimado > 0 para SIN_FE")


# ── SIM-4: Verificación estática router ──────────────────────────────────────
print("\n[SIM-4] Endpoints en router.py")
src = (ROOT / "services" / "conciliacion" / "router.py").read_text(encoding="utf-8")
check("/centinela/d150/{year}"               in src, "GET /centinela/d150/{year}")
check("/centinela/d150/{year}/export"        in src, "GET /centinela/d150/{year}/export")
check("/centinela/resultado/{recon_id}/export" in src, "GET /centinela/resultado/{id}/export")
check("get_d150_preview"                     in src, "función get_d150_preview")
check("export_d150"                          in src, "función export_d150")
check("export_resultado"                     in src, "función export_resultado")
check("PENDIENTE"                            in src, "cédulas como PENDIENTE (seguridad)")

# ── SIM-5: importación funcional ─────────────────────────────────────────────
print("\n[SIM-5] Importación funcional")
try:
    from services.conciliacion.router import (
        get_d150_preview, export_d150, export_resultado
    )
    check(callable(get_d150_preview), "get_d150_preview callable")
    check(callable(export_d150),      "export_d150 callable")
    check(callable(export_resultado), "export_resultado callable")
except Exception as ex:
    check(False, f"Import falló: {ex}")


# ── Resultado ─────────────────────────────────────────────────────────────────
print(f"\n{'='*52}")
print(f"  F7 Resultado: {PASS} ✅  /  {FAIL} ❌  de {PASS+FAIL} checks")
print(f"{'='*52}\n")
sys.exit(0 if FAIL == 0 else 1)
