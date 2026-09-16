# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Current focus (updated 2026-09-15)

**Vision:** replace FetLife with a better alternative ("FetLife meets Hipsy"). **Growth logic:** a Switch already populated with real events and claimable organizer profiles attracts visitors, which attracts promoters, who claim their profile and manage events through the agent harness, including events not public anywhere. Canonical: mem `switch-two-track-spine-and-vision` (spine) + `challenge-driven-dogfood-as-design-main-thread` (method) + [ADR-019](docs/decisions/ADR-019-agent-harness-as-a-product.md).

**Two parallel tracks, both challenge/walk-driven** (walk one honest journey, file children only as the walk reveals friction, never pre-decompose):

- **Track A, event collector** (`sb-7wzb`): consolidate Berlin events from public sites (IKSK first) and Telegram channels into Switch. First act = brainstorm sitting with the user (`sb-7wzb.1`): outcome, sources, positioning ruling vs ADR-010 canonical-home.
- **Track B, agentic harness for facilitators** (`sb-k2ds`): capability in `switch-cli`, skills as thin wrappers, all data through Switch. Next = the Challenge 0 walk (`sb-k2ds.1`, needs the user at their phone), then co-design Challenge 1 (`sb-z50e`: website skill / marketing-channel skills / FetLife).
- **Cross-cutting:** `sb-n41z` turns walks into agentic e2e drives via `/verify scaffold`, after the first hand-walk.

The UI-polish tail is **frozen** (deferred beads); no new UI investment unless a walk demands it. Business model lives in `sb-uy99`; do not settle it before a facilitator asks to pay.

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

## Persistent Knowledge

Durable knowledge lives in `mem`, workspace `switch-berlin` — not in `bd remember`, not in MEMORY.md files. The 77 memories this project once held in bd were migrated to `mem` on 2026-09-15 and the bd memory store is now empty; re-populating it re-splits the substrate.

- Query: `mem context "<task>"`; read one: `mem show <slug>`. The session-start hook injects the cluster-hub index at T=0.
- Write: `mem add --kind <kind> --scope workspace --key <lesson-naming-slug> "<body>"`. Read `mem add --help` for the write-time quality bar (slug / tier / link / scope tests) — it is canonical, do not restate it here.
- Default `--scope workspace`. Reach for `global` only if the lesson survives stripping every project-specific noun.

Done-condition for any knowledge write: `mem check` exits 0 and `mem show <slug>` returns your fact.

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
