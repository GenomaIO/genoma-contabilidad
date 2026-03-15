"""
integration/journal_mapper_v2.py
════════════════════════════════════════════════════════════
Motor de Mapeo Contable v2 — A nivel de línea CABYS

Diferencia con v1 (journal_mapper.py):
  v1: trabaja con totales del documento (total_venta, total_iva)
  v2: trabaja con cada linea[] del documento + su CABYS + tarifa IVA

Filosofía:
  - Cada línea del doc genera sus líneas contables individuales
  - IVA heredado por tarifa_codigo (no calculado globalmente)
  - Si el payload no tiene lineas[] → delega al motor v1 (compatibilidad)
  - El asiento siempre queda en DRAFT

Reglas de Oro:
  - Nunca lanza excepción hacia el llamador
  - Siempre produce DR = CR (ajuste automático si diferencia < ₡1)
  - tenant_id en todas las líneas (aislamiento multi-tenant)
"""
import uuid
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.integration.cabys_engine import resolver_cabys, iva_tipo_desde_tarifa
from services.tax.router import get_prorrata

logger = logging.getLogger(__name__)

# Cuentas por defecto (fallback si no está en catálogo)
DEFAULT_ACCOUNTS = {
    "CXC":            "1102",
    "CXP":            "2101",
    "BANCO":          "1101",
    "IVA_CREDITO":    "1104",
    "IVA_DEBITO":     "2102",
    "IVA_DIFERIDO":   "2108",   # IVA diferido cond. venta 11 (Art.17 Ley IVA 9635)
    "INGRESO_VENTAS": "4101",
    "INGRESO_SERV":   "4102",
    "INGRESO_EXENTO": "4103",
    "OTROS_GASTOS":   "5299",  # Otros Gastos Operativos — cuenta real del catálogo (5999 no existe)
}


def _normalizar_codigo(code: str) -> str:
    """Quita puntos, guiones y espacios para comparar prefijos normalizados."""
    return code.replace(".", "").replace("-", "").replace(" ", "")


# Mapa semántico: standard_code → (account_type_in_db, keywords para ILIKE)
# Usado como fallback cuando exact+prefix match fallan (catálogos punteados).
# Garantiza que "1104" encuentre "1.1.4.01 IVA Acreditable" aunque los prefijos
# normalizados no coincidan por diferencia de esquema numérico.
_SEMANTIC_MAP: dict = {
    "1104": ("ACTIVO",  ["iva", "acreditable", "crédito fiscal", "credito fiscal"]),
    "2101": ("PASIVO",  ["proveedor", "cuentas por pagar", "acreedores comerciales"]),
    "2102": ("PASIVO",  ["iva", "débito", "iva debito", "ventas"]),
    "1102": ("ACTIVO",  ["cliente", "cuentas por cobrar", "deudores comerciales"]),
    "1101": ("ACTIVO",  ["caja", "banco", "efectivo", "disponible"]),
    "4101": ("INGRESO", ["ventas", "ingresos por ventas", "venta de bienes"]),
    "4102": ("INGRESO", ["servicios", "ingresos por servicios"]),
    "5299": ("GASTO",   ["otros gastos", "gastos varios", "gastos operativos"]),
    "5101": ("GASTO",   ["costo", "mercancía", "inventario", "costo de venta"]),
}


