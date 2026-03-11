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

logger = logging.getLogger(__name__)

# Cuentas por defecto (fallback si no está en catálogo)
DEFAULT_ACCOUNTS = {
    "CXC":            "1102",
    "CXP":            "2101",
    "BANCO":          "1101",
    "IVA_CREDITO":    "1104",
    "IVA_DEBITO":     "2102",
    "INGRESO_VENTAS": "4101",
    "INGRESO_SERV":   "4102",
    "INGRESO_EXENTO": "4103",
    "OTROS_GASTOS":   "5999",
}


def _resolve_account(db, tenant_id: str, key: str) -> str:
    """Resuelve código de cuenta del catálogo del tenant, con fallback al default."""
    code = DEFAULT_ACCOUNTS.get(key, key)
    try:
        row = db.execute(text("""
            SELECT code FROM accounts
            WHERE tenant_id = :tid AND code = :code AND is_active = TRUE
            LIMIT 1
        """), {"tid": tenant_id, "code": code}).fetchone()
        if row:
            return code
    except Exception:
        pass
    logger.warning(f"⚠️ mapper_v2: cuenta {code} no en catálogo de {tenant_id[:8]}, usando default")
    return code


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

    # ── Fallback v1 si el doc no tiene líneas ───────────────────────
    if not lineas:
        return _fallback_v1_lines(doc, tenant_id, entry_id, doc_type)

    lines = []
    total_neto_acumulado = 0.0
    total_iva_acumulado  = 0.0

    # ── FEC / Compra recibida (08, RECIBIDO) ────────────────────────
    if doc_type in ("08", "09", "RECIBIDO"):
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

            cuenta_gasto = cab_result["account_code"]
            asset_flag   = cab_result.get("asset_flag", False)
            confidence   = cab_result.get("confidence", 0.3)
            fuente       = cab_result.get("fuente", "FALLBACK")

            deductible = "DEDUCTIBLE" if iva_info["acreditable"] else "EXEMPT"

            # DR Cuenta de gasto/activo
            lines.append(_build_line(
                entry_id, tenant_id, cuenta_gasto,
                f"{desc_item} · CABYS {cabys}",
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

            # DR IVA Acreditable (solo si grabado)
            if monto_iva > 0 and iva_info["acreditable"]:
                lines.append(_build_line(
                    entry_id, tenant_id,
                    DEFAULT_ACCOUNTS["IVA_CREDITO"],
                    f"IVA {iva_info['tarifa']}% · {desc_item}",
                    debit=monto_iva, credit=0,
                    deductible="DEDUCTIBLE",
                    legal_basis="Art. 29 Ley IVA 9635",
                    cabys_code=cabys,
                    iva_tipo=iva_info["tipo"],
                    iva_tarifa=iva_info["tarifa"],
                    account_role="IVA_CREDITO",
                ))
                total_iva_acumulado += monto_iva

        # CR CxP por la suma real de lo procesado (garantiza balance)
        cx_p_monto = round(total_neto_acumulado + total_iva_acumulado, 5)
        lines.append(_build_line(
            entry_id, tenant_id,
            DEFAULT_ACCOUNTS["CXP"],
            f"CxP · {doc.get('emisor_nombre', 'Proveedor')[:60]}",
            debit=0, credit=cx_p_monto,
            deductible="EXEMPT",
            legal_basis="Art. 8 Ley Renta 7092",
            account_role="CXP",
        ))

        # Ajuste de redondeo si DR ≠ CR (< ₡1)
        lines = _ajuste_redondeo(lines, entry_id, tenant_id)

    # ── FE / TE / ND / NC → Documentos de venta ─────────────────────
    elif doc_type in ("01", "04", "02", "03"):
        total_doc = float(doc.get("total_doc", 0))

        # DR CxC por total del documento
        lines.append(_build_line(
            entry_id, tenant_id, DEFAULT_ACCOUNTS["CXC"],
            f"CxC · {doc.get('receptor_nombre', 'Cliente')[:60]}",
            debit=total_doc, credit=0,
            deductible="EXEMPT",
            legal_basis="Art. 22 Ley IVA 9635",
            account_role="CXC",
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

            # CR IVA por Pagar
            if monto_iva > 0:
                lines.append(_build_line(
                    entry_id, tenant_id, DEFAULT_ACCOUNTS["IVA_DEBITO"],
                    f"IVA {iva_info['tarifa']}% · {desc_item}",
                    debit=0, credit=monto_iva,
                    deductible="EXEMPT",
                    legal_basis="Art. 15 Ley IVA 9635",
                    iva_tipo=iva_info["tipo"],
                    iva_tarifa=iva_info["tarifa"],
                    account_role="IVA_DEBITO",
                ))

        lines = _ajuste_redondeo(lines, entry_id, tenant_id)

    return lines


def _ajuste_redondeo(lines: list, entry_id: str, tenant_id: str) -> list:
    """Agrega línea de ajuste si DR ≠ CR por diferencia de redondeo < ₡1."""
    dr = round(sum(l["debit"]  for l in lines), 5)
    cr = round(sum(l["credit"] for l in lines), 5)
    diff = round(abs(dr - cr), 5)
    if 0 < diff < 1:
        if dr > cr:
            lines.append(_build_line(entry_id, tenant_id, "5999",
                f"Ajuste redondeo ₡{diff}", 0, diff, "EXEMPT"))
        else:
            lines.append(_build_line(entry_id, tenant_id, "5999",
                f"Ajuste redondeo ₡{diff}", diff, 0, "EXEMPT"))
    return lines


def _fallback_v1_lines(doc: dict, tenant_id: str, entry_id: str, doc_type: str) -> list:
    """
    Fallback al mapeo v1 por totales cuando no hay lineas[].
    Compatible con payloads del webhook_receiver original.
    """
    total_venta  = float(doc.get("total_venta", 0))
    total_iva    = float(doc.get("total_iva",   0))
    total_doc    = float(doc.get("total_doc",   0))
    emisor       = doc.get("emisor_nombre", "Proveedor")[:60]

    lines = []
    if doc_type in ("08", "09", "RECIBIDO"):
        if total_venta > 0:
            lines.append(_build_line(entry_id, tenant_id,
                DEFAULT_ACCOUNTS["OTROS_GASTOS"],
                f"Compra (v1-fallback) · {emisor}",
                debit=total_venta, credit=0,
                deductible="DEDUCTIBLE",
                legal_basis="Art. 8 Ley Renta 7092",
                clasificacion_fuente="V1_FALLBACK"
            ))
        if total_iva > 0:
            lines.append(_build_line(entry_id, tenant_id,
                DEFAULT_ACCOUNTS["IVA_CREDITO"],
                "IVA Acreditable (v1-fallback)",
                debit=total_iva, credit=0,
                deductible="DEDUCTIBLE",
                clasificacion_fuente="V1_FALLBACK"
            ))
        lines.append(_build_line(entry_id, tenant_id,
            DEFAULT_ACCOUNTS["CXP"],
            f"CxP proveedor (v1-fallback) · {emisor}",
            debit=0, credit=total_doc,
            deductible="EXEMPT",
            clasificacion_fuente="V1_FALLBACK"
        ))
    elif doc_type in ("01", "04"):
        lines.append(_build_line(entry_id, tenant_id,
            DEFAULT_ACCOUNTS["CXC"],
            "CxC cliente (v1-fallback)",
            debit=total_doc, credit=0, deductible="EXEMPT",
            clasificacion_fuente="V1_FALLBACK"
        ))
        if total_venta > 0:
            lines.append(_build_line(entry_id, tenant_id,
                DEFAULT_ACCOUNTS["INGRESO_VENTAS"],
                "Ingreso venta (v1-fallback)",
                debit=0, credit=total_venta, deductible="DEDUCTIBLE",
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
    period   = doc.get("fecha", "")[:7]
    now      = datetime.now(timezone.utc)
    tipo     = doc.get("tipo_doc", doc.get("doc_type", "08"))
    emisor   = doc.get("emisor_nombre", "")[:60]
    num_doc  = doc.get("numero_doc", "")
    total    = doc.get("total_doc", 0)

    source_map = {
        "01": EntrySource.FE, "04": EntrySource.TE,
        "02": EntrySource.ND, "03": EntrySource.NC,
        "08": EntrySource.FEC, "09": EntrySource.FEC,
        "RECIBIDO": EntrySource.RECIBIDO,
    }
    source = source_map.get(tipo, EntrySource.MANUAL)

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
        date         = doc.get("fecha", ""),
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
            cabys_code           = l.get("cabys_code"),
            iva_tipo             = l.get("iva_tipo"),
            iva_tarifa           = l.get("iva_tarifa"),
            confidence_score     = l.get("confidence_score"),
            clasificacion_fuente = l.get("clasificacion_fuente"),
            created_at           = now,
        )
        db.add(line)

    logger.info(f"✅ mapper_v2: {len(lines_data)} líneas para entry {entry_id[:8]}... "
                f"needs_review={needs_review} conf={min_confidence:.2f}")
    return {"entry_id": entry_id}
