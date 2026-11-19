# ---- Stage 1: build the React frontend to static files ----
FROM node:22-alpine AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python 3.12 + FastAPI app serving API and built frontend ----
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=frontend-build /build/dist ./static

# Runtime configuration (override via env / .env):
ENV DATA_DIR=/data \
    FRONTEND_DIST=/app/static \
    PORT=8787

# Single exposed HTTP port; SQLite DB + cover cache live in the /data volume.
EXPOSE 8787
VOLUME ["/data"]

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8787}"]
