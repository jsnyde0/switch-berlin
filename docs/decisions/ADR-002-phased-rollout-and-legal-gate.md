# ADR-002: Phased rollout, legal gate, and deferred decisions

**Status:** Accepted
**Date:** 2026-04-17
**Design:** [Roadmap 0.1 → 1.0](../plans/2026-04-17-roadmap-0.1-to-1.0.md)
**Parent:** [ADR-001](ADR-001-core-product-and-stack.md)
**Related:** [ADR-003](ADR-003-cheap-foresight-patterns.md)

## Context

ADR-001 fixed the product shape and technical stack. The companion design doc (`2026-04-17-v0-design.md`) describes the full scope of what was originally called "V0" — but on closer reading, that scope is a 1.0 soft-launch, not a first milestone. Shipping it blind in one push is how solo side projects die.

Four parallel brainstorms (risk-first, user-value-first, solo-ops, legal-gate) converged on the need for a phased 0.1 → 1.0 roadmap and diverged on three questions:

1. When does the German legal compliance checklist (JuSchG, DSA, GDPR) ship?
2. Should the React island be committed to, deferred, or cut?
3. When does the first outside human touch the product?

This ADR records the load-bearing decisions from that synthesis.

## Decisions

### D1: Phased 0.1 → 1.0 rollout replaces a single "V0" launch

**Firmness: FIRM**

The path to 1.0 is broken into seven releasable milestones (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0). Each milestone is usable end-to-end by a specific audience, kills a specific risk, and fits in ≤2–4 weekends of solo-maintainer time. The full ladder lives in the roadmap doc.

**Rationale:**

Three mutually-reinforcing failure modes otherwise dominate: (1) schema gets baked before a second human's events exist to test it; (2) legal, UX, and social signals all land in one release with no time to observe any of them in isolation; (3) the 15 min/day admin budget gets blown because extraction, review UX, and moderation hit simultaneously. A phased ladder lets each of these be proven before the next lands on top.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Phased 0.1 → 1.0 ladder (chosen)** | Each phase is demoable + learnable; risk isolated; fits weekend budget | More up-front roadmap design |
| Single big-bang 1.0 | Simpler mental model; one release | Everything lands simultaneously; no signal on what actually works |
| Continuous deployment without version gates | Maximum iteration speed | No clear "closed beta" vs. "public" line → legal trap |

**What would invalidate this:**

If the first 2–3 phases complete faster than projected (e.g., phases 0.1 and 0.2 together in <4 weeks), collapse later phases. The ladder is a ceiling on scope per release, not a floor.

---

### D2: Legal gate at 0.5, closed-beta positioning before

**Firmness: FIRM**

The German legal compliance checklist (JuSchG age gate, DSA takedown, GDPR consent + opt-out, Terms/Privacy/Imprint, bot consent text, cookie policy, takedown inbox) ships as a single sprint between 0.4 and 0.5. Before 0.5, the product is a closed, login-walled beta — not a public offering under DSA/JuSchG. Phases 0.3 and 0.4 have a hard login-wall, `robots.txt` disallow-all, no OG tags, no anonymous read path.

Review of the compliance checklist is by AI agents, not a lawyer. Risk is accepted explicitly and documented here: willing to take down on complaint, willing to accept that a hobby-scale closed beta under ~100 users is unlikely to attract regulator attention.

**Rationale:**

An invite-gated, login-walled service is treated differently from a public offering by the regulatory regimes in question. DSA obligations scale with "active recipients of the service" and public accessibility. JuSchG age-gate obligations target publicly-reachable content depicting adult themes. Both regimes have precedent treating closed testing differently from a launched product. Holding the gate at 0.5 buys three phases of real product learning (schema shakedown, organizer cold-start, map privacy model, HTMX-vs-island decision) without paying the legal tax up front.

The alternative — shipping compliance at 0.3 as soon as any reachable URL exists — means debating JuSchG wording before the schema is settled. That's expensive and premature.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Legal gate at 0.5, closed beta before (chosen)** | Fast pre-gate iteration; compliance is one focused sprint | Requires discipline — one public-reachable URL breaks the posture |
| Legal gate at 0.3 (ship compliance with first internal release) | Never any ambiguity about exposure | 3 phases of legal tax on work that's still being figured out |
| No gate — always-public from 0.1 | No ambiguity | Schema churn happens in public; extraction bugs are visible; DSA risk from day 1 |
| Legal gate at 1.0 (stay invite-only forever) | Lowest legal risk | Never reaches the product's target audience |

**What would invalidate this:**

