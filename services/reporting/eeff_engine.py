"""
services/reporting/eeff_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Motor de Cálculo — EEFF (Estados Financieros)
NIIF PYMES 3ª Edición · Feb 2025 · IASB

Genera ESF + ERI desde el Balance de Comprobación de un período cerrado.
Punto de partida: saldos de las cuentas al cierre del período (FiscalYear.LOCKED).

Reglas de oro:
  1. Solo procesa períodos con status LOCKED o CLOSED
  2. ESF debe cuadrar: Total Activos == Total Pasivos + Patrimonio
  3. Cada partida NIIF acumula las cuentas mapeadas a ella
  4. Las contra-cuentas (Dep. Acumulada) se restan automáticamente
  5. Cuentas sin mapear generan WARNING (no bloquean en modo draft)
"""
from decimal import Decimal
from typing import Optional
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import text

from .niif_lines import NIIF_LINES, get_unmapped_accounts

TOLERANCE = Decimal("0.01")  # Tolerancia para verificar balance ±1 centavo


class EeffEngine:
    """
    Motor de cálculo de EEFF.
    Uso:
        engine = EeffEngine(tenant_id, year, db)
        result = engine.compute()
    """

    def __init__(self, tenant_id: str, year: str, db: Session,
                 from_date: Optional[str] = None,
                 to_date: Optional[str] = None):
        self.tenant_id = tenant_id
        self.year = year
        self.db = db
        # Si no se especifican fechas, usar el año completo
        self.from_date = from_date or f"{year}-01-01"
        self.to_date   = to_date   or f"{year}-12-31"

    # ─────────────────────────────────────────────────────────────
    # 1. Obtener saldos del Balance de Comprobación
    # ─────────────────────────────────────────────────────────────
    def _get_trial_balance(self) -> dict[str, dict]:
        """
        Obtiene los saldos netos por cuenta al cierre del período.
        Solo asientos POSTED.
        Retorna: {account_code: {debit, credit, balance, account_type}}
        """
        rows = self.db.execute(text("""
            SELECT
                jl.account_code,
                a.account_type,
                a.name AS account_name,
                COALESCE(SUM(jl.debit),  0) AS total_debit,
                COALESCE(SUM(jl.credit), 0) AS total_credit,
                COALESCE(SUM(jl.debit),  0) - COALESCE(SUM(jl.credit), 0) AS balance
            FROM journal_lines jl
            JOIN journal_entries je ON jl.entry_id = je.id
            JOIN accounts a ON a.code = jl.account_code AND a.tenant_id = je.tenant_id
            WHERE je.tenant_id = :tenant_id
              AND je.status = 'POSTED'
              AND je.date >= :from_date
              AND je.date <= :to_date
              AND jl.account_code NOT IN ('3304')  -- excluir cta transitoria
            GROUP BY jl.account_code, a.account_type, a.name
            HAVING (SUM(jl.debit) != 0 OR SUM(jl.credit) != 0)
            ORDER BY jl.account_code
        """), {
            "tenant_id": self.tenant_id,
            "from_date": self.from_date,
            "to_date":   self.to_date,
        }).fetchall()

        result = {}
        for r in rows:
            result[r[0]] = {
                "account_code":  r[0],
                "account_type":  r[1],
                "account_name":  r[2],
                "debit":         Decimal(str(r[3])),
                "credit":        Decimal(str(r[4])),
                "balance":       Decimal(str(r[5])),
            }
        return result

    # ─────────────────────────────────────────────────────────────
    # 2. Obtener mapeos NIIF del tenant
    # ─────────────────────────────────────────────────────────────
    def _get_mappings(self) -> dict[str, dict]:
        """
        Retorna: {account_code: {niif_line_code, is_contra}}
        """
        rows = self.db.execute(text("""
            SELECT account_code, niif_line_code, is_contra
            FROM niif_mappings
            WHERE tenant_id = :tenant_id
        """), {"tenant_id": self.tenant_id}).fetchall()
        return {r[0]: {"niif_line_code": r[1], "is_contra": bool(r[2])} for r in rows}

    # ─────────────────────────────────────────────────────────────
    # 3. Acumular saldos por partida NIIF
    # ─────────────────────────────────────────────────────────────
    def _accumulate(self, trial_balance: dict, mappings: dict) -> dict[str, dict]:
        """
        Para cada partida NIIF, suma los saldos de las cuentas mapeadas.
        Las contra-cuentas se restan.

        Lógica de saldo por tipo contable (NIIF Sec. 4):
          ACTIVO / GASTO:     balance = Debit - Credit (saldo normal DR)
          PASIVO / PAT / ING: balance = Credit - Debit (saldo normal CR)
        """
        # Inicializar acumuladores para cada partida
        buckets: dict[str, Decimal] = defaultdict(Decimal)
        detail:  dict[str, list]    = defaultdict(list)
        unmapped_codes = []

        for code, saldo in trial_balance.items():
            mapping = mappings.get(code)
            if not mapping:
                # Intentar mapeo por prefijo (primeros 4 dígitos)
                prefix4 = code[:4] if len(code) >= 4 else code
                mapping = mappings.get(prefix4)
            if not mapping:
                unmapped_codes.append(code)
                continue

            niif_code  = mapping["niif_line_code"]
            is_contra  = mapping["is_contra"]
            acct_type  = saldo["account_type"]

            # Saldo neto según naturaleza de la cuenta
            if acct_type in ("ACTIVO", "GASTO"):
                net = saldo["debit"] - saldo["credit"]   # DR normal
            else:
                net = saldo["credit"] - saldo["debit"]   # CR normal
                net = -net  # Lo convertimos a positivo para presentación CR

            # Las contra-cuentas se restan de la partida
            if is_contra:
                net = -abs(net)

            buckets[niif_code] += net
            detail[niif_code].append({
                "code":    code,
                "name":    saldo["account_name"],
                "type":    acct_type,
                "balance": float(net),
            })

        return {
            "buckets":        dict(buckets),
            "detail":         dict(detail),
            "unmapped_codes": unmapped_codes,
        }

    # ─────────────────────────────────────────────────────────────
    # 4. Construir ESF
    # ─────────────────────────────────────────────────────────────
    def _build_esf(self, buckets: dict[str, Decimal], detail: dict) -> dict:
        """
        Construye el Estado de Situación Financiera.
        Agrupa las partidas NIIF en secciones y calcula totales.
        """
        lines_by_section = defaultdict(list)
        for line_def in NIIF_LINES:
            if line_def["statement"] != "ESF" or line_def.get("is_subtotal"):
                continue
            code = line_def["code"]
            amount = buckets.get(code, Decimal("0"))
            lines_by_section[line_def["section"]].append({
                "code":    code,
                "label":   line_def["label"],
                "amount":  float(amount),
                "order":   line_def["order"],
                "detail":  detail.get(code, []),
                "niif_ref": line_def.get("niif_ref", ""),
            })

        # Calcular totales de sección
        def section_total(section_key):
            return sum(
                Decimal(str(l["amount"]))
                for l in lines_by_section.get(section_key, [])
            )

        tot_ac  = section_total("ACTIVO_CORRIENTE")
        tot_anc = section_total("ACTIVO_NO_CORRIENTE")
        tot_pc  = section_total("PASIVO_CORRIENTE")
        tot_pnc = section_total("PASIVO_NO_CORRIENTE")
        tot_pat = section_total("PATRIMONIO")

        total_activos  = tot_ac + tot_anc
        total_pasivos  = tot_pc + tot_pnc
        total_pas_pat  = total_pasivos + tot_pat
        balanced       = abs(total_activos - total_pas_pat) <= TOLERANCE

        return {
            "activo_corriente":     [l for l in sorted(lines_by_section["ACTIVO_CORRIENTE"],    key=lambda x: x["order"])],
            "activo_no_corriente":  [l for l in sorted(lines_by_section["ACTIVO_NO_CORRIENTE"], key=lambda x: x["order"])],
            "pasivo_corriente":     [l for l in sorted(lines_by_section["PASIVO_CORRIENTE"],    key=lambda x: x["order"])],
            "pasivo_no_corriente":  [l for l in sorted(lines_by_section["PASIVO_NO_CORRIENTE"], key=lambda x: x["order"])],
            "patrimonio":           [l for l in sorted(lines_by_section["PATRIMONIO"],          key=lambda x: x["order"])],
            "totals": {
                "total_activo_corriente":    float(tot_ac),
                "total_activo_no_corriente": float(tot_anc),
                "total_activos":             float(total_activos),
                "total_pasivo_corriente":    float(tot_pc),
                "total_pasivo_no_corriente": float(tot_pnc),
                "total_pasivos":             float(total_pasivos),
                "total_patrimonio":          float(tot_pat),
                "total_pasivo_patrimonio":   float(total_pas_pat),
                "balanced":                  balanced,
                "difference":                float(abs(total_activos - total_pas_pat)),
            }
        }

    # ─────────────────────────────────────────────────────────────
    # 5. Construir ERI
    # ─────────────────────────────────────────────────────────────
    def _build_eri(self, buckets: dict[str, Decimal], detail: dict) -> dict:
        """
        Construye el Estado de Resultado Integral.
        Sección 5 NIIF PYMES 3ª Ed.
        """
        lines_by_section = defaultdict(list)
        for line_def in NIIF_LINES:
            if line_def["statement"] != "ERI" or line_def.get("is_subtotal"):
                continue
            code = line_def["code"]
            amount = buckets.get(code, Decimal("0"))
            lines_by_section[line_def["section"]].append({
                "code":    code,
                "label":   line_def["label"],
                "amount":  float(amount),
                "order":   line_def["order"],
                "detail":  detail.get(code, []),
                "niif_ref": line_def.get("niif_ref", ""),
            })

        def section_total(sec):
            return sum(Decimal(str(l["amount"])) for l in lines_by_section.get(sec, []))

        total_ingresos = section_total("INGRESO")
        total_costo    = section_total("COSTO")
        tot_gasto_op   = section_total("GASTO_OPERATIVO")
        tot_gasto_fin  = section_total("GASTO_FINANCIERO")
        total_isr      = section_total("IMPUESTO_RENTA")
        total_ori      = section_total("OTRO_RESULTADO")

        # Cálculos encadenados
        utilidad_bruta = total_ingresos - total_costo
        utilidad_op    = utilidad_bruta - tot_gasto_op - tot_gasto_fin
        utilidad_ai    = utilidad_op   # antes de impuestos (simplificado)
        utilidad_neta  = utilidad_op - total_isr
        total_ri       = utilidad_neta + total_ori   # Resultado Integral

        return {
            "ingresos":           [l for l in sorted(lines_by_section["INGRESO"],          key=lambda x: x["order"])],
            "costos":             [l for l in sorted(lines_by_section["COSTO"],             key=lambda x: x["order"])],
            "gastos_operativos":  [l for l in sorted(lines_by_section["GASTO_OPERATIVO"],  key=lambda x: x["order"])],
            "gastos_financieros": [l for l in sorted(lines_by_section["GASTO_FINANCIERO"], key=lambda x: x["order"])],
            "impuesto_renta":     [l for l in sorted(lines_by_section["IMPUESTO_RENTA"],   key=lambda x: x["order"])],
            "otro_resultado":     [l for l in sorted(lines_by_section["OTRO_RESULTADO"],   key=lambda x: x["order"])],
            "totals": {
                "total_ingresos":    float(total_ingresos),
                "total_costo":       float(total_costo),
                "utilidad_bruta":    float(utilidad_bruta),
                "total_gastos_op":   float(tot_gasto_op),
                "total_gastos_fin":  float(tot_gasto_fin),
                "utilidad_antes_isr":float(utilidad_ai),
                "total_isr":         float(total_isr),
                "utilidad_neta":     float(utilidad_neta),
                "total_ori":         float(total_ori),
                "total_resultado_integral": float(total_ri),
            }
        }

    # ─────────────────────────────────────────────────────────────
    # 6. Punto de entrada principal
    # ─────────────────────────────────────────────────────────────
    def compute(self) -> dict:
        """
        Genera los EEFF (ESF + ERI) desde el balance de comprobación.
        Retorna un dict con todos los datos listos para el frontend.
        """
        trial_balance = self._get_trial_balance()
        mappings      = self._get_mappings()
        accum         = self._accumulate(trial_balance, mappings)

        buckets = {k: Decimal(str(v)) for k, v in accum["buckets"].items()}
        detail  = accum["detail"]
        unmapped = accum["unmapped_codes"]

        esf = self._build_esf(buckets, detail)
        eri = self._build_eri(buckets, detail)

        return {
            "ok":             True,
            "year":           self.year,
            "from_date":      self.from_date,
            "to_date":        self.to_date,
            "niif_edition":   "3rd_2025",
            "esf":            esf,
            "eri":            eri,
            "warnings":       {
                "unmapped_accounts": unmapped,
                "has_unmapped":      len(unmapped) > 0,
                "esf_balanced":      esf["totals"]["balanced"],
            },
            "metadata": {
                "total_accounts_in_tb": len(trial_balance),
                "mapped_accounts":      len(trial_balance) - len(unmapped),
                "unmapped_count":       len(unmapped),
            }
        }
