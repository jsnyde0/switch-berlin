# Repository Guidelines

## Project Structure & Modules
- Root uv workspace with `api/`, `pipeline/`, and `models/` packages; shared config in `pyproject.toml` and `.env` (see `.env.example`).
- API service code lives in `api/src/`; pipeline logic under `pipeline/core/` with Prefect flows in `pipeline/orchestration/`; shared Pydantic/SQLAlchemy models in `models/src/`.
- Tests sit alongside each package (`pipeline/tests/`, `models/tests/`); assets/docs in `docs/` and the provided Dockerfiles compose the local stack.

## Build, Test, and Development Commands
- Install hooks/tools: `uv run pre-commit install` (enables lint/format on commit).
- Lint/format: `uv run ruff check .` and `uv run ruff format .` (88-char lines, double quotes, spaces).
- Run tests: `uv run pytest` (from repo root) or `cd pipeline && uv run pytest` for pipeline-only.
- Local stack: `docker compose up --build` to launch DB + Prefect + pipeline; add `-f docker-compose.debug.yml` to wait for a debugger on port 5678.

## Coding Style & Naming
- Python 3.12; prefer typed functions and Pydantic models for data boundaries.
- Stick to ruff defaults in `pyproject.toml` (E,F,I,B); keep imports sorted; 4-space indents, double quotes, and concise docstrings for flows/tasks.
- Name tests and flows descriptively (e.g., `test_fetch_events.py`, `siegessaeule_flow`).

## Testing Guidelines
- Use `pytest`; mark LLM-dependent cases with `@pytest.mark.llm` and skip via `-m "not llm"` when needed.
- Favor unit-level tests around parsers and model validators; integration tests can rely on docker-compose services.
- Aim for deterministic fixtures; avoid hitting real external APIs without vcr/mocks.

## Commit & PR Guidelines
- Follow the existing style: short, present-tense summaries (e.g., `add scrape fallback`, `fix prefect deployment env`).
- Before opening a PR: ensure `uv run ruff check .` and `uv run pytest` pass; include relevant screenshots/log snippets for UI or flow changes.
- Reference related issues or links in the PR body; briefly describe pipeline impacts (new flows, env vars, DB schema changes) and any migration steps.

## Environment & Secrets
- Keep secrets in `.env` (root) and never commit them; docker-compose reads from it.
- Document new env vars in `README.md` or service-specific README and provide safe defaults when possible.
