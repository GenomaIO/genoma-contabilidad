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

    # ── Auto-reseed: al arrancar, aplica cuentas nuevas del seed a TODOS
    # los tenants con cuentas existentes. Usa seed_standard_catalog()
    # con raw SQL / ON CONFLICT DO NOTHING — igual que el boton Sembrar.
    if _engine:
        try:
            from services.catalog.seeder import seed_standard_catalog as _seed_fn
            from sqlalchemy.orm import Session as _Session

            with _Session(_engine) as _sess:
                _rows = _sess.execute(
                    text("SELECT DISTINCT tenant_id FROM accounts")
                ).fetchall()
                _tenant_ids = [r[0] for r in _rows]

            total_inserted = 0
            for _tid in _tenant_ids:
                with _Session(_engine) as _s2:
                    _n = _seed_fn(_tid, _s2)
                    total_inserted += _n

            if total_inserted:
                logger.info(f"✅ Auto-reseed: {total_inserted} cuentas nuevas en {len(_tenant_ids)} tenants")
            else:
                logger.info("✅ Auto-reseed: catalogo al dia en todos los tenants")
        except Exception as _e:
            logger.warning(f"⚠️  Auto-reseed omitido: {_e}")

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