def _resolver_cuenta_jerarquica(db, tenant_id: str, code_base: str) -> str:
    """
    Resuelve la cuenta más específica del catálogo del tenant.

    Estrategia (exact → prefix → semántico → fallback):
      1. Exact match: busca code_base tal cual.
      2. Prefix match: busca código que EMPIECE con code_base normalizado.
         Ej: '1102' matchea '110201'. Falla para catálogos punteados
         donde '1104' normaliza a '1104' pero '1.1.4.01' normaliza a '11401'.
      3. Semántico: si el código está en _SEMANTIC_MAP, busca por tipo de
         cuenta + keyword en el nombre (ILIKE). Diseñado para catálogos
         con esquema numérico diferente (ej. 1.1.4.xx vs 1104).
      4. Fallback: retorna code_base con warning (el contador revisará).
    """
    try:
        # 1. Exact match
        row = db.execute(text("""
            SELECT code FROM accounts
            WHERE tenant_id = :tid AND code = :code AND is_active = TRUE
            LIMIT 1
        """), {"tid": tenant_id, "code": code_base}).fetchone()
        if row:
            return code_base

        # 2. Prefix match — catálogos extendidos (4d, 6d, 8d, dotados, con guión)
        norm_base = _normalizar_codigo(code_base)
        rows = db.execute(text("""
            SELECT code FROM accounts
            WHERE tenant_id = :tid AND is_active = TRUE
              AND REPLACE(REPLACE(REPLACE(code, '.', ''), '-', ''), ' ', '') LIKE :prefix || '%'
            ORDER BY LENGTH(code) ASC
            LIMIT 1
        """), {"tid": tenant_id, "prefix": norm_base}).fetchone()
        if rows:
            logger.info(
                f"📐 cuenta {code_base} → '{rows[0]}' (prefix-match catálogo {tenant_id[:8]})"
            )
            return rows[0]

        # 3. Semántico — para catálogos punteados con esquema distinto
        # (ej. tenant usa 1.1.4.01 pero buscamos 1104)
        semantic = _SEMANTIC_MAP.get(code_base)
        if semantic:
            acc_type, keywords = semantic
            for kw in keywords:
                sem_row = db.execute(text("""
                    SELECT code FROM accounts
                    WHERE tenant_id    = :tid
                      AND account_type = :atype
                      AND is_active    = TRUE
                      AND allow_entries = TRUE
                      AND LOWER(name)  LIKE :kw
                    ORDER BY LENGTH(code) ASC
                    LIMIT 1
                """), {
                    "tid":   tenant_id,
                    "atype": acc_type,
                    "kw":    f"%{kw}%",
                }).fetchone()
                if sem_row:
                    logger.info(
                        f"🔍 cuenta {code_base} → '{sem_row[0]}' "
                        f"(semántico '{kw}' catálogo {tenant_id[:8]})"
                    )
                    return sem_row[0]

    except Exception as ex:
        logger.warning(f"⚠️ resolver_cuenta_jerarquica error: {ex} — usando fallback {code_base}")

    # 4. Fallback — log warning, el contador verá el entry en needs_review
    logger.warning(
        f"⚠️ mapper_v2: sin match para '{code_base}' en catálogo de {tenant_id[:8]}, usando fallback"
    )
    return code_base


# Alias corto para compatibilidad interna
_resolve_account = _resolver_cuenta_jerarquica



def _build_line(entry_id, tenant_id, code, desc, debit, credit,
                deductible="DEDUCTIBLE", legal_basis=None,
                cabys_code=None, iva_tipo=None, iva_tarifa=None,
                confidence_score=None, clasificacion_fuente=None,
                account_role=None, needs_review=False) -> dict:
    """Construye un dict de línea contable (para SIM y para DB)."""
    return {
        "id":                   str(uuid.uuid4()),
        "entry_id":             entry_id,
        "tenant_id":            tenant_id,
        "account_code":         code,
        "description":          desc,
        "debit":                round(float(debit), 5),
        "credit":               round(float(credit), 5),
        "deductible_status":    deductible,
        "legal_basis":          legal_basis,
        "cabys_code":           cabys_code,
        "iva_tipo":             iva_tipo,
        "iva_tarifa":           iva_tarifa,
        "confidence_score":     confidence_score,
        "clasificacion_fuente": clasificacion_fuente,
        "account_role":         account_role,
        "needs_review":         needs_review,
        "created_at":           datetime.now(timezone.utc),
    }


