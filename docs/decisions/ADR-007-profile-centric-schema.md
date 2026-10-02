# ADR-007: Profile-centric schema — one Profile for organizers and artists, defer Festival

**Status:** Accepted 2026-05-11 (D5 revised 2026-05-21; revised 2026-10-02 — D2 facilitator → artist with name-text credits, D3/D4 wording, D5 claimants → managers; D7–D9 added — identity vocabulary, venues, organizer attribution)
**Parent:** [ADR-001 D8 normalized schema from day 1](ADR-001-core-product-and-stack.md)
**Scope:** event/profile/venue data model — Phase 0.5+ schema. Extends ADR-001 D8 to cover real event shapes that the V0 schema can't express.

## Context

The V0 schema per ADR-001 D8 modeled `Event` with a single FK to `Organizer` and no facilitator concept. Real events in the kink scene surface three shapes the schema cannot express cleanly:

1. **Facilitators distinct from organizers.** Lavinia teaches a "Silent Hunger" workshop *organized by* IKSK. She isn't IKSK; she's a human facilitator with her own following, bio, and pronouns. Currently she can only live in the description string.
2. **Co-organizers.** "IKSK × KACHENKA presents…" is common. `Event.organizer` as a single FK forces an artificial primary and hides the other.
3. **Multi-facilitator festivals.** Xplore Berlin has one organizer (IKSK) but ~20 presenters across 5 days. Currently unrepresentable except as free text.

These gaps are user-visible on `switch.berlin/events/` today (e.g. the event drawer shows organizer but no facilitator), and they affect followability — users want to follow Lavinia, not just IKSK.

*Vocabulary note (2026-10-02):* the context above keeps its 2026-05 wording. Since 2026-10-02 the person credited on an event is an **artist**, and "facilitator" is retired in that sense (D7). The decisions below use the current words.

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
  # managers: see D5 (ProfileClaim through-model)
  status, approved_at, approved_by,      # verified mark: computed, ADR-014 D4
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
| Keep `Organizer`, add `kind` field | Smallest migration | "Organizer" name misleading for an artist who doesn't organize anything |

**Field-set growth within `kind` (sb-fx9 D1, 2026-05-19):**

`Profile.kind=person` carries additional structured-identity data via a join model `ProfileTag(profile, tag, intensity nullable, note CharField blank, created_at)` for tags of `kind ∈ {gender, role, orientation, kink, not_looking_for}` (see ADR-003 F3 for the Tag.kind enum extension and intensity semantics). Person Profiles also carry two visibility-tier fields (`identity_visibility_surface`, `identity_visibility_kink`) governing who sees which subset of identity data; collective Profiles ignore both fields. This is field-set growth *within* a `kind`, not a structural split — D1's "third actor kind forcing structural split" invalidation trigger does not fire. The unified-Profile decision-property is unchanged.

### D2: Two through-tables for Event ↔ Profile relations (organizer + artist) — *evolved in place 2026-10-02*

