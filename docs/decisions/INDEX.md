# Anchored Decision Records — Index

Navigation surface for `docs/decisions/`. Each ADR captures a cross-cutting, load-bearing decision with per-decision firmness (FIRM / FLEXIBLE / EXPLORATORY) and links upstream context via `## canonical_refs`. ADRs evolve in place (no supersession chains) per the global ADR-011 D1 discipline (`~/.claude/docs/decisions/ADR-011-adrs-reflect-target-architecture.md`).

## ADRs

| ADR | Title | Scope | Status | One-line description |
|---|---|---|---|---|
| [ADR-001](ADR-001-core-product-and-stack.md) | Core product shape and technical stack | product | Accepted (pending soft-launch) | Curated queer/conscious kink events in Berlin; two-tier trust; Django monolith + one React island. |
| [ADR-002](ADR-002-phased-rollout-and-legal-gate.md) | Phased rollout, legal gate, and deferred decisions | rollout | Accepted | Seven-phase 0.1→1.0 ladder with legal gate at 0.5; closed-beta before public flip. |
| [ADR-003](ADR-003-cheap-foresight-patterns.md) | Cheap foresight patterns | schema | Accepted | Shape model fields/naming now for zero cost; defer behavioral abstraction until observed need. |
| [ADR-004](ADR-004-htmx-vs-island-default-plus-tripwire.md) | HTMX+Alpine as default for `/events` map surface, React island as tripwire escape hatch | frontend | Accepted — spike graduated 2026-04-20 | HTMX + Alpine + vanilla MapLibre default; React island preserved dormant with objective tripwires. |
| [ADR-005](ADR-005-bundle-post-0.5-execution.md) | Post-0.5 execution regrouped into Bundle A (code) + Bundle B (ops) + Bundle C (post-observation design) | execution | Accepted 2026-04-21 | Decouple code sprints (A) from ops (B) from decision-loaded UX (C); three bundles by work nature. |
| [ADR-006](ADR-006-legal-gate-execution.md) | Legal gate execution — parameterize now, fill operator identity at deploy | legal | Accepted 2026-04-22 | Attendance uses Art. 9 consent; organizers under Art. 6(1)(f) legitimate interest; operator identity via env vars. |
| [ADR-007](ADR-007-profile-centric-schema.md) | Profile-centric schema — unify Organizer/Facilitator, defer Festival | schema | Accepted 2026-05-11 (D5 revised 2026-05-21) | Unified `Profile` model with `kind` discriminator; separate `EventOrganizer` and `EventFacilitator` through-tables. D5 evolved in place: single-FK `claimed_by` → multi-claimant `ProfileClaim` through-model. |
| [ADR-008](ADR-008-code-posture-refactor-hard-fail-loud.md) | Code posture — refactor hard, fail loud | code-posture | Accepted (D3 clarified 2026-05-22) | No backward compatibility pre-V1; no speculative abstraction; fail loud on data integrity (read AND write/migration time); retry transport errors. |
| [ADR-009](ADR-009-mutual-connection-graph-and-identity-visibility.md) | Mutual Connection graph, identity visibility, and anti-engagement ranking posture | social-graph | Accepted 2026-05-19 (revised 2026-05-20) | `Connection` mutual graph orthogonal to Follow/Vouch; 4-tier visibility (`public>vouched>friends>private`); no global engagement ranking. |
| [ADR-010](ADR-010-event-based-product-posture.md) | Event-based product posture — facilitate real-world action, not platform engagement | product | Accepted 2026-05-20 | Real-world action is the goal; engagement is an instrument, not an end; business model cannot monetize engagement. |
| [ADR-011](ADR-011-personal-agent-layer-additive.md) | Personal-agent layer — core platform scope web-UI-complete, extended scope agent-natural | arch | Accepted 2026-05-20 | Core platform features (mission scope) web-UI-complete; agent-extended scope may be agent-only; web-UI parity preferred but not required in extended scope. |
| [ADR-012](ADR-012-event-visibility-tiers.md) | Event visibility tiers and access-control matrix | social-graph | Accepted 2026-05-21 (revised 2026-05-22 — D4 added) | `Event.visibility ∈ {public, semi_public, unlisted}` with source-derived `max(public)` defaults; viewer-tier × Event-tier access matrix configurable via `settings.EVENT_VISIBILITY_TRUSTED_STATUSES`; robot indexing derived from tier; D4 binds future migrations to de-facto-prior visibility as floor. |
| [ADR-013](ADR-013-user-trust-model.md) | User trust model: tiered authentication, vouching graph, invite economy | social-graph | Accepted 2026-05-21 | `User.status ∈ {open, vouched, suspended_pending_investigation, banned}`; two signup paths (open + vouched-with-invite); `Vouch` graph with proportional consequences and one-hop cascade; V0 admin-grant invite economy with schema-ready earning formula. EXPLORATORY pending dogfooding. |
| [ADR-014](ADR-014-profile-claim-flow.md) | Profile claim flow: multi-claimant through-model, two-track verification, magic-link envelope | schema | Accepted 2026-05-21 | Replaces ADR-007 D5 single-FK with `ProfileClaim(profile, user, verified_at, verified_method, verified_by_admin, role)` through-model; web-first entry on public Profile page; two-track verification (email-domain fast-path + admin-review fallback); 1-day single-use scoped magic-link. EXPLORATORY pending dogfooding. |
| [ADR-015](ADR-015-payment-processor-strategy-for-explicit-event-ticketing.md) | Payment-processor strategy for explicit-event ticketing | payment-infra | Accepted 2026-05-21 | V0/V1 tactical: organizer-direct Stripe in Mode A coordination-layer + cutover-readiness (kb-y6w/kb-6y6/kb-d9s/kb-bw0/kb-94h). Long-term sister-platform: pending via kb-hm0. Both legs FLEXIBLE. |
| [ADR-016](ADR-016-outbound-syndication-architecture-event-post-projections.md) | Outbound syndication architecture — canonical Event + Post, per-platform projections, agent + UI co-equal API clients | arch | Accepted 2026-05-25 (revised 2026-05-26) | Canonical Event and Post are separate entities (Event = structured facts, Post = communication artifact, one Event many Posts). Per-platform projections of kind ∈ {listing, promotion} carry editable copies (live-canonical + override_data + provenance) + content-policy filtering (kb-o0j). D4: projections target a `PlatformConnection` destination (not a platform string), eager-fanned per enabled connection × supported kind. D5: explicit, actor-attested publish lifecycle (`mark-published` is a co-equal API verb; draft=WIP, draft→ready=completeness gate). Web UI and external agents are co-equal HTTP API clients (Moltbook-pattern Bearer + identity-token). D6: API framework = Django Ninja (in-process, shared service layer with HTMX views; django-bolt rejected — its separate Rust server breaks the co-equal-handler constraint). BYO-agent at v0; bundled-agent deferred. All decisions FLEXIBLE. |

