# ADR-013 — User trust model: tiered authentication, vouching graph, invite economy

**Status:** Accepted 2026-05-21 (EXPLORATORY pending dogfooding per ADR-012 D6 bar)
**Scope:** social-graph
**Supersedes:** —
**Canonicalizes:** kb-m69 D4, D6, D9 (D1 — profile claim flow — deferred to forthcoming ADR-014)

## Context

Switch Berlin's curated-trust default (ADR-001 D1) gates community-signal-bearing content behind admin approval in Phase 0.5. Post the public-read flip (kb-9hw), the gate needs an operational shape: who can authenticate, what they see at each tier, how trust accumulates, and how the invite economy works without either chilling growth (vouchers afraid to invite anyone) or losing selectivity (vouchers spamming invites).

ADR-012 (event visibility tiers) already references "vouched User" as the gating audience for `semi_public` events but does not define what makes a User vouched. ADR-009 D2 references the `vouched` visibility tier and D3 treats Vouch as reputation-private — both decisions cite `kb-m69 D4` / `kb-m69 D6` as the forthcoming upstream definition. This ADR is that upstream definition.

The kb-m69 brainstorm (2026-05-18) landed four decisions in this cluster — tiered auth (D4), vouching with proportional consequences (D6), invite economy (D9), and profile-claim flow (D1). The first three are tightly coupled at the trust-posture layer; profile-claim is a sibling user-flow that touches `Profile` schema and warrants its own ADR (ADR-014, forthcoming). This ADR canonicalizes D4 + D6 + D9.

EXPLORATORY firmness is the safe default per ADR-012 D6 — none of these decisions have been dogfooded yet. The shape is firm enough to implement against; the specific weights, thresholds, and cascade rules are signal-gated and expected to evolve.

## Decisions

### D1 — `User.status` enum gates audience access

**Decision:** Authenticated users carry a `User.status` field with values:

```
status ∈ {'open', 'vouched', 'suspended_pending_investigation', 'banned'}
```

- `open` — verified email; sees `public` events; can claim their own `kind=person` Profile; cannot see `semi_public` events; cannot invite others.
- `vouched` — same as `open` plus: sees `semi_public` and `unlisted` (if URL-shared) events per the ADR-012 D3 access matrix; eligible to receive vouch_score and personal_rating signals; eligible to be granted invite codes per D4 below.
- `suspended_pending_investigation` — reversible intermediate state during admin review of a complaint or pattern flag. Same view as `open` (downgraded); cannot redeem outstanding invite codes; vouches issued or received remain on the books but do not count toward `vouch_score`.
- `banned` — admin-confirmed terminal state. No login. Existing vouches removed; future invites blocked.

State transitions are admin-mediated (per ADR-001 D1 curated-trust default); the only system-automatic transition is `signed_up_via_invite_redemption → vouched` on successful invite-code redemption.

**Firmness:** EXPLORATORY

**Rationale:**

- `direct:` kb-m69 D4 explicit: "open signup required to see the 'public' events but you need to be vouched in in order to see the semi-public and private ones." `User.status` is the schema realization of that gate.
- `reasoned:` ADR-012 D3's access matrix names `vouched User` as the audience tier for `semi_public` events but does not define it. Without an enum, every read-path query has to invent its own "is this user trusted" predicate — fragile and inconsistent.
- `external:` FetLife uses an analogous account-status enum (`active` / `suspended` / `deleted`) with admin-gated transitions (scout, 2026-05-18). Confirms the shape composes at scale.
- `reasoned:` `suspended_pending_investigation` as a distinct reversible state (rather than overloading `banned` and reverting) preserves audit trail and avoids the "we banned them and now we have to un-ban" friction.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Three-tier auth (open / registered-but-not-vouched / vouched) | `reasoned:` YAGNI for V0. The middle tier ("logged in but not yet vouched") collapses to `open` operationally — same view permissions. Splitting it adds schema and query complexity without buying a distinguishable audience. ADR-012 D1 preserves the option to split `semi_public` into `registered_only`+`vouched_only` later; the auth-tier split would follow that, not lead it. |
| Single boolean `is_vouched` instead of enum | `reasoned:` Cannot represent the reversible `suspended_pending_investigation` state without overloading nullability or adding a parallel boolean. Enum is cheap-foresight per ADR-003 — one column, four discriminated states, room to extend. |
| Auth status derived from `Vouch` table (no `User.status` field) | `reasoned:` Forces every read query to JOIN against `Vouch` and apply business logic; conflates "currently has at least one active vouch" with "is in good standing." Suspended users have active vouches but should not see vouched content. Status must be authoritative, not derived. |
| Auto-fire ban on N negative complaints | `reasoned:` Removes admin judgment from the consent-positive-space gate that ADR-001 D1 makes load-bearing. Pattern-match thresholds in this domain are gameable (coordinated false complaints) and the cost of a wrongful ban is high. Admin-approved bans are non-negotiable. |

