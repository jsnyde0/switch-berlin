# ADR-010: Event-based product posture — facilitate real-world action, not platform engagement

**Status:** Accepted 2026-05-20 (D1 Switch-as-canonical-home growth-loop application added 2026-06-01 via syndication-hub IA realignment; post-canonical-anchor cheap-foresight evolution 2026-06-04 — dogfooding feedback, FLEXIBLE-path)
**Parent:** [ADR-001 D1 — curated-trust product framing](ADR-001-core-product-and-stack.md)
**Scope:** product-posture decision binding feature scope, UX patterns, and business model — applies to all design surfaces. Adjacent to ADR-009 D4 (anti-engagement at feed-ranking layer); this ADR binds the product-purpose layer above it.

## Context

The discovery posture from ADR-009 D4 forbids global engagement-optimized ranking at the feed-ranking layer — the FetLife "Kinky & Popular" feedback-loop failure mode. That constraint binds *how feeds rank*, but does not by itself constrain *what features ship*, *what business model is pursued*, or *how UX patterns are chosen*.

The kb-2ve Phase A long-term vision brainstorm (2026-05-20) surfaced the product-posture-layer expression of the same anti-engagement principle: Switch Berlin's purpose is **facilitating real-world action** — people meeting in the real world, attending events, building community offline. Platform engagement (time-on-platform, return-visit-frequency, follow-counts) is not a goal in itself; it can serve the real-world facilitation goal as an instrument, but it must not become the goal.

Without canonicalization at the product-posture layer, future decisions on features (e.g., should we ship streaks? infinite scroll? engagement-monetization?), UX patterns (notification gamification?), and business model (engagement-revenue?) re-litigate the posture from scratch — exactly the drift FetLife's K&P feedback loop emerged from (engagement was "one signal among many" until incremental re-weighting pulled the system toward demographic concentration).

## Decisions

### D1: Real-world action is the goal; engagement is an instrument, not an end

**Firmness: FLEXIBLE** — Pattern mirrors ADR-009 D4's FLEXIBLE-because-unshipped rationale. Decision binds an unshipped product posture (the V0 platform is still pre-launch); substantive observation (e.g., a real-world-impact-aligned feature whose primary success metric is platform engagement demonstrating measurable real-world outcomes) is sufficient warrant to mutate.

Switch Berlin's purpose is to facilitate real-world action — people meeting in the real world at events, building offline community, forming connections that exist beyond the platform. Platform success is measured by real-world outcomes (event attendance, real connections formed, scene-formation, organizer success at filling events), **NOT** by platform engagement metrics as ends in themselves.

**Concretely operationalized:**

- **(a) Engagement metrics as instruments, not goals.** Engagement signals (RSVPs, follows, clicks, dwell time) may legitimately serve product decisions — surface event-listing clarity issues, learn which organizers are useful to highlight, feed bounded ranking per ADR-009 D4. They are evaluated on whether they advance real-world action, not on whether they advance engagement for its own sake.
- **(b) Feature shipping discipline.** Engagement-driving design patterns (streaks, badges-for-time-on-platform, infinite scroll, notification gamification, return-engagement loops) are evaluated against real-world outcome, not against platform engagement metrics. A feature that would increase platform engagement without advancing real-world impact does not ship.
- **(c) Business-model constraint.** Revenue paths that monetize engagement (ads, attention-revenue, premium-engagement-features, engagement-based subscription tiers) are blocked because they structurally misalign platform incentives with user goal. Revenue must come from facilitating real-world events (e.g., ticketing fees on the sister platform per kb-2ve Phase A D1, organizer subscriptions tied to event-facilitation value).
- **(d) Agentic-layer constraint.** Personal agents (kb-2ve Phase A D4) must serve the user's real-world goals; they may not be optimized to keep users on the platform or to drive platform-engagement metrics.

**Boundary with ADR-009 D4:** ADR-009 D4 forbids global engagement-optimized ranking at feed-ranking surfaces; it explicitly permits engagement signals within bounded strata as inputs to discovery relevance. This ADR-010 D1 operates one level up: it binds the *goal* of the platform, not the *means*. Bounded engagement signals (ADR-009 D4) are permitted as instruments serving the real-world-action goal (this D1) — the two constraints compose without tension.

