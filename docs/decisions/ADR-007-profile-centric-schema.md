# ADR-007: Profile-centric schema — unify Organizer/Facilitator, defer Festival

**Status:** Accepted 2026-05-11
**Parent:** [ADR-001 D8 normalized schema from day 1](ADR-001-core-product-and-stack.md)
**Scope:** event/profile/venue data model — Phase 0.5+ schema. Extends ADR-001 D8 to cover real event shapes that the V0 schema can't express.

## Context

The V0 schema per ADR-001 D8 modeled `Event` with a single FK to `Organizer` and no facilitator concept. Real events in the kink scene surface three shapes the schema cannot express cleanly:

1. **Facilitators distinct from organizers.** Lavinia teaches a "Silent Hunger" workshop *organized by* IKSK. She isn't IKSK; she's a human facilitator with her own following, bio, and pronouns. Currently she can only live in the description string.
2. **Co-organizers.** "IKSK × KACHENKA presents…" is common. `Event.organizer` as a single FK forces an artificial primary and hides the other.
3. **Multi-facilitator festivals.** Xplore Berlin has one organizer (IKSK) but ~20 presenters across 5 days. Currently unrepresentable except as free text.

These gaps are user-visible on `switch.berlin/events/` today (e.g. the event drawer shows organizer but no facilitator), and they affect followability — users want to follow Lavinia, not just IKSK.

## Decisions

### D1: Unified `Profile` model with `kind` discriminator

**Firmness: FIRM** — load-bearing for everything downstream; revisitable only if a third actor kind (e.g. `sponsor`, `venue_operator`) forces structural split.

Replace `Organizer` with `Profile` (`kind="person"|"collective"`). One table, one slug namespace, one follow mechanism, one claim mechanism. The field set is the superset of what either kind needs.

```
Profile(
  kind: "person" | "collective",
  name, slug, description, avatar, website,
  telegram_link,                         # both kinds: person's TG channel OR collective's TG channel
  pronouns,                              # mostly persons but optional for either
  claimed_by: FK(User, null=True),       # see D5
  claimed_at,
  status, verified_badge, approved_at, approved_by,
  consent_recorded_at, consent_method, consent_notes,   # carried from Organizer (ADR-006 D2)
  hidden, follower_count, avg_rating, rating_count,
)
```

**Rationale:** A unified table preserves a single follow/claim/badge/moderation system. The kink scene's real actors don't cleanly split into "humans" and "orgs" — Lavinia may also run her own play parties, IKSK is fronted by a small group of named humans. Forcing two models duplicates code; forcing them apart with separate `Person` and `Organizer` creates sync pain when the same User claims both. One model with `kind` discrimination keeps the option to merge or split per-kind UX without schema churn.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Unified `Profile` with `kind` (chosen)** | One follow/claim system; one slug namespace; cheap to evolve | "kind" fields scattered (pronouns mostly-but-not-always for persons) |
| Separate `Person` + keep `Organizer` | Each model carries only its own fields | Two follow tables; sync when same user claims both; two slug namespaces; user-facing "is this a person or a collective?" leaks into URLs |
| `Profile` abstract base, `PersonProfile` + `CollectiveProfile` subtables | Django multi-table inheritance gives polymorphism | Joins on every query; querysets across types are awkward; community fields (follow, rating) need generic FKs |
| Keep `Organizer`, add `kind` field | Smallest migration | "Organizer" name misleading for a facilitator who doesn't organize anything |

**Field-set growth within `kind` (kb-fx9 D1, 2026-05-19):**

`Profile.kind=person` carries additional structured-identity data via a join model `ProfileTag(profile, tag, intensity nullable, note CharField blank, created_at)` for tags of `kind ∈ {gender, role, orientation, kink, not_looking_for}` (see ADR-003 F3 for the Tag.kind enum extension and intensity semantics). Person Profiles also carry two visibility-tier fields (`identity_visibility_surface`, `identity_visibility_kink`) governing who sees which subset of identity data; collective Profiles ignore both fields. This is field-set growth *within* a `kind`, not a structural split — D1's "third actor kind forcing structural split" invalidation trigger does not fire. The unified-Profile decision-property is unchanged.

### D2: Two through-tables for Event ↔ Profile relations (organizer + facilitator)

**Firmness: FIRM** for the split organizer/facilitator; FLEXIBLE on whether to consolidate later.

```
EventOrganizer(event, profile, is_primary: bool, order: int)
   # at most one is_primary per event (partial unique constraint)
   # ergonomic accessor: event.primary_organizer

EventFacilitator(event, profile, role: str, order: int)
   # role is free text: "Lead", "Co-facilitator", "DJ", "Doula", "Host", …
```

`Event.organizers = M2M(Profile, through=EventOrganizer)` and `Event.facilitators = M2M(Profile, through=EventFacilitator)`. The same Profile can appear in both for the same Event (Lavinia organizes her own workshop AND leads it).

**Rationale:** Querying "events organized by X" vs "events facilitated by X" is a frequent UX need (profile page tabs, search filters). Separate tables keep queries ergonomic (`Event.objects.filter(organizers=p)` vs `filter(facilitators=p)`). A single polymorphic `EventProfile(event, profile, role)` table is more compact but makes every query do `WHERE role='organizes'` and obscures the semantic distinction between "legal/financial responsibility" (organizer) and "leads the activity" (facilitator).

