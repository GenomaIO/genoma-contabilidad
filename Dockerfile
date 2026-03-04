# ── Stage 1: Build React frontend ──────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --silent
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python API ─────────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código del backend
COPY services/ ./services/
COPY data/ ./data/

# Copiar frontend buildeado
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

EXPOSE 8100

CMD ["uvicorn", "services.gateway.main:app", "--host", "0.0.0.0", "--port", "8100"]