def _build_entry_lines_from_doc(doc: dict, tenant_id: str, entry_id: str, cabys_rules: dict) -> list:
    """
    Construye todas las líneas contables de un documento.

    Si el doc tiene lineas[] → mapeo por línea CABYS (v2).
    Si no → mapeo por totales del documento (fallback v1).

    Retorna lista de dicts (sin insertar en DB aquí).
    """
    doc_type  = doc.get("tipo_doc", doc.get("doc_type", "08"))
    lineas    = doc.get("lineas", [])

    # ── Guard: normalizar tipo si el doc fue importado como recibido ─
    # El Facturador retorna el tipo_doc ORIGINAL de Hacienda (ej: "01")
    # aunque sea una FE que un proveedor emitió a la empresa.
    # router_pull.py marca estos docs con _es_recibido=True al importar.
    if doc.get("_es_recibido"):
        doc_type = "RECIBIDO"

    # ── Fallback v1 si el doc no tiene líneas ───────────────────────
    if not lineas:
        return _fallback_v1_lines(doc, tenant_id, entry_id, doc_type)

    lines = []
    total_neto_acumulado = 0.0
    total_iva_acumulado  = 0.0

    # ── FEC / Compra recibida (08, RECIBIDO) ────────────────────────
    if doc_type in ("08", "09", "RECIBIDO"):
        # Leer prorrata del tenant una sola vez (Art. 31 Ley IVA 9635)
        # Si la db es None (SIM sin DB), usar prorrata del doc o default 1.0
        try:
            prorrata = get_prorrata(tenant_id, doc["_db"]) if doc.get("_db") else doc.get("prorrata_iva", 1.0)
        except Exception:
            prorrata = doc.get("prorrata_iva", 1.0)
        prorrata = max(0.0, min(1.0, float(prorrata)))   # clamp 0.0-1.0

        for linea in lineas:
            cabys     = linea.get("cabys_code", "")
            desc_item = linea.get("descripcion", "Compra")
            monto_n   = float(linea.get("monto_total", 0))
            monto_iva = float(linea.get("monto_iva", 0))
            tarifa_c  = linea.get("tarifa_codigo", "08")
            tipo_exon = linea.get("tipo_exoneracion")

            iva_info  = iva_tipo_desde_tarifa(tarifa_c, tipo_exon)

            # Resolver cuenta por CABYS (usa engine)
            cab_result = resolver_cabys(
                cabys_rules, tenant_id, cabys, desc_item, monto_n
            ) if callable(getattr(cabys_rules, 'execute', None)) else {
                "account_code": DEFAULT_ACCOUNTS["OTROS_GASTOS"],
                "confidence": 0.3, "fuente": "FALLBACK", "asset_flag": False
            }

            # Resolver la cuenta CABYS jerárquicamente en el catálogo NIIF del tenant
            # cabys_rules IS la db-session aquí (inyectada por map_document_lines_to_entry).
            # _resolve_account hace exact → prefix → fallback contra la tabla accounts
            # garantizando que el código resultante EXISTA en el catálogo del tenant.
            # Si cabys_rules es un dict vacío (tests SIM sin DB) devuelve el código base.
            cuenta_gasto_raw = cab_result["account_code"]
            cuenta_gasto = (
                _resolve_account(cabys_rules, tenant_id, cuenta_gasto_raw)
                if callable(getattr(cabys_rules, "execute", None))
                else cuenta_gasto_raw
            )
            asset_flag   = cab_result.get("asset_flag", False)
            confidence   = cab_result.get("confidence", 0.3)
            fuente       = cab_result.get("fuente", "FALLBACK")

            deductible = "DEDUCTIBLE" if iva_info["acreditable"] else "EXEMPT"

            # DR Cuenta de gasto/activo (neto sin IVA)
            lines.append(_build_line(
                entry_id, tenant_id, cuenta_gasto,
                f"{desc_item} \u00b7 CABYS {cabys}",
                debit=monto_n, credit=0,
                deductible=deductible,
                legal_basis="Art. 8 Ley Renta 7092",
                cabys_code=cabys,
                iva_tipo=iva_info["tipo"],
                iva_tarifa=iva_info["tarifa"],
                confidence_score=confidence,
                clasificacion_fuente=fuente,
                account_role="ACTIVO_POSIBLE" if asset_flag else "GASTO",
                needs_review=asset_flag,
            ))
            total_neto_acumulado += monto_n

            # ── DR IVA Acreditable y no acreditable (Prorrata Art. 31 Ley 9635) ──
            if monto_iva > 0 and iva_info["acreditable"]:
                iva_acreditable    = round(monto_iva * prorrata, 5)
                iva_no_acreditable = round(monto_iva - iva_acreditable, 5)

                # DR 1104 IVA Crédito Fiscal (parte acreditable)
                if iva_acreditable > 0:
                    lines.append(_build_line(
                        entry_id, tenant_id,
                        DEFAULT_ACCOUNTS["IVA_CREDITO"],
                        f"IVA Acreditable {prorrata*100:.0f}% \u00b7 {desc_item}",
                        debit=iva_acreditable, credit=0,
                        deductible="DEDUCTIBLE",
                        legal_basis="Art. 29 Ley IVA 9635",
                        cabys_code=cabys,
                        iva_tipo=iva_info["tipo"],
                        iva_tarifa=iva_info["tarifa"],
                        account_role="IVA_CREDITO",
                    ))
                    total_iva_acumulado += iva_acreditable

                # DR misma cuenta gasto (IVA no acreditable = costo adicional)
                if iva_no_acreditable > 0:
                    lines.append(_build_line(
                        entry_id, tenant_id,
                        cuenta_gasto,   # ← misma cuenta 5xxx del gasto
                        f"IVA no acreditable {(1-prorrata)*100:.0f}% \u00b7 {desc_item}",
                        debit=iva_no_acreditable, credit=0,
                        deductible="PARTIAL",
                        legal_basis="Art. 31 Ley IVA 9635 \u2014 prorrata",
                        cabys_code=cabys,
                        iva_tipo=iva_info["tipo"],
                        iva_tarifa=iva_info["tarifa"],
                        account_role="IVA_NO_ACREDITABLE",
                    ))
                    total_iva_acumulado += iva_no_acreditable

        # ── DR por OtrosCargos (Cruz Roja, 911, flete, etc.) ─────────────────
        # Regla de Oro: OtrosCargos son parte del TotalComprobante pero NO
        # están en DetalleServicio — deben registrarse como DR separados.
        _OC_CUENTAS = {
            "01": "5710", "02": "5990", "03": "5480",
            "04": "5420", "05": "5710", "99": "5990",
        }
        for otro in doc.get("otros_cargos", []):
            monto_oc = float(otro.get("monto_cargo_crc", 0))
            if monto_oc <= 0:
                continue
            tipo_oc  = otro.get("tipo_doc_oc", "99")
            cuenta_oc = otro.get("cuenta") or _OC_CUENTAS.get(tipo_oc, "5990")
            desc_oc   = otro.get("descripcion", f"OtroCargo tipo {tipo_oc}")[:80]
            lines.append(_build_line(
                entry_id, tenant_id, cuenta_oc,
                f"{desc_oc} · OtroCargo",
                debit=monto_oc, credit=0,
                deductible="DEDUCTIBLE",
                legal_basis="OtrosCargos — FE v4.4 Art.12",
                account_role="OTRO_CARGO",
            ))

        # ── CR según condicion_venta del documento ────────────────────────────
        # Regla de Oro #2: usar TotalComprobante del XML como fuente de verdad.
        # Regla de Oro #3: CondicionVenta determina la cuenta (Banco vs CxP).
        # total_comprobante viene de parse_doc_metadata (XML) → ya en CRC.
        # Fallback explícito (is not None) para no perder 0 legítimo vs missing.
        _tc = doc.get("total_comprobante")
        _td = doc.get("total_doc")
        if _tc is not None and _tc > 0:
            total_cr = float(_tc)
        elif _td is not None and _td > 0:
            total_cr = float(_td)
        else:
            total_cr = round(total_neto_acumulado + total_iva_acumulado, 5)

        condicion      = doc.get("condicion_venta", doc.get("condicion", "02"))
        emisor         = doc.get("emisor_nombre", "Proveedor")[:60]

        if condicion == "01":   # contado — pagado de inmediato
            cuenta_balance = DEFAULT_ACCOUNTS["BANCO"]
            desc_balance   = f"Pago contado · {emisor}"
            role_balance   = "BANCO"
        else:                   # crédito — queda en CxP
            cuenta_balance = DEFAULT_ACCOUNTS["CXP"]
            desc_balance   = f"CxP · {emisor}"
            role_balance   = "CXP"

        lines.append(_build_line(
            entry_id, tenant_id,
            cuenta_balance, desc_balance,
            debit=0, credit=total_cr,
            deductible="EXEMPT",
            legal_basis="Art. 8 Ley Renta 7092",
            account_role=role_balance,
        ))

        # Ajuste de redondeo si DR ≠ CR (< ₡1) — se pasa db para resolver cuenta
        lines = _ajuste_redondeo(lines, entry_id, tenant_id, db=cabys_rules
                                 if callable(getattr(cabys_rules, "execute", None)) else None)

    # ── FE / TE / ND / NC → Documentos de venta ─────────────────────
    elif doc_type in ("01", "04", "02", "03"):
        total_doc  = float(doc.get("total_doc", 0))
        condicion  = doc.get("condicion_venta", doc.get("condicion", "02"))
        receptor   = doc.get("receptor_nombre", "Cliente")[:60]

        # ── DR según condicion_venta del documento ───────────────────
        # '01' contado → Banco (cobrado al momento de la venta)
        # '02'/default → CxC cliente (queda pendiente de cobro)
        if condicion == "01":   # contado — cobrado de inmediato
            cuenta_dr  = DEFAULT_ACCOUNTS["BANCO"]
            desc_dr    = f"Cobro contado · {receptor}"
            role_dr    = "BANCO"
        else:                   # crédito — queda en CxC
            cuenta_dr  = DEFAULT_ACCOUNTS["CXC"]
            desc_dr    = f"CxC · {receptor}"
            role_dr    = "CXC"

        lines.append(_build_line(
            entry_id, tenant_id, cuenta_dr, desc_dr,
            debit=total_doc, credit=0,
            deductible="EXEMPT",
            legal_basis="Art. 22 Ley IVA 9635",
            account_role=role_dr,
        ))

        # Por cada línea → CR Ingreso + CR IVA por Pagar
        for linea in lineas:
            desc_item = linea.get("descripcion", "Venta")
            monto_n   = float(linea.get("monto_total", 0))
            monto_iva = float(linea.get("monto_iva", 0))
            tarifa_c  = linea.get("tarifa_codigo", "08")
            tipo_exon = linea.get("tipo_exoneracion")
            iva_info  = iva_tipo_desde_tarifa(tarifa_c, tipo_exon)

            cuenta_ing = (DEFAULT_ACCOUNTS["INGRESO_EXENTO"]
                          if iva_info["tipo"] == "EXENTO"
                          else DEFAULT_ACCOUNTS["INGRESO_VENTAS"])

            # CR Ingreso
            lines.append(_build_line(
                entry_id, tenant_id, cuenta_ing,
                f"Ingreso · {desc_item}",
                debit=0, credit=monto_n,
                deductible="DEDUCTIBLE" if iva_info["acreditable"] else "EXEMPT",
                legal_basis="Art. 8 Ley Renta 7092",
                iva_tipo=iva_info["tipo"],
                iva_tarifa=iva_info["tarifa"],
                account_role="INGRESO",
            ))

            # CR IVA por Pagar (o IVA Diferido si condicion=11)
            if monto_iva > 0:
                if condicion == "11":
                    # Venta a plazo: IVA diferido hasta vencimiento (Art.17 Ley IVA 9635)
                    cuenta_iva = DEFAULT_ACCOUNTS["IVA_DIFERIDO"]
                    desc_iva   = f"IVA Diferido cond.11 · {desc_item}"
                    role_iva   = "IVA_DIFERIDO"
                    basis_iva  = "Art. 17 Ley IVA 9635 — venta a plazo"
                else:
                    cuenta_iva = DEFAULT_ACCOUNTS["IVA_DEBITO"]
                    desc_iva   = f"IVA {iva_info['tarifa']}% · {desc_item}"
                    role_iva   = "IVA_DEBITO"
                    basis_iva  = "Art. 15 Ley IVA 9635"
                lines.append(_build_line(
                    entry_id, tenant_id, cuenta_iva,
                    desc_iva,
                    debit=0, credit=monto_iva,
                    deductible="EXEMPT",
                    legal_basis=basis_iva,
                    iva_tipo=iva_info["tipo"],
                    iva_tarifa=iva_info["tarifa"],
                    account_role=role_iva,
                ))

        lines = _ajuste_redondeo(lines, entry_id, tenant_id)

    return lines


