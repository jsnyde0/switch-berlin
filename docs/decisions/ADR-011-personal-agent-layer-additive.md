# ADR-011: Personal-agent layer — core platform scope web-UI-complete, extended scope agent-natural

**Status:** Accepted 2026-05-20
**Parent:** [ADR-010 D1 — event-based product posture](ADR-010-event-based-product-posture.md)
**Scope:** architectural binding on the personal-agent layer (per kb-2ve Phase A D4) — separates "core platform scope" (web-UI-complete) from "agent-extended scope" (may be agent-only). Adjacent to ADR-008 D2 (no speculative abstraction at code-pattern layer) and ADR-010 D1 (agent layer must serve real-world goals).

## Context

The kb-2ve Phase A long-term vision brainstorm (2026-05-20) surfaced a **personal-agent layer** as a load-bearing architectural component: each profile (facilitator + attendee) has access to a preconfigured personal Switch agent inspired by pi.dev / nanoclaw / nanobot-style runtimes. The agent layer is positioned to handle:

- Per-target event syndication with content cleaning (kb-2ve Phase A D2 cleaning layer lives here)
- Promo-post drafting and cross-platform publishing (Telegram, IG, FB, FetLife)
- Personalization via access to the user's own content (websites, markdown files, prior posts, voice/tone preferences)
- Agent self-modification and learning of personal preferences
- Glue between Switch Berlin and external platforms

This raises an architectural question: **does the agent layer become required for any core platform feature, or does the platform always work without it?**

A strict formulation — "everything the agent does must also exist in the web UI" — was considered and rejected as too restrictive: some agent-natural features (per-user content derivation, learning from external user files, agent self-modification) are inherently hard to express in a SaaS web UI and would either go unbuilt or be built poorly. The looser formulation that survived is the one this ADR canonicalizes: **the core platform scope is web-UI-complete; agent-extended scope can exceed it**.

Without canonicalization, future decisions on the agent layer drift between two failure modes: (a) building a SaaS surface for every agent capability and producing a bloated platform whose features don't fit web-UI affordances; (b) letting agent-only features creep into the core platform scope and producing a web-UI that's incomplete for users who don't run an agent.

## Decisions

### D1: Core platform scope is web-UI-complete; agent-extended scope may be agent-only

**Firmness: FLEXIBLE** — Pattern mirrors ADR-009 D4 and ADR-010 D1's FLEXIBLE-because-unshipped rationale. Decision binds an unshipped surface (the personal-agent layer doesn't exist yet); substantive observation (e.g., a core platform feature proves genuinely unservable at acceptable quality via web UI alone, or the core/extended boundary collapses under real usage patterns) is sufficient warrant to mutate.

Switch Berlin's **core platform scope** — the V0/V1 mission features through which a user receives the platform's core value proposition — works completely via web UI. No agent is required for any core platform feature. The **personal-agent layer extends beyond core platform scope** with capabilities that are naturally agent-shaped, and within that extended scope, web-UI parity is preferred where reasonable but not required.

**Core platform scope (web-UI-complete):**

- Event browsing, filtering, map view (ADR-001 D5)
- RSVPing and attendance signals (ADR-006 D1)
- Identity / profile management including 4-tier visibility configuration (ADR-009 D2)
- Vouching (kb-m69 D6)
- Connection requests and acceptance (ADR-009 D1)
- Organizer authoring of events with consent context, tier visibility, EventRequirement (ADR-007 D1+D2; kb-fx9 D13)
- Web feeds per ADR-009 D4 (Following / For-You / Discover)
- Updates / shoutbox-style organizer-to-attendee content (kb-fx9 D9)

A user who never touches an agent can do all of the above and receive the full curated-trust event-discovery value proposition (ADR-001 D1).

**Agent-extended scope (may be agent-only):**