**Switch as canonical home — the growth-loop application (added 2026-06-01 — syndication-hub IA realignment; FLEXIBLE-path edit, announce + proceed per ADR-013 D3).** A direct application of "real-world action is the goal": **Switch own-page is the platform-of-record / canonical home for an event's full content.** Facilitators author the complete event on Switch first; syndication to external platforms (FetLife, Telegram, Instagram, …) is **downstream promotion/reach**, not a co-equal authoring surface. This is load-bearing because it *is* the growth loop — building a syndication tool good enough that facilitators willingly publish *all* their events to Switch as the canonical home is what creates the event inventory, and that inventory is the user-acquisition magnet (events bring the audience that the platform's curated-trust value, ADR-001 D1, then serves). **UI consequence** (realized in the syndication composer, ADR-016 D2): an Event's canonical content-version is anchored/presented as the **Switch channel tab** (the master); other channels sync-or-diverge from it. A *Post* currently has no native-home channel **because Switch does not yet offer post/promotion publishing** (Switch hosts events, not posts), so a post's canonical is presented as an abstract **"Master copy"** anchor rather than a channel. This asymmetry is **temporary, not intrinsic** (revised 2026-06-04, dogfooding feedback): when Switch posting ships, a post's canonical home becomes the **Switch channel** symmetrically with events, and the abstract Master-copy anchor is replaced by a real Switch post projection. Per **cheap foresight ([ADR-003](ADR-003-cheap-foresight-patterns.md))** the composer's post anchor is shaped now as a named canonical-anchor *slot* — structurally the same slot an event's Switch-listing projection fills — so that convergence is a cheap flip, not a re-architecture. We do **not** build Switch post-publishing now (ADR-008 D2 — no speculative behavioral abstraction); only the data/naming shape is made forward-compatible. Until posting ships, **no Switch *promotion* projection is minted for posts** — a Switch connection is listing-only at the projection-minting gate, capability-aware and fail-loud per ADR-008 D3 — so no spurious "Switch" promo tab appears beside the post Master copy. *What would invalidate:* facilitators treat Switch as just-another-channel rather than home — e.g. they author events elsewhere and cross-post *to* Switch with equal weight, or the canonical-home framing produces no measurable lift in events-published-to-Switch. Then Switch is a peer destination and the canonical anchor should not privilege it.

**Counter-argument (FLEXIBLE-path acknowledgment):** The alternative — leaving this as orchestrator judgment + ADR-009 D4 coverage — rests on the premise that the feed-ranking-layer constraint is sufficient. Counter: ADR-009 D4 is scoped to ranking surfaces; future decisions on feature shipping, UX patterns, and business-model paths currently have NO load-bearing decision to point at. Without canonicalization at the product-posture layer, every future decision re-litigates the posture, and incremental drift toward engagement-as-goal is structurally possible (the same drift shape that produced FetLife K&P). FLEXIBLE rather than FIRM acknowledges that substantive real-world observation is sufficient warrant to evolve, but a hypothetical "users want engagement features" without observed real-world-impact warrant is not sufficient.

**Rationale:**

- `external:` kb-2ve Phase A brainstorm (user-explicit, 2026-05-20) — "facilitating people to actually do things in the real world, get people together, rather than keep them on the platform." Positioning angle differentiates from FetLife (engagement-monetized) and aligns with the curated-trust framing in ADR-001 D1.
- `external:` ADR-009 D4 rationale chain — FetLife critique digest (K&P feedback loop) demonstrates that engagement-optimization at any layer pulls toward demographic concentration. Product-posture-layer constraint prevents the same drift via feature-shipping discipline rather than only ranking-algorithm discipline.
- `reasoned:` Business-model alignment between platform and user goal: if revenue comes from engagement, platform incentives diverge from the user's real-world goal. If revenue comes from facilitating real-world events, incentives align. The structural choice is at the business-model layer.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Leave to ADR-009 D4 + orchestrator judgment (no product-posture-layer canonicalization) | `reasoned:` ADR-009 D4 scope is feed-ranking only; future feature/UX/business-model decisions have no load-bearing ADR to point at. Risk of incremental drift toward engagement-as-goal (K&P-shape failure mode at the product-posture layer). |
| FIRM rather than FLEXIBLE | `reasoned:` FIRM forecloses legitimate evolution if a real-world-impact-aligned use of engagement-as-primary-signal emerges. FLEXIBLE preserves canonicality while allowing substantive-observation-driven mutation. Pattern matches ADR-009 D4's same-shape calibration (also FLEXIBLE, also pre-shipping). |
| Anti-engagement absolute (no engagement signals as inputs anywhere) | `reasoned:` engagement signals are useful as instruments (ADR-009 D4 already permits bounded-strata engagement within feeds). Forbidding engagement signals entirely throws out useful information for no real-world-impact gain. |
| Engagement-permitted, real-world-action-also-considered (both as goals) | `reasoned:` two goals at the product-purpose layer create incentive ambiguity at every feature decision. The K&P-shape drift emerges precisely from "both" framings — engagement starts as one of two goals and becomes the practical-default-goal through measurement-affordance asymmetry (engagement is easier to measure than real-world impact). |

