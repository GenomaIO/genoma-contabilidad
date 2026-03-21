"""
Genoma Contabilidad — Gateway
Sistema contable NIIF PYMES · Hacienda v4.4 · Tribu-CR
"""
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from services.auth.database import init_db, get_session
from services.auth.router import router as auth_router
from services.catalog.router import router as catalog_router
from services.ledger.router import router as ledger_router
from services.integration.webhook_receiver import router as integration_router
from services.integration.router_pull      import router as pull_router
from services.assets.router import router as assets_router
from services.tax.router import router as tax_router
from services.reporting.router import router as reporting_router
from services.conciliacion.router import router as conciliacion_router
import services.catalog.models  # noqa: F401 — registra Account en Base para create_all
import services.ledger.models   # noqa: F401 — registra JournalEntry/JournalLine en Base
import services.ledger.audit_log  # noqa: F401 — registra AuditLog en Base
import services.reporting.models  # noqa: F401 — registra NiifMapping/EeffSnapshot en Base
import services.assets.models   # noqa: F401 — registra FixedAsset en Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")
_engine = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _engine
    logger.info("🚀 Genoma Contabilidad arrancando...")
    if DATABASE_URL:
        try:
            _engine = init_db()
            logger.info("✅ DB inicializada y tablas creadas")
        except Exception as e:
            logger.error(f"❌ Error inicializando DB: {e}")

        # ── Migración A0: catalog_mode en tenants ─────────────────
        # IF NOT EXISTS → idempotente, seguro en cada arranque.
        # catalog_mode NULL = tenant nuevo (trigger de onboarding en el frontend).
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
                    "catalog_mode VARCHAR(20) DEFAULT NULL"
                ))
            logger.info("✅ Migración A0: catalog_mode agregado a tenants")
        except Exception as e:
            logger.warning(f"⚠️  Migración A0 omitida: {e}")

        # ── Migración A0b: entity_type en tenants ─────────────────
        # PERSONA_JURIDICA = default (empresas); PERSONA_FISICA = propietario único.
        # Controla el label "Capital Social" vs "Capital Personal" en el ECP (NIIF Sec.22).
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
                    "entity_type VARCHAR(30) DEFAULT 'PERSONA_JURIDICA'"
                ))
            logger.info("✅ Migración A0b: entity_type agregado a tenants")
        except Exception as e:
            logger.warning(f"⚠️  Migración A0b omitida: {e}")

        # ── Migración A0c: Terminación de Actividades ──────────────
        # Campos en fiscal_years para Cierre por Terminación (Art.51 Ley 7092 / NIIF Sec.3.8).
        # Tenant.terminated_at para marcar fecha de cese.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE fiscal_years ADD COLUMN IF NOT EXISTS "
                    "termination_date VARCHAR(10) DEFAULT NULL"
                ))
                conn.execute(text(
                    "ALTER TABLE fiscal_years ADD COLUMN IF NOT EXISTS "
                    "termination_reason VARCHAR(200) DEFAULT NULL"
                ))
                conn.execute(text(
                    "ALTER TABLE fiscal_years ADD COLUMN IF NOT EXISTS "
                    "termination_by VARCHAR(36) DEFAULT NULL"
                ))
                conn.execute(text(
                    "ALTER TABLE fiscal_years ADD COLUMN IF NOT EXISTS "
                    "termination_at TIMESTAMP DEFAULT NULL"
                ))
                conn.execute(text(
                    "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS "
                    "terminated_at TIMESTAMP DEFAULT NULL"
                ))
            logger.info("✅ Migración A0c: columnas de terminación agregadas")
        except Exception as e:
            logger.warning(f"⚠️  Migración A0c omitida: {e}")


        # ── Migración A1: tabla accounts (catálogo de cuentas) ────
        # CREATE TABLE IF NOT EXISTS → idempotente.
        # La tabla se crea con create_all, pero los índices adicionales
        # se garantizan aquí para Render donde create_all puede omitir cambios.
        try:
            from sqlalchemy import text as _text
            with _engine.begin() as conn:
                conn.execute(_text("""
                    CREATE TABLE IF NOT EXISTS accounts (
                        id              VARCHAR(36) PRIMARY KEY,
                        tenant_id       VARCHAR(36) NOT NULL,
                        code            VARCHAR(20) NOT NULL,
                        name            VARCHAR(200) NOT NULL,
                        description     TEXT,
                        account_type    VARCHAR(20) NOT NULL,
                        account_sub_type VARCHAR(30),
                        parent_code     VARCHAR(20),
                        allow_entries   BOOLEAN NOT NULL DEFAULT TRUE,
                        is_active       BOOLEAN NOT NULL DEFAULT TRUE,
                        is_generic      BOOLEAN NOT NULL DEFAULT FALSE,
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ,
                        UNIQUE (tenant_id, code)
                    )
                """))
                conn.execute(_text(
                    "CREATE INDEX IF NOT EXISTS idx_accounts_tenant ON accounts(tenant_id)"
                ))
                conn.execute(_text(
                    "CREATE INDEX IF NOT EXISTS idx_accounts_type ON accounts(tenant_id, account_type)"
                ))
            logger.info("✅ Migración A1: tabla accounts creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración A1 omitida: {e}")

        # ── Migración M_ENUM: agregar valores al enum entrysource ──
        # Fix crítico: Postgres lanza DataError si se intenta insertar un valor
        # que no existe en el enum. ALTER TYPE ... ADD VALUE IF NOT EXISTS es
        # idempotente — no falla si el valor ya existe (Postgres 9.1+).
        # Valores nuevos: APERTURA (apertura de ejercicio) y CIERRE (cierre de período).
        try:
            with _engine.begin() as conn:
                # En Postgres, ALTER TYPE ADD VALUE no puede correr dentro de una
                # transacción explícita abierta. Usamos AUTOCOMMIT para este bloque.
                conn.execute(text(
                    "ALTER TYPE entrysource ADD VALUE IF NOT EXISTS 'APERTURA'"
                ))
                conn.execute(text(
                    "ALTER TYPE entrysource ADD VALUE IF NOT EXISTS 'CIERRE'"
                ))
            logger.info("✅ Migración M_ENUM: APERTURA y CIERRE agregados a entrysource")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_ENUM omitida (puede ser SQLite o valor ya existente): {e}")

        logger.warning("⚠️  DATABASE_URL no configurado")

        # ── Migración B1: tablas ledger ───────────────────────────
        try:
            from sqlalchemy import text as _text
            with _engine.begin() as conn:
                conn.execute(_text("""
                    CREATE TABLE IF NOT EXISTS journal_entries (
                        id           VARCHAR(36) PRIMARY KEY,
                        tenant_id    VARCHAR(36) NOT NULL,
                        period       VARCHAR(7)  NOT NULL,
                        date         VARCHAR(10) NOT NULL,
                        description  TEXT        NOT NULL,
                        status       VARCHAR(10) NOT NULL DEFAULT 'DRAFT',
                        source       VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
                        source_ref   VARCHAR(100),
                        created_by   VARCHAR(36) NOT NULL,
                        approved_by  VARCHAR(36),
                        approved_at  TIMESTAMPTZ,
                        voided_by    VARCHAR(36),
                        voided_at    TIMESTAMPTZ,
                        reversal_id  VARCHAR(36),
                        created_at   TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.execute(_text("""
                    CREATE TABLE IF NOT EXISTS journal_lines (
                        id                VARCHAR(36) PRIMARY KEY,
                        entry_id          VARCHAR(36) NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
                        tenant_id         VARCHAR(36) NOT NULL,
                        account_code      VARCHAR(20) NOT NULL,
                        description       TEXT,
                        debit             NUMERIC(18,5) NOT NULL DEFAULT 0,
                        credit            NUMERIC(18,5) NOT NULL DEFAULT 0,
                        deductible_status VARCHAR(20) DEFAULT 'PENDING',
                        legal_basis       VARCHAR(100),
                        dim_segment       VARCHAR(50),
                        dim_branch        VARCHAR(50),
                        dim_project       VARCHAR(50),
                        created_at        TIMESTAMPTZ DEFAULT NOW(),
                        CONSTRAINT chk_debit_or_credit CHECK (debit = 0 OR credit = 0)
                    )
                """))
                conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_je_tenant_period ON journal_entries(tenant_id, period)"))
                conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_je_tenant_status ON journal_entries(tenant_id, status)"))
                conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_je_source_ref    ON journal_entries(source_ref)"))
                conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_jl_entry_id      ON journal_lines(entry_id)"))
                conn.execute(_text("CREATE INDEX IF NOT EXISTS idx_jl_tenant_code   ON journal_lines(tenant_id, account_code)"))
            logger.info("✅ Migración B1: tablas journal_entries + journal_lines creadas/verificadas")
        except Exception as e:
            logger.warning(f"⚠️  Migración B1 omitida: {e}")

        # ── Migración B2: tabla audit_log ─────────────────────────
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id          VARCHAR(36)  PRIMARY KEY,
                        tenant_id   VARCHAR(36)  NOT NULL,
                        user_id     VARCHAR(36)  NOT NULL,
                        user_role   VARCHAR(20)  NOT NULL,
                        user_email  VARCHAR(200),
                        action      VARCHAR(40)  NOT NULL,
                        entity_type VARCHAR(50),
                        entity_id   VARCHAR(36),
                        before_json TEXT,
                        after_json  TEXT,
                        note        TEXT,
                        ip          VARCHAR(45),
                        created_at  TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_tenant_date ON audit_log(tenant_id, created_at)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_entity      ON audit_log(entity_type, entity_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_user        ON audit_log(user_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_action      ON audit_log(action)"))
            logger.info("✅ Migración B2: tabla audit_log creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración B2 omitida: {e}")

        # ── Migración M_ASSETS: tabla fixed_assets ────────────────
        # Activos Fijos NIIF PYMES Sección 17 — idempotente.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS fixed_assets (
                        id                    VARCHAR(36)  PRIMARY KEY,
                        tenant_id             VARCHAR(36)  NOT NULL,
                        categoria             VARCHAR(20)  NOT NULL DEFAULT 'OTRO',
                        nombre                VARCHAR(200) NOT NULL,
                        descripcion           TEXT,
                        numero_serie          VARCHAR(100),
                        ubicacion             VARCHAR(100),
                        proveedor             VARCHAR(200),
                        numero_factura        VARCHAR(100),
                        account_code          VARCHAR(20)  NOT NULL,
                        dep_acum_code         VARCHAR(20)  NOT NULL,
                        dep_gasto_code        VARCHAR(20)  NOT NULL,
                        fecha_adquisicion     VARCHAR(10)  NOT NULL,
                        fecha_disponible      VARCHAR(10)  NOT NULL,
                        costo_historico       NUMERIC(18,5) NOT NULL,
                        valor_residual        NUMERIC(18,5) NOT NULL DEFAULT 0,
                        vida_util_meses       INTEGER      NOT NULL,
                        metodo_depreciacion   VARCHAR(30)  NOT NULL DEFAULT 'LINEA_RECTA',
                        dep_acum_apertura     NUMERIC(18,5) NOT NULL DEFAULT 0,
                        meses_usados_apertura INTEGER      NOT NULL DEFAULT 0,
                        apertura_line_id      VARCHAR(36),
                        estado                VARCHAR(10)  NOT NULL DEFAULT 'ACTIVO',
                        baja_fecha            VARCHAR(10),
                        baja_motivo           TEXT,
                        created_by            VARCHAR(36)  NOT NULL,
                        created_at            TIMESTAMPTZ  DEFAULT NOW(),
                        updated_at            TIMESTAMPTZ
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_fa_tenant "
                    "ON fixed_assets(tenant_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_fa_tenant_st "
                    "ON fixed_assets(tenant_id, estado)"
                ))
            logger.info("✅ Migración M_ASSETS: tabla fixed_assets creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_ASSETS omitida: {e}")

        # ── Migración M_FISCAL_PROFILE: perfil fiscal por tenant ───────────
        # Almacena tipo de contribuyente (PJ/PF), gran contribuyente, mes de cierre.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS fiscal_profiles (
                        id                    TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id             TEXT UNIQUE NOT NULL,
                        taxpayer_type         TEXT NOT NULL DEFAULT 'PJ',
                        is_large_taxpayer     BOOLEAN NOT NULL DEFAULT FALSE,
                        fiscal_year_end_month INTEGER NOT NULL DEFAULT 9,
                        created_at            TIMESTAMPTZ DEFAULT NOW(),
                        updated_at            TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_fp_tenant ON fiscal_profiles(tenant_id)"
                ))
            logger.info("✅ Migración M_FISCAL_PROFILE: tabla fiscal_profiles creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_FISCAL_PROFILE omitida: {e}")

        # ── Migración M_PRORRATA: prorrata IVA por tenant (Art. 31 Ley 9635) ─
        # prorrata_iva: factor 0.0-1.0 que determina qué fracción del IVA pagado
        # en compras es acreditable. Default 1.0 = 100% acreditable (sin cambio).
        # Solo afecta a empresas con actividad mixta (gravada + exenta).
        # ALTER ... ADD COLUMN IF NOT EXISTS es idempotente — seguro en cada arranque.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE fiscal_profiles "
                    "ADD COLUMN IF NOT EXISTS prorrata_iva NUMERIC(5,4) DEFAULT 1.0"
                ))
            logger.info("✅ Migración M_PRORRATA: prorrata_iva agregada a fiscal_profiles")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_PRORRATA omitida: {e}")

        # ── Migración M_TAX_BRACKETS: tramos de renta por año/tipo ────────
        # El usuario gestiona estos datos desde la UI. Sin hardcode.
        # Los tramos 2026 se insertan bajo demanda via POST /tax/tax-brackets/prefill-2026.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS tax_brackets (
                        id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id     TEXT NOT NULL,
                        fiscal_year   INTEGER NOT NULL,
                        taxpayer_type TEXT NOT NULL,
                        income_from   NUMERIC(18,5) NOT NULL,
                        income_to     NUMERIC(18,5),
                        rate          NUMERIC(6,5) NOT NULL,
                        UNIQUE (tenant_id, fiscal_year, taxpayer_type, income_from)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_tb_tenant_year ON tax_brackets(tenant_id, fiscal_year)"
                ))
            logger.info("✅ Migración M_TAX_BRACKETS: tabla tax_brackets creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_TAX_BRACKETS omitida: {e}")

        # ── Migración M_ASSETS_V2: columna tasa_anual ─────────────
        # Modo Tasa Fiscal (Decreto 18455-H) — cuota constante.
        # ALTER ... IF NOT EXISTS es idempotente en Postgres 9.6+.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE fixed_assets "
                    "ADD COLUMN IF NOT EXISTS tasa_anual NUMERIC(5,2)"
                ))
            logger.info("✅ Migración M_ASSETS_V2: columna tasa_anual agregada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_ASSETS_V2 omitida: {e}")

        # ── Migración M_PERIOD: mes_inicio_periodo + period_locks ───
        # Cierre de período por mes → generación de libros digitales.
        # Art. 51 Ley Renta CR: Diario, Mayor, Inventarios y Balances.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE tenants "
                    "ADD COLUMN IF NOT EXISTS mes_inicio_periodo INTEGER DEFAULT 1"
                ))
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS period_locks (
                        id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id   TEXT NOT NULL,
                        year_month  TEXT NOT NULL,
                        status      TEXT NOT NULL DEFAULT 'OPEN',
                        closed_by   TEXT,
                        closed_at   TIMESTAMPTZ,
                        notes       TEXT,
                        UNIQUE(tenant_id, year_month)
                    )
                """))
            logger.info("✅ Migración M_PERIOD: mes_inicio_periodo + period_locks")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_PERIOD omitida: {e}")

        # ── Migración M_CONCILIACION: Conciliación Bancaria + CENTINELA ──
        # Tablas para el módulo de conciliación bancaria inteligente y el
        # detector de fugas fiscales CENTINELA. Idempotentes.
        try:
            with _engine.begin() as conn:
                # Sesiones de conciliación (una por PDF subido)
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bank_reconciliation (
                        id            TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id     TEXT NOT NULL,
                        period        TEXT NOT NULL,
                        banco         TEXT NOT NULL,
                        account_code  TEXT NOT NULL,
                        filename      TEXT,
                        saldo_inicial NUMERIC(18,2) DEFAULT 0,
                        saldo_final   NUMERIC(18,2) DEFAULT 0,
                        score_riesgo  INTEGER DEFAULT 0,
                        estado        TEXT NOT NULL DEFAULT 'PENDIENTE',
                        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_bankrecon_tenant_period "
                    "ON bank_reconciliation(tenant_id, period)"
                ))

                # Transacciones individuales del estado de cuenta PDF
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bank_transactions (
                        id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        recon_id         TEXT NOT NULL REFERENCES bank_reconciliation(id) ON DELETE CASCADE,
                        tenant_id        TEXT NOT NULL,
                        fecha            DATE NOT NULL,
                        descripcion      TEXT,
                        tipo             TEXT NOT NULL,
                        monto            NUMERIC(18,2) NOT NULL,
                        saldo            NUMERIC(18,2),
                        referencia       TEXT,
                        telefono         TEXT,
                        matched_entry_id TEXT,
                        match_estado     TEXT NOT NULL DEFAULT 'SIN_MATCH',
                        match_confianza  NUMERIC(5,2) DEFAULT 0,
                        fuga_tipo        TEXT,
                        score_puntos     INTEGER DEFAULT 0,
                        iva_estimado     NUMERIC(18,2) DEFAULT 0,
                        base_estimada    NUMERIC(18,2) DEFAULT 0,
                        d270_codigo      TEXT,
                        accion           TEXT,
                        accion_tomada    BOOLEAN DEFAULT FALSE,
                        ai_clasificacion TEXT,
                        ai_cuenta_hint   TEXT,
                        ai_confianza     NUMERIC(5,2) DEFAULT 0,
                        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_banktxn_recon "
                    "ON bank_transactions(recon_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_banktxn_tenant_fecha "
                    "ON bank_transactions(tenant_id, fecha)"
                ))

                # Reglas de clasificación aprendidas (Bank Rules)
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bank_rules (
                        id             TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id      TEXT NOT NULL,
                        pattern        TEXT NOT NULL,
                        pattern_type   TEXT NOT NULL DEFAULT 'description_contains',
                        contact_name   TEXT,
                        ledger_account TEXT,
                        d270_codigo    TEXT,
                        note           TEXT,
                        uses_count     INTEGER DEFAULT 0,
                        created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(tenant_id, pattern_type, pattern)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_bankrules_tenant "
                    "ON bank_rules(tenant_id)"
                ))

                # Score fiscal mensual por tenant (CENTINELA)
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS centinela_score (
                        id               TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id        TEXT NOT NULL,
                        period           TEXT NOT NULL,
                        score_total      INTEGER DEFAULT 0,
                        fugas_tipo_a     INTEGER DEFAULT 0,
                        fugas_tipo_b     INTEGER DEFAULT 0,
                        fugas_tipo_c     INTEGER DEFAULT 0,
                        exposicion_iva   NUMERIC(18,2) DEFAULT 0,
                        exposicion_renta NUMERIC(18,2) DEFAULT 0,
                        exposicion_total NUMERIC(18,2) DEFAULT 0,
                        d270_regs        INTEGER DEFAULT 0,
                        score_detalle    JSONB,
                        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        UNIQUE(tenant_id, period)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_centinela_tenant_period "
                    "ON centinela_score(tenant_id, period)"
                ))
            logger.info("✅ Migración M_CONCILIACION: bank_reconciliation, bank_transactions, bank_rules, centinela_score")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CONCILIACION omitida: {e}")

        # ── Migración M_CONC_V2: columnas faltantes en bank_transactions ──
        # La migración M_CONCILIACION creó bank_transactions sin las columnas:
        #   moneda, monto_orig_usd, tc_bccr, monto_crc, score_puntos,
        #   iva_estimado, base_estimada, accion, accion_tomada,
        #   ai_clasificacion, ai_cuenta_hint, ai_confianza
        # que el router bulk-insert necesita. ALTER ... ADD COLUMN IF NOT EXISTS
        # es idempotente — falla silenciosamente si la columna ya existe.
        try:
            with _engine.begin() as conn:
                _cols = [
                    ("moneda",          "VARCHAR(3)       DEFAULT 'CRC'"),
                    ("monto_crc",       "NUMERIC(18,2)    DEFAULT 0"),
                    ("monto_orig_usd",  "NUMERIC(18,2)"),
                    ("tc_bccr",         "NUMERIC(10,4)"),
                    ("score_puntos",    "INTEGER          DEFAULT 0"),
                    ("iva_estimado",    "NUMERIC(18,2)    DEFAULT 0"),
                    ("base_estimada",   "NUMERIC(18,2)    DEFAULT 0"),
                    ("accion",          "TEXT"),
                    ("accion_tomada",   "BOOLEAN          DEFAULT FALSE"),
                    ("ai_clasificacion","TEXT"),
                    ("ai_cuenta_hint",  "TEXT"),
                    ("ai_confianza",    "NUMERIC(5,2)     DEFAULT 0"),
                ]
                for col, typedef in _cols:
                    conn.execute(text(
                        f"ALTER TABLE bank_transactions "
                        f"ADD COLUMN IF NOT EXISTS {col} {typedef}"
                    ))
            logger.info("✅ Migración M_CONC_V2: columnas faltantes en bank_transactions agregadas")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CONC_V2 omitida: {e}")

        # ── Migración M_RECON_V2: score_riesgo en bank_reconciliation ──────────
        # score_riesgo existe en el CREATE TABLE pero si la tabla fue creada antes
        # de agregarlo, la columna no existe en producción → 500 en list_sesiones.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE bank_reconciliation "
                    "ADD COLUMN IF NOT EXISTS score_riesgo INTEGER DEFAULT 0"
                ))
            logger.info("✅ Migración M_RECON_V2: score_riesgo en bank_reconciliation")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_RECON_V2 omitida: {e}")

        # ── Migración M_CATALOG_V2: columna es_reguladora en accounts ──────
        # La columna existe en el modelo SQLAlchemy (catalog/models.py) pero
        # nunca se agregó en producción con ALTER TABLE.
        # Sin ella, GET /catalog/accounts lanza un InternalError 500 y el
        # frontend muestra "Failed to fetch".
        # ALTER ... ADD COLUMN IF NOT EXISTS es idempotente — seguro cada arranque.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE accounts "
                    "ADD COLUMN IF NOT EXISTS es_reguladora BOOLEAN NOT NULL DEFAULT FALSE"
                ))
            logger.info("✅ Migración M_CATALOG_V2: columna es_reguladora agregada a accounts")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CATALOG_V2 omitida: {e}")

        # ── Migración M_CENTINELA_V1: beneficiario extraído en bank_transactions ──
        # Agrega columnas para persistir el nombre normalizado del beneficiario
        # y su categoría (TERCERO, BANK_FEE, BANK_INTEREST, SINPE).
        # Son la base del análisis acumulado cross-meses de CENTINELA.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS beneficiario_nombre TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS beneficiario_telefono_norm TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS beneficiario_categoria TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS tiene_fe BOOLEAN DEFAULT FALSE"
                ))
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS fe_numero TEXT"
                ))
                conn.execute(text(
                    "ALTER TABLE bank_transactions "
                    "ADD COLUMN IF NOT EXISTS tarifa_iva NUMERIC(5,2) DEFAULT 13.0"
                ))
            logger.info("✅ Migración M_CENTINELA_V1: columnas beneficiario + tiene_fe + tarifa_iva en bank_transactions")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CENTINELA_V1 omitida: {e}")

        # ── Migración M_CENTINELA_V2: tabla bank_counterparties ────────────────
        # Acumula datos de beneficiarios cross-meses para análisis fiscal.
        # Regla de Oro: tenant_id en TODA tabla — aislamiento multi-tenant absoluto.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS bank_counterparties (
                        id                  TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id           TEXT NOT NULL,
                        nombre_norm         TEXT NOT NULL,
                        telefono            TEXT,
                        categoria           TEXT DEFAULT 'TERCERO',
                        total_debitos       NUMERIC(18,2) DEFAULT 0,
                        total_creditos      NUMERIC(18,2) DEFAULT 0,
                        n_transacciones     INTEGER DEFAULT 0,
                        primer_periodo      TEXT,
                        ultimo_periodo      TEXT,
                        d150_monto_anual    NUMERIC(18,2) DEFAULT 0,
                        d150_flag           BOOLEAN DEFAULT FALSE,
                        riesgo_nivel        TEXT DEFAULT 'VERDE',
                        updated_at          TIMESTAMPTZ DEFAULT NOW(),
                        UNIQUE (tenant_id, nombre_norm)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_counterparties_tenant "
                    "ON bank_counterparties (tenant_id)"
                ))
            logger.info("✅ Migración M_CENTINELA_V2: tabla bank_counterparties creada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CENTINELA_V2 omitida: {e}")






        # La cuenta '5900.01' fue creada accidentalmente por el bug de
        # nextChildCode (generaba prefijo-string en lugar de parent_code).
        # Solo se elimina si existe y NO tiene asientos → 100% seguro.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    DELETE FROM accounts
                    WHERE code = '5900.01'
                      AND NOT EXISTS (
                          SELECT 1 FROM journal_lines jl
                          WHERE jl.account_code = '5900.01'
                            AND jl.tenant_id = accounts.tenant_id
                      )
                """))
            logger.info("✅ Migración M_CLEANUP_5900_01: cuenta fantasma eliminada (si existía)")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CLEANUP_5900_01 omitida: {e}")

        # ── Migración M_ENUM_DEPRECIACION: añadir valor al enum Postgres ──
        # Postgres Enum Hazard: ALTER TYPE entrysource ADD VALUE es idempotente
        # con IF NOT EXISTS — no falla si ya existe. Necesario porque
        # SQLAlchemy no altera enums existentes al modificar el modelo Python.
        try:
            with _engine.begin() as conn:
                conn.execute(text(
                    "ALTER TYPE entrysource ADD VALUE IF NOT EXISTS 'DEPRECIACION'"
                ))
            logger.info("✅ Migración M_ENUM_DEPRECIACION: valor DEPRECIACION en entrysource")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_ENUM_DEPRECIACION omitida: {e}")

        # ── Migración M_AUTOIMPOR: Auto-Importación desde Genoma Contable ──
        # Tablas y columnas para el módulo de importación de FE/FEC.
        # 100% idempotente: IF NOT EXISTS + ADD COLUMN IF NOT EXISTS.
        # Cero riesgo de romper tablas existentes — solo adiciones.
        try:
            with _engine.begin() as conn:
                # Tabla de reglas CABYS → cuenta (aprende del contador)
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS cabys_account_rules (
                        id           TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id    TEXT NOT NULL,
                        cabys_code   TEXT,
                        cabys_prefix TEXT,
                        account_code TEXT NOT NULL,
                        asset_flag   BOOLEAN DEFAULT FALSE,
                        min_amount   NUMERIC(18,5),
                        fuente       TEXT DEFAULT 'MANUAL',
                        prioridad    INT DEFAULT 10,
                        created_at   TIMESTAMPTZ DEFAULT now(),
                        UNIQUE (tenant_id, cabys_code)
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_cabys_rules_tenant "
                    "ON cabys_account_rules (tenant_id, cabys_code)"
                ))

                # Tabla de sesiones de importación (dedup + auditoría)
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS import_batch (
                        id          TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text,
                        tenant_id   TEXT NOT NULL,
                        period      TEXT NOT NULL,
                        tipo        TEXT NOT NULL,
                        total_docs  INT DEFAULT 0,
                        importados  INT DEFAULT 0,
                        skipped     INT DEFAULT 0,
                        estado      TEXT DEFAULT 'PENDIENTE',
                        created_at  TIMESTAMPTZ DEFAULT now()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_import_batch_tenant_period "
                    "ON import_batch (tenant_id, period)"
                ))

                # Columnas nuevas en journal_lines (trazabilidad CABYS)
                for col_sql in [
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS cabys_code TEXT",
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS cabys_descripcion TEXT",
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS iva_tarifa NUMERIC(5,2)",
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS iva_tipo TEXT",
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(3,2)",
                    "ALTER TABLE journal_lines ADD COLUMN IF NOT EXISTS clasificacion_fuente TEXT",
                ]:
                    conn.execute(text(col_sql))

                # Columnas nuevas en journal_entries (revisión del contador)
                for col_sql in [
                    "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS needs_review BOOLEAN DEFAULT FALSE",
                    "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS confidence_score NUMERIC(3,2)",
                    "ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS source_doc_lines JSONB",
                ]:
                    conn.execute(text(col_sql))

            logger.info("✅ Migración M_AUTOIMPOR: cabys_account_rules, import_batch y columnas CABYS creadas")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_AUTOIMPOR omitida: {e}")

        # ── Migración M_IVA_DIFERIDO: tabla iva_diferidos ─────────────
        # Tracking de IVA diferido (condición de venta 11, Art.17 Ley IVA 9635).
        # Cuando un doc tiene condicion=11, el IVA queda en cuenta 2108 (IVA Diferido)
        # y se registra aquí con su fecha de vencimiento (fecha_doc + 90 días).
        # El worker corre diariamente y genera DR 2108 → CR 2102 cuando vence.
        # CREATE TABLE IF NOT EXISTS + índices = idempotente en cada arranque.
        try:
            with _engine.begin() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS iva_diferidos (
                        id               VARCHAR(36) PRIMARY KEY,
                        tenant_id        VARCHAR(36) NOT NULL,
                        entry_id         VARCHAR(36) NOT NULL,
                        source_ref       VARCHAR(100),
                        fecha_doc        VARCHAR(10) NOT NULL,
                        vencimiento      VARCHAR(10) NOT NULL,
                        monto_iva        NUMERIC(18,5) NOT NULL,
                        cuenta_origen    VARCHAR(20) NOT NULL DEFAULT '2108',
                        cuenta_destino   VARCHAR(20) NOT NULL DEFAULT '2102',
                        estado           VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',
                        entry_id_cierre  VARCHAR(36),
                        created_at       TIMESTAMPTZ DEFAULT NOW()
                    )
                """))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_iva_dif_tenant "
                    "ON iva_diferidos(tenant_id)"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_iva_dif_estado_venc "
                    "ON iva_diferidos(estado, vencimiento)"
                ))
            logger.info("✅ Migración M_IVA_DIFERIDO: tabla iva_diferidos creada/verificada")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_IVA_DIFERIDO omitida: {e}")

        # ── Migración M_CABYS_SEED: UNIQUE constraint para cabys_prefix ────
        # cabys_account_rules fue creada con UNIQUE(tenant_id, cabys_code)
        # pero las reglas por prefijo usan cabys_prefix (cabys_code=NULL).
        # Sin constraint en el prefijo, ON CONFLICT DO NOTHING no puede
        # detectar duplicados → se insertarían filas repetidas en cada arranque.
        # Esta migración agrega el constraint de forma idempotente.
        try:
            with _engine.begin() as conn:
                # Primero eliminamos filas duplicadas de prefijo si las hubiera
                conn.execute(text("""
                    DELETE FROM cabys_account_rules a
                    USING cabys_account_rules b
                    WHERE a.id > b.id
                      AND a.tenant_id     = b.tenant_id
                      AND a.cabys_prefix  = b.cabys_prefix
                      AND a.cabys_prefix IS NOT NULL
                      AND a.cabys_code   IS NULL
                """))
                # Agregar UNIQUE constraint idempotente
                conn.execute(text("""
                    DO $$ BEGIN
                        IF NOT EXISTS (
                            SELECT 1 FROM pg_constraint
                            WHERE conname = 'uq_cabys_rules_prefix'
                        ) THEN
                            ALTER TABLE cabys_account_rules
                            ADD CONSTRAINT uq_cabys_rules_prefix
                            UNIQUE (tenant_id, cabys_prefix);
                        END IF;
                    END $$;
                """))
            logger.info("✅ Migración M_CABYS_SEED: UNIQUE constraint uq_cabys_rules_prefix listo")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_CABYS_SEED (constraint) omitida: {e}")


        # ── Migración M_CLEAN_SEEDED_ACCOUNTS: limpia cuentas estándar ───────
        # Elimina códigos 4-dígitos estándar (ej. 1104, 2101, 5299) que fueron
        # sembrados erróneamente en tenants con catálogo personalizado punteado
        # (ej. 1.1.4.01, 5901.01). Sólo elimina si la cuenta NO tiene
        # journal_lines asociadas (no destruye datos historicos).
        try:
            with _engine.begin() as conn:
                result = conn.execute(text("""
                    DELETE FROM accounts
                    WHERE tenant_id IN (
                        SELECT DISTINCT tenant_id FROM accounts
                        WHERE code LIKE '%%.%%'
                    )
                    AND code ~ '^[0-9]{4}$'
                    AND is_generic = FALSE
                    AND NOT EXISTS (
                        SELECT 1 FROM journal_lines jl
                        WHERE jl.account_code = accounts.code
                          AND jl.tenant_id    = accounts.tenant_id
                    )
                """))
                deleted = result.rowcount or 0
            if deleted:
                logger.info(
                    f"✅ Migración M_CLEAN_SEEDED_ACCOUNTS: {deleted} cuentas "
                    f"estándar removidas de tenants con catálogo personalizado"
                )
            else:
                logger.info("✅ Migración M_CLEAN_SEEDED_ACCOUNTS: nada que limpiar")
        except Exception as e:
            logger.warning(f"⚠️  M_CLEAN_SEEDED_ACCOUNTS omitida: {e}")

        # ── Migración M_PURGE_TENANTS: limpia datos contables cruzados ────
        # Fix multi-tenant: los datos de Álvaro (202830516) se importaron
        # bajo los tenants de Angélica (603170547) y la SA (3101953441)
        # por el bug de falta de filtro por cédula en router_pull.py.
        # Esta migración borra SOLO journal_lines, journal_entries e import_batch
        # de esos 2 tenants. NO toca: tenants, accounts, users, fiscal_profiles.
        # Idempotente: si ya corrió y no hay datos, no hace nada.
        try:
            with _engine.begin() as conn:
                _purge_cedulas = ["603170547", "3101953441"]
                _purge_tids = []
                for _ced in _purge_cedulas:
                    _row = conn.execute(text(
                        "SELECT id FROM tenants WHERE cedula = :ced LIMIT 1"
                    ), {"ced": _ced}).fetchone()
                    if _row:
                        _purge_tids.append(_row[0])

                if _purge_tids:
                    # Contar antes de borrar (auditoría)
                    for _tbl in ["journal_lines", "journal_entries", "import_batch"]:
                        _ph = ", ".join([f":t{i}" for i in range(len(_purge_tids))])
                        _pm = {f"t{i}": t for i, t in enumerate(_purge_tids)}
                        try:
                            _cnt = conn.execute(text(
                                f"SELECT COUNT(*) FROM {_tbl} WHERE tenant_id IN ({_ph})"
                            ), _pm).fetchone()
                            _n = _cnt[0] if _cnt else 0
                            if _n > 0:
                                logger.info(f"  🔴 M_PURGE: {_tbl} → {_n} filas a borrar")
                        except Exception:
                            pass

                    # Borrar en orden FK: lines → entries → batch
                    _ph = ", ".join([f":t{i}" for i in range(len(_purge_tids))])
                    _pm = {f"t{i}": t for i, t in enumerate(_purge_tids)}
                    for _tbl in ["journal_lines", "journal_entries", "import_batch"]:
                        try:
                            _res = conn.execute(text(
                                f"DELETE FROM {_tbl} WHERE tenant_id IN ({_ph})"
                            ), _pm)
                            _del = _res.rowcount or 0
                            if _del > 0:
                                logger.info(f"  ✅ M_PURGE: {_tbl} → {_del} filas borradas")
                        except Exception as _ex:
                            logger.warning(f"  ⚠️  M_PURGE: {_tbl} → {_ex}")

            logger.info("✅ Migración M_PURGE_TENANTS: datos cruzados purgados de Angélica y SA")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_PURGE_TENANTS omitida: {e}")

        # ── Migración M_REASSIGN_GCRNHJ: datos de Álvaro salvados del tenant fantasma ──
        # Bug del JWT: antes del fix switch-tenant, el partner_handoff generaba
        # JWTs con tenant_id="GC-RNHJ" (el código del contador, no un tenant real).
        # Todo lo creado manualmente (catálogo, asiento apertura, asientos de febrero)
        # quedó bajo GC-RNHJ en lugar de bajo 1001 (Álvaro González Alfaro).
        # Esta migración mueve todos esos datos al tenant correcto.
        # Idempotente: si ya corrió, los datos ya están en 1001 → rowcount=0.
        try:
            with _engine.begin() as conn:
                _from = "GC-RNHJ"
                _to   = "1001"
                _tbls = [
                    "accounts",
                    "journal_entries",
                    "journal_lines",
                    "period_locks",
                    "import_batch",
                    "cabys_account_rules",
                ]
                _total = 0
                for _tbl in _tbls:
                    try:
                        _r = conn.execute(text(
                            f"UPDATE {_tbl} SET tenant_id=:to WHERE tenant_id=:from"
                        ), {"to": _to, "from": _from})
                        _n = _r.rowcount or 0
                        if _n > 0:
                            logger.info(f"  🔄 M_REASSIGN: {_tbl} → {_n} filas reasignadas")
                        _total += _n
                    except Exception as _te:
                        logger.warning(f"  ⚠️  M_REASSIGN: {_tbl} → {_te}")
                # niif_mappings (opcional)
                try:
                    _r2 = conn.execute(text(
                        "UPDATE niif_mappings SET tenant_id=:to WHERE tenant_id=:from"
                    ), {"to": _to, "from": _from})
                    _total += _r2.rowcount or 0
                except Exception:
                    pass
            if _total > 0:
                logger.info(
                    f"✅ Migración M_REASSIGN_GCRNHJ: {_total} filas "
                    f"reasignadas de '{_from}' → '{_to}' (Álvaro González)"
                )
            else:
                logger.info("✅ Migración M_REASSIGN_GCRNHJ: sin datos pendientes (ya aplicada)")
        except Exception as e:
            logger.warning(f"⚠️  Migración M_REASSIGN_GCRNHJ omitida: {e}")


    # REGLA DE ORO: NO se toca ningún tenant que ya tenga su propio catálogo.
    # Solo aplica a tenants recién registrados (0 cuentas) para darles
    # el catálogo estándar inicial automáticamente.
    if _engine:
        try:
            from services.catalog.seeder import seed_standard_catalog as _seed_fn
            from sqlalchemy.orm import Session as _Session

            # Solo tenants con 0 cuentas (nunca configurados = necesitan seed)
            with _Session(_engine) as _sess:
                _all_tenants = _sess.execute(
                    text("SELECT DISTINCT tenant_id FROM journal_entries")
                ).fetchall()
                _tenants_with_accounts = set(
                    r[0] for r in _sess.execute(
                        text("SELECT DISTINCT tenant_id FROM accounts")
                    ).fetchall()
                )
                # Tenants que tienen actividad contable pero aún no tienen cuentas
                _tenants_sin_catalogo = [
                    r[0] for r in _all_tenants
                    if r[0] not in _tenants_with_accounts
                ]

            total_inserted = 0
            for _tid in _tenants_sin_catalogo:
                with _Session(_engine) as _s2:
                    _n = _seed_fn(_tid, _s2)
                    total_inserted += _n

            if total_inserted:
                logger.info(
                    f"✅ Auto-reseed: {total_inserted} cuentas sembradas en "
                    f"{len(_tenants_sin_catalogo)} tenant(s) sin catálogo"
                )
            else:
                logger.info("✅ Auto-reseed: todos los tenants ya tienen catálogo")
        except Exception as _e:
            logger.warning(f"⚠️  Auto-reseed omitido: {_e}")

    # ── Auto-seed CABYS: siembra reglas prefijo CABYS → cuenta NIIF ──
    # REGLA DE ORO: Solo para tenants con catálogo estándar (códigos 4-dígitos).
    # Tenants con catálogo personalizado punteado usan sus propias cuentas;
    # las reglas cabys_account_rules sólo aplican si el tenant tiene cuentas
    # en formato estándar que existen en el catálogo sembrado.
    if _engine:
        try:
            from services.catalog.seed_cabys_rules import seed_cabys_rules_all_tenants as _seed_cabys
            from sqlalchemy.orm import Session as _CabysSession
            with _CabysSession(_engine) as _cabys_sess:
                _cabys_result = _seed_cabys(_cabys_sess)
            _nr = _cabys_result.get("reglas", 0)
            _nt = _cabys_result.get("tenants", 0)
            if _nr:
                logger.info(
                    f"✅ Auto-seed CABYS: {_nr} reglas CABYS sembradas en {_nt} tenant(s)"
                )
            else:
                logger.info("✅ Auto-seed CABYS: reglas ya al día en todos los tenants")
        except Exception as _cabys_err:
            logger.warning(f"⚠️  Auto-seed CABYS omitido: {_cabys_err}")

    # ── Auto-Fix: Corrección de cuentas incorrectas en activos ──────
    # Corre ANTES del recovery de depreciación para que los DRAFTs
    # regenerados ya usen las cuentas correctas.
    # Idempotente: si no hay cuentas incorrectas, no hace nada.
    if _engine:
        try:
            from services.assets.auto_fix import fix_bad_depreciation_accounts
            from sqlalchemy.orm import Session as _FixSession
            with _FixSession(_engine) as _fix_sess:
                _fix_result = fix_bad_depreciation_accounts(_fix_sess)
            if _fix_result["fixed_assets"] > 0:
                logger.info(
                    f"🔧 Auto-Fix Dep.: {_fix_result['fixed_assets']} activo(s) corregido(s), "
                    f"{_fix_result['voided_drafts']} DRAFT(s) anulado(s)"
                )
        except Exception as _fix_err:
            logger.warning(f"⚠️  Auto-Fix Dep. omitido: {_fix_err}")

    # ── Migración B0: Revertir [REVERSIÓN] POSTED en períodos abiertos ──
    # Las reversiones generadas automáticamente por void_entry fueron
    # creadas como POSTED (bug corregido ahora). Este paso las restablece
    # a DRAFT para que el contador las revise antes de aprobarlas.
    # Idempotente: solo afecta a [REVERSIÓN] que NO han pasado por el cierre.
    if _engine:
        try:
            with _engine.begin() as _rev_conn:
                _rev_result = _rev_conn.execute(text("""
                    UPDATE journal_entries
                    SET status      = 'DRAFT',
                        approved_by = NULL,
                        approved_at = NULL
                    WHERE description LIKE '[REVERSIÓN]%'
                      AND status = 'POSTED'
                      AND period NOT IN (
                          SELECT year_month FROM period_status WHERE status = 'CLOSED'
                      )
                """))
                reverted_count = _rev_result.rowcount or 0
            if reverted_count > 0:
                logger.info(
                    f"🔄 Migración B0: {reverted_count} asiento(s) [REVERSIÓN] "
                    f"revertido(s) a DRAFT (períodos abiertos)"
                )
            else:
                logger.info("✅ Migración B0: sin asientos [REVERSIÓN] para revertir")
        except Exception as _rev_err:
            logger.warning(f"⚠️  Migración B0 omitida: {_rev_err}")

    # ── Auto-Depreciación: Startup Recovery ─────────────────────
    # Al arrancar, genera los asientos DRAFT de depreciación para
    # todos los meses sin cobertura (desde apertura hasta mes anterior).
    # Idempotente: omite períodos que ya tienen asiento.
    # En Marzo 2026 → genera Enero + Febrero automáticamente.
    if _engine:
        try:
            from services.assets.depreciation import startup_depreciation_recovery
            from sqlalchemy.orm import Session as _DepSession
            with _DepSession(_engine) as _dep_sess:
                _dep_results = startup_depreciation_recovery(_dep_sess)
            if _dep_results:
                total_dep = sum(r.get("created", 0) for r in _dep_results)
                periods_dep = [r["period"] for r in _dep_results]
                logger.info(
                    f"✅ Auto-Depreciación: {total_dep} asientos DRAFT generados "
                    f"en {len(_dep_results)} período(s): {periods_dep}"
                )
            else:
                logger.info("✅ Auto-Depreciación: sin períodos pendientes")
        except Exception as _dep_err:
            logger.warning(f"⚠️  Auto-Depreciación omitida: {_dep_err}")

    # ── Fix Mapeos NIIF: corrige prefijos incorrectos en niif_mappings ──
    # Idempotente: solo actualiza registros que apunten a la línea incorrecta.
    # Principal corrección: 1201/1202 → ESF.AC.02 (CxC) → ESF.ANC.01 (PPE)
    if _engine:
        try:
            from services.reporting.niif_lines import fix_existing_mappings
            from sqlalchemy.orm import Session as _NiifSession
            from sqlalchemy import text as _sql_text
            with _NiifSession(_engine) as _niif_sess:
                # Obtener todos los tenant_ids activos
                _tenant_ids = [
                    r[0] for r in _niif_sess.execute(
                        _sql_text("SELECT DISTINCT id FROM tenants WHERE is_active = TRUE")
                    ).fetchall()
                ]
                _total_fixed = 0
                for _tid in _tenant_ids:
                    _total_fixed += fix_existing_mappings(_tid, _niif_sess)
            if _total_fixed:
                logger.info(
                    f"✅ Fix Mapeos NIIF: {_total_fixed} registro(s) corregido(s) "
                    f"en {len(_tenant_ids)} tenant(s)"
                )
            else:
                logger.info("✅ Fix Mapeos NIIF: sin correcciones necesarias (ya al día)")
        except Exception as _niif_err:
            logger.warning(f"⚠️  Fix Mapeos NIIF omitido: {_niif_err}")

    # ── Migración: Tablas Conciliación Bancaria + CENTINELA ──────
    # CREATE IF NOT EXISTS → idempotente, sin riesgo en instancias existentes.
    # Tablas: bank_reconciliation, bank_transactions, bank_rules, centinela_score
    if _engine:
        try:
            from sqlalchemy import text as _sql_bank
            _bank_ddl = """
            CREATE TABLE IF NOT EXISTS bank_reconciliation (
                id              SERIAL PRIMARY KEY,
                tenant_id       INTEGER NOT NULL,
                banco           VARCHAR(80) NOT NULL,
                period          VARCHAR(6)  NOT NULL,
                archivo_nombre  VARCHAR(255),
                saldo_inicial   NUMERIC(18,2) DEFAULT 0,
                saldo_final     NUMERIC(18,2) DEFAULT 0,
                moneda          VARCHAR(3) DEFAULT 'CRC',
                status          VARCHAR(20) DEFAULT 'PENDING',
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS bank_transactions (
                id              SERIAL PRIMARY KEY,
                recon_id        INTEGER NOT NULL,
                tenant_id       INTEGER NOT NULL,
                fecha           DATE,
                descripcion     TEXT,
                tipo            VARCHAR(2),
                monto           NUMERIC(18,2) DEFAULT 0,
                moneda          VARCHAR(3) DEFAULT 'CRC',
                monto_crc       NUMERIC(18,2) DEFAULT 0,
                monto_orig_usd  NUMERIC(18,2),
                tc_bccr         NUMERIC(10,4),
                telefono        VARCHAR(30),
                match_estado    VARCHAR(20) DEFAULT 'PENDIENTE',
                match_confianza INTEGER DEFAULT 0,
                journal_entry_id INTEGER,
                fuga_tipo       VARCHAR(1),
                d270_codigo     VARCHAR(5),
                created_at      TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS bank_rules (
                id              SERIAL PRIMARY KEY,
                tenant_id       INTEGER NOT NULL,
                nombre          VARCHAR(120) NOT NULL,
                patron          TEXT NOT NULL,
                tipo_match      VARCHAR(20) DEFAULT 'CONTIENE',
                cuenta_contable VARCHAR(30),
                tipo_txn        VARCHAR(2),
                activa          BOOLEAN DEFAULT TRUE,
                prioridad       INTEGER DEFAULT 0,
                created_at      TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS centinela_score (
                id              SERIAL PRIMARY KEY,
                tenant_id       INTEGER NOT NULL,
                period          VARCHAR(6)  NOT NULL,
                recon_id        INTEGER,
                score_total     INTEGER DEFAULT 0,
                nivel           VARCHAR(15) DEFAULT 'SIN_DATOS',
                exposicion_iva  NUMERIC(18,2) DEFAULT 0,
                exposicion_renta NUMERIC(18,2) DEFAULT 0,
                fugas_tipo_a    INTEGER DEFAULT 0,
                fugas_tipo_b    INTEGER DEFAULT 0,
                fugas_tipo_c    INTEGER DEFAULT 0,
                d270_regs       INTEGER DEFAULT 0,
                detalle         JSONB DEFAULT '[]',
                created_at      TIMESTAMP DEFAULT NOW(),
                updated_at      TIMESTAMP DEFAULT NOW(),
                UNIQUE(tenant_id, period)
            );
            """
            with _engine.connect() as _bank_conn:
                _bank_conn.execute(_sql_bank(_bank_ddl))
                _bank_conn.commit()
            logger.info("✅ Migración Conciliación+CENTINELA: 4 tablas bank_* + centinela_score verificadas")
        except Exception as _bank_err:
            logger.warning(f"⚠️  Migración Conciliación+CENTINELA omitida: {_bank_err}")

    yield
    logger.info("🛑 Genoma Contabilidad cerrando...")



