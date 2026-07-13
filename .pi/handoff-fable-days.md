# Handoff — making the most of the Fable days across my own repos

**Read this first, then start work.**

## What this is

I (the repo owner, jsnyde0) have a few days left with the Fable model and want to spend it on the
**highest-judgment work** across repos **I authored myself** — the stuff where the top-end model's edge
is largest and successors (Opus/Sonnet) can execute the fixes afterward. Fable *finds and decides*;
later sessions *execute*.

There are **four workstreams**, not one. They matter roughly equally; emphasis varies per repo:

1. **Architecture reviews** — per repo: module boundaries, coupling, coherence, deletion tests. Output: findings + ADRs.
2. **Open design forks** — genuinely unresolved decisions I'm carrying, argued adversarially both ways, resolved into ADRs.
3. **The Challenge spine** — push the actual product thread in switch-berlin forward.
4. **Security / robustness hardening** — for the security-relevant repos, review the threat model and find
   weak spots *to fix*. This is ONE stream, not the frame for everything.

Everything lands as **beads and ADRs** (discoverable via `bd`), or a report referenced from a bead.

## Framing rule — applies mainly to workstream 4 (security)

A previous session got bumped off Fable mid-task. The cause was **framing + breadth on the security stream**,
not the topic: offensive verbs ("red-team", "find the escape", "bypass-hunting") stacked together and applied
fleet-wide read like offensive tooling to a blunt classifier — even for one's own repos.

Workstreams 1–3 (architecture, design forks, product) carry **zero flag risk** — no special framing needed.
For workstream 4 only:
- **Defensive verbs.** "Review the threat model and find weaknesses to fix / harden the boundary."
  Not "attack / bypass / escape / evade."
- **One repo, concrete scope, per session.** Not "sweep all repos and rank attack surface."
- **State it's my own authored repo, hardening pass** — once, plainly.
- Expect that **deep sandbox-escape work on rip-cage** may flag anyway (genuinely dual-use). That's the
  one place an Opus fallback is acceptable; don't fight it.

## First session = PLANNING, not concrete work

The **first** fresh Fable session should produce the **overall plan/roadmap**, not dive into one repo.
Deliverable: a bead epic (or roadmap doc referenced from a bead) that lays out, across all the repos below,
what gets worked on, in what order, with what emphasis (architecture / design fork / product / hardening) —
so later sessions (Fable while it lasts, Opus/Sonnet after) can each pick up one scoped chunk and run it down.

Breadth caution for the planning session: the security stream (workstream 4) is where breadth is risky.
When the plan covers it, frame it as **organizing my own maintenance/quality backlog into beads** — a
maintainer's roadmap — NOT "rank all my repos by attack surface." Workstreams 1–3 have no such caution.

### Session opener — PLANNING (paste into the first fresh Fable session)

> Read `.pi/handoff-fable-days.md` in switch-berlin. These are all repos I authored myself. Help me turn
> this into an ordered roadmap — a bead epic — for making the most of my remaining Fable days: architecture
> reviews, open design forks, the Challenge product thread, and robustness/hardening on the security-relevant
> repos. Don't start concrete work yet; produce the plan and the beads first.

### Session opener — CONCRETE WORK (paste into later sessions, once the plan exists)

> This is my own repo that I authored, working per the roadmap in `.pi/handoff-fable-days.md`.
> [architecture/design] Review <repo>'s design — boundaries, coupling, coherence — and file findings as beads/ADRs.
> [security stream only] Review <repo>'s threat model for robustness weaknesses to fix and file them as beads.
> Start with <specific scope>.

## Repos, in priority order

Per-repo the emphasis differs (hardening vs. architecture vs. design). Criticality noted.

| Repo | Emphasis | Criticality | Notes |
|---|---|---|---|
| **switch-berlin** | hardening + architecture + Challenge spine | HIGH | Live product, real user data as system of record. Biggest stakes. Also holds the Challenge 0 product thread (front-door verbs, enable-for-promotion, the Challenge 0 walk that needs me at my phone). |
| **rip-cage** | defensive posture review | HIGH | Agent sandbox/cage. Review *composed with the guards* (`destructive_command_guard` etc.) — the composition is where the value is. Deep escape-hunting may flag; keep it defensive ("where are the gaps, how do I close them"). |
| **dotpi** + **personal-pi-agent** | hardening + substrate architecture | MED-HIGH | Agent runtime + my personal agent. Substrate: hooks, skills, herdr workflow, the dotpi-3bi epic bead. |
| **~/.claude (dotclaude)** | substrate coherence + hardening | MED-HIGH | Lots of substrate: hooks, skills, herdr integration, dotpi-3bi-related. Coherence review across skills/hooks belongs here. |
| **harness/** | architecture | MED | Verification-harness repo. |
| **homebrew-rip-cage** | hardening | MED | Distribution tap for rip-cage — supply-chain-adjacent, worth a careful look. |
| **meshmonk** | architecture + hardening | MED | (confirm current scope on open) |
| **resume** | light | LOW | Not critical. Quick pass only. |
| **wg-gesucht** (LOCATE FIRST — not under ~/code/personal by obvious name) | light hardening | LOW | Personal tool, not published to a wide audience. Lower stakes. |

## Cross-cutting work (zero flag risk — lead with these when time is short)

These are pure judgment work where Fable's edge is largest and nothing trips the safeguard:

- **Substrate coherence review** — read the whole ADR corpus + bead memories + skill library at once;
  find ADRs that quietly contradict, firmness miscalibration, boundary drift. Output: ADR edits + findings.
  (Best done in one big-context session — that's the Fable-scarce-resource play.)
- **Open design forks** — genuinely unresolved decisions I'm carrying, argued adversarially both ways,
  resolved into ADRs.
- **Challenge spine** — the actual product thread in switch-berlin.

## Durability contract

- Findings → `bd create` (defensive-hardening + architecture beads), triaged by severity.
- Decisions → ADRs in each repo's `docs/decisions/` (switch-berlin has the mature convention).
- Longer reports → a doc referenced from a bead so it's discoverable via `bd`.
- Session close per switch-berlin CLAUDE.md: file follow-ups, run gates, **push** (`git pull --rebase; bd dolt push; git push`).

## Sequencing

1. **Session 1 — planning** (this doc's PLANNING opener): produce the ordered roadmap + bead epic. No repo work yet.
2. **Sessions 2..N — concrete work**, one scoped chunk each. Lead with the zero-flag-risk cross-cutting work
   (substrate coherence, open design forks, switch-berlin architecture + Challenge spine) while Fable lasts —
   that's the highest Fable-only leverage. Slot per-repo hardening reviews in with careful defensive scoping.
3. **Save rip-cage escape-surface work for last** — accept it may run on Opus.
