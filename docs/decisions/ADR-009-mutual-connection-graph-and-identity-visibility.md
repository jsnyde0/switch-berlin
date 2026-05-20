# ADR-009: Mutual Connection graph, identity visibility, and anti-engagement ranking posture

**Status:** Accepted 2026-05-19 (revised 2026-05-20 — added D4 anti-engagement ranking principle per kb-4pj)
**Parent:** [ADR-007 D1 + D6 unified Profile + Follow](ADR-007-profile-centric-schema.md)
**Scope:** social-graph primitives (mutual friendship) + Profile-level identity visibility tiers + event-page social-proof surface + feed-ranking posture (D4) — Phase 0.5+. Extends ADR-007's Profile/Follow architecture with a third orthogonal social-graph primitive (User↔User, not Profile-centric) and binds the kb-fx9 D7 multi-feed surface to a bounded-strata ranking rule.

## Context

kb-m69 (identity / trust / visibility substrate) and kb-fx9 (social-discovery foundation) brainstorms identified a *mid-tier* social signal that neither existing graph carries:

- **Follow** (ADR-007 D6) is asymmetric subscription — "I want to see your content."
- **Vouch** (kb-m69 D6) is asymmetric reputation-stake — "I trust you in shared spaces; my account is on the hook if you misbehave."

Real-world kink-scene relationships also include a *low-stakes mutual* signal: "we know each other and like each other; I wouldn't burn a scarce invite vouching for you, but you're not a stranger either." That signal is absent.

Separately, the V0 differentiation analysis (kb-fx9 D7) identified **friend-graph-driven event discovery** as the missing feature across modern event platforms (Partiful, Lu.ma, FetLife) — but that surface presupposes a friend graph to drive it.

Both gaps argue for a new mutual social-graph primitive. This ADR canonicalizes it and the identity-visibility tier it unlocks.

## Decisions

### D1: `Connection` as orthogonal mutual social-graph primitive

**Firmness: FIRM** — load-bearing for D2 (visibility tier) and D3 (social proof); foundational for V1+ DM-bypass behavior (deferred to kb-svg per ADR-002 D4).

```
Connection(
  initiator: FK(User),
  receiver: FK(User),
  status: 'pending' | 'accepted' | 'declined' | 'blocked',
  requested_at: DateTime,
  accepted_at: DateTime null,
  declined_at: DateTime null,
)
# Bidirectional uniqueness: if A→B exists in any non-terminal status
# (pending or accepted), B cannot send a new pending; the receiver's
# UI auto-promotes the existing request ("Anna also wants to
# connect — accept?").
```

Connection is **orthogonal** to:
- `Follow(user, profile)` — asymmetric subscription (ADR-007 D6)
- `Vouch(voucher, vouchee, …)` — asymmetric reputation-stake (kb-m69 D6)

V0 scope is **graph-only**: Connection-acceptance unlocks D2 (visibility) and D3 (social proof). DM-bypass semantics (mutual Connection bypasses cold-DM eligibility) are *captured* in kb-svg M1/M2 but **not implemented at V0** because ADR-002 D4 defers all native 1:1 messaging until the 1.0 retrospective.

**Counter-argument (FIRM-path requirement):** The alternative "Follow + Vouch is sufficient — don't add a third graph" was the previous default and rests on the observation that modern event platforms (Partiful, Lu.ma) have dropped mutual friendship in favor of asymmetric follow only. That rationale held *if Switch Berlin's scope were strictly an event platform*. The kb-fx9 user-reframe ("we're going beyond an event platform") rebuts the premise: kink-platform identity disclosure, consent communication, and mid-stakes acquaintance need a mid-tier signal that Vouch's scarcity (kb-m69 D9 — invites are deliberately rare) and Follow's asymmetry can't carry. The original two-graph rationale's premise no longer holds, so the FIRM decision flips.

**Rationale:**
- `direct:` kb-fx9 D3 — vouching is reputation-stakes; friendship is "we know each other and like each other." Different sensitivity, different volume, different consent semantics.
- `external:` Scout (`history/scout-features-switch-berlin-2026-05-18.md`) — FetLife has mutual friending (gates DM caps + messaging presets); Diversia has "Seems Nice/Interesting" mutual-match flag. Modern *event* platforms (Partiful, Lu.ma) dropped the primitive — but Switch Berlin's scope is broader than event-platform-only.
- `reasoned:` Three orthogonal graphs (Follow / Vouch / Connection) carry three distinct semantics; collapsing any pair conflates trust signals.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| No mutual primitive — Follow + Vouch only | `reasoned:` Loses "we know each other" mid-tier; the kb-fx9 user-framing identified this as real and not served by either. |
| Connection replaces Follow (asymmetric subscription dies) | `reasoned:` Subscription ("see their events") and mutual connection ("we know each other") are different semantics; users need both. |
| Transitive friend-of-friend trust (Facebook FoF visibility) | `reasoned:` Transitive trust escalates without consent — same lesson as kb-m69 D6's deliberate one-hop vouch-cascade. |
| Friendship with admin-curated approval (curated trust) | `reasoned:` Over-gates a low-stakes mutual signal; turns acquaintance into a vouching-shaped process. Conflates with kb-m69 D6 vouching curation. |

