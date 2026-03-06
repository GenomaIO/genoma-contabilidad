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
import services.catalog.models  # noqa: F401 — registra Account en Base para create_all
import services.ledger.models   # noqa: F401 — registra JournalEntry/JournalLine en Base
import services.ledger.audit_log  # noqa: F401 — registra AuditLog en Base

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
    else:
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
