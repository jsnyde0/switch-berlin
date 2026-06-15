# Harness Inventory — `kinky-bubbles` (Switch Berlin)

Catalog of feedback mechanisms available in this repo. This is the Switch app (public-facing: switch.berlin, repo still named `kinky-bubbles`): a Berlin queer/kinky/conscious events aggregator on Django 5 + HTMX + Alpine.js + a Tailwind/React island built via Vite. Structured by speed (fastest first), then per-category fit profiles. Memory and ADR findings are folded in-line — ADR-008 (FIRM: refactor hard, fail loud, no silent fallbacks on data integrity) is the binding constraint for many of the checks below.

Pantry, not a recipe. Agents compose per-task by consulting fit profiles first.

---

## Fast / deterministic signals

### `ruff` — linter + formatter

- **What**: Python linter (`E`, `F`, `I`, `B`, `UP` rule selectors — pyflakes + pycodestyle + isort + bugbear + pyupgrade) and formatter; configured in `pyproject.toml`. Excludes `**/migrations/*` and `**/test_migrations/*`.
- **Command**: `uv run ruff check .` then `uv run ruff format --check .` (two calls — no `&&`)
- **Speed**: sub-second
- **Catches**: Import ordering, unused imports, style violations, common bugbear patterns, py-version-inappropriate idioms.
- **Useful when**: After any Python edit — first thing to run before tests.
- **Less useful when**: Bug is behavioral; ruff won't catch logic, auth, or routing mistakes.

### `djlint --check` — Django template linter

- **What**: Template linter configured in `pyproject.toml` (`profile = "django"`, `indent = 2`). CI runs it across the whole repo (`uv run djlint --check . --extension=html`), not just `templates/`.
- **Command**: `uv run djlint --check . --extension=html`
- **Speed**: seconds
- **Catches**: Malformed HTML, unclosed Django tags, indentation drift in templates including `templates/cotton/`, `templates/cotton/kb/` (editorial primitives), and per-app `templates/`.
- **Useful when**: After editing templates (cotton components, kb editorial primitives, page templates).
- **Less useful when**: The bug is Alpine.js reactivity or HTMX swap behavior — djlint doesn't parse `x-data`, `@click`, or `hx-*` directives.
- **Reformat caveat**: `uv run djlint --reformat` is NOT whitespace-only — it has collapsed a rendered `" · "` separator to `"·"` and line-wrapped `href` attribute values, both invisible to `djlint --check` AND pytest (kb-33do.3, 2 of 18 templates). After any reformat: lock render with `response.content` assertions (`syndication/test_render_regressions.py`), prefer a filter for literal separators (`{{ x|join:" · " }}`), fence un-wrappable attrs with single-line `{# djlint:off #}`, and fresh-context review the diff — do not self-certify "whitespace-only." Memory `djlint-reformat-mutates-rendered-output`.

### TypeScript build (`tsc -b && vite build`)

- **What**: TypeScript type check + Vite production build with two entries: `src/app.css` (Tailwind v4 + daisyUI) and `src/events/main.tsx` (React island). Output lands in `static/dist/` with a manifest consumed by `django-vite`.
- **Command**: `cd frontend` (separate call), then `npm run build` (separate call)
- **Speed**: seconds
- **Catches**: TypeScript type errors, Vite bundling failures, missing imports between the island and its dependencies (htmx.org, maplibre-gl, nuqs, react, react-dom).
- **Useful when**: After editing `frontend/src/` or changing the Tailwind v4 config (Tailwind v4 reads `@theme` and config from CSS — bundling surfaces config typos).
- **Less useful when**: Editing Alpine.js (CDN-loaded, not in the TS build) or Django template logic.

### `bandit` — Python security linter (CI; uvx-only locally)

- **What**: AST-based static analysis for Python security antipatterns. CI gates on `-lll -iii` (HIGH severity, HIGH confidence) only — lower tiers are noisy. Repo has no `bandit` config file; CI excludes `.venv,node_modules,staticfiles,static`. Not in `pyproject.toml` dev deps — invoked via `uvx`.
- **Command**: `uvx bandit -r . -lll -iii --exclude=./.venv,./node_modules,./staticfiles,./static`
- **Speed**: seconds
- **Catches**: HIGH-severity security antipatterns (shell injection, weak crypto, hardcoded secrets, insecure deserialization). Current baseline is zero findings at the HIGH/HIGH threshold.
- **Useful when**: Adding code that does subprocess execution, shell-outs, deserialization, or crypto. Run before committing such changes to avoid CI-only discovery.
- **Less useful when**: Pure ORM / view-layer work — bandit's signal-to-noise on web request handlers is low at the HIGH/HIGH gate.

### `pip-audit` — CVE scan over locked deps (CI; uvx-only locally)

- **What**: Scans the resolved `uv export` requirements (project deps only, no dev) against PyPI advisory DB. CI runs against the locked pin so the gate fires the moment a CVE drops against a pinned version. No persistent baseline file.
- **Command**: `uv export --frozen --no-dev --no-emit-project --format requirements.txt > /tmp/reqs.txt` (separate call), then `uvx pip-audit -r /tmp/reqs.txt` (separate call)
- **Speed**: seconds (resolution) to ~10s (advisory fetch)
- **Catches**: Known CVEs against pinned production dependencies.
- **Useful when**: After bumping `pyproject.toml` deps, before merging dep changes.
- **Less useful when**: First-party code review — CVE scanning doesn't catch repo-local vulns.

### `gitleaks` — secret scan

- **What**: Pre-commit hook + CI mirror that scans for committed secrets. Pre-commit scans staged changes; CI uses `gitleaks detect --source . --no-banner --redact` with `fetch-depth: 0` (full history) so leaks from past commits surface even after the file is gone from HEAD.
- **Command**: Pre-commit fires it via `uv run pre-commit run gitleaks --all-files`. Direct: install `gitleaks` (Homebrew or release tarball) and run `gitleaks detect --source . --no-banner --redact`.
- **Speed**: seconds (HEAD scan) to ~30s (full-history scan)
- **Catches**: API tokens, private keys, password-bearing URLs accidentally staged or already in history.
- **Useful when**: Before committing anything that touches `.env` patterns, deploy scripts, or fixture files.
- **Less useful when**: Custom secret formats not covered by the default ruleset — repo has no custom ruleset.

### `pre-commit` (ruff + whitespace + check-yaml/toml + gitleaks + pytest)

