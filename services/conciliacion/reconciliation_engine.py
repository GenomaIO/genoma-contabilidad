"""
reconciliation_engine.py — Motor de Matching Bancario vs. Libro Diario

Compara las transacciones del PDF contra los asientos contabilizados
en el período, usando fuzzy matching por fecha ± monto.

Estados de match:
  CONCILIADO   - Fecha ±3 días + monto exacto (100% confianza)
  PROBABLE     - Mismo período + monto ±1%   (75% confianza)
  SIN_ASIENTO  - En banco, no en libros → candidato para nuevo asiento
  SOLO_LIBROS  - En libros, no en banco → posible cheque pendiente
"""
from __future__ import annotations
import logging
from datetime import date, timedelta
from decimal import Decimal

logger = logging.getLogger(__name__)

UMBRAL_EXACTO   = 0.001   # 0.1% tolerancia de monto (±₡10 en ₡10,000)
UMBRAL_PROBABLE = 0.010   # 1.0% tolerancia de monto ampliada
DIAS_EXACTO     = 3       # ±3 días para match exacto
DIAS_PROBABLE   = 7       # ±7 días para match probable


def _fecha(s: str) -> date:
    """Convierte string 'YYYY-MM-DD' a date."""
    from datetime import datetime
    return datetime.strptime(s, "%Y-%m-%d").date()


def _diff_pct(a: float, b: float) -> float:
    """Diferencia porcentual absoluta entre dos montos."""
    if b == 0:
        return 1.0 if a != 0 else 0.0
    return abs(a - b) / abs(b)


def match_transactions(
    bank_txns: list[dict],
    journal_lines: list[dict]
) -> list[dict]:
    """
    Hace el matching entre transacciones bancarias y líneas del Libro Diario.

    Args:
        bank_txns:     Lista de transacciones del PDF (output de bank_pdf_parser)
        journal_lines: Lista de asientos del Libro Diario del mismo período.
                       Cada item: {id, date, description, debit, credit, account_code}

    Returns:
        Lista de transacciones enriquecidas con campos de match.
    """
    unmatched_journal = list(journal_lines)  # copia para marcar usados
    results = []

    for txn in bank_txns:
        try:
            txn_fecha = _fecha(txn["fecha"])
            txn_monto = float(txn["monto"])
            txn_tipo  = txn["tipo"]  # CR o DB

            best_match = None
            best_conf  = 0.0
            best_estado = "SIN_ASIENTO"

            for i, jl in enumerate(unmatched_journal):
                try:
                    jl_fecha = _fecha(jl.get("date", jl.get("fecha", "")))
                except Exception:
                    continue

                # Determinar el monto relevante según tipo
                if txn_tipo == "CR":
                    jl_monto = float(jl.get("credit", jl.get("credito", 0)) or 0)
                else:
                    jl_monto = float(jl.get("debit", jl.get("debito", 0)) or 0)

                if jl_monto <= 0:
                    continue

                diff_dias  = abs((txn_fecha - jl_fecha).days)
                diff_monto = _diff_pct(txn_monto, jl_monto)

                # Match exacto
                if diff_dias <= DIAS_EXACTO and diff_monto <= UMBRAL_EXACTO:
                    confianza = 1.0 - (diff_dias / 100) - diff_monto
                    if confianza > best_conf:
                        best_conf   = confianza
                        best_match  = (i, jl)
                        best_estado = "CONCILIADO"

                # Match probable (si no tenemos uno exacto aún)
                elif best_estado != "CONCILIADO" and diff_dias <= DIAS_PROBABLE and diff_monto <= UMBRAL_PROBABLE:
                    confianza = 0.75 - (diff_dias / 200) - diff_monto
                    if confianza > best_conf:
                        best_conf   = confianza
                        best_match  = (i, jl)
                        best_estado = "PROBABLE"

            enriched = dict(txn)
            if best_match:
                idx, jl = best_match
                enriched["match_estado"]     = best_estado
                enriched["match_confianza"]  = round(best_conf * 100, 1)
                enriched["matched_entry_id"] = jl.get("id") or jl.get("entry_id")
                # Marcar como usado para no hacer doble match
                unmatched_journal.pop(idx)
            else:
                enriched["match_estado"]    = "SIN_ASIENTO"
                enriched["match_confianza"] = 0.0
                enriched["matched_entry_id"] = None

            results.append(enriched)

        except Exception as exc:
            logger.warning(f"Match error en txn {txn.get('fecha')}/{txn.get('monto')}: {exc}")
            txn["match_estado"]    = "ERROR"
            txn["match_confianza"] = 0.0
            results.append(txn)

    return results


def find_solo_libros(
    bank_txns: list[dict],
    journal_lines: list[dict]
) -> list[dict]:
    """
    Identifica asientos del Libro Diario que NO tienen correspondencia en el banco.
    Estos pueden ser:
    - Cheques emitidos aún sin cobrar
    - Errores de registro
    - Partidas pendientes de acreditación

    Returns:
        Lista de journal_lines sin match bancario.
    """
    matched_ids = {
        txn["matched_entry_id"]
        for txn in bank_txns
        if txn.get("matched_entry_id")
    }

    solo_libros = []
    for jl in journal_lines:
        jl_id = jl.get("id") or jl.get("entry_id")
        if jl_id not in matched_ids:
            jl = dict(jl)
            jl["match_estado"] = "SOLO_LIBROS"

            # Flag si lleva muchos días sin cobrar
            try:
                from datetime import datetime
                jl_fecha = datetime.strptime(
                    jl.get("date", jl.get("fecha", "")), "%Y-%m-%d"
                ).date()
                dias = (date.today() - jl_fecha).days
                jl["dias_pendiente"] = dias
                if dias > 60:
                    jl["alerta"] = f"⚠️ Sin cobrar {dias} días"
            except Exception:
                jl["dias_pendiente"] = 0

            solo_libros.append(jl)

    return solo_libros


def calcular_diferencia_saldo(
    saldo_banco_final: float,
    saldo_libros: float
) -> dict:
    """
    Calcula la diferencia entre saldo bancario y saldo en libros.

    Returns:
        dict con diferencia, estado y observación.
    """
    diff = saldo_banco_final - saldo_libros
    if abs(diff) < 1.0:
        estado = "CUADRADO"
        obs    = "✅ Saldo bancario cuadra con el Libro Mayor"
    elif abs(diff) < 50_000:
        estado = "DIFERENCIA_MENOR"
        obs    = f"🟡 Diferencia de ₡{abs(diff):,.0f} — revisar centavos o ajustes"
    else:
        estado = "DIFERENCIA_SIGNIFICATIVA"
        obs    = f"🔴 Diferencia de ₡{abs(diff):,.0f} — requiere investigación"

    return {
        "saldo_banco":  saldo_banco_final,
        "saldo_libros": saldo_libros,
        "diferencia":   diff,
        "estado":       estado,
        "observacion":  obs,
    }
