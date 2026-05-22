# Harness Inventory — `kinky-bubbles`

A catalog of feedback mechanisms available in this repo. This is the Switch app: a Berlin queer/kinky/conscious events aggregator built on Django + HTMX + Alpine.js + React island. The inventory is structured by speed (fastest first), followed by per-category fit profiles that tell agents which mechanism to reach for on each work surface.

Pantry, not a recipe. Agents compose per-task by consulting fit profiles first.

---

## Fast / deterministic signals

### `ruff` — linter + formatter

- **What**: Python linter (pyflakes + pycodestyle + bugbear + isort) and formatter, configured in `pyproject.toml`. Excludes migrations and test_migrations directories.
- **Command**: `uv run ruff check .` / `uv run ruff format --check .`
- **Speed**: seconds
- **Catches**: Import ordering, unused imports, style violations, common bugbear patterns.
- **Useful when**: After any Python edit — catches trivial errors before running tests.
- **Less useful when**: The bug is behavioral (ruff won't catch logic errors, missing auth checks, or view routing mistakes).

### `pre-commit` (ruff + trailing-whitespace + check-yaml + gitleaks)

- **What**: Pre-commit hooks configured in `.pre-commit-config.yaml`. Runs ruff (lint + format), whitespace fixers, YAML/TOML check, gitleaks secret scan, AND pytest on every Python file commit.
- **Command**: `uv run pre-commit run --all-files`
- **Speed**: seconds to ~1 minute (pytest runs as part of the hook)
- **Catches**: Everything ruff catches + accidentally committed secrets (gitleaks) + test regressions (pytest hook).
- **Useful when**: Before committing — this is the gate. The `pytest` hook means pre-commit doubles as test gate.
- **Less useful when**: Iterating quickly mid-work — too slow for tight loop; run targeted pytest instead.

### TypeScript build check (`tsc -b && vite build`)

- **What**: TypeScript type check + Vite bundle build for the React island (EventsIsland.tsx + main.tsx). Configured via `frontend/tsconfig.json`.
- **Command**: `cd frontend && npm run build`
- **Speed**: seconds
- **Catches**: TypeScript type errors, Vite bundling failures.
- **Useful when**: After editing frontend TypeScript (`frontend/src/`). The React island is currently scaffolding-only (`EventsIsland.tsx` just renders placeholder text), so this signal is low-value until the island grows.
- **Less useful when**: Changing Alpine.js template logic — Alpine is CDN-loaded and not part of the TS build.

---

## Test suite

### `pytest` — full suite

- **What**: pytest + pytest-django, configured in `pyproject.toml`. Settings module: `a_core.settings` (default); `a_core.test_settings` substitutes SQLite in-memory and no-op migration modules for pg-specific extensions. Auto-excludes `agentic` and `slow` markers by default.
- **Command**: `uv run pytest` (uses SQLite in-memory via `DJANGO_SETTINGS_MODULE=a_core.settings`, which reads `.env` — for isolated test runs use `a_core.test_settings`)
- **Speed**: 30–60 seconds for full suite
- **Catches**: View routing + response codes, model constraints, form validation, ingestion pipeline logic (mocked externals), migration data correctness, deploy-check system checks, auth adapter behavior.
- **Useful when**: Before commit, after a non-trivial change, when you need confidence across the whole codebase.
- **Less useful when**: Tight iteration on one specific behavior — use targeted `pytest tests/path/to/specific_test.py` instead.

### `pytest` — targeted

- **What**: Same as above but scoped to a test file, directory, or `-k` expression.
- **Command**: `uv run pytest tests/test_views_csd3.py` / `uv run pytest ingestion/tests/` / `uv run pytest -k "turnstile"`
- **Speed**: seconds (single file) to ~10s (one app's tests)
- **Catches**: Same as full suite but scoped — faster feedback loop for a specific work surface.
- **Useful when**: Actively implementing a feature and iterating on a single test file.

### Deploy-check test (`tests/test_deploy_check.py` + Turnstile checks)

- **What**: Tests that exercise Django system checks (`check_legal_contact`, `check_turnstile_keys`) registered in `a_core/checks.py`. These checks fire on `manage.py check --deploy` and on startup. Tests parametrize across `{DEBUG, PUBLIC_READ_ENABLED}` and present/missing config.
- **Command**: `uv run pytest tests/test_deploy_check.py accounts/test_open_signup_turnstile.py`
- **Speed**: seconds
- **Catches**: Deploy-config regressions — missing environment vars, absent keys, check precedence bugs. The Turnstile E007 check is an example: it only surfaces when `PUBLIC_READ_ENABLED=True` + Turnstile keys missing, a class of bug invisible to view-level tests.
- **Useful when**: After adding a new deploy check, modifying `a_core/checks.py`, or wiring a new env-variable dependency.
- **Less useful when**: The problem is in runtime behavior rather than config completeness.

### Migration test suite (`tests/test_organizer_lia_migration.py` + pattern)

- **What**: Tests that exercise Django migration forward/reverse functions by loading the migration executor and calling RunPython operations directly (without running `migrate`). Pattern: `MigrationLoader + get_migration + operation.code(apps, schema_editor)`.
- **Command**: `uv run pytest tests/test_organizer_lia_migration.py`
- **Speed**: seconds (in-memory SQLite, no schema changes needed for data migration tests)
- **Catches**: Data migration forward/reverse correctness, idempotency, row-level transformations, edge cases on existing data.
- **Useful when**: Authoring or modifying a data migration (RunPython). Tests the migration function logic without requiring a live database.

### Integration tests (`tests/integration/`)

- **What**: Django TestCase tests that exercise full request-response cycles with a test client. Cover auth flows (Turnstile-gated signup, phase-based trust model, vouching, invite codes), event visibility, organizer follow.
- **Command**: `uv run pytest tests/integration/`
- **Speed**: ~10–20s
- **Catches**: End-to-end auth path correctness, middleware interaction (LoginWallMiddleware, AgeGateMiddleware), trust tier transitions.
- **Useful when**: Changes touch middleware, auth adapter, or multi-step user flows.

### Ingestion test suite (`ingestion/tests/`)

- **What**: Tests for the ingestion pipeline: enrichment (URL fetch + parsing), extraction (LLM-backed EventDraft), task processing, bot dispatch, schedule tasks. External calls (httpx, pydantic-ai) are mocked; internal logic is exercised directly.
- **Command**: `uv run pytest ingestion/tests/ -m "not agentic"`
- **Speed**: seconds (mocked externals); agentic-marked tests hit real LLM — excluded by default.
- **Catches**: Enrichment cap/truncation, extraction schema mapping, task idempotency, approval gate, bot dispatch routing.
- **Useful when**: Changing pipeline logic, schema shapes, or task dispatch behavior. `not agentic` guard means you can iterate without LLM cost.

---

## Runtime / observable signals

### Django dev server + browser manual probe

- **What**: `uv run python manage.py runserver` (or `docker-compose up app` for full stack with Postgres). Alpine.js components render in the live browser; reactivity is only observable here.
- **Command**: `uv run python manage.py runserver` (SQLite) or `docker compose up` (full stack)
- **Speed**: seconds to start; interactive probe is manual
- **Catches**: Alpine.js reactivity bugs, HTMX partial rendering, template context errors, CSS visual state. The filter_chips component (`templates/cotton/filter_chips.html`) reactivity (tag toggle state, form auto-submit on change) is not covered by pytest — only observable in a live browser.
- **Useful when**: After any change to Alpine.js `x-data` logic, HTMX partial endpoints, or template context.
- **Less useful when**: The bug is in Python logic — pytest is faster and deterministic for that.

### `manage.py check --deploy`

- **What**: Django system check framework with `--deploy` flag. Triggers all registered checks including security checks (HTTPS settings, HSTS, secret key), custom checks in `a_core/checks.py` (legal contact W006/E006, Turnstile E007), and any extension checks.
- **Command**: `uv run python manage.py check --deploy --settings=a_core.settings`
- **Speed**: seconds
- **Catches**: Missing env vars that only matter in production (TURNSTILE keys, legal contact fields, HTTPS settings). This is the mechanism that catches the Turnstile-keys-missing class of bug — view tests pass, deploy fails.
- **Useful when**: After adding a new env-variable dependency, changing `SILENCED_SYSTEM_CHECKS`, or before deploying.
- **Less useful when**: The issue is in test/dev mode only (many security checks skip when `DEBUG=True`).

### `djlint` — Django template linter

- **What**: Template linter configured in `pyproject.toml` (`profile = "django"`). Catches HTML formatting issues, unclosed tags, attribute errors in Django templates.
- **Command**: `uv run djlint templates/ --check`
- **Speed**: seconds
- **Catches**: Malformed HTML, unclosed Django template tags, indentation issues.
- **Useful when**: After editing templates, especially django-cotton components.
- **Less useful when**: The bug is in Alpine.js logic rather than HTML structure — djlint doesn't parse Alpine directives.

---

## Build-it patterns (no pre-existing check)

When a fast check doesn't exist, build one:

- **Alpine.js reactive probe** — launch `runserver`, open the relevant page in a browser, manually toggle filter chips or trigger the Alpine component. No automated test framework covers Alpine reactivity in this repo. The browser-automation skill can script Chrome + Puppeteer if manual probing is too slow.
- **Migration dry-run script** — `uv run python manage.py sqlmigrate <app> <migration>` shows the SQL before applying. For data migrations, the existing MigrationLoader pattern in `test_organizer_lia_migration.py` is the build-it reference.
- **Targeted pytest fixture** — the `conftest.py` has well-factored fixtures (approved_organizer, published_event, user_with_went_attendance) — adding a new targeted test for a specific view or model behavior is low-overhead.
- **Ingestion fixture replay** — for pipeline changes, construct a synthetic `RawMessage` with realistic text and run `process_raw_message` through a patched external calls layer (httpx, pydantic-ai).

---

## Fit profiles

### Django views

For Django view changes in this repo, prefer `uv run pytest` targeting the relevant view test file (e.g., `events/tests/test_views.py`, `tests/test_views_csd3.py`, `tests/integration/`) because the test client exercises URL routing, middleware stack (LoginWallMiddleware, AgeGateMiddleware, HtmxMiddleware), permission checks, and template rendering in one pass — matching the altitude at which user-observed regressions surface. For changes that add a new env-variable dependency or deploy-time config (e.g., adding Turnstile-gated features), pair with `uv run pytest tests/test_deploy_check.py` or the relevant system-check test, because deploy-config bugs (missing keys, absent required settings) are invisible to view-level tests but surface as E00x errors at `manage.py check --deploy` — the Turnstile E007 pattern is the precedent.

### Alpine components

For Alpine.js component changes in this repo, prefer a live browser probe (via `uv run python manage.py runserver` + manual interaction) because Alpine reactivity bugs — toggle state, `$nextTick` timing, `:value` binding on hidden inputs — do not surface under static analysis or pytest, and the repo has no JavaScript test framework. The load-bearing Alpine components are `filter_chips.html` (tag toggle + form auto-submit, the most complex Alpine logic in the repo) and the date inputs in the same file. If the change is purely structural HTML (no `x-data` / `@click` / `:class` directive changes), `djlint templates/ --check` is sufficient for a first pass. For Alpine reactivity changes, the browser is the only goal-faithful signal currently available — consider using the browser-automation skill to script the probe if the interaction is non-trivial.

### Data migrations

For data migrations in this repo, prefer the `MigrationLoader + RunPython.code()` pattern established in `tests/test_organizer_lia_migration.py` because it exercises the migration function logic (forward + reverse + idempotency) in SQLite in-memory without running `migrate` on the full schema — fast (seconds) and deterministic. Pair with `uv run python manage.py sqlmigrate <app> <migration>` to inspect the generated SQL before applying to any live database, because `sqlmigrate` will surface schema-level mistakes (wrong column types, missing FK constraints) that the Python-level migration test won't catch. Note: `a_core/test_settings.py` swaps `a_core` and `ingestion` migrations for no-op overrides (to skip `pg_trgm` extension dependency in CI); new app-level no-op overrides should follow this pattern if they add postgres-only extensions.

### Ingestion pipelines

For ingestion pipeline changes in this repo, prefer `uv run pytest ingestion/tests/ -m "not agentic"` because the test suite covers enrichment (URL cap + truncation), extraction schema mapping, task idempotency, bot dispatch routing, and approval gate logic with mocked externals (httpx, pydantic-ai) — giving fast, deterministic feedback without LLM cost. For schema changes to `EventDraft` in `ingestion/schemas.py`, also run `uv run pytest ingestion/tests/test_models.py ingestion/tests/test_pipeline.py` because those tests exercise the full path from raw text to persisted model fields and will catch field-mapping regressions. The `agentic`-marked tests hit a real LLM and are excluded from the default run (`addopts = "-m 'not agentic and not slow'"`); run them explicitly when changing the extraction prompt or LLM provider configuration.

---

## Conventions worth knowing

- **SQLite for tests, Postgres in dev/prod.** `a_core/test_settings.py` substitutes SQLite `:memory:` for all pytest runs. This means `pg_trgm`, `pgvector`, and other Postgres extensions cannot be tested in CI — their migrations are swapped for no-ops in `MIGRATION_MODULES`. Keep this in mind when writing migrations that use Postgres-specific features.
- **`agentic` and `slow` markers are excluded by default.** `pyproject.toml` `addopts = "-m 'not agentic and not slow'"`. Tests hitting real LLMs or running `makemessages` must be explicitly opted-in.
- **Alpine.js is CDN-loaded.** There is no local Alpine import or build step — it's pulled from `unpkg.com` in `_base.html`. No Vite/TypeScript coverage for Alpine directives.
- **Docker compose is required for Postgres-dependent work.** The app connects to `postgres://postgres:postgres@db:5432/postgres` by default. For purely Django-model and view work, SQLite via `a_core.test_settings` is sufficient.
- **ruff excludes migrations.** `pyproject.toml` `exclude` list includes `**/migrations/*` and `**/test_migrations/*` — linter won't flag style issues in migration files.

## Entrypoints

- `CLAUDE.md` — agent instructions and ADR pointer
- `docs/decisions/INDEX.md` — ADR table (cross-cutting decisions like trust model, visibility tiers, code posture)
- `a_core/settings.py` + `a_core/test_settings.py` — settings and test overrides
- `tests/` — top-level test suite (views, deploy checks, migrations, integration flows)
- `ingestion/` — ingestion pipeline app (models, tasks, schemas, tests)
- `templates/cotton/filter_chips.html` — primary Alpine.js component
- `frontend/src/` — React island (currently scaffolding)