**What would invalidate this:** A pattern where Connection volume is essentially zero (most users have 0–1 accepted Connections after 6+ months) and Follow-alone serves the same UX needs that D2 and D3 below require. The signal: D2 visibility-tier `friends` is unused in practice, or D3 social-proof overlay always shows "0 friends going."

### D2: 4-tier identity visibility (`public > vouched > friends > private`)

**Firmness: FIRM** — depends on D1; load-bearing for kink-identity-disclosure UX (kb-fx9 D1 + ADR-003 F3).

Profile-level identity visibility knobs (`Profile.identity_visibility_surface` and `Profile.identity_visibility_kink` per ADR-007 D1's field-set-growth note) take values from a 4-tier enum:

| Tier | Audience |
|---|---|
| `public` | Anyone, no login required |
| `vouched` | Any vouched User (kb-m69 D4) |
| `friends` | Mutually-Connected Users only (D1 of this ADR, accepted status) |
| `private` | Only the user themselves |

Tier ordering is **monotonic**: a higher tier's audience is a strict superset of a lower tier's. No special-case visibility rules at query time.

Default knob values (unchanged from kb-m69 D3):
- Surface identity → `public`
- Kink identity → `vouched`

**Counter-argument (FIRM-path):** The alternative "keep 3-tier from kb-m69 D3" is the safer minimal extension and the path of least resistance. Counter: D1 of this ADR introduces a natural mid-tier between `vouched` and `private`; *not* surfacing it as a visibility knob wastes D1's primary identity-disclosure value. Mutual Connection's whole value proposition for identity disclosure is "things I'd show people I personally know but not the broader vouched circle"; without `friends`, that target is unreachable. So the 3-tier alternative isn't safer — it's incoherent given D1.

**Rationale:**
- `direct:` kb-fx9 D4 — adding Connection creates a natural mid-tier; surfacing it is the consistent application of D1.
- `reasoned:` Monotonic ordering avoids special-case query logic; predictable for both engineering and user mental-model.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Keep 3-tier (no `friends` value) | `reasoned:` Wastes D1's identity-disclosure value; renders Connection-acceptance UX-disconnected. |
| 5-tier (add `friends-of-friends` between `friends` and `vouched`) | `reasoned:` Transitive friendship — anti-pattern per D1 invalidation reasoning. |
| Per-field visibility knobs (FetLife-style 5 knobs, one per dimension) | `external:` kb-fx9 D1 visibility-discipline closed this off — 2-knob (Surface / Kink) is the V0 ceiling; per-field is V1+ if demand materializes. ADR-009 D2 inherits that 2-knob discipline. |

**What would invalidate this:** D1 invalidation cascades to D2 (if Connection is rarely used, `friends` tier collapses). Independent signal: even with healthy Connection use, if zero users actually set any visibility knob to `friends` value (everyone stays at `vouched` or `private`), the tier earned no discrimination value.

### D3: Friends-tier social-proof overlay on event RSVPs

**Firmness: FIRM** — depends on D1; load-bearing as the V0 social-discovery differentiation lever (kb-fx9 D7).

On any event page where the viewer can see an attendee context (per kb-m69 D5 event-visibility tier + kb-fx9 D14 RSVP-visibility), the RSVP surface includes a **named-friends-going overlay**: *"Anna and 2 others (your Connections) are going"* — surfaces accepted-status Connections (D1) who have RSVPed to the event.

Connection-acceptance constitutes consent for the connected User to see your RSVP visibility, regardless of your per-RSVP `hide me from attendee list` setting. Rationale: Connection is a mutual disclosure agreement; surfacing RSVP in the social-proof overlay is the *natural extension* of that agreement, and opting out of it on a per-RSVP basis defeats the overlay's purpose. Users who want to hide a specific RSVP from Connections should mark themselves "going privately" (the same per-RSVP `hide me` setting) AND optionally block the Connection from seeing that event entirely (block list — kb-svg M2 part 4).

**Counter-argument (FIRM-path):** The alternative "no social-proof overlay" matches Lu.ma's pattern (zero friend-graph signal in their Discover surface) and reduces UI surface. Counter: kb-fx9 D7 identified friend-graph-driven event discovery as the V0 differentiation lever precisely *because* none of Partiful / Lu.ma / FetLife surface this. Removing the overlay collapses kb-fx9 D7's "For You" feed value proposition; the project's social-discovery V0 thesis depends on D3 here.

**Rationale:**
- `direct:` kb-fx9 D7 — Network RSVPs signal is the V0 differentiator; D3 here is the user-facing surface.
- `external:` Scout findings — friend-graph-driven event discovery is the gap modern event platforms left.
- `reasoned:` Vouchers / vouchees are NOT surfaced in this overlay (only Connections are). Vouch graph feeds For-You *ranking* (kb-fx9 D7) — internal scoring, bounded-strata per D4 below — but does not surface named in the public overlay. Vouching is reputation-private; Connection is mutual disclosure.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| No social-proof overlay | `reasoned:` Collapses kb-fx9 D7 differentiation; project's V0 thesis loses its named UI surface. |
| Vouchers/vouchees also named in overlay | `reasoned:` Leaks reputation-stake into a public-attention surface; vouching is private. Use ranking-signal-only. |
| Friends-of-friends shown in overlay | `reasoned:` Transitive disclosure without consent — D1 anti-pattern. |
| Show count only ("3 friends going"), not names | `reasoned:` Loses the trust-cue value ("I'd go if Anna's going"). Count-only is a degraded version of the differentiator. |

**What would invalidate this:** Pattern where users opt out at high rates (e.g., >20% of Connections explicitly block social-proof on their RSVPs) signals the overlay wasn't wanted. Less obvious signal: D3 overlay always shows zero friends-going for >50% of vouched users — means the Connection graph isn't dense enough to populate the surface, which feeds back to D1 invalidation.

### D4: Anti-engagement ranking principle (no global popular feed; engagement bounded within strata)

**Firmness: FLEXIBLE** — added 2026-05-20 per kb-4pj `/brainstorm` → `/adversarial-review` (verdict:pass) → `/adr-write` chain. FLEXIBLE rather than FIRM because the decision binds an unshipped surface (kb-fx9 D7 feeds); a substantive real-world observation (e.g., cold-start Discover failure for 6+ months across multiple user cohorts) is sufficient warrant to mutate. Substrate motivation is strong external prior art (FetLife critique digest) + V0-clear product conviction, but dogfooding signal is zero per ADR-012 D6.

No platform discovery surface ever computes a global engagement-optimized ranking across all content. Engagement signals (RSVPs, follows, attendance, reactions) are permitted **only within bounded strata**; aggregation across strata into a single global ranking is structurally not done. Concretely:

- **(a) Hard absence of a global-popular feed.** No unified "popular" / "trending" / "top across Switch Berlin" feed is permitted alongside or inside the kb-fx9 D7 three-feed architecture (Following / For-You / Discover). The absence is the load-bearing structural constraint — without it, the architecture's three-feed shape is decorative, not protective.
- **(b) For-You ranking bound.** The ranking referenced in D3 (Vouch + Connection signals feeding For-You internal scoring per kb-fx9 D7) operates only on bounded-strata inputs. The specific signal sources for For-You remain EXPLORATORY per kb-fx9 D7 (pending kb-2ve Sub-Q1 platform-positioning brainstorm), but no formulation may route cross-strata engagement aggregation into For-You ranking.
- **(c) Discover ranking bound.** Discover (the "outside your network" feed per kb-4pj D2) uses stratified sampling with bounded engagement signal within strata. The specific strata dimensions (geographic / categorical / organizer / temporal / kink-type / other) and the generator mechanism are EXPLORATORY (kb-4pj D4 and D7); the *posture* (no global aggregation) is what's bound here.

**Counter-argument (FLEXIBLE-path):** The alternative is to allow global engagement signals as one input among many in ranking — let the implementing engineer decide weights per-surface, treating "no monoculture" as documentation rather than substrate. Counter: this is the FetLife K&P-shape failure mode. K&P never claimed to be engagement-only; engagement was one signal weighted among many in a global ranking, and the demographic-skew feedback loop emerged anyway (popular → more views → more popular → demographic concentration). The structural absence of a global-popular surface is the only design that survives implementation drift; allowing it "as one input among many" is the path that leads to the K&P shape via incremental re-weighting. FLEXIBLE rather than FIRM acknowledges that a real-world observation (Discover too sparse to be useful) could legitimately re-open this — but a hypothetical "users want trending" without that signal is not sufficient warrant.

**Rationale:**
- `external:` FetLife critiques (Maymay 2011 "FetLife Considered Harmful," Lunas 2013 "Got Consent? III: FetLife Doesn't Get It," Atlantic 2015, Frisky Fairy 2015, Maymay 2015 Creep List) — global engagement optimization reproduces demographic-skew monoculture. Full citation chain in `history/fetlife-critique-digest.md`. Most pointed datum: Maymay 2015 cross-reference showing ~73% male paying-customer base reproducing the FetLife "Kinky & Popular" demographic surface.
- `direct:` kb-4pj D1 + D2 (Land discovery posture) — user-confirmed posture from `/brainstorm` session, `/adversarial-review` verdict:pass after one-round fold-in.
- `reasoned:` Bounded-strata engagement preserves the relevance signal users actually want (what's popular in *my* scene segment) without producing the cross-scene feedback loop. The structural commitment is to never compute a single global ranking; what counts as a stratum is left FLEXIBLE / EXPLORATORY per kb-4pj D4 (resolved per-implementation in kb-fx9 / descendants).

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Allow global engagement signals as one input among many in ranking | `external:` FetLife K&P feedback loop per critique digest; the "one input among many" framing is exactly how K&P happened — engagement was never the only signal, it was weighted-but-not-sole and the optimization loop pulled toward demographic concentration. |
| Anti-engagement absolute (no engagement signal anywhere, structural rotation only) | `reasoned:` engagement-within-strata is useful for surfacing genuinely relevant content within the scope a user has selected; eliminating engagement entirely produces a feed that feels mechanical and assumes structural categories alone capture relevance, which they don't. |
| Diversity floor (positive constraint with demographic quotas across surfaces) | `reasoned:` operationalizing "diversity" via quotas requires choosing canonical axes (gender, sexuality, race, body, age, kink-type) and assigning weights — itself a contested editorial act that creates a different monoculture risk (the platform's chosen diversity definition becomes canonical). |
| Allow global "popular" feed but mark it opt-in | `reasoned:` opt-in doesn't break the feedback loop — once the surface exists, its computation runs platform-wide regardless of who views it; the K&P demographic skew shows up the moment the signal is computed. The hard absence is what makes the posture load-bearing. |
| Cap any single organizer/category at X% of a global-popular surface | `reasoned:` does not solve monoculture, only fragments it; the platform still computes a global ranking, just with a post-hoc fairness filter applied. The K&P feedback loop runs underneath. |

**What would invalidate this:** A pattern where bounded-strata engagement is insufficient for cold-start discovery (e.g., 6+ months of Discover usage shows new users never finding events outside their immediate network across multiple cohorts) AND an explicit decision to accept K&P-shape risk for some user segment as a trade for cold-start UX. Either signal alone is insufficient — the K&P risk is the structural concern, not a soft preference. Less obvious signal: a real-world implementation discovers that "bounded strata" is not operationalizable at our scale (strata are either so coarse they're effectively global, or so fine they produce no signal), in which case D4 reformulates (e.g., to "engagement signals are user-explicit-only" or "engagement is time-bounded only") rather than dies.

## Consequences

### Direct

- New table `Connection(initiator, receiver, status, requested_at, accepted_at, declined_at)` with bidirectional uniqueness constraint.
- Visibility-tier enum for `Profile.identity_visibility_surface` and `Profile.identity_visibility_kink` extends from 3 to 4 values (adds `friends` between `vouched` and `private`); migration is additive enum value.
- Event RSVP-list query adds a Connection-JOIN to fetch "named friends going" for the viewer; small JOIN on accepted-Connection rows.
- D4 binds the kb-fx9 D7 feed-ranking surface to bounded-strata signal only; no global engagement aggregation. Future feed implementations in kb-fx9 / descendants cite D4 as the constraint on signal scope. No new schema is implied by D4 itself — the bound is on aggregation queries, not on signal capture (per-event/per-organizer denorm aggregates from ADR-003 F8 remain unchanged).

### Carried forward

- ADR-007 D1 (unified Profile) holds; Connection is sibling to Follow, not subordinate to Profile schema.
- ADR-007 D6 (unified Follow) holds; Connection is the third orthogonal graph alongside Follow + Vouch.
- ADR-001 D1 (curated-trust) holds; Connection is a low-stakes signal *alongside* curation, not replacing it.
- ADR-006 D1 (Art. 9 consent for special-category data) — D2 `friends` tier acceptance flow is itself the consent vehicle for the connected User to see disclosed identity at that tier; no separate consent form needed at Connection-accept time, but the accept-UX must surface the disclosure implication.

### Risk

- Connection sits orthogonally to existing trust graphs (Follow + Vouch); risk that users confuse the three. Mitigation: distinct UX vocabulary ("Follow X" vs "Vouch for Y" vs "Connect with Z") and admin-curated explanation in the onboarding flow.
- D3 social-proof overlay creates implicit visibility upgrade (your RSVP becomes visible to Connections in a UI surface). Consent comes from D1 Connection-acceptance, not per-RSVP — must be clear in the connect-accept UI ("connected users will see when you're going to the same events").

## canonical_refs

- [ADR-007 D1 + D6](ADR-007-profile-centric-schema.md) — Profile + Follow substrate this ADR extends; Connection is sibling to Follow.
- [ADR-001 D1](ADR-001-core-product-and-stack.md) — curated-trust posture; Connection is a lower-stakes signal alongside curation, not replacing.
- [ADR-002 D4](ADR-002-phased-rollout-and-legal-gate.md) — bans native 1:1 DMs pre-1.0; D1 of this ADR ships graph-only at V0; DM-bypass behavior lives in kb-svg until 1.0 retrospective.
- [ADR-003 F3](ADR-003-cheap-foresight-patterns.md) — Tag.kind enum extended by kb-fx9 D1; D2 visibility tiers apply to those identity-disclosure surfaces.
- [ADR-006 D1](ADR-006-legal-gate-execution.md) — Art. 9 consent for special-category data; D2 `friends` tier accept-UX is the consent vehicle for connected-User disclosure.
- [ADR-008 D1](ADR-008-code-posture-refactor-hard-fail-loud.md) — per-decision predicates; this ADR's decisions all carry firmness + rationale + alternatives + invalidation.
- `kb-fx9` (Ship social foundation) — bead-substrate D3, D4, D7 that this ADR canonicalizes. D4 of this ADR binds kb-fx9 D7's three-feed ranking surface to bounded-strata signal.
- `kb-m69` (Identity / trust / visibility-tier substrate) — D3 (3-tier visibility) extended here to 4-tier; D6 vouching is orthogonal trust graph.
- `kb-svg` (Defer native messaging) — deferred design home for Connection's DM-bypass behavior (M1, M2); D1 of this ADR ships graph-only V0 because of kb-svg's deferral.
- `kb-4pj` (Land discovery posture) — `/brainstorm` + `/adversarial-review` (verdict:pass) substrate that motivated D4 of this ADR. Acceptance contract on kb-4pj is satisfied by this revision.
- `kb-2ve` (Long-term platform vision brainstorm — Sub-Q1 platform-positioning) — open dependency; resolution may narrow kb-fx9 D7's For-You signal sources (D4 (b) above) but does not invalidate D4's posture.
- [ADR-003 F8](ADR-003-cheap-foresight-patterns.md) — denormalized per-event/per-organizer aggregates pattern; D4 of this ADR adds the posture that no global cross-strata rollup is computed on top.
- [ADR-012 D6](ADR-012-substrate-thick-process-thin.md) — dogfooding bar; cited in D4's FLEXIBLE-firmness rationale (decision binds an unshipped surface; substantive observation is sufficient warrant to mutate).
- [ADR-013 D3](ADR-013-memory-layer-architecture.md) — firmness-governed mutation rule; D4 firmness path is FLEXIBLE per this ADR.
- `history/scout-features-switch-berlin-2026-05-18.md` — FetLife / Diversia / Bluesky / Partiful / Lu.ma scout grounding the modern-platform-pattern comparison in D1 rationale.
- `history/fetlife-critique-digest.md` — synthesized digest of FetLife critique sources (Bandana Blog 2015, Disrupting Dinner Parties / Lunas 2013, Maymay 2011 + 2015, Atlantic 2015, Frisky Fairy 2015, Sex and the 405 2012) grounding D4's external-evidence warrants.

## Open questions deferred

| Question | Resolution path |
|---|---|
| DM-gating via Connection | Lives in kb-svg M1/M2; revisits when ADR-002 D4 evolves at 1.0 retro. |
| Per-field identity visibility knobs (5 knobs vs 2-knob discipline) | kb-fx9 D1 — defer to V1+ if user demand surfaces. |
| Connection-strength / "close friends" sub-tier | Defer; YAGNI until users ask. Cheap-foresight cost is zero (binary accepted-status now; add a strength field later). |
| Connection request rate-limiting / spam mitigation | Defer; if cold-Connection-spam materializes, add per-User send-rate-limit. |
