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
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_engine():
    if not DATABASE_URL:
        return None
    # Render usa postgres:// pero SQLAlchemy necesita postgresql://
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return create_engine(url)


def run_startup_migrations():
    """Crea tablas base si no existen. Alembic se agrega después."""
    engine = get_engine()
    if not engine:
        logger.warning("⚠️  DATABASE_URL no configurado — running sin DB")
        return
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("✅ Conexión a PostgreSQL establecida")
    except OperationalError as e:
        logger.error(f"❌ No se pudo conectar a PostgreSQL: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Genoma Contabilidad arrancando...")
    run_startup_migrations()
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


# ── Endpoints API ──────────────────────────────────────────────

@app.get("/health")
def health():
    engine = get_engine()
    db_ok = False
    if engine:
        try:
            with engine.connect() as conn:
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
            "auth": "🔴 pending",
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