- Per-target event syndication with content cleaning (kb-2ve Phase A D2 — sister-platform / Hipsy-bridge / FetLife / Diversia / organizer's own site)
- Promo-post drafting across Telegram / IG / FB / FetLife with per-platform tone and per-user voice
- Personalized variant generation drawing on the user's external content (websites, markdown files, voice/tone history)
- Agent self-modification — learning personal preferences over time and tailoring future suggestions
- Cross-platform glue (publishing to external platforms via the user's own credentials and skills)
- Composable agent skills/tools that integrate with the user's own stack

These capabilities may be agent-only because they are inherently personalization-heavy, self-modifying, or dependent on the user's content outside the platform — all of which are agent-natural and SaaS-painful.

**Drawing the core/extended line:** the test is *value-proposition receipt*. If a user cannot receive Switch Berlin's curated-trust event-discovery value (browse, RSVP, identity, trust) without a feature, that feature is core and must be web-UI-complete. If a feature extends beyond value-proposition receipt — augmenting the user's experience but not gating it — that feature can live in agent-extended scope.

**Concretely operationalized:**

- **(a) Web-UI completeness for core.** Every core platform feature ships with a web UI affordance. Web UI is the canonical authoring surface for high-stakes structured fields (consent context, tier visibility, EventRequirement) regardless of whether an agent affordance also exists.
- **(b) Agent-only allowed for extended.** Features in agent-extended scope may ship agent-only without a web-UI mirror. The MCP surface (kb-2ve Phase A D4) can expose operations that have no web-UI counterpart when those operations are agent-extended-scope.
- **(c) Web-UI parity preferred where reasonable in extended scope.** If an agent-extended capability has a clean web-UI shape (e.g., a "schedule cross-channel post" UI for users who don't run agents), build it. The preference is not a requirement.
- **(d) Drift discipline.** Periodic check that no feature has migrated from agent-extended-scope into core platform scope without acquiring a web-UI affordance. If a feature becomes load-bearing for value-proposition receipt, it has crossed into core scope and needs web-UI.

**Counter-argument acknowledgment (FLEXIBLE-path):** The alternative — strict "everything in agent must also be in web UI" — rests on the premise that user-platform-equity is paramount and agent dependence is a regression. Counter: the strict formulation forecloses real value that is structurally agent-natural (per-user content derivation, learning, self-modification, integration with the user's own files and tools). Forbidding agent-only features in extended scope would either suppress those features or force them into a SaaS form that's bloated and poorly-fit. The loose formulation preserves user-platform-equity for the *value proposition* (web-UI users get full mission delivery) while allowing genuine agent-natural extensions without compromising the SaaS surface.

**The opposite alternative** — let agent-only features creep into core scope — was also rejected: a user who doesn't run an agent must still be able to use Switch Berlin's curated-trust event-discovery completely. Core/extended boundary is the discipline that prevents creeping agent-dependence.

**Rationale:**

- `external:` kb-2ve Phase A brainstorm (user-explicit, 2026-05-20) — "the platform should still work without this agent. Just that an agent can be incredibly useful interface that easily glues to different parts and even glues between our platform and others." Also: "some features are really tough to pull off on the platform itself without people using a Switch personal agent. For example deriving different version to post on different places ... that might be WAY easier with a personal agent that then also has access to their other content like their website, personal markdown files etc etc so they can tweak their agent to know their personal preferences etc."
- `reasoned:` Agent-natural features (personalization via external content, self-modification, learning, cross-platform glue) are structurally hard in SaaS form because they require per-user customization that doesn't fit standardized UI surfaces. Forcing web-UI parity for these would either prevent them or produce bloat. Allowing them agent-only preserves them as genuine extensions.
- `reasoned:` Core scope as web-UI-complete preserves value-proposition equity for users who don't run an agent. The platform's curated-trust event-discovery value proposition (ADR-001 D1) is fully receivable without agentic infrastructure.
- `external:` ADR-008 D2 (no speculative abstraction) — by leaving agent-extended scope outside the core SaaS surface, we avoid building speculative SaaS abstractions for personalization use-cases that may not materialize. The agent layer itself is also constrained by D2 — Phase B reduction must NOT pre-build the MCP surface ahead of validated agent use-cases (kb-2ve Phase A D4 rationale).

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Strict: everything in agent must also be in web UI (the original Q4 formulation) | `external:` user explicit (2026-05-20) — too restrictive. Forecloses agent-natural features (personalization via external content, learning, self-modification) that are genuinely hard to express as SaaS surfaces. |
| Loose: no constraint on agent vs web-UI — feature placement is per-decision judgment | `reasoned:` invites creeping agent-dependence; users who don't run an agent gradually find core platform features unreachable. The discipline of "core platform scope is web-UI-complete" is what prevents the creep. |
| Web UI parity required for everything except a fixed list of agent-only features | `reasoned:` premature concretization (ADR-008 D2). The set of agent-natural features evolves with what agents can do; fixing the list now produces drift or rigidity. The principle (core scope web-UI-complete; extended scope agent-natural) is more durable than a list. |
| Defer the decision until agent layer ships | `reasoned:` kb-2ve Phase A D4 architecture choices (MCP surface design, feature placement, onboarding flows) depend on this binding. Deferring means each downstream decision re-litigates the principle. |

**What would invalidate this:**

- A core platform feature (per the value-proposition test above) proves genuinely unservable at acceptable quality via web UI alone. Substantive observation per FLEXIBLE-path; revisit whether that feature should be moved to extended scope (and the value proposition adjusted) or whether web UI patterns can carry it after all.
- The core/extended boundary collapses under real usage — e.g., users routinely cannot complete a core flow without invoking the agent because of UX friction, even though the feature is technically web-UI-complete. Reformulate boundary or expand core-UI investment.
- Agent-runtime maturity proves insufficient for non-technical users (per kb-2ve Phase A D4 invalidation predicate) — if the agent layer doesn't materialize as planned, this ADR's extended-scope provision becomes moot and the constraint collapses to "all features are web-UI" by default.

## Consequences

### Direct

- Future bead `--design` for features in the agent layer must cite this ADR and identify whether the feature is core or agent-extended scope. Core-scope features must include a web-UI affordance; extended-scope features may be agent-only.
- MCP-surface design (kb-2ve Phase A D4) can expose operations without web-UI counterparts when those operations are agent-extended scope.
- Onboarding flows must support facilitator and attendee paths that never touch the agent layer — the agent is introduced as an option, not a requirement.
- The core/extended boundary is itself subject to review at each new agent-layer feature decision.

### Carried forward

- ADR-001 D1 (curated-trust framing) — core platform scope serves the curated-trust value proposition; this ADR makes the web-UI-completeness obligation for that scope explicit.
- ADR-008 D2 (no speculative abstraction) — Phase B reduction must not pre-build MCP surface ahead of validated agent use-cases (already established in kb-2ve Phase A D4 rationale); this ADR doesn't change that, only adds the additional architectural constraint on what the MCP surface may eventually expose.
- ADR-010 D1 (event-based posture) — the agent layer must serve real-world action; this ADR adds the architectural binding (additive, never required for core).

### Risk

- Definition of "core platform scope" can drift over time as features mature. Mitigation: the value-proposition test (per ADR-001 D1) anchors what's core; new features that gate value-proposition receipt cross into core and need web-UI. Periodic audit at major version transitions.
- "Reasonable" web-UI parity in extended scope is judgment-laden — risk of always-defer ("not reasonable enough for web UI"). Mitigation: each major agent-extended feature decision documents whether web-UI parity is reasonable, with the rationale. Pattern: if web-UI parity would cost <30% of the agent feature's build, it's reasonable.
- Tension with kb-2ve Phase A D1 sister platform — sister platform's API for syndication is consumed by the agent. The sister platform itself is independent infrastructure (web UI on the sister), not affected by this ADR. Switch Berlin's agent talking to sister API is agent-extended-scope behavior.

## canonical_refs

- [ADR-001 D1](ADR-001-core-product-and-stack.md) — curated-trust framing; core platform scope serves the value proposition this D1 establishes.
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction; this ADR's extended-scope provision is a non-speculative discipline (allows agent-natural features without pre-building SaaS abstraction for them).
- [ADR-009 D4](ADR-009-mutual-connection-graph-and-identity-visibility.md) — anti-engagement ranking posture at feed-ranking layer; the agent layer must respect this constraint when interacting with feed surfaces.
- [ADR-010 D1](ADR-010-event-based-product-posture.md) — product-purpose posture; the agent layer must serve real-world action goals. This ADR-011 adds the architectural binding (additive vs required) on top of ADR-010's goal-orientation binding.
- `kb-2ve` (Long-term platform vision brainstorm) — Phase A D4 (personal-agent layer) is the architectural design this ADR-011 canonicalizes the additive constraint for; Phase A D2 (cross-channel event syndication) inherits the extended-scope provision.
- `kb-fx9` (Ship social foundation) — core platform features (D7 feeds, D9 Updates, D13 EventRequirement) are core platform scope and web-UI-complete per this ADR.

## Open questions deferred

| Question | Resolution path |
|---|---|
| "Reasonable web-UI parity in extended scope" — what threshold operationalizes the preference? | Defer; first agent-extended feature with web-UI-parity-candidacy decision exercises the threshold. Candidate heuristic recorded above (web-UI parity reasonable if <30% additional build cost relative to agent feature) — formalize when tested. |
| Periodic core/extended boundary audit — what cadence and trigger? | Defer; revisit at major version transitions (V0 → V1, V1 → V2). |
| Sister platform's web-UI obligations — does this ADR apply to the sister platform, or only to Switch Berlin? | Cross-reference at sister-platform design time. Working assumption: this ADR binds Switch Berlin only; the sister platform is independent infrastructure with its own architectural choices. |
