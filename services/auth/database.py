"""
Database session management — Genoma Contabilidad
Regla de Oro: 
  - DATABASE_URL siempre desde env var, nunca hardcodeado
  - postgres:// → postgresql:// para compatibilidad con Render
  - Todas las consultas filtradas por tenant_id (nunca cruzadas)
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator

from .models import Base


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL no configurado")
    # Render usa postgres://, SQLAlchemy necesita postgresql://
    return url.replace("postgres://", "postgresql://", 1)


def create_db_engine():
    url = get_database_url()
    return create_engine(
        url,
        pool_pre_ping=True,        # Detecta conexiones muertas
        pool_size=5,
        max_overflow=10,
        connect_args={"sslmode": "require"} if "render.com" in url else {},
    )


# Engine global (se configura al iniciar la app)
_engine = None
_SessionLocal = None


def init_db():
    """Inicializar engine y crear tablas si no existen."""
    global _engine, _SessionLocal
    _engine = create_db_engine()
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    # Crear tablas (Alembic se encarga en producción; esto es fallback)
    Base.metadata.create_all(bind=_engine)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """Dependency injection para FastAPI."""
    if _SessionLocal is None:
        raise RuntimeError("DB no inicializada. Llamar init_db() primero.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