**What would invalidate this:**

- A real-world feature ships where engagement-as-primary-success-metric demonstrates measurable real-world impact (e.g., a notification pattern materially increases event attendance with no observed real-world-quality degradation across multiple cohorts). Substantive observation per FLEXIBLE-path; revisit posture against the observed warrant.
- The "real-world action" framing proves too narrow for legitimate platform value (e.g., users derive substantial real-world-aligned value from on-platform interaction that isn't immediately attendance-shaped). Reformulate posture to capture the broader real-world-aligned scope.
- ADR-009 D4 evolves in a way that subsumes or contradicts this ADR's binding. Reconcile in place.

## Consequences

### Direct

- All future bead `--design` for features touching engagement signals must cite this ADR in `## canonical_refs` and explicitly justify how the feature advances real-world action.
- Business-model decisions cannot route through engagement-monetization paths without an in-place ADR-010 evolution.
- kb-2ve Phase A D3 (deep social-network) and D4 (personal-agent layer) inherit this constraint: features in those layers are evaluated against real-world-action advancement.
- Adjacent to but does not modify ADR-009 D4 — D4 binds feed-ranking layer; this D1 binds product-purpose at the meta-level.

### Carried forward

- ADR-001 D1 (curated-trust framing) — connection between curated-trust posture and event-facilitation goal is unchanged; this ADR makes the goal-orientation explicit.
- ADR-009 D4 (anti-engagement ranking) — extended from feed-ranking layer to product-purpose layer; no contradiction.
- ADR-008 D2 (no speculative abstraction) — this ADR does not pre-build any abstraction; it constrains future decisions without adding code surface.

### Risk

- Honest application requires platform team to evaluate every feature against "does this advance real-world action" — risk of theatrical compliance (calling everything "real-world aligned"). Mitigation: real-world-outcome metrics (event attendance, organizer feedback on attendee quality, retention measured by real-world-events-attended rather than platform-visits) become first-class success criteria.
- Tension with sister-platform shape (kb-2ve Phase A D1) — sister platform's third-party organizers (yoga, tantra, wellness) may have engagement-mode business pressures; the sister-platform brand operates at arm's length but the same posture binds Switch Berlin's relationship to it. Cross-reference at sister-platform design time.

## canonical_refs

- [ADR-001 D1](ADR-001-core-product-and-stack.md) — curated-trust product framing; this ADR makes the event-facilitation goal-orientation explicit on top of D1's audience and trust shape.
- [ADR-009 D4](ADR-009-mutual-connection-graph-and-identity-visibility.md) — anti-engagement ranking posture at feed-ranking layer; this ADR-010 extends the same principle to product-purpose layer (feature scope, UX, business model). The two compose: D4 binds means at the ranking layer; ADR-010 binds the goal at the product-posture layer.
- [ADR-008 D1](ADR-008-code-posture-refactor-hard-fail-loud.md) — per-decision predicates; this ADR carries firmness + rationale + alternatives + invalidation.
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction; this ADR constrains future decisions without pre-building abstraction.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight; the post canonical-anchor "Master copy" slot is shaped now (data/naming only) so Switch can become the post canonical home via a cheap flip once Switch posting ships, without speculative behavioral build (tension with ADR-008 D2 resolved per ADR-003's data-shape-vs-behavior split).
- [ADR-016 D2](ADR-016-outbound-syndication-architecture-event-post-projections.md) — per-platform projections + sync-from-channel; the UI consequence of D1's canonical-home decision is realized in the composer's anchor presentation.
- `kb-2ve` (Long-term platform vision brainstorm) — Phase A D3 (deep social) and D4 (personal-agent layer) inherit this constraint; positioning angle (event-based, not engagement-based) originated here.
- `kb-4pj` (Land discovery posture) — closed; canonicalized as ADR-009 D4. This ADR-010 is the product-purpose-layer companion.

## Open questions deferred

| Question | Resolution path |
|---|---|
| Real-world-outcome success metrics — which observable signals constitute "real-world action advancement"? | Defer until first feature requires the discrimination. Likely candidates: event attendance growth, organizer-reported attendee-quality signals, retention measured by real-world-events-attended rather than platform-visits. |
| Sister-platform brand posture inheritance — does ADR-010 D1 bind sister-platform's UX/feature decisions, or only Switch Berlin's? | Defer; sister-platform shape is FLEXIBLE per kb-2ve Phase A D1. Cross-reference at sister-platform design time. |