app = FastAPI(
    title="Genoma Contabilidad",
    description="Sistema contable multi-tenant · NIIF PYMES · Tribu-CR",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Incluir routers
app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(ledger_router)
app.include_router(integration_router)
app.include_router(pull_router)          # Auto-importación FE/FEC desde Genoma Contable

app.include_router(assets_router)
app.include_router(tax_router)
app.include_router(reporting_router)
app.include_router(conciliacion_router)

# ── Endpoints API ──────────────────────────────────────────────

@app.get("/health")
def health():
    global _engine
    db_ok = False
    if _engine:
        try:
            with _engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            db_ok = True
        except Exception:
            pass
    return {
        "status": "ok",
        "db": "ok" if db_ok else "unavailable",
    }


@app.get("/api")
def api_root():
    db_status = "🟢 connected" if DATABASE_URL else "🔴 not configured"
    return {
        "app": "Genoma Contabilidad",
        "version": "0.1.0",
        "status": "🟢 running",
        "architecture": "v2.7",
        "db": db_status,
        "environment": os.getenv("ENVIRONMENT", "development"),
        "services": {
            "gateway": "🟢 active",
            "auth": "🟢 active",
            "catalog": "🔴 pending",
            "ledger": "🔴 pending",
            "tax": "🔴 pending",
            "reporting": "🔴 pending",
            "integration": "🔴 pending",
            "document": "🔴 pending",
        },
    }


# ── Job manual: trigger depreciación (Render Cron / emergencia) ──
# POST /jobs/monthly-depreciation?secret=DEP_JOB_SECRET&period=2026-01
@app.post("/jobs/monthly-depreciation")
def trigger_monthly_depreciation(secret: str, period: str = None):
    """Genera DRAFT de depreciación para todos los activos. Idempotente."""
    if secret != os.getenv("DEP_JOB_SECRET", "genoma-dep-secret-2026"):
        from fastapi import HTTPException as _HE
        raise _HE(403, "Clave secreta inválida")
    if not _engine:
        from fastapi import HTTPException as _HE
        raise _HE(503, "Base de datos no disponible")
    if not period:
        from datetime import date as _d
        t = _d.today()
        m = t.month - 1 or 12
        y = t.year if t.month > 1 else t.year - 1
        period = f"{y}-{m:02d}"
    try:
        from services.assets.depreciation import auto_depreciate_period
        from sqlalchemy.orm import Session as _DS
        with _DS(_engine) as _s:
            result = auto_depreciate_period(_s, period)
        return result
    except Exception as exc:
        from fastapi import HTTPException as _HE
        raise _HE(500, str(exc))


# ── Job manual: IVA Diferido check (Render Cron / emergencia) ────────
# POST /jobs/run-iva-diferido-check?secret=...&auto_post=false
@app.post("/jobs/run-iva-diferido-check")
def trigger_iva_diferido_check(secret: str, auto_post: bool = False):
    """
    Ejecuta el worker de IVA Diferido para todos los tenants.
    Detecta registros iva_diferidos con vencimiento <= hoy y genera
    asientos DRAFT DR 2108 → CR 2102. Idempotente.

    auto_post=False (default): entry DRAFT (contador aprueba).
    auto_post=True: entry POSTED automático (solo modo cierre masivo).
    """
    if secret != os.getenv("IVA_JOB_SECRET", "genoma-iva-secret-2026"):
        from fastapi import HTTPException as _HE
        raise _HE(403, "Clave secreta inválida")
    if not _engine:
        from fastapi import HTTPException as _HE
        raise _HE(503, "Base de datos no disponible")
    try:
        from services.integration.iva_diferido_worker import run_iva_diferido_check as _iva_check
        from sqlalchemy.orm import Session as _IVAS
        with _IVAS(_engine) as _s:
            result = _iva_check(_s, auto_post=auto_post)
        logger.info(
            f"✅ IVA Diferido job: {result['generados']} asiento(s) generado(s), "
            f"{result['errores']} error(es)"
        )
        return result
    except Exception as exc:
        from fastapi import HTTPException as _HE
        raise _HE(500, str(exc))


# ── Job temporal: Reasignación de tenant GC-RNHJ → 1001 ─────────────────────
# POST /jobs/reassign-tenant?secret=REASSIGN_SECRET&from_tid=GC-RNHJ&to_tid=1001
# ELIMINAR después de ejecutar en producción. Uso único.
@app.post("/jobs/reassign-tenant")
def reassign_tenant_data(
    secret: str,
    from_tid: str = "GC-RNHJ",
    to_tid:   str = "1001",
):
    """
    Reasigna TODOS los registros de from_tid → to_tid en tablas contables.
    Protegido por secret. Idempotente — si ya corrió, rowcount = 0.
    """
    if secret != os.getenv("REASSIGN_SECRET", "genoma-reassign-gcrnhj-2026"):
        from fastapi import HTTPException as _HE
        raise _HE(403, "Clave secreta inválida")
    if not _engine:
        from fastapi import HTTPException as _HE
        raise _HE(503, "Base de datos no disponible")

    results = {}
    try:
        with _engine.begin() as conn:
            # 1. accounts (catálogo)
            r = conn.execute(text(
                "UPDATE accounts SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["accounts"] = r.rowcount

            # 2. journal_entries (cabeceras)
            r = conn.execute(text(
                "UPDATE journal_entries SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["journal_entries"] = r.rowcount

            # 3. journal_lines (líneas — FK a journal_entries)
            r = conn.execute(text(
                "UPDATE journal_lines SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["journal_lines"] = r.rowcount

            # 4. period_locks
            r = conn.execute(text(
                "UPDATE period_locks SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["period_locks"] = r.rowcount

            # 5. import_batch
            r = conn.execute(text(
                "UPDATE import_batch SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["import_batch"] = r.rowcount

            # 6. cabys_account_rules
            r = conn.execute(text(
                "UPDATE cabys_account_rules SET tenant_id=:to WHERE tenant_id=:from"
            ), {"to": to_tid, "from": from_tid})
            results["cabys_account_rules"] = r.rowcount

            # 7. niif_mappings (si existe)
            try:
                r = conn.execute(text(
                    "UPDATE niif_mappings SET tenant_id=:to WHERE tenant_id=:from"
                ), {"to": to_tid, "from": from_tid})
                results["niif_mappings"] = r.rowcount
            except Exception:
                results["niif_mappings"] = "tabla no existe"

        total = sum(v for v in results.values() if isinstance(v, int))
        logger.info(
            f"✅ reassign-tenant: {from_tid} → {to_tid} | "
            f"total={total} filas | {results}"
        )
        return {
            "ok": True,
            "from_tid": from_tid,
            "to_tid": to_tid,
            "total_filas_reasignadas": total,
            "detalle": results,
            "message": (
                f"Datos reasignados de '{from_tid}' → '{to_tid}'. "
                "Elimina este endpoint del código cuando confirmes."
            ),
        }
    except Exception as exc:
        from fastapi import HTTPException as _HE
        raise _HE(500, f"Error en reasignación: {exc}")


# ── Servir React SPA (debe ir AL FINAL) ────────────────────────
FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")

    @app.get("/")
    @app.get("/{full_path:path}")
    def serve_spa(full_path: str = ""):
        # Rutas de API no llegan aquí (están definidas arriba)
        index = FRONTEND_DIST / "index.html"
        return FileResponse(str(index))
else:
    @app.get("/")
    def root():
        return {"app": "Genoma Contabilidad", "version": "0.1.0", "status": "🟡 frontend not built"}
