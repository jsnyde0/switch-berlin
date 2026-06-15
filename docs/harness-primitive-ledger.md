# Harness primitive ledger

The cheap-foresight tracking surface for [ADR-019 D3](decisions/ADR-019-agent-harness-as-a-product.md) — the Switch agent harness as a product.

**What this is:** a running inventory of every primitive we build or reuse while walking the challenge journeys, so that isolating and publishing a primitive later (to users / pi / Codex / standalone) is cheap — we already know its lever, its dependency closure, and how portable it is. **Naming + tracking only — no machinery** (ADR-003-legal).

**What this is NOT:** a package manifest, a build system, or a dependency resolver. It is a doc. If it starts wanting to be code, that's the ADR-008 D2 "third caller" signal to design the real thing — until then it stays a table.

## How to use it

- **Add a row** whenever a challenge walk builds a new primitive or reuses an existing one as load-bearing.
- **Lever** ∈ `CLI` · `skill` · `hook` · `command` · `subagent` · `MCP` · `plugin` (per ADR-019 D1 / `/design-claude-extension`). Load-bearing *capability* should be `CLI`; `skill`/`hook` rows should be thin convenience wrappers.
- **Harness** ∈ `product` (shipped to Switch users) · `operator` (our own substrate) — keep them distinct per ADR-019 D4.
- **Dependencies** = the closure needed to run it standalone (other CLIs, external skills like `browser-automation`, API tokens/credentials, local sessions, runtime).
- **Portability** ∈ `Claude-only` · `CLI-portable` (runs over bash for any agent/human/CI) · `published` (extracted + installable standalone).
- **Review flag:** a `skill`/`hook` row whose primitive *does something* (not just thinks) is a flag to push the doing into a `CLI` verb (ADR-019 D1).

## Ledger

| Primitive | Lever | Harness | Dependencies | Portability | Notes |
|---|---|---|---|---|---|
| `switch-cli` (pair / configure / approve-projection / publish-projection / telegram distribute) | CLI | product | Switch REST API + Bearer/identity token; local Telegram session for `telegram distribute` (MTProto) | CLI-portable | The seed CLI and the canonical capability home (ADR-019 D1). Already drives the dogfood walk. |
| `browser-automation` | skill (+ CLI scripts) | operator (reused) | Chrome on CDP :9222; node scripts (start/nav/eval/wait/screenshot) | Claude-only (skill) over CLI-portable scripts | Reused as the studio read-back "eyes" (ADR-019 D5; bd memory `studio-composer-browser-readback-recipe`). Reuse-of-existing, not a new abstraction. Entanglement-with-operator-substrate is the thing to watch before any standalone publish. |

_Rows are added as challenge walks surface real primitives — do not pre-populate speculatively (ADR-008 D2). The two seed rows above are the primitives already in hand at ledger creation (2026-06-15)._