### D3: Festivals are single Events with many facilitators — no separate Festival entity for V0

**Firmness: FIRM for V0** — revisit if a festival arrives that genuinely needs per-workshop ticketing.

Xplore Berlin = one `Event` row with a 5-day duration, many facilitators, IKSK as primary organizer. The festival's internal schedule lives on its external website; Switch.berlin doesn't model the per-workshop schedule because **attendees register for the whole festival, not individual workshops**. If a future festival sells per-workshop tickets, add `parent_event = FK("self", null=True)` then and migrate sub-events into it. Until that pressure exists, the schema stays lean.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Single Event row with many facilitators (chosen)** | All existing Event UI works; no new model; zero schema risk | Can't model per-workshop ticketing/attendance until split |
| Self-FK on Event (`parent_event`) | Festivals + sub-events both queryable as Events | Adds complexity for zero current benefit; "is this a festival container?" check pollutes every feed query |
| Separate `Festival` model | Clean concept boundary | Feed/search/attendance span two models; new FestivalAttendance; more code now for speculative future |

### D4: "Host" disambiguation is deferred

**Firmness: FLEXIBLE**

"Host" has three plausible meanings in the kink scene: (a) synonym for organizer ("hosted by IKSK"), (b) public-facing MC/vibe-setter at the event, (c) house-host whose home a private party is at. All three exist. For V0:

- (a) maps to `EventOrganizer.is_primary` (the "hosting organizer")
- (b) maps to `EventFacilitator.role="Host"` (no new entity)
- (c) deferred entirely (probably belongs on `Venue.host_profile` when it arrives)

Revisit if a UX need forces disambiguation between these three.

### D5: Profiles are claimable via `ProfileClaim` through-model (multi-claimant) — *evolved in place 2026-05-21*

**Firmness: FIRM** — mirrors ADR-001 D1 curated-trust model. Decision-property "Profiles are claimable" unchanged since the original (2026-05-11) version; cardinality evolved from 0..1 (single-FK) to 0..N (through-model) to accommodate co-organized collectives. Original wording preserved in git history.

`Profile.claimants = M2M(User, through="ProfileClaim")` where `ProfileClaim(profile, user, verified_at, verified_method, verified_by_admin, role, created_at)`. A Profile is created without any claims (curated by us during ingestion or admin-side); the named human or admin can later claim/manage their page after signing up. Lavinia gets a Profile from day one whether or not she's a Switch.berlin user; if she signs up and claims it, she joins `claimants`. Collectives like IKSK accumulate multiple claims (one per co-organizer). `Profile.is_claimed` (= `claimants.exists()`) is the binary gate that gated `claimed_by IS NOT NULL` previously.

**Rationale:** matches the existing organizer-curation flow (we already create Organizer rows without User links). One mechanism handles "claim my page" for both kinds. The multi-claimant cardinality acknowledges that collectives (the dominant kink-scene actor type after individual facilitators) are co-organized by definition — IKSK is fronted by ~3 humans, not one. The verification metadata (`verified_at`, `verified_method`, `verified_by_admin`) on the through-model is load-bearing for the audit trail required by ADR-006 (legal gate) and ADR-001 D1 (curated-trust), which a plain M2M would lose.

**Note:** Claim *flow* (web-first entry, two-track verification, magic-link envelope) is canonicalized in [ADR-014](ADR-014-profile-claim-flow.md), which builds on this schema substrate.

### D6: One unified `Follow(user, profile)` table

**Firmness: FIRM**

Replaces `OrganizerFollow`. Users follow Profiles regardless of kind. `Profile.follower_count` aggregates from `Follow` rows; existing `OrganizerFollow` rows migrate into `Follow`.

## Consequences

### Direct
- `Organizer` model renamed to `Profile`; existing rows migrate with `kind='collective'`.
- `Event.organizer` FK migrates to `EventOrganizer(is_primary=True)` rows; FK then dropped.
- `OrganizerFollow` rows migrate to `Follow(user, profile)`; old table dropped.
- New: `EventOrganizer`, `EventFacilitator`, `Follow`, `Profile`.
- Django app `organizers/` is renamed (or its internals are renamed). URL `/organizers/{slug}/` redirects to `/p/{slug}/`.

### Carried forward
- ADR-001 D8 "normalized from day 1" still holds, extended.
- ADR-006 D2 organizer legitimate-interest LIA continues to apply (now per-Profile-of-kind=collective).
- ADR-001 D1 curated-trust model continues — Profiles have `status=candidate|approved|suspended`.

### Risk
- Migration touches many code paths (admin, ingestion, templates, views, tests). Plan as an epic with shippable child beads (see kb-???); each child preserves the system at every step (no half-state).
- `Profile.kind` discriminator must be enforced at write time — admin/ingestion needs to set it explicitly; defaults could mask bugs.

## Open questions deferred

| Question | Resolution path |
|---|---|
| Festival sub-events / per-workshop ticketing | Add `parent_event` self-FK when first festival needs it. |
| Person ↔ Organizer overlap (Lavinia also organizes solo events) | Two separate Profile rows for now; add `Profile.represented_by` cross-link if pain emerges. |
| House-host for private play parties | Probably `Venue.host_profile` FK; model when private-party UX surfaces. |
| Additional `kind` values (`sponsor`, `venue_operator`) | Extend `kind` choices when concrete UX surfaces. |