- **What**: Hook stack configured in `.pre-commit-config.yaml`. Critically includes a `local` hook that runs `uv run pytest` on every Python-file commit (`pass_filenames: false`, `always_run: true`, `types: [python]`) — so pre-commit doubles as a test gate, not just a lint gate.
- **Command**: `uv run pre-commit run --all-files`
- **Speed**: seconds (lint hooks) to ~30–60s (the pytest hook dominates)
- **Catches**: Everything ruff/djlint/gitleaks catch plus all test regressions on any Python edit.
- **Useful when**: Final gate before commit — this is what the user's session-close workflow runs.
- **Less useful when**: Iterating mid-work — too slow for the tight loop. Use targeted pytest while iterating, then pre-commit before committing.

---

## Test suite

### `pytest` — full suite

- **What**: pytest + pytest-django configured in `pyproject.toml`. Default `DJANGO_SETTINGS_MODULE = a_core.settings` (reads `.env`); for isolated runs override with `a_core.test_settings`, which substitutes SQLite `:memory:`, MD5 password hashing, disabled migrations for all local apps (kb-33do.2: `a_core` → `test_migrations`, `syndication` → `test_migrations`, the rest → `None`/run_syncdb — builds tables from current model state, skipping `pgvector`/`pg_trgm` and sidestepping renamed-model historical-FK breakage), and `RATELIMIT_ENABLE = False`. Genuinely Postgres-only tests (schema_editor-in-transaction, `pg_indexes`/`pg_constraint` catalog queries, `EXTRACT(EPOCH)`, `TrigramSimilarity`) carry `@skipIf(sqlite)` and run only on the Postgres path. Auto-excludes `agentic` and `slow` markers via `addopts = "-m 'not agentic and not slow'"`. CI uses real Postgres (pgvector/pgvector:pg17) instead of test_settings so migrations are exercised end-to-end.
- **Command**: `uv run pytest` (uses `a_core.settings` + `.env`) or `DJANGO_SETTINGS_MODULE=a_core.test_settings uv run pytest` (SQLite-only). Root `addopts` carries `--ignore=tools` so bare pytest does not descend into the nested `tools/switch-cli` uv sub-project (kb-33do.6 — collection-time `ModuleNotFoundError` otherwise; switch-cli tests are consequently NOT in main CI). Memory `nested-uv-subproject-breaks-root-pytest-collection`.
- **Speed**: 30–60s for full suite (locally, SQLite)
- **Catches**: View routing + response codes, model constraints, form validation, ingestion pipeline logic (mocked externals), data-migration correctness, deploy-check system checks, auth adapter behavior, middleware behavior (LoginWall, AgeGate, HtmxMiddleware).
- **Useful when**: Before commit, after a non-trivial change, when you need confidence across the codebase.
- **Less useful when**: Tight iteration on one behavior — use targeted scoping (next entry).

### `pytest` — targeted

- **What**: Same suite, scoped to file/dir/`-k`. The repo's two heaviest test trees are `tests/` (cross-cutting), `tests/integration/` (auth/trust-tier/visibility end-to-end via `Client`), `events/tests/` (visibility, OG meta, robots, markers, reviews, m2m), `ingestion/tests/` (pipeline), `accounts/tests*`, `organizers/tests*`, `reviews/tests*`.
- **Command**: `uv run pytest tests/integration/` or `uv run pytest events/tests/test_visibility.py` or `uv run pytest -k "turnstile"`
- **Speed**: seconds to ~15s
- **Catches**: Same as full suite, scoped — far faster feedback for a specific work surface.
- **Useful when**: Actively implementing a feature.

### Shared fixtures (`tests/conftest.py`)

