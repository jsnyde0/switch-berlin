# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Current focus (updated 2026-07-07)

The main thread is the **Challenge spine** (dogfood-as-design walks), NOT the scattered backlog. Strategy: **agent-first for facilitators** — capability in `switch-cli`, skills as thin wrappers, composable delivery rails (own Telegram/FetLife, compose Instagram/newsletters via external tools), and **all data through Switch** as system of record. Canonical: [ADR-019](docs/decisions/ADR-019-agent-harness-as-a-product.md) (esp. D6) + bd memory `challenge-driven-dogfood-as-design-main-thread`.

Next work: the two agent-surface gap beads under the Challenge 0 epic (`kb-k2ds.2` front-door verbs, `kb-k2ds.3` enable-for-promotion), then the Challenge 0 walk (`kb-k2ds.1`, needs the user at their phone). The UI-polish tail is **frozen** (deferred beads) — do not surface it as active work; no new UI investment unless a challenge walk demands it.

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


## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

### Decisions

Cross-cutting load-bearing decisions live in [`docs/decisions/`](docs/decisions/INDEX.md). Start at the INDEX for the scope-tagged ADR table and "when to consult" guidance. ADRs evolve in place; never silently contradict a FIRM decision.

### Code posture (V0, pre-launch)

Refactor hard, fail loud. See [ADR-008](docs/decisions/ADR-008-code-posture-refactor-hard-fail-loud.md) for the binding decisions:

- **D1:** No backward compatibility shims until V1 — delete on sight, no deprecation paths.
- **D2:** No speculative abstraction — simplest thing that works, one clear path. Extract from the third diverging caller, not the first.
- **D3:** No silent fallbacks on data integrity — raise, log with reason, render visible error state. Never zero-fill or synthesize missing fields.
- **D4:** Transport errors (network blips) get up to 2 retries then fail loud; data-integrity errors (4xx/5xx, parse errors, schema mismatches) never retry.

The additive counterpart — *what shape to give deferred features now at zero cost* — lives in [ADR-003](docs/decisions/ADR-003-cheap-foresight-patterns.md). The tension between ADR-008 D2 (no speculative abstraction) and ADR-003 (cheap foresight) is intentional: cheap foresight is for *data shape and naming*, ADR-008 D2 forbids speculative *behavioral* abstraction.
