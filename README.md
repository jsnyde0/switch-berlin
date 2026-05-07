# Switch Berlin

A queer / kinky / conscious events aggregator for Berlin. Trust-first, organizer-centric, scraping-powered.

Public domain: [switch.berlin](https://switch.berlin)

See [`docs/project_brief.md`](docs/project_brief.md), [`docs/plans/2026-04-17-v0-design.md`](docs/plans/2026-04-17-v0-design.md), and [`docs/decisions/ADR-001-core-product-and-stack.md`](docs/decisions/ADR-001-core-product-and-stack.md) for the why.

## Stack

- **Backend:** Django 5.2 + Python 3.13
- **Frontend:** HTMX + django-cotton + Tailwind v4 + DaisyUI for most pages; one React 19 + TypeScript island on `/events` via django-vite
- **DB:** Postgres 17 + pgvector
- **Jobs:** django-q2 (Postgres ORM broker — no Redis)
- **Ingestion / LLM:** pydantic-ai, httpx, beautifulsoup4, markdownify, python-telegram-bot
- **Observability:** Logfire

## Quick Start

### Prerequisites

- Docker + Docker Compose
- `uv` installed locally (for pre-commit, ruff, etc.)
- A `.env` (see `.env.example`)

### Run

```bash
uv run pre-commit install
docker compose -f docker-compose.yml -f docker-compose.local.yml up
```

Then open http://localhost:8000.

## Common tasks

```bash
# Migrations
docker compose exec app python manage.py makemigrations
docker compose exec app python manage.py migrate

# Tests (skip agentic/LLM tests by default)
docker compose exec app pytest
docker compose exec app pytest -m agentic  # run only LLM-backed tests

# Lint / format
uv run ruff check .
uv run ruff format --check .

# Background worker (runs as its own compose service)
docker compose logs -f qcluster
```

### React island (`/events`)

The Vite dev server runs as its own compose service on port 5173. `django-vite` auto-injects the dev bundle when `DEBUG=True`. Production builds land in `static/dist/` and are served by WhiteNoise.

### Debugging

```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up --build
```

Attach in VS Code: *Attach to App* (Django) or *Attach to qcluster* (worker).
