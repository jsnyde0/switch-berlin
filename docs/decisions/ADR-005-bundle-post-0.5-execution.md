# ADR-005: Post-0.5 execution regrouped into Bundle A (code) + Bundle B (ops) + Bundle C (post-observation design)

**Status:** Accepted 2026-04-21
**Design:** [Bundle A design doc](../plans/2026-04-21-bundle-a-post-0.5-code-sprint-design.md)
**Parent:** [ADR-002 D1 phased rollout](ADR-002-phased-rollout-and-legal-gate.md), [ADR-003 F9 kill-switches](ADR-003-cheap-foresight-patterns.md)
**Supersedes in scope:** phase-0.6, phase-0.7, phase-1.0 as standalone *implementation* plans (kept as reference)

## Context

Phase 0.5 is code-complete (2026-04-21). The original roadmap structure (`0.5 → 0.6 → 0.7 → 1.0`) bundles each phase's **code work** with its **human-gated observation work** (threshold calibration, go/no-go soaks, real-traffic tuning, UX decisions informed by organizer feedback).

For a solo maintainer with variable wall-clock availability, this coupling is the wrong shape:

- Code sprints are bursty and in-flow — the maintainer wants to build all reachable machinery in one run without blocking on "wait two weeks for traffic."
- Observation and tuning are calendar-bound — they happen when invite cohorts grow, when flags accumulate, when organizers react.
- Some 1.0 features (open signup UX, organizer self-edit ergonomics, bubble-bridging) are **decision-loaded** — building them before real-user data locks in assumptions that will turn out wrong.

Continuing the phase-by-phase sequence would either (a) block the code sprint waiting for each phase's human signal, or (b) proceed blindly through 0.6/0.7/1.0 code and risk burning time on UX work that needs real feedback first.

## Decisions

### D1: Regroup post-0.5 work into three bundles by *nature of the work*, not by feature phase

**Firmness: FLEXIBLE** — revisitable if a bundle proves hard to scope.

- **Bundle A — Code sprint** (design doc: `2026-04-21-bundle-a-post-0.5-code-sprint-design.md`). All human-independent implementation: 0.5 leftover (OG tags), 0.6 machinery (trending, `/me`, `ModerationAction`, threshold-config), 0.7 display logic (flag-gated, default OFF), 1.0 infra (rate limiting, panic mode, week-off runbook). Ships as one `/send-it` run.
- **Bundle B — Ops & soak** (tracked via beads; no design doc). All wall-clock work: event entry, legal copy review, `PUBLIC_READ_ENABLED=True` flip, 2-week traffic soak, threshold calibration, go/no-go validation. The maintainer works these whenever they have an hour.
- **Bundle C — Post-observation design** (design doc drafted after Bundle B produces signal). Decision-loaded UX: `SignupApplication` + admin-reviewed open signup, organizer self-edit (`OrganizerEdit`, `OrganizerUserLink`, re-review triggers), bubble-bridging UI, Logfire dashboards, calibrated threshold values.

**Rationale:**

Splitting by work-nature (code / ops / post-observation design) instead of by feature phase (0.6 / 0.7 / 1.0) means:

1. The maintainer never waits on themselves. Bundle A completes regardless of whether the cohort has grown.
2. Features that genuinely need real data (1.0 UX) don't get built blind.
3. Everything Bundle A ships is flag-guarded off by default (per ADR-003 F9) — merging code ≠ shipping the feature. The maintainer flips flags from Bundle B.
4. Bundle C gets designed with real information, not speculation.

The three old phase docs (`phase-0.6`, `phase-0.7`, `phase-1.0`) are retained as **reference material** for Bundle C design, but marked superseded as implementation plans.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Bundles A/B/C (chosen)** | Decouples code cadence from ops cadence; defers UX decisions until real data exists; single `/send-it` on Bundle A | Introduces a new structural concept; three old phase docs to mark superseded |
| Continue 0.6 → 0.7 → 1.0 sequentially | Familiar structure; no doc churn | Code sprint blocks on 2-week soaks; 1.0 UX built blind |
| Collapse 0.6+0.7+1.0 into one "post-0.5" phase doc | Single successor doc | Conflates code with ops + UX in one document; hides what can and can't be done now |
| Build Bundle A code only, leave 0.6/0.7/1.0 docs as-is | Minimal doc changes | Readers see conflicting narratives — "is 0.6 a phase? or part of Bundle A?" |

**What would invalidate this:**

If Bundle A's scope turns out to exceed ~2× Phase 0.4's 6-bead footprint, split Bundle A into A1 (0.6 machinery) and A2 (0.7 display + 1.0 infra). If Bundle C's "wait for real data" rationale proves over-cautious at actual traffic volume, promote specific 1.0 features back into Bundle A on evidence.

---

### D2: Bundle B has no design doc; it lives entirely in beads

**Firmness: FLEXIBLE**

Ops work is already tracked in beads (`kb-lqw`, `kb-vka`, `kb-5ef` for Phase 0.1 ops). Additional Bundle B beads will be filed as needed (`flip PUBLIC_READ_ENABLED`, `review German legal copy`, `calibrate thresholds after 2 weeks`, etc.). A checklist design doc would duplicate the bead tracker without adding design value.

**Rationale:** Design docs exist to capture architectural decisions. Bundle B has no architecture — it's a checklist. Beads are the correct home for checklists because they also track dependencies, assignment, and completion state.

**What would invalidate this:** If Bundle B grows enough dependency structure that beads feel unwieldy (e.g., a 20-step legal review with sub-checklists), write a `docs/runbooks/bundle-b-ops.md` runbook then. Not now.

---

### D3: Old phase docs (0.6, 0.7, 1.0) are retained, banner-marked, not deleted

**Firmness: FIRM** — deletion is lossy; banners are cheap.

Each phase doc gets a one-line top-of-file banner pointing to Bundle A (for implementation) and noting Bundle C will replace the rest. The body stays unchanged — the model definitions, go/no-go criteria, and UI notes remain useful reference for Bundle C design.

**What would invalidate this:** Once Bundle C ships, re-evaluate whether the old phase docs still add reference value or have become fully redundant. Delete at that point if redundant.

## Consequences

**Easier:**
- Single `/send-it` call produces all post-0.5 code. No "wait two weeks" pauses.
- 1.0 UX gets designed with real data.
- Roadmap post-0.5 shrinks from four phase entries to three bundle entries.

**Harder:**
- Readers unfamiliar with the bundling concept may look for "Phase 0.6 plan" and land on a superseded doc. Banners mitigate.
- Bundle C writing is deferred — requires discipline to not pre-design it during Bundle A implementation.

**Tradeoffs:**
- Accepts that Bundle A's scope is ~3× a single phase's typical footprint. Mitigated by the Bundle A design doc's explicit suggested bead structure (9 bead slices) and by the option to split A into A1+A2 if scope hurts.