| [ADR-017](ADR-017-authorization-edit-publish-policy.md) | Authorization policy — who may edit/publish an Event/Post/Projection | authz | Accepted 2026-05-26 | Edit/publish authority = claimant of an `EventOrganizer` Profile (+ their paired agent); `EventFacilitator`s credited-only; rights derive from which through-table you're in, no new field. All authz routes through a single `can_edit` predicate (chokepoint, cheap foresight vs scattered checks). `ProfileClaim` is the team-membership seam — future roles/team-mgmt widen `ProfileClaim.role` + grant/revoke claims, no new model. All FLEXIBLE; authz distinct from ADR-016 D3 authn. |

## Scope tags

Single-keyword filter for "which ADRs might constrain this work?". Not exhaustive — propose new tags rather than over-fit existing ones.

- **product** — what we're building and for whom (positioning, audience, top-level shape)
- **rollout** — phasing, gates, sequencing of public exposure
- **arch** — system-level architecture (layer boundaries, surface contracts, agent-vs-SaaS placement)
- **frontend** — UI rendering strategy, framework choices, escape hatches
- **execution** — how work is organized into bundles / sprints / dependencies
- **legal** — GDPR posture, consent bases, operator identity, takedown
- **schema** — data model shape, field naming, deferred-abstraction posture
- **code-posture** — refactor / error-handling / abstraction discipline
- **social-graph** — Connection / Follow / Vouch / visibility / ranking posture
- **payment-infra** — payment-processor selection, merchant-of-record posture, content-policy risk routing
- **authz** — authorization policy: who may edit/publish/act on a resource (distinct from authentication and from read-side visibility)

## When to consult

Survey ADRs in scope at these junctures (per global `~/.claude/CLAUDE.md` → Substrate orientation):

- **Authoring a new bead `--design`** — populate `## canonical_refs` from in-scope ADRs; never silently contradict a FIRM decision.
- **Authoring or evolving an ADR** — run the 5-dim overlap check (ADR-008 D7) against existing entries before creating a new file; prefer in-place edit per ADR-011 D1.
- **Scoping work that touches a design surface** — e.g. social-graph features pull in ADR-009; data-model changes pull in ADR-003 + ADR-007; frontend rendering pulls in ADR-004.
- **Mid-implementation when a load-bearing decision surfaces** — pause and scout before encoding the choice into code.
- **Post-compaction or session resume on substantive work** — re-survey before sinking into context-laden execution.

The `/scout-adrs` skill operationalizes this lookup — invoke when scope is unclear or context is stale.

## Bead linkage convention

Beads that depend on an ADR's decision cite it in `--design ## canonical_refs` (preferred) or `--notes` as `ADRs: ADR-NNN, ADR-MMM`. Reverse linkage (ADR → bead) lives in the ADR's own `## canonical_refs` when a bead motivated or grounded the decision.