- **What**: Top-level pytest fixtures with two load-bearing autouse hooks: `isolate_logfire_token` (forces `LOGFIRE_TOKEN=""` to prevent contributor `.env` leaks into Logfire from test runs) and `clear_cache_between_tests` (clears Django's cache before+after each test — critical because `django-ratelimit` stores counters in LocMemCache and would cross-contaminate tests with false 429s). Factory fixtures: `approved_organizer`, `published_event`, `user_with_went_attendance`, `past_event_fixture`, `review_for_event_with_count`, `organizer_with_rating_count`, `organizer_with_follower_count`, `superuser`, `staff_user`, `regular_user`.
- **Speed**: per-fixture seconds
- **Catches**: Not a check itself — but the autouse cache-clear means tests that *depend on* rate-limit state must explicitly re-enable `RATELIMIT_ENABLE` via `override_settings` (test_settings disables it by default).
- **Useful when**: Building a targeted test for any surface that needs an organizer, event, vouched user, or denormalized count.

### Deploy-check tests (`tests/test_deploy_check.py`)

- **What**: Exercises Django system checks registered in `a_core/checks.py`: `check_legal_contact` (W006 if DEBUG, E006 if PUBLIC_READ_ENABLED) and `check_turnstile_keys` (E007 if PUBLIC_READ_ENABLED + Turnstile keys missing — ADR-014 D4). Parametrizes across the {DEBUG, PUBLIC_READ_ENABLED} × {present, missing config} matrix. Pre-migrate FeatureFlag-table-missing case is handled and tested.
- **Command**: `uv run pytest tests/test_deploy_check.py accounts/test_open_signup_turnstile.py`
- **Speed**: seconds
- **Catches**: Deploy-config regressions invisible to view-level tests — missing env vars that only matter when `PUBLIC_READ_ENABLED=True`, check-precedence bugs.
- **Useful when**: After adding a new deploy check, modifying `a_core/checks.py`, or wiring a new env-variable dependency. ADR-008 D3 (fail loud) lives here.

### Migration test pattern (`tests/test_organizer_lia_migration.py`)

- **What**: Pattern that loads a Django migration via `MigrationLoader`, gets the migration, and calls each `RunPython` operation's `.code(apps, schema_editor)` directly — no `migrate` invocation needed. Tests forward, reverse, and idempotency.
- **Command**: `uv run pytest tests/test_organizer_lia_migration.py`
- **Speed**: seconds (SQLite in-memory, no schema run)
- **Catches**: Data-migration forward/reverse correctness, idempotency, row-level transformations on existing data.
- **Useful when**: Authoring or modifying a data migration (`RunPython`). Memory `django-m2m-through-compat-property-add-bypass`: when migrating FK→M2M-through with `is_primary`, an `add` bypassing the through-model's defaults is a known trap — exercise via this pattern.

### Integration tests (`tests/integration/`)

- **What**: `Client`-based end-to-end tests covering Turnstile-gated signup, phase-based trust transitions, vouching, invite codes, event visibility, organizer follow, attendance endpoints. These exercise the full middleware stack (`LoginWallMiddleware`, `AgeGateMiddleware`, `HtmxMiddleware`) and the auth adapter — surfaces that unit tests don't hit.
- **Command**: `uv run pytest tests/integration/`
- **Speed**: ~10–20s
- **Catches**: End-to-end auth/trust path correctness, middleware interaction, multi-step flows. Memory `loginwall-must-allow-static-prefix`: any new login-wall middleware that 302s static URLs breaks the asset pipeline silently — integration tests are the cheapest catch.
- **Useful when**: Changes touch middleware, auth adapter, trust transitions, or visibility tiers.

### Ingestion test suite (`ingestion/tests/`)

- **What**: Covers enrichment (URL cap + truncation), extraction (LLM-backed → `EventDraft` schema), task processing, bot dispatch, schedule tasks, digest enhancements, integration. Externals (httpx, pydantic-ai) are mocked. `agentic`-marked tests hit a real LLM and are excluded by default.
- **Command**: `uv run pytest ingestion/tests/ -m "not agentic"`
- **Speed**: seconds
- **Catches**: Pipeline logic, schema mapping, idempotency, approval gate, bot routing.
- **Useful when**: Changing pipeline logic, `EventDraft` schema, task dispatch.
- **Less useful when**: Changing the LLM prompt itself — run `agentic`-marked tests explicitly for that.

### Per-app test suites

- **What**: Each Django app has its own `tests/` or `tests.py`. Notable: `events/tests/` (`test_visibility.py`, `test_views_markers.py`, `test_og_meta.py`, `test_x_robots_tag.py`, `test_event_organizer_m2m.py`, `test_event_facilitator_m2m.py`, `test_review_display.py`, `test_review_sort.py`, `test_trending_sort.py`, `test_following_section.py`, `test_admin.py`, `test_models.py`); `accounts/`, `organizers/`, `reviews/`, `pages/`, `venues/`, `history/` similar.
- **Command**: `uv run pytest events/tests/test_visibility.py`
- **Speed**: seconds per file
- **Catches**: App-local model/view/visibility logic. Memory `data-migration-backfill-default-regresses-prior-visibility` is exercised here — ADR-012 D4 requires visibility floors honor de-facto prior state.

---

## Runtime / observable signals

### Django dev server (`manage.py runserver` or `docker compose up`)

- **What**: Local server for manual probes. Two modes: bare `runserver` (SQLite or whatever `DATABASE_URL` points at) or `docker compose up` (full stack with pgvector/pg17, qcluster for django-q2, telegram bot, and an init container that runs migrate + createsuperuser + collectstatic). The local-overlay `docker-compose.local.yml` provides dev-safe defaults so contributors can `docker compose up` without populating `.env`.
- **Command**: `uv run python manage.py runserver` (bare) or `docker compose up` (full stack)
- **Speed**: seconds to start; manual probe is interactive
- **Catches**: Alpine.js reactivity bugs (filter_chips toggle, `$nextTick` timing, hidden-input `:value` binding), HTMX partial swap behavior, template context errors, CSS visual state, Tailwind v4 → daisyUI cascade. Alpine stores in `static/js/events/store.js` + `bridge.js` + `map.js` are only observable here. Memory `alpine-3-x-directives-mouseenter-click-class-x`: any element with `@click`/`:class`/`x-show`/etc. is *inert* unless an ancestor has `x-data` — only the live browser surfaces this.
- **Useful when**: After any change to Alpine.js logic, HTMX partial endpoints, MapLibre integration (events map), or template context.
- **Less useful when**: The bug is in Python logic — pytest is faster and deterministic.
- **Precondition for any driven pass (kb-ide0.5, 2026-06-04)**: the *running* dev Postgres must carry HEAD's full migration set. A generated-but-unapplied migration is INVISIBLE to pytest (fresh test DBs build from current files, always green) while the live dev app 500s on the missing column. Before a driven `/ui-craft` or `browser-automation` pass after adding a migration: `docker compose exec app python manage.py migrate`, and reset dev data to a clean canonical state (stale dev rows rabbit-hole the verifier). Sibling of memory `editing-applied-migration-in-place-diverges-prod-schema` (prod-graph divergence) — same green-on-fresh-DB blindness, dev-not-migrated direction.
- **Local-overlay launch + template-cache restart (kb-kgza round 3, 2026-06-06)**: the dev server `command` (`./start.sh`) lives ONLY in `docker-compose.local.yml` (base `docker-compose.yml` defines no `command` for `app`). So `docker compose restart app` against the base file does NOT serve the dev server — bring it up with `docker compose -f docker-compose.yml -f docker-compose.local.yml up -d app`. Separately, Django's `cached.Loader` serves STALE templates until the process restarts: a template-only change (e.g. an OOB fragment edit) is invisible to a live browser probe until the `app` container is restarted. A driven readback that "sees no change" after a template edit is usually this, not a broken fix — restart first. Local counterpart to memory `prod-vps-compose-overlay-required`.

### `manage.py check --deploy --fail-level WARNING`

- **What**: Django system check framework with `--deploy` flag, run under prod-shaped env (DEBUG=False, ALLOWED_HOSTS=switch.berlin,..., CSRF_TRUSTED_ORIGINS=https://..., long SECRET_KEY). Triggers Django's security checks plus the repo's custom checks in `a_core/checks.py` (legal contact W006/E006, Turnstile E007). `--fail-level WARNING` is strict — `W005` and `W021` are intentionally silenced in `settings.py` for the HSTS-soak strategy.
- **Command**: `DEBUG=False ALLOWED_HOSTS=switch.berlin SECRET_KEY=<50+chars> uv run python manage.py check --deploy --fail-level WARNING`
- **Speed**: seconds
- **Catches**: DEBUG=True regressions, missing CSRF_TRUSTED_ORIGINS, security header misconfig, missing legal env vars, missing Turnstile keys. CI mirrors this exactly in `.github/workflows/test.yml` under the `check --deploy` step.
- **Useful when**: After changing settings, adding env-var-dependent code, modifying `SILENCED_SYSTEM_CHECKS`, or before merging.
- **Less useful when**: DEBUG-only behavior — many security checks skip when DEBUG=True.

### `manage.py makemigrations --check --dry-run`

- **What**: Asserts there are no unapplied schema changes — i.e., the model graph and on-disk migration set agree. Mirrors CI; catches the "I added a model field but forgot to run makemigrations" class.
- **Command**: `uv run python manage.py makemigrations --check --dry-run`
- **Speed**: seconds
- **Catches**: Out-of-date migration set after model edits.
- **Useful when**: After any change to `models.py` anywhere. CI gates on this.

### `manage.py makemessages -l de` (i18n empty-catalog guard)

- **What**: Regenerates the German `.po` catalog and CI asserts at least one `msgid` is present (`grep -q '^msgid '`). Guards against silent removal of `{% trans %}` tags from templates that would empty the translation pipeline. Requires `gettext` on the system.
- **Command**: `uv run python manage.py makemessages -l de` then verify `locale/de/LC_MESSAGES/django.po` is non-empty.
- **Speed**: seconds (marked as `slow` in pytest, hence excluded from default run)
- **Catches**: Accidentally empty translation catalog.
- **Useful when**: After bulk template edits or after refactoring strings out of templates.

### `gh run watch` / `gh run view` — CI feedback

- **What**: Two workflows: `test.yml` (lint + security + test+deploy-check, runs on push/PR) and `deploy.yml` (prod deploy on push to `main`, paths-ignored for `.beads/`, `docs/`, `history/`, `*.md`). CI's `test` job uses a real pgvector-pg17 service so migrations + Postgres-specific behavior land for real.
- **Command**: `gh run list --workflow=Tests --limit=5` then `gh run view <id> --log-failed`
- **Speed**: ~3–6 min full pipeline
- **Catches**: Postgres-specific migration issues that SQLite test_settings hides, bandit/pip-audit/gitleaks gates, makemessages catalog check, prod-shaped deploy check.
- **Useful when**: After pushing — especially if local was SQLite-only.
- **Less useful when**: Tight inner-loop work; full CI cycle is slow.
- **"CI green" caveat**: a task whose acceptance is "CI green on HEAD" must verify the FULL job set, not a pytest+djlint proxy — `test.yml` gates on `ruff check .` + `ruff format --check .` + `djlint --check` (lint job), bare `uv run pytest` + `makemigrations --check` + `check --deploy` (test job), and `gitleaks` (full history) + `bandit` + `pip-audit` (security job). Run each with its EXACT command (bare `uv run pytest`, not a local `--ignore`'d variant) and reproduce CI's env — tests reading a local `.env` token (e.g. `TELEGRAM_BOT_TOKEN`) pass locally and fail in CI. Local-green ≠ CI-green (kb-33do, 2026-06-02 — a narrow gate closed a parent on a false "CI green" bullet). Memory `ci-green-means-full-ci-job-set-not-pytest-proxy`.

### Logfire (`LOGFIRE_TOKEN` set in prod)

- **What**: Pydantic Logfire instrumentation for production observability. `LOGFIRE_TOKEN` is force-emptied during tests by the autouse fixture in `tests/conftest.py`. In dev/local the token is empty by default.
- **Command**: Not invoked locally; check the Logfire dashboard for prod traces.
- **Speed**: N/A
- **Catches**: Production error rates, slow queries, ingestion pipeline traces. **Less useful when** local — Logfire is off in tests and typically off in dev.

### `browser-automation` skill — real-client render verification (incl. authenticated Telegram web / studio)

- **What**: The `~/.claude/skills/browser-automation` CLI (`start.js` / `nav.js` / `eval.js` / `wait.js` / `screenshot.js` / `type.js`) drives a real Chrome over CDP on `localhost:9222`. This is the **ground-truth signal for any acceptance bullet of the form "an external/real client renders X"** — the class no first-party check (`pytest`, `curl`, `runserver` HTML scrape) can reach, because the truth lives in a *third-party renderer's* behavior (Telegram's unfurler, a browser's cascade, an authenticated SPA's JS).
- **Command**: `node $SKILL/start.js` (idempotent; reuses an existing :9222), then `nav`/`type`/`wait`/`screenshot`. `export SKILL=$HOME/.claude/skills/browser-automation`.
- **Speed**: seconds per step; one-time human login for authed surfaces.
- **Catches**: what a proxy structurally cannot — e.g. kb-t93r: `curl -A TelegramBot` false-greened the OG card (curl's `Accept: */*` dodged the `text/html` age gate) while every real Telegram unfurl was 302'd to `/age-check/`; only driving real Telegram web surfaced it. Also: live Telegram link-preview cards (cache + image render), authenticated **studio** composer flows, Alpine/HTMX reactivity, Tailwind/daisyUI cascade.
- **Authenticated reach (standing capability, est. 2026-06-12)**: the :9222 Chrome can carry a logged-in session for **real Telegram web** (paste a URL into Saved Messages composer → read the rendered card; always use a never-before-seen `?v=<token>` since Telegram caches per-URL and does not strip the param) and the **switch.berlin studio**. One-time human login per surface persists in the profile, then the agent self-serves every subsequent verification — the user is not the verifier. This is what makes "card renders correctly on Telegram" a signal the agent can close itself.
- **Useful when**: the acceptance is user-/external-client-observable (OG cards, rendered UI, authed flows) and a first-party proxy's *default request shape may differ from the real client's* — see Fit profiles → Crawler-facing for the canonical false-green.
- **Less useful when**: the truth is purely server-side (assert with `pytest`); driving a browser for a `response.content`-checkable fact is overkill.

---

## Build-it patterns (no pre-existing check)

When no fast check fits, build one. This repo's tooling makes several patterns cheap:

- **Targeted pytest with shared fixtures** — `tests/conftest.py` carries factory fixtures (`approved_organizer`, `published_event`, `user_with_went_attendance`, `organizer_with_rating_count`, ...) so adding a one-off test for a view, model, or visibility surface is low-overhead. Pair with the autouse `clear_cache_between_tests` so ratelimit state doesn't leak.
- **Migration dry-run script** — `uv run python manage.py sqlmigrate <app> <migration>` shows the SQL pre-apply. For data migrations, mimic `tests/test_organizer_lia_migration.py` (`MigrationLoader` + `RunPython.code()`) for fast feedback without running `migrate`.
- **Alpine.js reactive probe** — `manage.py runserver`, open the page, manually toggle the Alpine surface (filter chips, store-backed map/list interactions in `static/js/events/`). The browser-automation skill can script Chrome via Puppeteer if manual is too slow.
- **Ingestion fixture replay** — construct a synthetic `RawMessage` with realistic text and run `process_raw_message` through patched `httpx` / `pydantic-ai`. The `not agentic` mark guards default runs from LLM cost.
- **Probe scripts in `bin/`** — `bin/init.sh` is the prod bootstrap (migrate + createsuperuser + collectstatic). Build short throwaway scripts here or in `tmp/` (already gitignored).
- **Cumulative-diff parent re-verify** — memory `parent-re-verify-catches-conjunction-drift` recommends a fresh-context cumulative-diff review after multi-bead work; agents can run `git diff <pre-work-sha>..HEAD` and hand it to an adversarial reviewer rather than re-checking each bead.
- **Live spike against a third-party platform API** — when verifying what an EXTERNAL service *actually* does (vs. what its docs claim), drive the real API against a real account; don't trust the spec. For Telegram (kb-mztq, 2026-06-11): a Telethon script with the user's own session, cross-checked against `core.telegram.org`. The live spike caught three things the docs did NOT surface: (1) broadcast channels silently do NOT persist API-set drafts (`saveDraft` no-ops there); (2) Telegram aggressively caches link-preview cards — a STALE age-gate preview survived correct OG tags being deployed (forced the cache-bust work, kb-6d7o); (3) a synced server-side draft can fail to surface in a client already holding a pre-existing LOCAL draft (the "AI Agents Berlin" anomaly). Doc-research would have asserted all three worked. Spike-rig gotchas: macOS `screencapture` cannot capture a window on another Space (Telegram on a different Space returns a blank desktop) — move the window to the active Space first; a `/tmp` probe script's `load_dotenv()` searches the SCRIPT dir not CWD — use `find_dotenv(usecwd=True)` or pass an explicit path. (This repo's harness is otherwise first-party-only — runserver/browser against OUR app; this is its sole third-party-API-behavior entry.) Crawler-facing Accept-gated behavior has its own fit profile — a bare curl's `Accept: */*` false-greens the JuSchG age gate; see Fit profiles → Crawler-facing.

---

## Fit profiles

### Django views

For Django view changes in this repo, prefer `uv run pytest` scoped to the relevant view test file (`events/tests/test_views.py`, `events/tests/test_visibility.py`, `tests/test_views_csd3.py`, `tests/integration/`) because the test `Client` exercises URL routing, the full middleware stack (`LoginWallMiddleware`, `AgeGateMiddleware`, `HtmxMiddleware`), permission checks, ratelimit (re-enable via `override_settings`), and template rendering in one pass — the altitude at which user-observed regressions surface. For changes that add a new env-variable dependency or a deploy-time gate (Turnstile-gated forms, legal-page rendering, public-read flag), pair with `uv run pytest tests/test_deploy_check.py` because deploy-config bugs (missing keys, absent required settings) are invisible to view-level tests but fire as `E00x` at `manage.py check --deploy`. Memory `loginwall-must-allow-static-prefix`: any new middleware that intercepts requests MUST allow `STATIC_URL` and `MEDIA_URL` prefixes — exercise via an integration test that fetches a static asset path through the middleware. **SQLite (the fast test DB under `test_settings`) does NOT enforce `CharField max_length` — an over-length value writes fine under SQLite but raises `DataError` (500) on Postgres in prod (kb-sbhs.3, 2026-06-12: a `friendly_name` overflow passed all tests green, would 500 in prod).** For any user-writable `CharField`/`VarChar`, validate length app-side and return a fail-loud 4xx (ADR-008 D4), then assert the over-length→4xx path in a test — a green over-length test on SQLite is a false green (general class: column-level constraints Postgres enforces and SQLite ignores, cousin of the migration-schema divergence in the pytest entry).

### Crawler-facing / Accept-gated behavior (OG cards, link previews)

`AgeGateMiddleware` (`accounts/middleware.py`) only fires on `text/html` requests, and its `BOT_AGENTS` allowlist decides which crawlers bypass the JuSchG gate. **`curl` defaults to `Accept: */*`, which does NOT contain `text/html` — so a bare `curl -A "<crawlerUA>" <url>` DODGES the gate and returns a FALSE GREEN: the correct OG card, never the gated `/age-check/` interstitial the real crawler hits** (kb-t93r, 2026-06-12 — curl "verified" the kb-6d7o card while every real social unfurler was 302'd to age-check, scraping "Age Verification — Switch Berlin" instead of the event; only search-engine UAs were in `BOT_AGENTS`, Telegram/Twitter/FB/etc. were not). Two fit-for-purpose signals: (1) **cheap decisive repro** — `curl -A "TelegramBot (like TwitterBot)" -H "Accept: text/html" <event-url>`; the `-H "Accept: text/html"` is load-bearing (without it the gate never engages): pre-fix 302s to `/age-check/`, post-fix returns 200 + event `og:title`. (2) **ground truth** — drive the user's logged-in real Telegram web via the `browser-automation` skill (CDP Chrome :9222), type the URL into the Saved Messages composer, read the *rendered* card; this is the only signal that reproduces what the real client shows and is what caught the bug curl structurally could not. Telegram caches per-URL and does NOT strip `?v=`: always verify with a never-before-seen `?v=<token>` (a URL scraped during a broken window stays poisoned until cache expiry; a fresh `?v=` also validates the kb-6d7o cache-bust end-to-end). Unit guard: `accounts/tests.py::test_agegate_social_crawlers_bypass_gate` + `_human_browser_ua_still_gated` pin the middleware decision *with* `HTTP_ACCEPT="text/html"` — they guard the code path, not the false-green class (they can't stop a future bare-curl verification). Memory `curl-default-accept-dodges-content-negotiated-gate`.

### Templates and the kb editorial design system

For template changes in this repo (`templates/`, `templates/cotton/`, `templates/cotton/kb/`), prefer `uv run djlint --check . --extension=html` *plus* a live browser probe via `runserver` because djlint catches HTML/Django-tag structure but cannot see the Tailwind v4 + daisyUI cascade or the kb editorial primitives' visual register (alert, field, field_wrap, page_header, section in `templates/cotton/kb/`). For component-level visual changes, the browser-automation skill can screenshot the rendered surface; pair with `pytest` if the change touches template context (`render` calls). For OG meta or robots-related template changes, scope tests to `events/tests/test_og_meta.py` and `events/tests/test_x_robots_tag.py` — those tests assert on header + meta-tag shape directly. **Two failure classes that both `djlint` and test-Client assertions miss on this surface (each recurred twice in the kb-wz8m syndication epic):** (1) view tests asserting `response.context[...]` instead of `response.content` pass while the template that renders it is broken — assert on rendered HTML (`assertContains` / `response.content.decode()`) for any user-observable acceptance bullet (memory `django-view-test-context-vs-content-hollow`); (2) multi-line `{# #}` comments render as raw page text (Django strips only single-line comments) and are invisible to marker-present assertions — only a browser read-back catches rendered-junk bleed (memory `django-multiline-hash-comment-renders-raw`). For any user-facing template change here, a browser read-back (runserver + `browser-automation` screenshot) is load-bearing, not optional polish. **For a multi-child UI epic, the load-bearing browser read-back runs on the FINAL composed state at parent-re-verify altitude — not the per-child screenshot.** A per-child read-back passes while cross-child wiring stays broken: in kb-q4u9 (2026-06) probe 3 was per-child green, yet a post's "publish-all-ready" fired the event-scoped HTMX endpoint and post-composer cards had no navigation link — both invisible until a read-back of the composed UI (where live tab-switching, inter-workspace nav links, and the fail-loud visible-error path are first reachable). **A composed read-back is still blind to a shared partial's OTHER render context.** When a child extracts a body partial served by BOTH a standalone page AND an embedded/HTMX fragment (kb-9f1h.3's `_post_hub_body.html`), the composed read-back must load EACH context the partial serves — not just the primary assembled flow. kb-9f1h.5 read back the full in-studio composed UI and passed, yet a cross-link carrying `hx-target="#studio-main"` was a silent `htmx:targetError` no-op on the standalone `/syndication/posts/<pk>/` deep-link page (`#studio-main` absent) — caught only at parent re-verify (kb-9f1h.7). "Composed state" means every render context a shared element is reachable in, including the deep-link/refresh path, not only the happy-path navigation through the new shell. Memories `dry-partial-merge-collapses-render-contexts`, `parent-re-verify-catches-conjunction-drift`. **Split the driven `/ui-craft` VERIFY from the FIX (kb-ide0.5, 2026-06-04).** Dispatch the driven pass as a *report-only* verifier (drive the flow, return observations + residual-gap beads — no edits); dispatch any resulting fix as a separate `implementer`. A single agent asked to drive + diagnose + fix + report truncated twice on this surface (stale-dev-data and Puppeteer-`input`-event rabbit-holes); report-only verifiers completed in ~37k–125k tokens. Cross-ref `implementer-subagent-self-report-unreliable-verify-diff`. **A class-of-bug regression guard must scan the whole surface (directory/codebase grep), not the single file the bug first appeared in (kb-kgza.14, 2026-06-06).** kb-kgza.12's per-file content guard checked only `_channel_editor.html` for the document-scoped HTMX `from:` autosave bug; the identical bug survived one file over in `post_syndication.html` and was caught only at parent re-verify. The fix replaced the per-file guard with a directory canary (`syndication/tests/test_autosave_trigger_scope.py::SyndicationTemplatesAutosaveTriggerScopeTest`, `rglob` over `templates/syndication/`). When the bug is a *class* (a forbidden attribute pattern, a forgotten hidden input, a swallow idiom), grep the whole surface — a per-file assertion lags exactly like the inline twin it was meant to guard. Memories `inline-copy-of-shared-partial-drifts`, `parent-re-verify-catches-conjunction-drift`. **A surface-wide content guard with an allowlisted exception must match the allowlist at the OFFENDING-OCCURRENCE level (the specific line/node), not at file level (kb-v93q, 2026-06-07).** `syndication/tests/test_composer_twin_drift_guard.py` rglobs `templates/syndication/` for twin-tell comment idioms (`must match`, `keep in sync`, `copy of`) with one allowlisted exception (the Switch-badge inline mirror of `_sync_bar.html` in `_channel_editor.html`). The first cut tested `allow_fragment in source` — file-level — which silenced EVERY twin-tell idiom in any file that contained the allowlisted comment: a second, illegitimate twin comment dropped into `_channel_editor.html` would pass undetected, blind in the one file that already holds an exception. Fix: allowlist key = `(path_suffix, verbatim_line_fragment)`, matched per-occurrence (`allow_fragment in line` against the same line that triggered the hit). General rule: an allowlist whitelists a *specific occurrence*, never a whole file — file-scoped suppression turns the canary into a per-file blind spot exactly like the per-file guard it replaced. Prove it by injecting a synthetic SECOND twin into the allowlisted file → the guard must still go RED ("the canary passes" is not evidence it bites; only a deliberate red→green cycle is). Also avoid cosmetic structural fingerprints (a Tailwind class, letter-spacing) as the canary's signature — a benign restyle spuriously breaks the guard; pick a semantic marker (a url-name assignment, a template-var interpolation). Memory `surface-wide-guard-allowlist-must-match-occurrence-not-file`. **A view that returns a fragment to an `hx-swap="none"` HTMX request has its response body discarded browser-side — state must be delivered as `hx-swap-oob` (kb-nexw.2, 2026-06-08).** Editing a published Switch listing's canonical surfaced no dirty/Re-publish marker because `event_hub_edit` returned a full fragment to the focus-preserving autosave form (`hx-swap="none"`); HTMX dropped it. This is INVISIBLE to a `response.content`/`assertContains` test — the OOB markup IS in the returned body and the assertion passes; the discard happens in the browser, so only a live read-back (or a test asserting the response is OOB-exclusive) catches it. For every `hx-swap="none"` autosave form in `templates/syndication/`, confirm its view delivers all user-visible state via `hx-swap-oob`, never a returned-and-dropped body. Memory `htmx-swap-none-discards-returned-fragment-oob-only`. **The request-leg sibling: an autosave surface that filters to SUBMITTED keys (to protect partial POSTs from wiping untouched fields) silently breaks setting a checkbox back to False — an unchecked box is absent from the POST body, indistinguishable from "field not in this partial form" (kb-y209.1, 2026-06-11). Expose a checkbox on such a surface only with a hidden companion `<input type="hidden" name="X" value="false">` placed before it (full form only); test the uncheck→False direction, not just check→True — a test that only asserts turning the box ON passes while turning it OFF silently no-ops. Memory `htmx-autosave-checkbox-uncheck-discard-needs-hidden-companion`.** **When a change routes a value through a SHARED resolver claimed as the single source for two surfaces (kb-6d7o, 2026-06-11: `events/og.py::card_image_url` feeding both the live event-page og:image AND the studio preview), a meta-tag-SHAPE or filename-SUBSTRING assertion is hollow — it passes against a parallel inline twin whose output merely overlaps in the common case. kb-6d7o.1 re-implemented the default-fallback inline in `detail.html`; the substring test (`assertContains(response, "og-default.png")`) stayed green while the no-cover absolute URL diverged from the resolver on non-standard ports / SCRIPT_NAME — caught only at parent re-verify (kb-6d7o.4). Assert byte-EQUALITY of the rendered tag to the resolver's direct output for BOTH branches (cover + no-cover), built on the request the view actually used (`response.wsgi_request`): `events/tests/test_og_meta.py:265-304` is the pattern, carrying a "parallel implementation detected" failure message. A single-source claim across surfaces needs an equality test, not a substring. Memories `parent-re-verify-catches-conjunction-drift`, `inline-copy-of-shared-partial-drifts`.**

### Alpine.js components and stores

For Alpine.js changes in this repo, prefer a live browser probe via `manage.py runserver` because Alpine reactivity bugs do not surface under any static check and the repo has no JavaScript test framework. The load-bearing Alpine surface lives in: `templates/cotton/filter_chips.html` (tag toggle + form auto-submit, the densest cotton-level Alpine), `static/js/events/store.js` (Alpine.store('map') with `selectedKey`/`hoveredEventId`/`bounds`), `static/js/events/bridge.js` (Alpine ↔ HTMX glue), `static/js/events/map.js` (MapLibre integration). Per memory `alpine-3-x-directives-mouseenter-click-class-x`: any `@click`/`:class`/`x-show`/`x-bind` is *inert* without an ancestor `x-data` — the live browser is the only place this surfaces. For purely structural HTML (no `x-data`/directives touched), `djlint --check` is the cheaper first pass. Consider browser-automation (Puppeteer) for non-trivial multi-step interactions you'd otherwise repeat by hand. **A user/stored value interpolated into an Alpine expression attribute (`@click`/`x-on`/`:attr="...{{ value }}..."`) is a stored-XSS vector even with Django autoescape ON — the browser HTML-decodes `&#x27;` back to `'` before Alpine evaluates the expression, so the value breaks out of the JS string literal (kb-sbhs.3, 2026-06-12: a theme-tag with a quote injected into the tag chip's `@click`). Pass the value via a plain `data-*` attribute and read `el.dataset.*` in the handler — never into the expression string; verify the quote-bearing value in a live browser (a `response.content` assertion sees the escaped entity and false-greens; the decode-then-eval is browser-side only). Memory `django-autoescape-decoded-before-alpine-expression-eval-xss`.**

### React island (Vite/Tailwind/daisyUI/MapLibre)

For React island changes (`frontend/src/events/`, `frontend/src/app.css`), prefer the Vite TypeScript build (`cd frontend` then `npm run build`) because `tsc -b` catches type errors and `vite build` catches missing imports / config typos in the two bundle entries (`app.css`, `events/main.tsx`). The island writes to `static/dist/` with a manifest that `django-vite` consumes; a build break means the page fails to load assets — observable only when the page is fetched. Pair with a live browser probe via `runserver` (Vite dev server runs on `:5173`, set `origin = http://localhost:5173` in `vite.config.ts`) for behavioral verification. Tailwind v4 reads config from CSS (`@theme` blocks in `app.css`); changes to `daisyui` themes or Tailwind tokens require a rebuild to surface in the django-rendered pages.

### Data migrations and schema changes

For data migrations in this repo, prefer the `MigrationLoader + RunPython.code()` pattern established in `tests/test_organizer_lia_migration.py` to exercise forward + reverse + idempotency without running the full migrate. Note (kb-33do.2): tests that enter `connection.schema_editor()` inside a `TestCase` transaction (including this migration test) are `@skipIf(sqlite)` — SQLite blocks schema edits in a transaction, so they run only on the Postgres path; verify them under default `a_core.settings`, not `test_settings`. Pair with `uv run python manage.py sqlmigrate <app> <migration>` to inspect the generated SQL before applying — schema-level mistakes (wrong column types, missing FK constraints) don't surface in the Python-level test. After model edits, always run `uv run python manage.py makemigrations --check --dry-run` — CI gates on this. Note: `a_core/test_settings.py` disables migrations for all local apps under SQLite (kb-33do.2 — see the pytest full-suite entry above); new apps that add Postgres-only extensions follow the run_syncdb-from-model-state pattern automatically. Memory `data-migration-backfill-default-regresses-prior-visibility`: data migrations that backfill a new visibility column MUST honor de-facto prior visibility as a floor (ADR-012 D4) — write a test that asserts the floor explicitly. Memory `django-migrate-after-restore-from-old-snapshot-gotcha`: restoring an OLD pg_dump pre-RenameModel hits `InconsistentMigrationHistory` — relevant for backup-restore work.

### Ingestion pipeline changes

For ingestion pipeline changes, prefer `uv run pytest ingestion/tests/ -m "not agentic"` because the suite covers enrichment (URL cap + truncation), extraction schema mapping, task idempotency, bot dispatch routing, approval gate, and the `tasks_flags` toggles with mocked externals (httpx, pydantic-ai) — fast and deterministic without LLM cost. For schema changes to `EventDraft` in `ingestion/schemas.py`, scope to `ingestion/tests/test_models.py ingestion/tests/test_pipeline.py` for full-path field-mapping coverage. The `agentic`-marked tests hit a real LLM and are excluded from the default run (`addopts = "-m 'not agentic and not slow'"`); run them explicitly when changing the extraction prompt or LLM provider.

### Auth, trust, and visibility (cross-cutting)

For changes touching the trust model (User.status enum, vouching, invite codes, Turnstile, AgeGate) or visibility tiers (`Event.visibility` matrix per ADR-012), prefer `uv run pytest tests/integration/` first because those tests exercise the matrix end-to-end (e.g. `test_phase_0_5_trust.py`, `test_phase_0_4_auth.py`) and surface middleware-interaction bugs that unit tests miss. Pair with `events/tests/test_visibility.py` for tier-specific access matrices. ADR-009/ADR-012/ADR-013 are the binding decisions; memory `adr-enum-vocabulary-drift-invisible-per-bead` is a caution against silently introducing new enum values without re-scoping the matrix. **A guard or mutation that resolves a row by an identifier shared across tenants (an external platform's chat_id, account id, email) is a cross-tenant leak unless the queryset is owner/tenant-scoped (kb-sbhs.3, 2026-06-12: the picker selectability guard fetched a `PlatformConnection` by Telegram `destination_id` without an organizer filter — two organizers admin'ing the same chat share a chat_id, so a crafted POST mutated the other org's row).** Single-tenant fixtures structurally cannot catch this — add a two-tenant-same-external-id test asserting A's crafted request cannot touch B's row. Memory `unscoped-lookup-by-shared-id-leaks-across-tenants`. **Same blind spot, integrity axis:** a `.get()` resolving on a *partial* unique key (kb-56c2.6, 2026-06-14 — `report_telegram_placements` keyed on `(organizer, platform, destination_id)` but the model's unique key is `(organizer, platform, destination_id, topic_id)`) silently works until a second legitimately-distinct row shares the partial key, then raises `MultipleObjectsReturned`→uncaught 500. Single-*row* fixtures miss it exactly as single-*tenant* fixtures miss the cross-tenant leak — seed ≥2 rows sharing the partial key, and catch both `DoesNotExist` and `MultipleObjectsReturned` as structured errors. Both traps ride the same external-id `.get()`; both surfaced only at parent re-verify, not per-child green. Memory `resolve-by-full-unique-key-partial-get-breaks-on-second-row`.

### ADR authorship and substrate writes

For ADR authorship or edits (`docs/decisions/`), prefer the `/scout-adrs` and `/adr-write` slash-skills over freehand because they enforce the in-place edit + firmness asymmetry from ADR-011 / ADR-013. Memory `adr-placement-structural-fit-over-adjacency`: when placing a new cross-cutting decision, structural fit beats chronological adjacency. `docs/decisions/INDEX.md` is the navigation surface; per-decision firmness (FIRM / FLEXIBLE / EXPLORATORY) is load-bearing. No automated check exists for ADR shape — fresh-context `/adversarial-review` is the discipline.

### Pre-commit / pre-push

Before committing, prefer `uv run pre-commit run --all-files` because the local `pytest` hook means pre-commit is both lint gate and test gate. Before pushing, the CI mirror (test.yml) catches Postgres-specific issues SQLite hides, plus bandit/pip-audit/gitleaks/makemessages — `gh run watch` after push is the fastest way to learn what CI will gate on.

---

## Conventions worth knowing

- **Public name vs. repo name.** Project rebranded to **Switch Berlin** (domain: switch.berlin) in May 2026; the GitHub repo is `switch-berlin`, but this local checkout is still named `kinky-bubbles`. Memory `project-rebrand-switch` has the details. Some legacy strings (`kb-*` bead-ID prefix, the `kb` cotton namespace, this directory name) retain the old name — that's intentional, not stale.
- **SQLite for tests, Postgres in dev/prod.** `a_core/test_settings.py` substitutes SQLite `:memory:` and disables migrations (run_syncdb) for all local apps to skip `pg_trgm` / `pgvector` and bypass historical FK resolution for renamed models (organizers.Organizer → Profile). CI uses real pgvector/pg17 so migrations + Postgres extensions are exercised in CI even though local test runs skip them. The fast SQLite loop runs all apps' tests; Postgres-only tests (EXTRACT/SIMILARITY/pg_constraint/schema_editor-in-transaction) are marked `@skipIf(sqlite)` and run on the default-Postgres path only. Fixed: kb-33do.2.
- **`agentic` and `slow` markers excluded by default.** `pyproject.toml` `addopts = "-m 'not agentic and not slow'"`. Tests that hit real LLMs or run `makemessages` must opt in explicitly (`-m agentic` or `-m slow`).
- **Pre-commit's `pytest` hook is `always_run: true` on Python edits.** Pre-commit doubles as test gate — expect 30–60s on every Python commit.
- **`LOGFIRE_TOKEN` autouse-isolated in tests.** Contributors with a real `LOGFIRE_TOKEN` in `.env` won't accidentally emit prod telemetry from `pytest`.
- **Ratelimit cache cleared autouse.** `django-ratelimit` uses `LocMemCache`; `clear_cache_between_tests` prevents 429 cross-talk. Tests that *need* ratelimit must `override_settings(RATELIMIT_ENABLE=True)` because test_settings disables it.
- **Alpine.js is CDN-loaded.** No local Alpine import or build step — pulled from `unpkg.com` in `_base.html`. No Vite/TypeScript coverage for Alpine directives.
- **ruff excludes migrations.** `**/migrations/*` and `**/test_migrations/*` are excluded — migration files are not lint-gated.
- **Docker compose for full-stack work.** App connects to `postgres://postgres:postgres@db:5432/postgres` by default. For pure Django-model/view work, SQLite via `a_core.test_settings` is sufficient.
- **`docker-compose.yml` is the base; overlays compose.** `docker-compose.local.yml` carries dev defaults (DEBUG=True, hard-coded superuser, `tail -f /dev/null` so contributors can exec freely). Prod uses `docker-compose.yml + docker-compose.prod.yml` per memory `prod-vps-compose-overlay-required`.
- **No `&&` chains in Bash calls.** Repo hooks block compound shell commands; this affects subagents too. Split into separate tool calls.
- **No mypy.** Despite a `.mypy_cache/` directory, mypy is not configured in `pyproject.toml` and no CI step runs it. Type-only feedback comes from `tsc -b` for the React island.
- **No JS test framework.** Alpine and the React island have no jest/vitest/playwright coverage — runtime browser probing or build-time `tsc` is the only signal.
- **ADR-008 D3 (FIRM) is binding.** No silent fallbacks on data integrity — raise/log/render-visible-error, never zero-fill or synthesize. Memory `2026-05-18-adr-008-d3-silent-fallback-audit` records the standing audit. When reviewing PRs, look for `try/except: pass` and default-value zero-fills.

## Entrypoints

- `CLAUDE.md` — agent instructions, beads integration, ADR pointer.
- `docs/decisions/INDEX.md` — ADR table with scope tags and "when to consult".
- `docs/runbooks/` — operational runbooks (`panic-mode.md`, `week-off.md`).
- `docs/compliance/` — DPA + LIA docs (legal compliance artifacts).
- `a_core/settings.py` + `a_core/test_settings.py` — base + test-override settings.
- `a_core/checks.py` — custom deploy checks (W006/E006/E007).
- `a_core/middleware.py` — LoginWall / AgeGate / Htmx middleware.
- `tests/conftest.py` — shared fixtures + autouse isolation.
- `tests/integration/` — auth/trust/visibility end-to-end.
- `ingestion/` — ingestion pipeline app.
- `templates/cotton/` + `templates/cotton/kb/` — cotton components + editorial primitives.
- `static/js/events/` — Alpine stores, MapLibre, HTMX-Alpine bridge.
- `frontend/src/events/main.tsx` — React island entry.
- `.github/workflows/test.yml` — full CI mirror (lint + security + test).
- `.github/workflows/deploy.yml` — prod deploy pipeline.