**Firmness: FIRM** for the split organizer/artist (unchanged); FLEXIBLE on whether to consolidate later (unchanged). The rename and the name-text credit were confirmed by the human on 2026-10-02 ("yes on the ADR", brain:sb-7wzb's pane, covering sb-x5xh.3 as written). The original 2026-05-11 wording (`EventFacilitator(event, profile, role, order)`) is in git history.

```
EventOrganizer(event, profile, is_primary: bool, order: int)
   # at most one is_primary per event (partial unique constraint)
   # ergonomic accessor: event.primary_organizer
   # attribution provenance (explicit | publisher): D9

EventArtist(event, profile NULL, name: str, role: str, order: int)
   # an artist credit is a display name, optionally linked to a Profile
   # role is free text ("Lead", "DJ", "Doula", "Host", …); kept, not displayed
```

`Event.organizers = M2M(Profile, through=EventOrganizer)`. An artist credit is a **display name, optionally linked to a Profile**; the link is set only by the event's organizer managers or staff, never inferred and never claimed by the artist (D7). The same Profile can appear as organizer and as linked artist on the same Event (Lavinia organizes her own workshop AND leads it). The screen says "Organized by" and "Artists" — the same words as the code.

Renamed from `EventFacilitator` (2026-10-02) so code and screen share one word; "facilitator" is retired in the event-role sense. *Code catches up in sb-x5xh.4* (today's code still has `EventFacilitator` with a required `profile`).

**Rationale:** Querying "events organized by X" vs "events where X is an artist" is a frequent UX need (profile page tabs, search filters). Separate tables keep queries ergonomic. A single polymorphic `EventProfile(event, profile, role)` table is more compact but makes every query do `WHERE role='organizes'` and obscures the semantic distinction between "runs it and may edit" (organizer — ADR-017 D1) and "credited on the program" (artist).

**Why the 2026-10-02 change (counter-argument to the original wording):** the original rationale assumed every credited person is a Profile. The collector (Track A) reads names off posts and flyers for people who are often private individuals with scene names; making a Profile for each would build public pages about people without their consent and merge different people who share a name (`external:` Bandcamp's unmergeable duplicates). A nullable `profile` plus `name` keeps the credit without the page. "Facilitator" was also a word the screen never used and that Track B uses for organizers — two meanings for one word. The split itself (controller vs credit) still holds, so it stays FIRM.

**Alternatives (2026-10-02 rename):**

| Alternative | Why rejected |
|---|---|
| Flat "Hosted by" list, one table (Luma) | `reasoned:` blurs who can edit; a second flag would rebuild the split. `direct:` the human wanted runs-it vs on-the-program distinguishable (sb-x5xh.2). |
| Keep `EventFacilitator` in code, show "Artists" on screen | `direct:` the human rejected it (sb-x5xh.2) — three words for two things. |
| Rename organizer to "host" instead (Host · Artist · Venue) | `reasoned:` "organizer" is in ~200 files plus the legal basis (ADR-006 D2 LIA); the warmer word is not worth rewriting compliance prose. |
| Artist credit requires a Profile (keep `profile` NOT NULL) | `reasoned:` forces public pages for private people; auto-created artist profiles are parked behind a legal review (sb-7wzb.17). |

**What would invalidate this:** an organizer needs a listed co-organizer who must NOT edit (ADR-017 D1's own path); or legal review (sb-7wzb.17) finds even text-only artist credits need a different basis.

### D3: Festivals are single Events with many artists — no separate Festival entity for V0

**Firmness: FIRM for V0** — revisit if a festival arrives that genuinely needs per-workshop ticketing. (Wording only, 2026-10-02: "facilitators" → "artists", confirmed by the human 2026-10-02; the decision is unchanged.)

Xplore Berlin = one `Event` row with a 5-day duration, many artists, IKSK as primary organizer. The festival's internal schedule lives on its external website; Switch.berlin doesn't model the per-workshop schedule because **attendees register for the whole festival, not individual workshops**. If a future festival sells per-workshop tickets, add `parent_event = FK("self", null=True)` then and migrate sub-events into it. Until that pressure exists, the schema stays lean.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Single Event row with many artists (chosen)** | All existing Event UI works; no new model; zero schema risk | Can't model per-workshop ticketing/attendance until split |
| Self-FK on Event (`parent_event`) | Festivals + sub-events both queryable as Events | Adds complexity for zero current benefit; "is this a festival container?" check pollutes every feed query |
| Separate `Festival` model | Clean concept boundary | Feed/search/attendance span two models; new FestivalAttendance; more code now for speculative future |

### D4: "Host" disambiguation is deferred

**Firmness: FLEXIBLE** (wording evolved in place 2026-10-02, announce-and-proceed; the human's 2026-10-02 "yes on the ADR" also covers it)

"Host" has three plausible meanings in the kink scene: (a) synonym for organizer ("hosted by IKSK"), (b) public-facing MC/vibe-setter at the event, (c) house-host whose home a private party is at. All three exist. For V0:

- (a) maps to an organizer (`EventOrganizer`; the collector treats "hosted by" as explicit organizer wording, D9)
- (b) maps to an artist credit, `EventArtist.role="Host"` (no new entity)
- (c) a private-party address is a **private venue** (`Venue.privacy_mode="private"`), optionally run by a Profile via `Venue.run_by`. It is never a location note: a location note never carries a street address (D8). No house-host Profile is created.

The reserved `Venue.host_profile` seam of the 2026-05-11 wording became `Venue.run_by` (one profile runs many venues; built in sb-x5xh.6).

Revisit if a UX need forces disambiguation between these three.

### D5: Profiles are claimable via `ProfileClaim` through-model (many managers) — *evolved in place 2026-05-21; wording 2026-10-02*

**Firmness: FIRM** — mirrors ADR-001 D1 curated-trust model. Decision-property "Profiles are claimable" unchanged since the original (2026-05-11) version; cardinality evolved from 0..1 (single-FK) to 0..N (through-model) to accommodate co-organized collectives. 2026-10-02: the accessor `Profile.claimants` is renamed `Profile.managers` — confirmed by the human on 2026-10-02 ("yes on the ADR", covering sb-x5xh.3). The `ProfileClaim` model name and the decision-property are unchanged; "claim" now names only the act of becoming a manager (D7). Original wording preserved in git history. *Code catches up in sb-x5xh.5* (today's code still says `claimants`).

`Profile.managers = M2M(User, through="ProfileClaim")` where `ProfileClaim(profile, user, verified_at, verified_method, verified_by_admin, role, created_at)`. A Profile is created without any managers (curated by us during ingestion or admin-side); the named human or admin can later claim the page after signing up and so become its manager. Lavinia gets a Profile from day one whether or not she's a Switch.berlin user; if she signs up and claims it, she joins `managers`. Collectives like IKSK accumulate multiple managers (one per co-organizer). `Profile.is_claimed` (= `managers.exists()`) is the binary gate that gated `claimed_by IS NOT NULL` previously.

**Why "manager" (2026-10-02):** "claimant" named the person after the act they once did, not the role they now hold; the screen and the scene say "manages this profile". Counter-argument considered: the old word matched the model name `ProfileClaim`. It still does for the act — the model records claims — but the accessor names the people, so it takes the role word. Rejected alternatives: "owner" (`reasoned:` implies one person and the hostage-admin problem Meta Pages show, `external:` sb-x5xh.2 research digest); "admin" (`reasoned:` collides with staff admin and with `ProfileClaim.role="admin"`).

**Rationale:** matches the existing organizer-curation flow (we already create Organizer rows without User links). One mechanism handles "claim my page" for both kinds. The multi-claimant cardinality acknowledges that collectives (the dominant kink-scene actor type after individual organizers and artists) are co-organized by definition — IKSK is fronted by ~3 humans, not one. The verification metadata (`verified_at`, `verified_method`, `verified_by_admin`) on the through-model is load-bearing for the audit trail required by ADR-006 (legal gate) and ADR-001 D1 (curated-trust), which a plain M2M would lose.

**Note:** Claim *flow* (web-first entry, two-track verification, magic-link envelope) is canonicalized in [ADR-014](ADR-014-profile-claim-flow.md), which builds on this schema substrate.

### D6: One unified `Follow(user, profile)` table

**Firmness: FIRM**

Replaces `OrganizerFollow`. Users follow Profiles regardless of kind. `Profile.follower_count` aggregates from `Follow` rows; existing `OrganizerFollow` rows migrate into `Follow`.

### D7: Identity vocabulary — Account · Profile · Manager · Claim; Organizer · Artist · Venue — and five foresight rules (added 2026-10-02)

**Firmness:** the **vocabulary is FIRM** (confirmed by the human 2026-10-02, "yes on the ADR", covering sb-x5xh.3); the **five rules are FLEXIBLE** (cheap foresight per ADR-003 — shape and naming now, nothing built).

**Vocabulary — one word per thing, the same in code and on screen:**

| Word | Means | In the schema |
|---|---|---|
| **Account** | a private login | `User` |
| **Profile** | a public page, person or collective (D1). Every account has exactly one personal profile. | `Profile` |
| **Manager** | an account that manages a profile; a profile has many | `Profile.managers` via `ProfileClaim` (D5) |
| **Claim** | only the act of becoming a manager: automatic at signup for your own personal profile, verified when someone else created the profile (ADR-014 D2) | a `ProfileClaim` row records it |
| **Organizer** | a profile that runs an event; its managers may edit it (ADR-017 D1) | `EventOrganizer` (D2) |
| **Artist** | a name credited on an event; optionally linked to a profile | `EventArtist` (D2) |
| **Venue** | one physical place (D8) | `Venue` |

"Facilitator" in the event-role sense and "claimant" are retired. Organizer-sense "facilitator" in ADR-016 / ADR-019 (Track B) means **organizer**; renaming it there is Track B's, not this decision's. *Code catches up in sb-x5xh.4 (artist) and sb-x5xh.5 (manager).*

**Artist links:** only the event's organizer managers or staff link an artist name to a profile. No automatic linking; artists cannot claim a credit; no artist profiles are auto-created (parked behind the legal review sb-7wzb.17).

**Five rules (FLEXIBLE):**
1. Social features (follows, messages, posts, visible RSVPs) attach to **profiles, never accounts**. Every write records both the acting profile and the account, chosen in a visible "acting as" picker — never a hidden mode.
2. A profile **never drops to zero managers**; staff can reassign.
3. **Who manages a profile is private** by default.
4. **No business / portfolio layer** above profiles until a multi-profile organisation asks for one.
5. A claim **keeps** the profile's follows, events and history; duplicate profiles are **merged, never recreated** (staff merge: sb-7wzb.22).

**Rationale:**
- `direct:` ratified live with the human in the sb-x5xh.2 sitting (2026-10-01..02); the human plans Switch to become a social network, so the account/profile split must be right before social features land.
- `external:` login separate from the public entity, many managers per entity and per-event role links are the norm (Resident Advisor, GitHub orgs, LinkedIn Pages, Eventbrite, Luma, ActivityPub actors); schema.org Event's organizer / performer / location maps to Organizer / Artist / Venue (sb-x5xh.2 research digest).
- `external:` the five rules each answer a documented failure: Meta Pages' admin bound to one login (orphaned pages → rule 2), modal "switch into Page" acting as the wrong identity (→ rule 1), stacked business layers (→ rule 4), one-way migrations that dropped follows (→ rule 5).

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Account = page (Bandcamp model) | `external:` Bandcamp pays in shared credentials and unmergeable duplicates; PayPal's 1:1 account-user coupling forced a rework. |
| Keep code words, map screen words in a glossary | `direct:` the human rejected it — three words for two things. |
| Business/portfolio layer or account types (personal/creator/business) now | `external:` Meta's renamed Business Manager/Suite/Portfolio and Instagram account types are the documented pain. |
| Artists claim their own credits | `direct:` the human: only the organizing profile or staff sets the link. |
| Auto-create or auto-link artist profiles | `reasoned:` builds public pages about private people without consent; name collisions merge different people. |

**What would invalidate this:** a real user needs social activity that belongs to the account, not any profile (signal: a feature cannot name an acting profile); or a multi-profile organisation asks for shared settings above its profiles (rule 4's own trigger); or legal review (sb-7wzb.17) rules out text-only artist credits.

### D8: A venue is one physical place, optionally run by a profile; anything else is a location note (added 2026-10-02)

**Firmness: FLEXIBLE** — ratified in the sb-x5xh.2 sitting 2026-10-02; dogfood-pending on the collector walk.

- A venue is **one physical place** (one address). A profile can run several venues: `Venue.run_by` → Profile, optional. Venues never create profiles, and a venue is not a profile kind.
- **Moving = a new venue** (the old one closed), never an address overwrite.
- **No direct venue claim.** A profile's managers manage its venues; for now linking and editing venues is staff-only (admin).
- **Not a place → location note:** free text on the event (`Event.location_note`, e.g. "Online (Zoom)", "Secret location, Mitte — shared with ticket holders"), shown where the venue would be; an event may have both. **A location note never carries a street address** — an address belongs on a venue, where `privacy_mode` applies. An event with only a note has no map pin.
- **Private-party addresses are private venues** (`privacy_mode="private"`), never location notes. The collector sets `private` when the text restricts the address (on request, ticket holders, secret) or the source is a private channel.
- Deferred until something reads them: venue open/closed and show-on-profile fields.

Built in sb-x5xh.6 (`run_by`, `location_note`) and sb-7wzb.19 (collector venues, address check on notes).

**Rationale:**
- `reasoned:` a place is not a who — making venues profiles would turn parks and private flats into public, claimable pages.
- `direct:` dev-DB spike (sb-x5xh.2): many venue strings are placeholders ("Zoom", "Berlin", "Secret location"); only 3 of 122 rows carried a street address — placeholders need a home that is not a venue.
- `reasoned:` keeping every address on a venue gives one place where privacy applies; a free-text note would leak a private address.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Venue as a profile kind | `reasoned:` a place is not a who; touches FIRM D1. |
| Direct venue claims | `reasoned:` a second claim mechanism; venues come with the profile that runs them. |
| Private-party address as a location note | `reasoned:` the address would bypass `privacy_mode` (sb-x5xh.2 post-fold item 7). |
| One-off locations as unlisted venues | `direct:` replaced in the sitting 2026-10-02 by the location note — placeholders are not places. |
| Geocode venues now (OSM) | `direct:` spike — 3 of 122 rows carry an address; name-only geocoding returned San Francisco for "Soma House Berlin". |

**What would invalidate this:** events commonly need several venues (multi-venue events, parked); or online events need their own listing behaviour that a note cannot carry.

### D9: Collected events credit the publisher as organizer unless the text names another; provenance is recorded (added 2026-10-02)

**Firmness: FLEXIBLE** — ratified in the sb-x5xh.2 sitting; provenance added by the post-fold adjudication (brain:sb-7wzb, 2026-10-02, accepted by default under the human's ruling). Dogfood-pending.

- **Organizer** = the publishing source's declared identity, unless the text explicitly names another ("organised by", "hosted by", "presented by", "Veranstalter") — then that one, and the publisher is at most the venue. **Never infer an organizer** (no fuzzy auto-link, no known-names list in the extraction prompt). One profile per name; several named organizers give several rows, the first named primary. Channel titles are not trusted as profile names; source config names the profile. Aggregator sources (a source-config flag) hold rows lacking explicit organizer wording for review.
- **Attribution provenance** on `EventOrganizer`: `explicit` (the text named it) or `publisher` (taken from the source). On a duplicate merge an explicit organizer replaces a publisher one; "different organizers never merge" applies only when both are explicit.
- Every other named person becomes an **artist credit as text**, one per name (D2, D7).

*Code catches up in sb-7wzb.18* (provenance field, organizer rule) and sb-7wzb.16 (duplicate rule).

**Rationale:**
- `direct:` spike (sb-x5xh.2): the declared payload organizer always won, so "PELVIC WORK" by Visionary Body and Telegram rows naming other people landed under IKSK; channel titles became profile names.
- `reasoned:` without provenance, every third-party IKSK event stays split between its website and Telegram copies, because one copy credits the named organizer and the other the publisher.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Infer organizers by fuzzy name match | `direct:` spike — the review band held a false positive (Haus Lebenskraft ~ Haus Lebenskunst). |
| Publisher is always the organizer | `direct:` spike — credits third-party events to IKSK. |
| No provenance field | `reasoned:` the duplicate rule cannot tell a real organizer conflict from a publisher default. |

**What would invalidate this:** real posts commonly name the organizer only implicitly, so most third-party events stay credited to the publisher; or an explicit organizer moves many third-party events to new unclaimed profiles that publish at ingest (ADR-017 D4) faster than review can follow.

## Consequences

### Direct
- `Organizer` model renamed to `Profile`; existing rows migrate with `kind='collective'`.
- `Event.organizer` FK migrates to `EventOrganizer(is_primary=True)` rows; FK then dropped.
- `OrganizerFollow` rows migrate to `Follow(user, profile)`; old table dropped.
- New: `EventOrganizer`, `EventArtist` (shipped 2026-05 as `EventFacilitator`; renamed in sb-x5xh.4), `Follow`, `Profile`.
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
| House-host for private play parties | Resolved 2026-10-02: a private venue, optionally `Venue.run_by` a Profile (D4). |
| Additional `kind` values (`sponsor`, `venue_operator`) | Extend `kind` choices when concrete UX surfaces. |

## canonical_refs

- [ADR-001 D1, D8](ADR-001-core-product-and-stack.md) — curated trust; normalized schema this ADR extends.
- [ADR-014](ADR-014-profile-claim-flow.md) — claim flow on the D5 substrate; D4 computed verified mark.
- [ADR-017 D1](ADR-017-authorization-edit-publish-policy.md) — gives the D2 split its permission meaning (organizer edits, artist is credited).
- [ADR-006 D2](ADR-006-legal-gate-execution.md) — organizer LIA; why "organizer" is not renamed.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — the D7 five rules are cheap foresight: shape now, nothing built.
- [ADR-016](ADR-016-outbound-syndication-architecture-event-post-projections.md), [ADR-019](ADR-019-agent-harness-as-a-product.md) — use "facilitator" in the organizer sense; D7 names it organizer, rename is Track B's.
- [ADR-008 D1, D3](ADR-008-code-posture-refactor-hard-fail-loud.md) — renames without shims; fail loud on a location note carrying an address.
- `sb-x5xh.2` — event-roles sitting (ruling, spike, research digest, post-fold adjudication) behind the 2026-10-02 evolution; `sb-x5xh.3` applied it; code: `sb-x5xh.4` (artist), `sb-x5xh.5` (manager), `sb-x5xh.6` (run_by, location note), `sb-7wzb.18` (organizer rule, provenance), `sb-7wzb.19` (collector venues), `sb-7wzb.16` (duplicates), `sb-7wzb.22` (staff merge); `sb-7wzb.17` legal review of artist names.
