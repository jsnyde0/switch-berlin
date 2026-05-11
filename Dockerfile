# ---- Frontend builder stage ----
# Builds Vite assets (incl. .vite/manifest.json) consumed by django_vite tags.
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend/ ./frontend/
# vite.config.ts: outDir = ../static/dist, so artifacts land at /build/static/dist.
RUN cd frontend && npm run build

# ---- Python app stage ----
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

RUN apt-get update && apt-get install -y --no-install-recommends gettext && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy project
COPY . /app

# Overlay built frontend artifacts (manifest + bundles) onto the source tree.
COPY --from=frontend /build/static/dist /app/static/dist

# Install project itself
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# Collect static files at build time (D7: Whitenoise serves them; no runtime collectstatic needed)
RUN python manage.py collectstatic --noinput

EXPOSE 8000

COPY entrypoint.sh ./
RUN chmod +x ./entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