**What would invalidate this:**

- If the open-signup tier sees ~zero use after V0.6 (everyone signs up via invite), the `open` state is dead schema; collapse to invite-only and remove the enum's first value.
- If `suspended_pending_investigation` is never used (every admin review terminates in either no-action or ban without a parking state), the intermediate state is overhead; collapse to a two-state `vouched` ↔ `banned` flow.
- If a coordinated-complaint pattern emerges (multiple users colluding to suspend a target), the reversible-suspension primitive itself becomes the abuse vector — re-evaluate.

### D2 — Two onboarding paths: open signup, vouched signup

**Decision:** Two authentication entry-points reach an authenticated state:

1. **Open signup** — email + password (or email + magic link). On verification, `User.status = 'open'`. User receives an auto-created `Profile(kind=person)` per kb-m69 D3 (deferred to ADR-014 / schema work, not in scope of this ADR).
2. **Vouched signup** — same form plus an invite code field. On successful code redemption, `User.status = 'vouched'` and a `Vouch(voucher=<code-issuer>, vouchee=<new-user>, created_at=now())` row is created.

Invite codes are single-use, time-bounded (default TTL 14 days, configurable per code), scoped to a single voucher. Codes display with the voucher's display name visible to the redeemer at the redemption screen — the social cost of bad invites is borne by the named voucher.

Open-signup users can later be upgraded to `vouched` via the same invite-redemption flow (entering a code on an existing account upgrades status); no separate "upgrade" path is needed.

**Firmness:** EXPLORATORY

**Rationale:**

