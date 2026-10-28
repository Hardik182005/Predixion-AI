# syntax=docker/dockerfile:1

# Build the frontend.
FROM node:24-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Python runtime serving the API and the built frontend.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ ./src/
RUN uv sync --frozen --no-dev
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN useradd --system --uid 10001 --home-dir /app predixion \
    && mkdir -p /app/data && chown predixion /app/data
USER predixion

# Binding 0.0.0.0 requires AUTH_MODE=token, or ALLOW_UNAUTHENTICATED_BIND=true when the port
# is published on host loopback only (see compose.yaml).
ENV PATH="/app/.venv/bin:$PATH" \
    PREDIXION_ENV=production \
    PREDIXION_HOST=0.0.0.0 \
    PREDIXION_PORT=8000 \
    PREDIXION_DB_PATH=/app/data/predixion.sqlite3 \
    SERVE_FRONTEND_DIR=/app/frontend/dist
EXPOSE 8000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
CMD ["predixion", "serve"]
