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

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->
