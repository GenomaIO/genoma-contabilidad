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
import services.catalog.models  # noqa: F401 — registra Account en Base para create_all

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