def _ajuste_redondeo(lines: list, entry_id: str, tenant_id: str, db=None) -> list:
    """Agrega línea de ajuste si DR ≠ CR por diferencia de redondeo < ₡1."""
    dr = round(sum(l["debit"]  for l in lines), 5)
    cr = round(sum(l["credit"] for l in lines), 5)
    diff = round(abs(dr - cr), 5)
    if 0 < diff < 1:
        # Resolver "5999" contra el catálogo real del tenant si hay DB disponible
        cuenta_ajuste = (
            _resolve_account(db, tenant_id, DEFAULT_ACCOUNTS["OTROS_GASTOS"])
            if db and callable(getattr(db, "execute", None))
            else DEFAULT_ACCOUNTS["OTROS_GASTOS"]
        )
        if dr > cr:
            lines.append(_build_line(entry_id, tenant_id, cuenta_ajuste,
                f"Ajuste redondeo ₡{diff}", 0, diff, "EXEMPT"))
        else:
            lines.append(_build_line(entry_id, tenant_id, cuenta_ajuste,
                f"Ajuste redondeo ₡{diff}", diff, 0, "EXEMPT"))
    return lines


def _fallback_v1_lines(doc: dict, tenant_id: str, entry_id: str, doc_type: str) -> list:
    """
    Fallback al mapeo v1 por totales cuando no hay lineas[].
    Compatible con payloads del webhook_receiver original.

    Correcciones:
    - total_venta = TotalComprobante (IVA incluido, lo que se le paga al proveedor).
      neto = total_venta - total_iva  → es el subtotal real sin IVA.
    - CR = total_venta (= TotalComprobante, monto que debes al proveedor).
    - Aplica prorrata IVA (Art. 31 Ley 9635) en path RECIBIDO:
        DR 1104  = total_iva * prorrata       (acreditable)
        DR 5xxx  = total_iva * (1-prorrata)   (no acreditable → mayor costo)
    """
    total_venta = float(doc.get("total_venta", 0))
    total_iva   = float(doc.get("total_iva",   0))
    emisor      = doc.get("emisor_nombre", "Proveedor")[:60]
    condicion   = doc.get("condicion_venta", doc.get("condicion", "02"))

    # CR = TotalComprobante = lo que le debes al proveedor (IVA incluido)
    # total_venta en el payload del Facturador = TotalComprobante del XML Hacienda
    total_cr = total_venta

    # Prorrata IVA (Art. 31 Ley 9635) — misma lógica que v2
    try:
        prorrata = get_prorrata(tenant_id, doc["_db"]) if doc.get("_db") else doc.get("prorrata_iva", 1.0)
    except Exception:
        prorrata = doc.get("prorrata_iva", 1.0)
    prorrata = max(0.0, min(1.0, float(prorrata)))

    # Resolver cuenta de gasto/otros-gastos jerárquicamente en el catálogo NIIF
    # doc["_db"] es inyectado por map_document_lines_to_entry antes de invocar
    # _build_entry_lines_from_doc → _fallback_v1_lines.
    # Si no hay DB (SIM tests sin DB), se usa el código base directamente.
    _db_v1 = doc.get("_db") if isinstance(doc, dict) else None
    _cuenta_gasto_v1 = (
        _resolve_account(_db_v1, tenant_id, DEFAULT_ACCOUNTS["OTROS_GASTOS"])
        if _db_v1 and callable(getattr(_db_v1, "execute", None))
        else DEFAULT_ACCOUNTS["OTROS_GASTOS"]
    )

    lines = []
    if doc_type in ("08", "09", "RECIBIDO"):
        # Neto = TotalComprobante - IVA = lo que va al gasto (sin impuesto)
        neto = round(total_venta - total_iva, 5)
        if neto > 0:
            lines.append(_build_line(entry_id, tenant_id,
                _cuenta_gasto_v1,
                f"Compra (v1-fallback) · {emisor}",
                debit=neto, credit=0,
                deductible="DEDUCTIBLE",
                legal_basis="Art. 8 Ley Renta 7092",
                clasificacion_fuente="V1_FALLBACK"
            ))
        if total_iva > 0:
            iva_acreditable    = round(total_iva * prorrata, 5)
            iva_no_acreditable = round(total_iva - iva_acreditable, 5)

            if iva_acreditable > 0:
                lines.append(_build_line(entry_id, tenant_id,
                    DEFAULT_ACCOUNTS["IVA_CREDITO"],
                    f"IVA Acreditable {round(prorrata*100,0):.0f}% (v1-fallback) · {emisor}",
                    debit=iva_acreditable, credit=0,
                    deductible="DEDUCTIBLE",
                    legal_basis="Art. 29 Ley IVA 9635",
                    clasificacion_fuente="V1_FALLBACK"
                ))
            if iva_no_acreditable > 0:
                lines.append(_build_line(entry_id, tenant_id,
                    _cuenta_gasto_v1,
                    f"IVA no acreditable {round((1-prorrata)*100,0):.0f}% (v1-fallback) · {emisor}",
                    debit=iva_no_acreditable, credit=0,
                    deductible="PARTIAL",
                    legal_basis="Art. 31 Ley IVA 9635 — prorrata",
                    clasificacion_fuente="V1_FALLBACK"
                ))
        # CR según condición: contado → Banco, crédito → CxP
        if condicion == "01":
            cuenta_balance = DEFAULT_ACCOUNTS["BANCO"]
            desc_balance   = f"Pago contado (v1-fallback) · {emisor}"
        else:
            cuenta_balance = DEFAULT_ACCOUNTS["CXP"]
            desc_balance   = f"CxP proveedor (v1-fallback) · {emisor}"
        lines.append(_build_line(entry_id, tenant_id,
            cuenta_balance, desc_balance,
            debit=0, credit=total_cr,
            deductible="EXEMPT",
            clasificacion_fuente="V1_FALLBACK"
        ))
    elif doc_type in ("01", "04"):
        # DR según condición: contado → Banco, crédito → CxC
        receptor = doc.get("receptor_nombre", "Cliente")[:60]
        if condicion == "01":
            cuenta_dr = DEFAULT_ACCOUNTS["BANCO"]
            desc_dr   = f"Cobro contado (v1-fallback) · {receptor}"
        else:
            cuenta_dr = DEFAULT_ACCOUNTS["CXC"]
            desc_dr   = f"CxC cliente (v1-fallback) · {receptor}"
        lines.append(_build_line(entry_id, tenant_id,
            cuenta_dr, desc_dr,
            debit=total_cr, credit=0, deductible="EXEMPT",
            clasificacion_fuente="V1_FALLBACK"
        ))
        # CR ingreso = neto (sin IVA) → DR total_venta = CR neto + IVA ✅
        neto_venta = round(total_venta - total_iva, 5)
        if neto_venta > 0:
            lines.append(_build_line(entry_id, tenant_id,
                DEFAULT_ACCOUNTS["INGRESO_VENTAS"],
                "Ingreso venta (v1-fallback)",
                debit=0, credit=neto_venta, deductible="DEDUCTIBLE",
                clasificacion_fuente="V1_FALLBACK"
            ))

        if total_iva > 0:
            lines.append(_build_line(entry_id, tenant_id,
                DEFAULT_ACCOUNTS["IVA_DEBITO"],
                "IVA Débito (v1-fallback)",
                debit=0, credit=total_iva, deductible="EXEMPT",
                clasificacion_fuente="V1_FALLBACK"
            ))
    return lines


