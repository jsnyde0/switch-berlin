# ---- Frontend builder stage ----
# Builds Vite assets (incl. .vite/manifest.json) consumed by django_vite tags.
# Base: node:22-slim (sha256 pin per kb-mhi; Dependabot bumps the digest weekly).
FROM node:26-slim@sha256:1e738cb88890a15c71880323fbc35a739b7bbc703d72e8bfd1613128f8182f78 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend/ ./frontend/
# Tailwind v4 @source directives in frontend/src/app.css scan
# ../../templates/**/*.html and ../../**/templates/**/*.html — those dirs
# must exist in the build stage or no utility classes get generated.
COPY templates/ ./templates/
COPY pages/templates/ ./pages/templates/
# vite.config.ts: outDir = ../static/dist, so artifacts land at /build/static/dist.
RUN cd frontend && npm run build

# ---- Python app stage ----
# Base: python:3.13-slim-bookworm (sha256 pin per kb-mhi).
FROM python:3.13-slim-bookworm@sha256:386df64585134ba00b1d5e307acb1e72f33e9e87dbbb00aad9b8f24dbb51db72

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install uv from official image — pinned at 0.11.14 via sha256 (kb-mhi).
# Dependabot's docker ecosystem only watches FROM lines — COPY --from digests
# are not auto-bumped. Manual-bump cadence tracked in kb-q2z; refresh by hand
# when uv ships a security release.
COPY --from=ghcr.io/astral-sh/uv:0.11.14@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 /uv /uvx /usr/local/bin/

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

# Non-root runtime (kb-a0c): create app user and chown /app so the init
# service can re-run collectstatic + migrate without root. UID 1000 matches
# the host deploy-user. Gunicorn binds 8000 (high port, no privileged cap).
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --shell /usr/sbin/nologin --home-dir /app app \
 && chown -R app:app /app
USER app

ENTRYPOINT ["/app/entrypoint.sh"]
