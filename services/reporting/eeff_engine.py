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
                 to_date: Optional[str] = None,
                 entity_type: str = "PERSONA_JURIDICA"):
        self.tenant_id   = tenant_id
        self.year        = year
        self.db          = db
        self.from_date   = from_date or f"{year}-01-01"
        self.to_date     = to_date   or f"{year}-12-31"
        # NIIF Sec.22: Persona Jurídica → "Capital Social"
        #              Persona Física   → "Capital Personal"
        self.entity_type = entity_type
        self.capital_label = (
            "Capital Personal"
            if entity_type == "PERSONA_FISICA"
            else "Capital Social / Capital del propietario"
        )

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
        # ── Overrides de prefijo: corrección de último recurso ────────────
        # Aplica ANTES de consultar niif_mappings. Garantiza que los prefijos
        # críticos siempre aterricen en la línea NIIF correcta,
        # independientemente de lo que haya en la tabla niif_mappings.
        #
        # Causa raíz: seed_standard_mapping() y el wizard pueden haber
        # creado entradas con niif_line_code incorrecto (ej: 1201.04 →
        # ESF.AC.02) que sobreviven reinicios porque el try/except del
        # lifespan puede silenciar el fix de DB.
        #
        # Clave: código normalizado sin punto, 4 dígitos (ej: "1201.04" → "1201")
        NIIF_PREFIX_OVERRIDE: dict[str, tuple[str, bool]] = {
            # (niif_line_code, is_contra)
            # ── Activo No Corriente — PPE (Sec. 17) ──
            "1201": ("ESF.ANC.01", False),  # Vehículos, Terrenos, Edificios, Maquinaria
            "1202": ("ESF.ANC.01", True),   # Depreciación Acumulada PPE (contra)
            # ── Activo No Corriente — Intangibles (Sec. 18) ──
            "1203": ("ESF.ANC.03", False),  # Intangibles adquiridos
            "1601": ("ESF.ANC.03", False),  # Software
            "1602": ("ESF.ANC.03", False),  # Marcas y patentes
            "1690": ("ESF.ANC.03", True),   # Amortización acumulada intangibles
            # ── Activo No Corriente — Otros ──
            "1204": ("ESF.ANC.05", False),  # Inversiones en asociadas (Sec. 14)
            "1205": ("ESF.ANC.07", False),  # Otros ANC (CxC LP, Efectos LP)
            "1701": ("ESF.ANC.06", False),  # Activo por ISR diferido (Sec. 29)
            # ── Pasivo No Corriente ──
            "2201": ("ESF.PNC.01", False),  # Préstamos bancarios LP
            "2202": ("ESF.PNC.03", False),  # Provisión aguinaldo/cesantía LP
            "2203": ("ESF.PNC.04", False),  # Otros pasivos no corrientes
            "2701": ("ESF.PNC.02", False),  # Pasivo por ISR diferido
        }

        # Inicializar acumuladores para cada partida
        buckets: dict[str, Decimal] = defaultdict(Decimal)
        detail:  dict[str, list]    = defaultdict(list)
        unmapped_codes = []

        for code, saldo in trial_balance.items():
            # 1. Normalizar código: eliminar punto y tomar los primeros 4 dígitos
            #    "1201.04" → "120104"[:4] → "1201"
            #    "1202.03" → "120203"[:4] → "1202"
            prefix4_norm = code.replace(".", "")[:4]

            # 2. Aplicar override si el prefijo está en la tabla de correcciones
            if prefix4_norm in NIIF_PREFIX_OVERRIDE:
                niif_code, is_contra = NIIF_PREFIX_OVERRIDE[prefix4_norm]
            else:
                # 3. Buscar en niif_mappings (código exacto → prefijo con punto)
                mapping = mappings.get(code)
                if not mapping:
                    # Fallback: prefijo de 4 caracteres con punto (ej: "1201" de "1201.04")
                    prefix4_dot = code[:4] if len(code) >= 4 else code
                    mapping = mappings.get(prefix4_dot)
                if not mapping:
                    unmapped_codes.append(code)
                    continue

                niif_code = mapping["niif_line_code"]
                is_contra = mapping["is_contra"]

            acct_type = saldo["account_type"]

            # Saldo neto según naturaleza de la cuenta (NIIF Sec. 4)
            # ACTIVO/GASTO: saldo normal Deudor  → Debe - Haber = positivo
            # PASIVO/PAT/INGRESO: saldo normal Acreedor → Haber - Debe = positivo
            if acct_type in ("ACTIVO", "GASTO"):
                net = saldo["debit"] - saldo["credit"]   # DR normal
            else:
                net = saldo["credit"] - saldo["debit"]   # CR normal

            # Las contra-cuentas (ej. Dep. Acumulada) se restan de su partida NIIF
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
    # 3b. Saldos de cuentas de APERTURA del año actual
    # ─────────────────────────────────────────────────────────────
    def _get_opening_buckets(self, mappings: dict) -> dict:
        """
        Acumula los saldos de los asientos marcados como APERTURA (source='APERTURA')
        del año en curso. Estos representan el patrimonio al inicio del período
        y deben mostrarse como 'saldo_inicial' en el ECP (NIIF Sec.6),
        no como 'movimiento'.

        Solo aplica para cuentas de PATRIMONIO (prefijos 3xxx) para no
        contaminar el ESF con saldos de apertura dobles.
        """
        rows = self.db.execute(text("""
            SELECT
                jl.account_code,
                a.account_type,
                a.name AS account_name,
                COALESCE(SUM(jl.debit),  0) AS total_debit,
                COALESCE(SUM(jl.credit), 0) AS total_credit
            FROM journal_lines jl
            JOIN journal_entries je ON jl.entry_id = je.id
            JOIN accounts a ON a.code = jl.account_code AND a.tenant_id = je.tenant_id
            WHERE je.tenant_id = :tenant_id
              AND je.status    = 'POSTED'
              AND je.source    = 'APERTURA'
              AND je.date     >= :from_date
              AND je.date     <= :to_date
              AND a.account_type IN ('PATRIMONIO', 'ACTIVO', 'PASIVO')
            GROUP BY jl.account_code, a.account_type, a.name
            HAVING (SUM(jl.debit) != 0 OR SUM(jl.credit) != 0)
        """), {
            "tenant_id": self.tenant_id,
            "from_date": self.from_date,
            "to_date":   self.to_date,
        }).fetchall()

        if not rows:
            return {}

        opening_tb = {r[0]: {
            "account_code": r[0], "account_type": r[1], "account_name": r[2],
            "debit":  Decimal(str(r[3])), "credit": Decimal(str(r[4])),
            "balance": Decimal(str(r[3])) - Decimal(str(r[4])),
        } for r in rows}
        oa = self._accumulate(opening_tb, mappings)
        return {k: Decimal(str(v)) for k, v in oa["buckets"].items()}


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
    # 6. Construir ECP — Estado de Cambios en el Patrimonio
    # ─────────────────────────────────────────────────────────────
    def _build_ecp(self, buckets_current: dict, buckets_prior: dict,
                   buckets_opening: dict,
                   utilidad_neta: Decimal) -> dict:
        """
        Estado de Cambios en el Patrimonio — Sección 6 NIIF PYMES 3ª Ed.

        Lógica de Saldo Inicial:
        - Si hay saldos del año N-1 (buckets_prior): usar esos como saldo_inicial (año normal)
        - Si NO hay saldos N-1 (primer año): usar buckets_opening (asiento de apertura)
          como saldo_inicial y RESTAR del movimiento para no duplicar
        """
        has_prior = bool(buckets_prior)
        # Para primer año: el saldo inicial viene del asiento de apertura
        saldo_base = buckets_prior if has_prior else buckets_opening

        PAT_COLUMNS = [
            {"key": "capital",       "label": self.capital_label,       "codes": ["ESF.PAT.01"]},
            {"key": "reservas",      "label": "Reservas",               "codes": ["ESF.PAT.02"]},
            {"key": "utilidades_ac", "label": "Utilidades Acumuladas",  "codes": ["ESF.PAT.03"]},
            {"key": "resultado",     "label": "Resultado del Período",  "codes": ["ESF.PAT.04"]},
            {"key": "ori",           "label": "ORI Acumulado",          "codes": ["ESF.PAT.05"]},
        ]

        def get_bucket(b, codes):
            return sum(
                (b.get(c, Decimal("0")) if isinstance(b.get(c, Decimal("0")), Decimal)
                 else Decimal(str(b.get(c, 0))))
                for c in codes
            )

        rows = []
        for col in PAT_COLUMNS:
            inicial  = get_bucket(saldo_base,      col["codes"])
            current  = get_bucket(buckets_current, col["codes"])

            # Movimiento = variación respecto al inicio (excluye el saldo de apertura)
            if not has_prior:
                # Primer año: movimiento = total acumulado MENOS el saldo de apertura
                opening_amt = get_bucket(buckets_opening, col["codes"])
                movimiento = current - opening_amt
            else:
                movimiento = current - inicial

            row = {
                "key":           col["key"],
                "label":         col["label"],
                "saldo_inicial": float(inicial),
                "movimiento":    float(movimiento),
                "saldo_final":   float(current),
            }
            if col["key"] == "resultado":
                row["movimiento"] = float(utilidad_neta)
                row["saldo_inicial"] = 0.0   # resultado del período comienza en 0
                row["nota"] = "Según Estado de Resultado Integral"
            rows.append(row)

        total_inicial = sum(Decimal(str(r["saldo_inicial"])) for r in rows)
        total_final   = sum(Decimal(str(r["saldo_final"])) for r in rows)

        return {
            "columns":  rows,
            "totals":   {
                "total_inicial":    float(total_inicial),
                "total_movimiento": float(total_final - total_inicial),
                "total_final":      float(total_final),
            },
            "niif_ref": "Sec.6 NIIF PYMES 3ª Ed.",
        }

    # ─────────────────────────────────────────────────────────────
    # 7. Construir EFE — Flujos de Efectivo Método Indirecto
    # ─────────────────────────────────────────────────────────────
    def _build_efe(self, buckets_current: dict, buckets_prior: dict,
                   eri_totals: dict, esf_totals: dict) -> dict:
        """
        EFE Método Indirecto — Sección 7 NIIF PYMES 3ª Ed.
        Validación CRÍTICA: efectivo final calculado == ESF.AC.01 (efectivo en Balance)
        Nueva req. 3ª Ed. Sec. 7.14: conciliación de pasivos de financiación.
        """
        def get(b, code):
            v = b.get(code, Decimal("0"))
            return v if isinstance(v, Decimal) else Decimal(str(v))

        efectivo_final   = get(buckets_current, "ESF.AC.01")
        efectivo_inicial = get(buckets_prior,   "ESF.AC.01")

        # A — OPERACIÓN (método indirecto: parte de utilidad neta)
        utilidad_neta = Decimal(str(eri_totals.get("utilidad_neta", 0)))

        # Cambios en Capital de Trabajo (Delta activos corrientes operativos)
        delta_cxc    = -(get(buckets_current, "ESF.AC.02") - get(buckets_prior, "ESF.AC.02"))
        delta_inv    = -(get(buckets_current, "ESF.AC.03") - get(buckets_prior, "ESF.AC.03"))
        delta_oth_ac = -(get(buckets_current, "ESF.AC.07") - get(buckets_prior, "ESF.AC.07"))
        # Delta pasivos corrientes operativos
        delta_cxp    =  (get(buckets_current, "ESF.PC.01") - get(buckets_prior, "ESF.PC.01"))
        delta_prv    =  (get(buckets_current, "ESF.PC.04") - get(buckets_prior, "ESF.PC.04"))
        delta_isr    =  (get(buckets_current, "ESF.PC.05") - get(buckets_prior, "ESF.PC.05"))

        total_operacion = utilidad_neta + delta_cxc + delta_inv + delta_oth_ac + delta_cxp + delta_prv + delta_isr

        # B — INVERSIÓN
        delta_ppe    = -(get(buckets_current, "ESF.ANC.01") - get(buckets_prior, "ESF.ANC.01"))
        delta_int    = -(get(buckets_current, "ESF.ANC.03") - get(buckets_prior, "ESF.ANC.03"))
        delta_inv_lp = -(get(buckets_current, "ESF.ANC.05") - get(buckets_prior, "ESF.ANC.05"))
        total_inversion = delta_ppe + delta_int + delta_inv_lp

        # C — FINANCIACIÓN
        prest_lp_fin = get(buckets_current, "ESF.PNC.01")
        prest_lp_ini = get(buckets_prior,   "ESF.PNC.01")
        delta_prest  =  (prest_lp_fin - prest_lp_ini)
        delta_cap    =  (get(buckets_current, "ESF.PAT.01") - get(buckets_prior, "ESF.PAT.01"))
        delta_res    =  (get(buckets_current, "ESF.PAT.02") - get(buckets_prior, "ESF.PAT.02"))
        utl_ac_ini   = get(buckets_prior,   "ESF.PAT.03")
        utl_ac_fin   = get(buckets_current, "ESF.PAT.03")
        dividendos   = -(max(Decimal("0"), utl_ac_ini - utl_ac_fin))
        total_financiacion = delta_prest + delta_cap + delta_res + dividendos

        # Conciliación de efectivo
        cambio_neto = total_operacion + total_inversion + total_financiacion
        efectivo_final_calculado = efectivo_inicial + cambio_neto
        diff = abs(efectivo_final_calculado - efectivo_final)
        cash_ok = diff <= TOLERANCE

        return {
            "metodo": "indirecto",
            "operacion": {
                "items": [
                    {"label": "Utilidad (Pérdida) neta del período",   "amount": float(utilidad_neta),  "type": "inicio"},
                    {"label": "Cambio en Deudores comerciales (CxC)",  "amount": float(delta_cxc),     "type": "capital_trabajo"},
                    {"label": "Cambio en Inventarios",                  "amount": float(delta_inv),     "type": "capital_trabajo"},
                    {"label": "Cambio en Otros activos corrientes",     "amount": float(delta_oth_ac),  "type": "capital_trabajo"},
                    {"label": "Cambio en Acreedores comerciales (CxP)","amount": float(delta_cxp),     "type": "capital_trabajo"},
                    {"label": "Cambio en Provisiones corrientes",       "amount": float(delta_prv),     "type": "capital_trabajo"},
                    {"label": "Cambio en ISR por pagar",               "amount": float(delta_isr),     "type": "capital_trabajo"},
                ],
                "total": float(total_operacion),
            },
            "inversion": {
                "items": [
                    {"label": "Compra neta de PPE",                    "amount": float(delta_ppe),     "type": "inversion"},
                    {"label": "Compra neta de Intangibles",             "amount": float(delta_int),     "type": "inversion"},
                    {"label": "Movimiento en Inversiones LP",           "amount": float(delta_inv_lp),  "type": "inversion"},
                ],
                "total": float(total_inversion),
            },
            "financiacion": {
                "items": [
                    {"label": "Préstamos netos (obtenidos/pagados)",    "amount": float(delta_prest),   "type": "financiacion"},
                    {"label": "Aportes de capital",                     "amount": float(delta_cap),     "type": "financiacion"},
                    {"label": "Dividendos pagados",                     "amount": float(dividendos),    "type": "financiacion"},
                    {"label": "Variación en reservas",                  "amount": float(delta_res),     "type": "financiacion"},
                ],
                "total": float(total_financiacion),
            },
            "conciliacion": {
                "efectivo_inicial":               float(efectivo_inicial),
                "total_actividades_operacion":     float(total_operacion),
                "total_actividades_inversion":     float(total_inversion),
                "total_actividades_financiacion":  float(total_financiacion),
                "cambio_neto_efectivo":             float(cambio_neto),
                "efectivo_final_calculado":         float(efectivo_final_calculado),
                "efectivo_final_esf":               float(efectivo_final),
                "diferencia":                       float(diff),
                "efe_cash_matches":                 cash_ok,
            },
            # Nueva req. 3ª Ed. Sec. 7.14: conciliación pasivos de financiación
            "conciliacion_pasivos_fin": [
                {"label": "Préstamos LP — Saldo Inicial",    "amount": float(prest_lp_ini)},
                {"label": "Nuevos préstamos obtenidos",     "amount": float(max(Decimal("0"), delta_prest))},
                {"label": "Pagos de capital",               "amount": float(min(Decimal("0"), delta_prest))},
                {"label": "Préstamos LP — Saldo Final",     "amount": float(prest_lp_fin)},
            ],
            "niif_ref": "Sec.7 NIIF PYMES 3ª Ed.",
            "warnings": [] if cash_ok else [
                f"⚠️ Diferencia EFE vs ESF: {float(diff):,.2f} — revisar mapeo"
            ],
        }

    # ─────────────────────────────────────────────────────────────
    # 8. Saldos del año anterior para EFE + ECP
    # ─────────────────────────────────────────────────────────────
    def _get_prior_year_buckets(self, mappings: dict) -> dict:
        """Saldos anuales del año anterior (N-1) para comparativo y deltas."""
        py = str(int(self.year) - 1)
        rows = self.db.execute(text("""
            SELECT jl.account_code, a.account_type, a.name,
                   COALESCE(SUM(jl.debit),0), COALESCE(SUM(jl.credit),0)
            FROM journal_lines jl
            JOIN journal_entries je ON jl.entry_id = je.id
            JOIN accounts a ON a.code = jl.account_code AND a.tenant_id = je.tenant_id
            WHERE je.tenant_id = :tid
              AND je.status = 'POSTED'
              AND je.date >= :f AND je.date <= :t
              AND jl.account_code NOT IN ('3304')
            GROUP BY jl.account_code, a.account_type, a.name
            HAVING (SUM(jl.debit) != 0 OR SUM(jl.credit) != 0)
        """), {"tid": self.tenant_id, "f": f"{py}-01-01", "t": f"{py}-12-31"}).fetchall()

        if not rows:
            return {}
        prior_tb = {r[0]: {
            "account_code": r[0], "account_type": r[1], "account_name": r[2],
            "debit":  Decimal(str(r[3])), "credit": Decimal(str(r[4])),
            "balance": Decimal(str(r[3])) - Decimal(str(r[4])),
        } for r in rows}
        pa = self._accumulate(prior_tb, mappings)
        return {k: Decimal(str(v)) for k, v in pa["buckets"].items()}

    # ─────────────────────────────────────────────────────────────
    # 9. Punto de entrada principal — genera los 4 EEFF con comparativo
    # ─────────────────────────────────────────────────────────────
    def compute(self) -> dict:
        """Genera ESF + ERI + ECP + EFE desde el balance de comprobación.
        Incluye prior_amount en cada línea ESF/ERI para comparativo N-1."""
        trial_balance = self._get_trial_balance()
        mappings      = self._get_mappings()
        accum         = self._accumulate(trial_balance, mappings)
        buckets  = {k: Decimal(str(v)) for k, v in accum["buckets"].items()}
        detail   = accum["detail"]
        unmapped = accum["unmapped_codes"]

        buckets_prior   = self._get_prior_year_buckets(mappings)
        buckets_opening = self._get_opening_buckets(mappings)

        esf = self._build_esf(buckets, detail)
        eri = self._build_eri(buckets, detail)

        # ── Inyectar Resultado del Período en ESF.PAT.04 ─────────────
        # Durante el año (sin asiento de cierre) la utilidad/pérdida vive en
        # las cuentas 4xxx/5xxx (ERI). ESF.PAT.04 queda en ¢0 hasta el cierre.
        # Para que el ESF cierre (A = P + PAT) se inyecta la utilidad del ERI.
        # Idéntico al comportamiento de SAP B1, Defontana, QuickBooks Avanzado:
        # el motor ES quien "pre-cierra" el resultado en el Balance.
        utilidad_neta_eri = Decimal(str(eri["totals"]["utilidad_neta"]))
        if buckets.get("ESF.PAT.04", Decimal("0")) == Decimal("0") and utilidad_neta_eri != Decimal("0"):
            buckets["ESF.PAT.04"] = utilidad_neta_eri
            esf = self._build_esf(buckets, detail)   # reconstruir con bucket actualizado

        ecp = self._build_ecp(
            buckets_current=buckets,
            buckets_prior=buckets_prior,
            buckets_opening=buckets_opening,
            utilidad_neta=Decimal(str(eri["totals"]["utilidad_neta"])),
        )
        efe = self._build_efe(
            buckets_current=buckets,
            buckets_prior=buckets_prior,
            eri_totals=eri["totals"],
            esf_totals=esf["totals"],
        )

        # ── Enriquecer líneas con prior_amount para comparativo N-1 ──
        has_prior = bool(buckets_prior)
        if has_prior:
            for sk in ("activo_corriente","activo_no_corriente",
                       "pasivo_corriente","pasivo_no_corriente","patrimonio"):
                for line in esf.get(sk, []):
                    line["prior_amount"] = float(
                        buckets_prior.get(line["code"], Decimal("0")))
            for sk in ("ingresos","costos","gastos_operativos",
                       "gastos_financieros","impuesto_renta","otro_resultado"):
                for line in eri.get(sk, []):
                    line["prior_amount"] = float(
                        buckets_prior.get(line["code"], Decimal("0")))

            def p(code): return float(buckets_prior.get(code, Decimal("0")))

            esf["prior_totals"] = {
                "total_activo_corriente":    sum(p(l["code"]) for l in esf["activo_corriente"]),
                "total_activo_no_corriente": sum(p(l["code"]) for l in esf["activo_no_corriente"]),
                "total_activos":             sum(p(l["code"]) for l in esf["activo_corriente"]+esf["activo_no_corriente"]),
                "total_pasivo_corriente":    sum(p(l["code"]) for l in esf["pasivo_corriente"]),
                "total_pasivo_no_corriente": sum(p(l["code"]) for l in esf["pasivo_no_corriente"]),
                "total_pasivos":             sum(p(l["code"]) for l in esf["pasivo_corriente"]+esf["pasivo_no_corriente"]),
                "total_patrimonio":          sum(p(l["code"]) for l in esf["patrimonio"]),
            }
            eri["prior_totals"] = {
                "total_ingresos":   sum(p(l["code"]) for l in eri["ingresos"]),
                "total_costo":      sum(p(l["code"]) for l in eri["costos"]),
                "total_gastos_op":  sum(p(l["code"]) for l in eri["gastos_operativos"]),
                "total_gastos_fin": sum(p(l["code"]) for l in eri["gastos_financieros"]),
                "total_isr":        sum(p(l["code"]) for l in eri["impuesto_renta"]),
            }

        return {
            "ok":           True,
            "year":         self.year,
            "prior_year":   str(int(self.year) - 1),
            "has_prior":    has_prior,
            "from_date":    self.from_date,
            "to_date":      self.to_date,
            "niif_edition": "3rd_2025",
            "esf":   esf,
            "eri":   eri,
            "ecp":   ecp,
            "efe":   efe,
            "warnings": {
                "unmapped_accounts":  unmapped,
                "has_unmapped":       len(unmapped) > 0,
                "esf_balanced":       esf["totals"]["balanced"],
                "efe_cash_matches":   efe["conciliacion"]["efe_cash_matches"],
                "efe_warnings":       efe.get("warnings", []),
            },
            "metadata": {
                "total_accounts_in_tb": len(trial_balance),
                "mapped_accounts":      len(trial_balance) - len(unmapped),
                "unmapped_count":       len(unmapped),
                "has_comparative":      has_prior,
            }
        }
