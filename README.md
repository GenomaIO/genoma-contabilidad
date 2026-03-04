# Genoma Contabilidad

> Sistema contable multi-tenant · NIIF PYMES · Hacienda v4.4 · Tribu-CR

## Stack

- Python 3.12 + FastAPI
- PostgreSQL 16
- Redis 7
- SQLAlchemy 2.0 + Alembic
- React + Vite (frontend)

## Desarrollo local

```bash
# Levantar servicios
docker-compose up -d

# Gateway en http://localhost:8100
curl http://localhost:8100/health
```

## Servicios

| Puerto | Servicio |
|---|---|
| 8100 | Gateway API |
| 5433 | PostgreSQL |
| 6380 | Redis |

## Arquitectura

v2.7 — Ver `docs/architecture.md`