- `direct:` kb-m69 D4 explicit on the two paths; this decision is the schema/UX realization.
- `reasoned:` Single-use codes prevent the "leaked invite link" failure mode — a code in the wild redeemed by an unintended party costs the voucher exactly one `Vouch` row, surfaced visibly.
- `reasoned:` Time-bounded codes prevent the "issued years ago, redeemed cold" path that loses the voucher's contemporaneous context. 14 days matches the typical IRL "I'll invite you next time we meet" cadence.
- `reasoned:` Naming the voucher to the redeemer at redemption time makes the social contract explicit — the redeemer knows whose name is attached to this entry. Reduces the "I redeemed it because I had a code" cold-redemption shape.
- `external:` Lobste.rs uses a similar named-invite economy; the social-cost-of-bad-invites mechanic is well-documented as a community-quality preservation tool (scout, kb-m69 brainstorm).

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Multi-use invite codes (one code, N redemptions until expiry) | `reasoned:` Decouples the named-voucher accountability — redemption #4 from the same code carries the same voucher weight as redemption #1 even though context drifted. Single-use forces deliberate per-invitee issuance. |
| Anonymous invite codes (voucher hidden from redeemer) | `reasoned:` Removes the social-contract signal the named-voucher creates. Redeemer doesn't know whose trust they're trading on, voucher cannot be socially held to standard. The mechanic depends on visibility. |
| Open signup only, no vouching path — upgrade-by-application after participation | `reasoned:` Bootstraps slowly (no signal for new users until they've attended events) and pushes admin workload up (every upgrade is a manual review). Vouching distributes the trust-extension work to the network. |
| Invite-only across all tiers (no open path) | `reasoned:` Status quo before kb-9hw — limits public-event discoverability after the flip. Counterproductive for legitimately public events (IKSK's website-published gatherings). |

**What would invalidate this:**

- If invite codes consistently expire unredeemed (TTL too tight) or are routinely shared in group chats (TTL too loose, single-use too restrictive), re-tune.
- If named-voucher visibility creates a chilling effect (vouchers refuse to issue any invite for fear of public association), the visibility mechanic was wrong — make voucher visible to admin only, not to redeemer.
- If users routinely create open-signup accounts and never redeem an invite to upgrade (open tier is the terminal state in practice), the upgrade path is dead; either the public-event tier is sufficient and `vouched` is overkill, or the vouched-content value-proposition is too weak.

### D3 — Vouching graph with proportional consequences and one-hop cascade

**Decision:** Vouching is modeled as a directed graph:

```python
class Vouch:
    voucher: FK(User)       # who issued the invite that was redeemed
    vouchee: FK(User)       # who redeemed it
    created_at: datetime    # redemption time
    cancelled_at: datetime  # nullable; cheap foresight, behavior not built in V0
```

Trust signals derived from this graph:

- `User.vouch_score` — separate field from `User.personal_rating` (latter is from event reviews). Update rule: when a `vouchee` is admin-confirmed `banned` or accumulates substantiated complaints, the `voucher`'s `vouch_score` takes a proportional hit. Magnitude is a function of (a) how many bad-invite signals the voucher has accumulated and (b) recency. **Specific weights are FLEXIBLE and tuned post-dogfooding.**
- **One-hop cascade only.** If A vouches B, and B vouches C, and C is banned: B's `vouch_score` takes a hit; A's `vouch_score` does not. The voucher is accountable for their direct invitees, not their invitees' invitees.
- **Bans are admin-approved.** Pattern signals (e.g., 3+ banned invitees within a window) trigger admin review (notification + queue entry), not automatic action. `suspended_pending_investigation` is the reversible intermediate (per D1).
- **Single low review does not cascade to voucher.** A 2/5 review of a vouchee affects the vouchee's `personal_rating` only; the voucher's `vouch_score` is unaffected. The graph reflects judgment-of-character signals (bans, substantiated complaints), not event-experience signals (ratings).

**Firmness:** EXPLORATORY (the graph shape, one-hop cascade, proportional-not-binary, separation from `personal_rating`); FLEXIBLE (specific weight formula, pattern-trigger thresholds — these will tune from dogfooding).

**Rationale:**

- `direct:` kb-m69 D6 explicit: "we do want people handing out invites, but be very selective. If they get too afraid, they may not invite and we don't grow." Proportional + one-hop is the chilling-effect mitigation. Binary-consequence vouching is documented to catastrophically reduce invite issuance.
- `direct:` kb-m69 D6 explicit on plausible-deniability via scarcity (paired with D4 below): when invites are visibly rare, "sorry, I'm out" is a credible social cover, lowering the cost of saying no to weak ties. The proportional-consequence + scarce-invite combination is the design pair, not either alone.
- `reasoned:` Separating `vouch_score` from `personal_rating` decouples two distinct trust signals: "I'm a good attendee at events" vs "I have good judgment about who to invite." Conflating them misrepresents both axes — a great attendee with poor invite judgment shouldn't be displayed as low-rated, and a discerning voucher who rarely attends events shouldn't be displayed as low-rated either.
- `reasoned:` One-hop cascade is the depth where accountability remains tractable. Multi-hop (A held responsible for B's vouches) creates paranoia that suppresses invite issuance; no cascade removes the selectivity incentive entirely.
- `reasoned:` Admin-approved bans (no auto-fire) honors ADR-001 D1 curated-trust default. Automated bans are a known abuse vector (coordinated false-flag campaigns) and the cost of a wrongful ban in this community is high.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Binary consequence (invitee banned → voucher auto-banned) | `reasoned:` Catastrophic chilling effect; vouchers stop inviting anyone they don't 100% trust forever. Network never grows past existing close-tie clusters. |
| No cascade (voucher faces no consequence for invitee outcomes) | `reasoned:` Removes selectivity incentive; vouching collapses to "I know them, let them in" without trust accountability. The whole point of the vouch graph is that issuing an invite carries weight. |
| Multi-hop cascade (A responsible for everything B vouches downstream) | `reasoned:` Paranoia at depth; B's invitee choices aren't A's. Distorts the trust-graph into a liability network. |
| Single `User.rating` covering both event behavior and vouching judgment | `reasoned:` Conflates two distinct signals (covered in rationale above). A user who attends one event and behaves perfectly but issues bad invites would display as high-rated. |
| Auto-suspend on N negative signals without admin review | `reasoned:` Same as D1's rejection of auto-fire bans — admin judgment is load-bearing per ADR-001 D1. Pattern signals trigger review, not action. |
| Cancel-vouch behavior built in V0 | `reasoned:` `Vouch.cancelled_at` field exists per cheap foresight (ADR-003 pattern); behavior — what happens to the vouchee when their vouch is revoked — is deferred. Pre-launch we have no signal on whether this is a needed primitive or unused capacity. |

**What would invalidate this:**

- If `vouch_score` never differentiates between users in practice (everyone hovers near initial value), the metric isn't doing work — retire it and rely on admin pattern-review alone.
- If one-hop cascade turns out insufficient (chronic bad-actor clusters where the bad actor is two hops out and one-hop accountability doesn't surface the pattern), evaluate two-hop selectively rather than blanket multi-hop.
- If `vouch_score` and `personal_rating` empirically correlate above ~0.9 across the user base, the separation is over-engineering; collapse to a single trust signal.

### D4 — Invite economy: V0 admin-grant only, schema-ready for earned-invite formula

**Decision:** V0 invite codes are issued exclusively by admin manual action. Newly-vouched users start with **zero invites**. Schema includes `User.invite_codes_remaining` (integer, default 0) and `InviteGrant(grantor=admin_or_system, grantee=User, count, reason, created_at)` audit log.

Future earning formulas (V1+) are not implemented but the schema is ready. Illustrative shapes considered (none committed):

- Threshold-based: e.g., 10+ positive reviews AND avg ≥4.5 over ≥5 reviews → unlocks 1 invite/quarter.
- Tenure-based: every N months of `vouched` status without negative signals → 1 invite.
- Hybrid: combine activity and tenure with admin-tunable weights.

The earning job is deferred; the cheap-foresight cost (one integer column + one audit table) is bounded.

**Firmness:** EXPLORATORY (V0 admin-only as the operational policy); FLEXIBLE (specific earning formula and activation timing).

**Rationale:**

- `direct:` kb-m69 D9 explicit: "How to earn invite codes is tricky but we can think of different ways… we probably do want this to feel like a very scarce resource." Start tight (admin-only); loosen with criteria over time.
- `reasoned:` Vouched-users-start-with-zero is the load-bearing design insight — *being vouched in doesn't make you a voucher*. The right to invite is earned through demonstrated participation, not granted on entry. This is what makes the invite economy a quality filter rather than a multiplier on initial signups.
- `reasoned:` Scarcity makes the social-deniability mechanic work (D2 rationale): when invites are visibly rare, the "I'm out of invites right now" excuse is credible. Granting N invites at signup destroys this mechanic.
- `reasoned:` Cheap foresight per ADR-003: ship `invite_codes_remaining` and `InviteGrant` audit log now; activate earning job when V1 review volume justifies a formula. Avoids a migration when the formula stabilizes.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Every vouched User gets N invites at signup | `reasoned:` Removes scarcity → removes plausible-deniability for selective inviting → chills selectivity. The whole D3 proportional-consequence design depends on invites being visibly scarce. |
| Reviews-only earning (no admin lever) | `reasoned:` Need bootstrap path; admin must be able to grant invites for new organizers / co-organizers who don't yet have review history. Pure formula-based locks the cold-start network. |
| Pay-for-invites (purchase invite codes) | `reasoned:` Directly contradicts ADR-010 (event-based product posture — facilitate real-world action, do not monetize engagement). The invite economy is not a revenue surface. |
| Invites as fully-renewable resource (replenishes per period regardless of conduct) | `reasoned:` Decouples invite supply from trust judgment. A voucher with a history of bad invites should not automatically refill. Conduct-gated replenishment is the entire point. |

**What would invalidate this:**

- If admin grant-volume becomes the rate-limiting constraint on network growth (admin can't keep up with legitimate org/co-organizer onboarding), the manual-only policy is too tight — activate a formula sooner.
- If the formula-readiness schema (`invite_codes_remaining`, `InviteGrant`) is never used beyond V0 admin-grant for the project lifetime, the cheap-foresight cost was wasted (acceptable — one integer column is bounded overhead).
- If invite-scarcity has zero observable effect on selectivity (vouchers issue every invite they have, regardless of trust signal), the scarcity mechanic isn't doing work; reconsider whether quantity-based scarcity is the right primitive.

## canonical_refs

- [ADR-001](ADR-001-core-product-and-stack.md) — D1 (curated-trust default), D4 (user accounts V0-load-bearing). This ADR operationalizes both: D1 routes admin judgment through `User.status` transitions; D4 receives its concrete shape as the two-path signup of D2.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — pattern applied to `User.status` enum extensibility, `Vouch.cancelled_at` nullable, `User.invite_codes_remaining` + `InviteGrant` schema-ready.
- [ADR-008](ADR-008-code-posture-refactor-hard-fail-loud.md) — D1 predicates (firmness / rationale / alternatives / invalidation); D3 fail-loud on `User.status` invariants (missing or invalid status raises, never silent-fallbacks to a permissive default); D5 mandatory canonical_refs.
- [ADR-009](ADR-009-mutual-connection-graph-and-identity-visibility.md) — D2 (4-tier visibility) and D3 (reputation-private Vouch) reference `vouched User` as the upstream audience tier this ADR canonicalizes. The `Vouch` graph defined in this ADR's D3 IS the substrate ADR-009 D3 calls reputation-private.
- [ADR-010](ADR-010-event-based-product-posture.md) — anti-engagement-monetization constraint informs D4's rejection of pay-for-invites.
- [ADR-011](ADR-011-personal-agent-layer-additive.md) — D1 (ADRs evolve in place); this ADR is a new entry, not an evolution.
- [ADR-012](ADR-012-event-visibility-tiers.md) — D1 (`semi_public` audience = "any vouched User") and D3 (access matrix gating `semi_public` reads on `User.status == 'vouched'`) depend on this ADR's D1 enum. Update ADR-012's "forthcoming ADR" references to point here after this commit.
- [kb-m69](../../) — source brainstorm (decisions D4, D6, D9); D1 (profile claim) deferred to forthcoming ADR-014.
- [kb-9hw](../../) — Phase 0.5 public-read flip; this ADR is one of the blockers for that flip's safe execution (PUBLIC_READ_ENABLED without User trust tiers means `semi_public` events have no audience definition).

## Post-write follow-ups (filed as discovered-from beads, per ADR-008 D4)

- ADR-012 D1 footnote and D3 access matrix currently say "forthcoming ADR" — should be updated to point to ADR-013 once this lands. (In-place edit of ADR-012 follow-up, not in this commit's scope per scope-discipline.)
- ADR-014 (Profile claim flow) — canonicalizes kb-m69 D1 (web-first claim with email-domain fast-path) and kb-m69 D2 (multi-claimant `ProfileClaim` through-model — evolves ADR-007 D5 in place per ADR-011 D1).
- kb-m69 to `/decompose` after ADR-013 + ADR-014 land — implementation children for schema migration, middleware extension, signup paths, tier-picker UI, invite-redemption flow.