- A regulator complaint or takedown notice during 0.3/0.4 (unlikely at N<50 users behind login-wall, but if it happens, move the gate earlier).
- A growth path where the invite list expands past ~100 users — at that point the "closed beta" framing weakens and the gate should be pulled forward.
- Any feature that accidentally creates a public read path (share-links with OG, public RSS, embed widgets) — see [ADR-002 D4](#d4-trap-features-never-ship-unflagged).

---

### D3: React island decision deferred to end of 0.3

**Firmness: FLEXIBLE** — **Resolved 2026-04-20 by [ADR-004](ADR-004-htmx-vs-island-default-plus-tripwire.md)**: HTMX + Alpine + vanilla MapLibre is the default for `/events`; the React island remains as a tripwire-gated escape hatch with `django-vite` scaffolding preserved.

Whether `/events` ships as a React + django-vite island or as HTMX-only is decided at the end of phase 0.3, not committed upfront. At 0.3 the product *must* have server-rendered event detail, organizer profile, and legal pages (HTMX is non-negotiable for those). So `/events` gets built HTMX-first at 0.3. If filter + list + state-sync feels fine, the island is cut entirely and ADR-001 D5 is revisited. If real seams emerge (cross-panel selection, filter URL state painful, map ↔ sidebar two-way interaction), the island ships at 0.4.

Regardless of outcome, `django-vite` and the Vite scaffold stay in the stack as dormant code — wiring an island later is cheap; deleting the capability is wasteful.

**Rationale:**

ADR-001 D5 is firm on *using* React specifically for the `/events` surface, but the decision to ship an island at all is checkable cheaply once the HTMX surface exists. Deferring lets evidence replace speculation. The two-mental-models tax (HTMX + Django most places, React on one page) is real; if HTMX can carry the whole surface, carrying one mental model is strictly better for a solo maintainer.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Defer to end of 0.3, decide on evidence (chosen)** | Cheapest-evidence decision; keeps options open | One phase with a pending decision |
| Commit to React island at 0.4 unconditionally (ADR-001 D5 as-is) | Simpler planning | Pays complexity tax even if HTMX suffices |
| Cut React island permanently, HTMX-only | Single mental model; simplest solo-maintainer stack | Bets against the D5 rationale before evidence exists |

**What would invalidate this:**

If HTMX surface at 0.3 is obviously broken on filter state management before the phase ends, the decision resolves early to "ship the island at 0.4." If the HTMX surface works but is ugly, the decision resolves "ship HTMX, revisit post-1.0."

---

### D4: Trap features — never ship unflagged

**Firmness: FIRM**

Certain features silently upgrade the product's regulatory class or operational burden. These are **banned in the pre-1.0 roadmap** regardless of user demand:

- **User-to-user DMs or group chat** — creates Number-Independent Interpersonal Communications Service status under TKG/EECC, inherits NetzDG-adjacent obligations. Never in pre-1.0 scope; defer to 2.0 with explicit re-evaluation.
- **Public share-links with OG preview before the legal gate** — an unauthenticated URL with OG tags is a public offering under DSA even if the rest of the site is login-walled.
- **Third-party embedded maps (Google Maps, etc.)** — GDPR international-transfer issue. MapLibre + OSM (self-hostable tiles) only.
- **Email notifications ("notify me when...") before legal gate** — requires documented lawful basis and unsubscribe flow. Ship at 0.5+, not before.
- **Event-level reviews displayed** before 0.7 — collect from 0.5, display at 0.7 once per-event attendance density supports ≥3 threshold.

**Rationale:**

Each of these looks like a small feature but either changes the regulatory class of the service or creates an unbounded moderation/support surface. A solo maintainer has no slack to absorb either. Listing them here prevents "just one quick addition" from cascading.

**What would invalidate this:**

Nothing pre-1.0. Re-evaluate any of these at the 1.0 retrospective with documented risk assessment.

---

### D5: First outside human at 0.3 — one organizer-peer

**Firmness: FIRM**

The first non-maintainer human touches the product at phase 0.3 as an organizer-peer (not a beta tester). Selection criteria: someone honest but chill, whose events the maintainer would personally attend, not a perfectionist or ghoster. They receive a link to their own `/o/<slug>` profile and send corrections.

**Rationale:**

Cheapest-possible-signal, highest-leverage feedback. They'll tell you whether the schema represents their real events (recurring series, co-hosts, weird formats) before schema is set in stone. Post-0.3 schema changes are expensive. They're also the social wedge for 0.4: if one organizer won't engage as a peer, 5 insiders won't either — and learning that at 0.3 is 10× cheaper than at 0.5.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **1 organizer-peer at 0.3 (chosen)** | Cheapest signal; schema feedback before it's set; social wedge test | Depends on finding the right person |
| 5 insiders at 0.4, no outside human before | Matches typical "closed beta" size | Misses the schema-review window; higher-risk social wedge test |
| Full invite list at 0.5 (first outsiders after legal gate) | Simplest plan | Schema already committed; no signal on organizer willingness until too late |

**What would invalidate this:**

If the chosen organizer-peer ghosts or refuses to engage, try one more. If two fail, the organizer-cold-start thesis in ADR-001 D1 is in trouble, and the roadmap should pause at 0.3.

## Consequences

**Easier:**
- Each phase has a clear success criterion; scope creep is visible immediately.
- Pre-gate phases move fast without legal ceremony.
- Decisions gated by evidence (React island) don't consume planning energy.
- Trap features are pre-declared; no "just one quick addition" cascades.

**Harder:**
- Discipline required to hold the login-wall through 0.4 — one public-reachable URL breaks the closed-beta posture.
- The "done at end of 0.3" React-island decision needs explicit resolution, not drift.
- Per-phase design docs add minor documentation overhead (paid for by avoiding re-litigation).

**Tradeoffs:**
- Agent-reviewed legal compliance trades money (€500–1500 saved) for accepted regulator risk. Documented; re-evaluate if audience size crosses ~100.
- Event-reviews-collected-but-hidden (0.5–0.6) is slightly weird UX — "you left a review, it's stored but not displayed yet." Mitigation: phase 0.7 is short; or surface reviews to their author only.