def map_document_lines_to_entry(db: Session, doc: dict, tenant_id: str) -> dict:
    """
    Punto de entrada principal para importar un documento al Libro Diario.
    Crea JournalEntry DRAFT + sus líneas contables.

    Args:
        db:        Sesión SQLAlchemy
        doc:       Documento parseado con lineas[]
        tenant_id: ID del tenant (del JWT)

    Returns:
        {"entry_id": str}
    """
    from services.ledger.models import JournalEntry, JournalLine, EntryStatus, EntrySource

    entry_id = str(uuid.uuid4())
    fecha_raw = (doc.get("fecha") or "")[:25]  # raw del Facturador
    period   = fecha_raw[:7]    # 'YYYY-MM'
    date_str = fecha_raw[:10]   # 'YYYY-MM-DD' — columna VARCHAR(10)
    now      = datetime.now(timezone.utc)
    tipo     = doc.get("tipo_doc", doc.get("doc_type", "08"))
    emisor   = (doc.get("emisor_nombre") or "")[:60]
    num_doc  = (doc.get("numero_doc") or "")[:50]
    total    = doc.get("total_doc", 0)

    source_map = {
        "01": EntrySource.FE, "04": EntrySource.TE,
        "02": EntrySource.ND, "03": EntrySource.NC,
        "08": EntrySource.FEC, "09": EntrySource.FEC,
        "RECIBIDO": EntrySource.RECIBIDO,
    }
    source = source_map.get(tipo, EntrySource.MANUAL)

    # Inyectar el db en el doc para que _build_entry_lines_from_doc
    # pueda llamar get_prorrata(tenant_id, db) y leer fiscal_profiles.
    # Se usa una copia para no mutar el dict original del llamador.
    doc = {**doc, "_db": db}

    # Verificar confianza mínima para marcar needs_review
    lines_data = _build_entry_lines_from_doc(doc, tenant_id, entry_id, db)
    needs_review = any(
        l.get("needs_review") or (l.get("confidence_score") or 1.0) < 0.7
        for l in lines_data
    )
    min_confidence = min(
        ((l.get("confidence_score") or 1.0) for l in lines_data), default=1.0
    )

    entry = JournalEntry(
        id           = entry_id,
        tenant_id    = tenant_id,
        period       = period,
        date         = date_str,
        description  = f"[{tipo}] {emisor} · {num_doc} · ₡{float(total or 0):,.2f}",
        status       = EntryStatus.DRAFT,
        source       = source,
        source_ref   = doc.get("clave", ""),
        created_by   = "AUTO_IMPORT",
        created_at   = now,
    )
    db.add(entry)

    for l in lines_data:
        line = JournalLine(
            id                   = l["id"],
            entry_id             = entry_id,
            tenant_id            = tenant_id,
            account_code         = l["account_code"],
            description          = l["description"],
            debit                = l["debit"],
            credit               = l["credit"],
            deductible_status    = l.get("deductible_status", "DEDUCTIBLE"),
            legal_basis          = l.get("legal_basis"),
            created_at           = now,
        )
        db.add(line)

    logger.info(f"✅ mapper_v2: {len(lines_data)} líneas para entry {entry_id[:8]}... "
                f"needs_review={needs_review} conf={min_confidence:.2f}")
    return {"entry_id": entry_id}
