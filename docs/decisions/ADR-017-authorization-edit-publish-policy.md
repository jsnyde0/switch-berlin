# ADR-017: Authorization policy — who may edit/publish an Event, Post, or Projection

**Status:** Accepted 2026-05-26 (D1 agent→claimant resolution settled 2026-05-27)
**Parent:** [ADR-007 D2 — EventOrganizer/EventFacilitator through-tables](ADR-007-profile-centric-schema.md) (the organizer-vs-facilitator distinction this ADR gives permission semantics to); [ADR-014 D1 — ProfileClaim multi-claimant through-model](ADR-014-profile-claim-flow.md) (the membership + `role` seam this ADR's team-management foresight lands on); [ADR-016 D3 — co-equal API authentication](ADR-016-outbound-syndication-architecture-event-post-projections.md) (the authentication layer this authorization layer composes with at the handler boundary)
**Scope:** authorization (authz) — what an authenticated principal is *permitted* to do to an Event and its Posts/Projections. Distinct from ADR-016 D3 (authentication — *who* the principal is) and from ADR-009/ADR-012 (read-side visibility/access of events to viewers). This ADR governs *write* authority (edit/publish), not read visibility.

## Context

The kb-a4u decomposition adversarial review (R1-F7) + scope-check surfaced that v0 ships `EventOrganizer`/`EventFacilitator` through-table rows with **no edit-permission gate** under an explicit single-facilitator-dogfooding assumption (kb-7oz). That assumption is safe for v0 (one facilitator, one claimant) but undefined the moment a second organizer or co-host exists — and the outbound-syndication work (ADR-016) adds a paired-agent principal that acts on a facilitator's behalf, widening the authorization surface.

The existing schema carries no permission semantics: `EventOrganizer` has only `is_primary` (descriptive), `EventFacilitator.role` is free-text credit ("Lead", "DJ"), and `ProfileClaim.role` is `"admin"` with a "cheap foresight for future roles" comment. Authorization is genuinely unbuilt. This ADR canonicalizes the policy so downstream beads (C3 authoring, C5 review, C7 CLI, the adapters, the agent path) don't each invent ad-hoc `is_primary` checks that drift.

The C3/C5 authoring-UX brainstorm (2026-05-26) converged the policy; this ADR is its canonicalization (kb-7oz).

## Decisions

### D1: Edit/publish authority derives from being an `EventOrganizer`-Profile claimant (+ that claimant's paired agent); `EventFacilitator`s are credited-only

**Firmness: FLEXIBLE** — converged 2026-05-26, dogfooding-pending. Reversible if multi-facilitator dogfooding shows organizers need an explicit grant/trust step before a listed co-organizer can edit (i.e. being-listed should not equal being-able-to-edit), or if a real workflow needs a facilitator (e.g. a co-host DJ) to hold edit rights.

A principal may edit/publish an Event — and its Posts and PlatformProjections — iff the principal is a **claimant (via `ProfileClaim`) of a Profile that is an `EventOrganizer` of that Event**, OR is a **paired agent of such a claimant** (the agent inherits its principal's organizer authority per ADR-016 D3). `EventFacilitator`s are **credited-only**: listed and rendered, but not authorized to edit. Authority thus derives from *which through-table you are in* (organizer = controller; facilitator = credit) — no new permission field is introduced at v0. v0 single-facilitator is the trivial case (one organizer Profile, one claimant) and ships correctly under this rule.

**Agent→claimant resolution (resolved 2026-05-27 — was a deferred open question).** A paired agent inherits its principal's organizer authority via this binding: `agents/register` (the C6 pairing flow) binds the issued long-lived credential to the **registering user's identity** — not to a single Profile — and `can_edit`/`can_publish` resolve the authenticated agent to that user's full `ProfileClaim` set. The agent thus presents *as* its owning claimant, holding no independent authority scope, exactly as that user's web session would; v0 single-facilitator is the trivial case. The credential→User binding lives on the agent-credential record issued during pairing (which mirrors the `MagicLinkToken` envelope); the issuance/auth mechanics — one-time pairing-token redemption, key→identity-token exchange, `verify-identity` stubbed at v0 — are pinned in ADR-016 D3's "v0 concrete shape" annotation. (Previously flagged deferred pending the `agents/register` data-model design; the 2026-05-27 agent-credential convergence settled it. Implementation lands in C2 + C6.)

**Rationale:**

- `external:` C3/C5 brainstorm 2026-05-26 — user chose model (a): *"organizers (and their agents) edit; facilitators are credited-only; rights derive from the table you're in, no new field."*
- `reasoned:` the `EventOrganizer`/`EventFacilitator` split (ADR-007 D2) already encodes the controller-vs-credit distinction; giving it permission semantics makes the table choice carry real weight instead of being cosmetic, and adds zero schema.
- `reasoned:` a paired agent acts on behalf of its principal (ADR-016 D3 co-equal clients); inheriting the principal's organizer authority is the only model consistent with "web UI and agent are co-equal" — a private agent authority scope would diverge.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Primary-organizer-only edit (`is_primary` gate); co-organizers display-only unless granted | `reasoned:` breaks the moment a genuine co-organizer needs to act — a co-organizer who can't touch the event is wrong past one facilitator; forces an immediate grant mechanism. `external:` user rejected in favor of (a). Retained as the *invalidation* path (if being-listed-shouldn't-equal-edit proves right). |
| New permission-role grant (owner/editor/viewer) on the `EventOrganizer` through-table | `reasoned:` speculative abstraction (ADR-008 D2) — builds a per-person grant matrix before any multi-facilitator workflow demands it. The `ProfileClaim.role` seam (D3) already absorbs future role needs without a new field now. |
| Facilitators also get edit rights | `reasoned:` collapses the controller/credit distinction the organizer/facilitator tables exist to express; a credited DJ shouldn't be able to rewrite the event or publish projections. |

**What would invalidate this:**

- Multi-facilitator dogfooding surfaces that being-listed-as-organizer should NOT automatically grant edit — organizers want to add a co-organizer for credit/visibility but gate edit behind an explicit trust step. Substantive observation; introduce a grant step (likely via the D3 role seam) without abandoning the table-derived default.
- A real workflow needs a specific `EventFacilitator` (e.g. a co-running host filed as facilitator) to hold edit rights. Operational signal; either refile them as an organizer or revisit the facilitator-credited-only rule.

### D2: All edit/publish authorization routes through a single authorization seam (the chokepoint)

**Firmness: FLEXIBLE** — same convergence. Reversible only in the sense that the seam's internal logic evolves; the single-chokepoint shape is the cheap-foresight commitment.

Every authorization check — web edit views, the Django Ninja API handlers, the switch-cli verbs, the adapter publish paths, the agent path — routes through **one authorization seam** (a single module), rather than scattering `is_primary`/claimant checks across call sites. The seam exposes the small set of write-authority questions the surfaces actually ask: `can_edit(user, event)` and its publish sibling `can_publish(user, event)`. "Single" refers to the **seam**, not literally one function — edit and publish are sibling predicates that **share the same v0 derivation** (claimant-of-an-`EventOrganizer`-Profile per D1); they are co-located so the future role logic enriches one place. At v0 both implement D1 identically (claimant of an organizer Profile; facilitators excluded; the `ProfileClaim.role` check is trivially satisfied since all claimants are `admin`). When team management arrives (D3) — or when edit and publish authority legitimately diverge (the invalidation case below) — the role logic enriches **this one seam** and every call site inherits it.

**Rationale:**

- `reasoned:` the failure mode this prevents is authz logic scattered across views, forms, API handlers, CLI, and adapters — which makes the future role model a painful grep-and-patch and invites drift (one surface forgets the check). A single seam is the cheap-foresight move that costs nothing now (the v0 check is trivial) and contains all future authz evolution.
- `external:` C3/C5 brainstorm 2026-05-26 — user asked for exactly this cheap foresight toward future team management.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Inline `is_primary`/claimant checks at each call site | `reasoned:` guarantees drift across the ~half-dozen write surfaces (web/API/CLI/adapters/agent); future role logic becomes a scatter-patch; one forgotten surface is a silent authz hole. |
| A full policy engine / permission framework now | `reasoned:` ADR-008 D2 speculative abstraction — a predicate function is the simplest thing that works; a framework is warranted only when per-action/per-role grants actually exist. |

**What would invalidate this:**

- The single-predicate shape proves insufficient because authorization needs to vary per action-type in ways a single boolean can't express (e.g. edit vs publish vs delete diverge sharply). Signal: the predicate sprouts many action flags. Refactor toward a small capability check — still centralized, not scattered.

### D3: `ProfileClaim` is the team-membership seam; future per-user team management widens `ProfileClaim.role` and grants/revokes claims — no new model

**Firmness: FLEXIBLE** — same convergence. Cheap-foresight shape commitment (ADR-003); the team-management *behavior* is explicitly deferred, not built at v0.

`ProfileClaim` (ADR-014 D1) is the (Profile × User) membership join and is treated as the team-membership table. Future "manage a Profile/team" capabilities map onto it with **no new model**:

- **add a user to a team** = grant a `ProfileClaim` (the existing claim flow, ADR-014).
- **remove a user** = revoke the claim.
- **assign roles / permissions** = widen the existing `ProfileClaim.role` enum and enrich the D2 predicate. **The role vocabulary is ADR-014's to set, not this ADR's** — ADR-014 D1 already reserves `role` with cheap-foresight values `contributor` (reduced edit rights) and `former` (archived claim) beyond the v0 `admin`. ADR-017 does not introduce a competing vocabulary; whatever values team-management needs are added to ADR-014's reservation in place, and the D2 seam maps them to edit/publish authority. (The point of D3 is *where the seam lives* — `ProfileClaim.role` — not which strings populate it.)

At v0 none of this is built — `role` stays `admin` and the D2 predicate's role check is trivially true. The decision is the *shape commitment*: the seam is `ProfileClaim.role`, not a future `Membership`/`TeamMember` model.

**Rationale:**

- `external:` C3/C5 brainstorm 2026-05-26 — user asked for cheap foresight toward "user management for a profile… assign different permissions, roles, add/remove users to a profile/team."
- `reasoned:` `ProfileClaim` already is the membership join with a `role` field explicitly commented "cheap foresight for future roles" (organizers/models.py); the future feature is widening an enum + grant/revoke, which the claim flow already supports — inventing a separate membership model later would duplicate `ProfileClaim`.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| A separate future `Membership`/`TeamMember` model | `reasoned:` duplicates `ProfileClaim`, which is already the (Profile × User) join with a role field; two membership tables is a consistency burden and a migration later. |
| Build the role vocabulary + team-management UI now | `reasoned:` ADR-008 D2 — speculative; v0 is single-facilitator with every claimant `admin`. Shape (the seam) now; behavior when a real multi-user team exists. |

**What would invalidate this:**

- Team management turns out to need attributes that don't fit on `ProfileClaim` (e.g. team-level settings independent of any single user's claim). Substantive observation; introduce a Profile-level team-settings model *alongside* `ProfileClaim`-as-membership, not replacing it.

## Consequences

### Direct

- C3 (kb-a4u.3) authoring, C5 (kb-a4u.5) review, C7 (kb-a4u.7) CLI, and the adapter/agent publish paths all gate edit/publish through the D2 predicate. C3's existing "co-host rows without edit-gate" note is now superseded: co-*organizers* DO get edit (via D1); the gate exists and is the predicate, it's just trivially satisfied for the v0 single-facilitator case.
- No new permission field or model ships at v0. The predicate reads `EventOrganizer` membership + `ProfileClaim` claimancy; `ProfileClaim.role` is consulted but trivially `admin`.
- The kb-7oz follow-up bead is satisfied by this ADR (close-and-link).

### Carried forward

- **ADR-007 D2 FIRM** — the organizer/facilitator through-tables now carry permission semantics (organizer = controller, facilitator = credit). The schema is unchanged; the *meaning* is canonicalized here.
- **ADR-014 D1 FLEXIBLE** — `ProfileClaim.role` is the team-membership/role seam; this ADR defines what that reserved field will govern.
- **ADR-016 D3 FLEXIBLE** — authentication (who you are) composes with this authorization layer (what you may do) at the handler boundary; a paired agent authenticates per D3 and inherits organizer authority per D1.
- **ADR-008 D2 FIRM** — no permission framework / role matrix until a real multi-facilitator grant workflow exists; the predicate + the `ProfileClaim.role` seam are the simplest thing that works.

### Consolidation note (ADR-008 D7)

Overlap with ADR-014 scored moderate (3.5/5) — `ProfileClaim`/`role` is the shared model. This ADR is placed separately on structural-fit grounds (authz *policy* is a different kind of decision than ADR-014's claim-*verification flow*, and it also spans ADR-007's organizer/facilitator boundary). If ADR-017 stays thin and ADR-014's role semantics and this authz policy prove inseparable in practice, consolidate ADR-017 D3 into ADR-014 in place.

## canonical_refs

- [ADR-007 D2](ADR-007-profile-centric-schema.md) — EventOrganizer/EventFacilitator through-tables; this ADR gives them permission semantics (organizer=controller, facilitator=credit).
- [ADR-014 D1](ADR-014-profile-claim-flow.md) — ProfileClaim multi-claimant through-model + `role` cheap-foresight field; D3 here is the team-membership realization of that reservation.
- [ADR-016 D3](ADR-016-outbound-syndication-architecture-event-post-projections.md) — co-equal API authentication; authz (this ADR) composes with authn (D3) at the handler boundary; paired agents inherit principal authority.
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction; predicate + role-field seam, not a permission framework.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight on shape: the D2 predicate seam and D3 `ProfileClaim.role` seam are shape commitments, behavior deferred.
- [ADR-009](ADR-009-mutual-connection-graph-and-identity-visibility.md) — read-side visibility/access (orthogonal: this ADR governs write authority, not who can view an event).
- `kb-7oz` — the deferred authorization-policy bead this ADR canonicalizes (discovered-from kb-a4u; close-and-link).
- `kb-a4u.3` — C3 authoring bead whose "co-host rows without edit-gate" v0 note this ADR supersedes.
