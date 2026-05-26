# ADR-012: Event visibility tiers and access-control matrix

**Status:** Accepted 2026-05-21 (revised 2026-05-22 — D3 trusted-viewer set extracted to `settings.EVENT_VISIBILITY_TRUSTED_STATUSES` with FLEXIBLE firmness on the policy layer; D4 added for migration-backfill discipline after a lost-events incident — see D4; scope-boundary clarified 2026-05-26 — visibility is **read-side only** and does **NOT** gate outbound syndication, see Carried forward + [ADR-016](ADR-016-outbound-syndication-architecture-event-post-projections.md))
**Scope:** Per-Event visibility model — `Event.visibility` enum, source-derived defaults, viewer-tier access matrix, robot indexing semantics. Companion to ADR-009 D2 (Profile identity visibility). The sibling User trust model — `User.status` tiers, vouch graph, invite economy — is the scope of [ADR-013](ADR-013-user-trust-model.md) (kb-m69 D1 + D4 + D6 + D9 substrate); this ADR references "vouched User" as a term that ADR canonicalizes. **This ADR governs read-side rendering of an Event *on switch.berlin* only** (who sees it in listings / on its own page / via robots) — it does **NOT** gate *outbound syndication* to external platforms (FetLife / Telegram / Ticket Tailor / etc.), which [ADR-016](ADR-016-outbound-syndication-architecture-event-post-projections.md) D4/D5 governs via explicit facilitator-controlled publish. A facilitator may syndicate their own event anywhere regardless of its Switch visibility tier.

## Context

Per-Event visibility lived only in bead substrate (kb-m69 D5, "FIRM" by the brainstorm's own tag) prior to this ADR. The pre-public-flip checklist (kb-9hw — Bundle B `PUBLIC_READ_ENABLED` cutover) initially assumed a single master switch — "flip → every published Event anonymously readable" — which conflicts with kb-m69 D5's source-tier-derived semantics. Without an ADR home, the per-Event tier decision was not citable as binding, and kb-m69 itself flagged the gap (*"D5 — touches event schema, query patterns, robot indexing, UI surfaces. Probably its own ADR. Route to `/adr-write` with action `compose new ADR`."*).

ADR-009 D2 (4-tier *Profile* identity visibility — `public > vouched > friends > private`) already canonicalizes the "vouched User" audience-tier semantics for Profile-side fields. This ADR canonicalizes the *Event*-side surface that pairs with it. The two surfaces share the `vouched` audience-tier concept (the bridge term canonicalized by [ADR-013](ADR-013-user-trust-model.md)), but the tier *enums* diverge — Events have a URL-keyed `unlisted` tier that Profiles don't, Profiles have a `friends` tier that Events don't. The divergence is deliberate: Event visibility and Profile identity visibility serve different audiences and use different mechanisms.

Per the global dogfooding bar (`~/.claude/docs/decisions/ADR-012-substrate-thick-process-thin.md` D6 — note same-number-different-content collision, see Open questions deferred), the tier model is authored as **EXPLORATORY** rather than FIRM. No implementation has dogfooded the 3-tier shape; a 4-tier refinement (registered-but-not-vouched as a distinct tier between `public` and `vouched`) is a plausible evolution on real-usage signal and is preserved as D1's invalidation path.

## Decisions

### D1: 3-tier `Event.visibility` enum — `public / semi_public / unlisted`

**Firmness: EXPLORATORY** — pending dogfooding. `semi_public` semantics may split into `semi_public` (registered-but-not-vouched) + `vouched` on real-usage signal; the 3-tier shape is the minimal V0 commitment.

```
Event.visibility ∈ {'public', 'semi_public', 'unlisted'}
```

| Tier | Audience | Discoverable how | URL alone grants access? |
|---|---|---|---|
| `public` | Anyone, no login | On-site search, listings, robots-indexed, sitemap | Yes (trivially — anonymous can navigate to it) |
| `semi_public` | Any vouched User (term canonicalized by [ADR-013](ADR-013-user-trust-model.md); bead substrate kb-m69 D4) | On-site, after login as a vouched User; `noindex`, excluded from sitemap | **No** — URL alone does not bypass tier |
| `unlisted` | Anyone with the URL | URL only — not findable, not listed, `noindex` | **Yes** — URL is the capability |

On-site (non-URL) tier ordering is monotonic: `public ⊃ semi_public`. The `unlisted` tier is orthogonal — URL-keyed rather than audience-keyed — and does not fit the on-site ordering. The asymmetry is deliberate (see D3 and Alternatives).

**Rationale:**
- `direct:` kb-m69 D5 — landed the 3-tier shape after `/brainstorm` + multi-platform scout.
- `external:` FetLife's `Public / FetLifers / Private` 3-tier model (`history/scout-features-switch-berlin-2026-05-18.md`); naming maps onto our enum cleanly.
- `reasoned:` 3-tier is the minimal split that distinguishes anonymous-readable, trust-gated, and URL-keyed audiences. 2-tier (public/private) collapses the URL-keyed case, which is real for in-progress drafts and private gatherings shared via direct link.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| 2-tier (`public` / `private`) | `reasoned:` Doesn't model the "shareable by URL but not findable" case (`unlisted`), which is real for in-progress drafts and private gatherings shared via direct link. |
| 4-tier (split `semi_public` into registered-but-not-vouched + vouched-only) | `reasoned:` Adds a tier whose use case is currently theoretical; preserve as an evolution path (see invalidation). EXPLORATORY firmness on D1 allows promotion to 4-tier without supersession per ADR-011 D1. |
| Per-Event ACL list (specific Users granted access) | `reasoned:` Over-engineered for V0; the `unlisted` tier covers the "share with specific people" case via URL distribution. ACL is a V1+ extension if demand surfaces. |
| Visibility derived from Profile-tier setting alone (no per-Event field) | `reasoned:` Couples Event visibility to Organizer Profile visibility; loses the per-Event override case (an organizer with a `vouched`-tier Profile may still want to publish individual public-facing intro events). |

**What would invalidate this:** Real-usage signal that the `semi_public` tier's audience definition ("any vouched User") is too coarse — for example, legitimate intro-session events that want registered-but-not-vouched visibility (no anonymous discovery, no trust gate), or organizers consistently working around the tier by publishing `public` events that should be gated. Either signal promotes D1 to a 4-tier shape per the "4-tier" Alternative row above. A separate less-obvious signal: `unlisted` sees essentially no usage after a meaningful observation window, in which case D1 collapses to 2-tier (`public / vouched`) and the URL-keyed case migrates to a per-Event share-token field.

### D2: Source-derived `max(public)` default tier on Event creation

**Firmness: EXPLORATORY** — depends on D1. The source→tier mapping is the most likely surface to need adjustment as ingestion sources diversify.

When an Event is created via the ingestion pipeline or admin-curated import, its initial `Event.visibility` defaults to the **maximum public tier** observed across all sources for that Event. The mapping:

| Source | Default tier |
|---|---|
| Scraped from public org website | `public` |
| Public Telegram channel (broadcast) | `public` |
| Private Telegram group | `semi_public` |
| User-submitted web form | `semi_public` |
| Manual admin or organizer creation | as explicitly set; otherwise `semi_public` |

If an Event is observed at multiple sources, the maximum public tier across them wins (`public > semi_public > unlisted`). The "max" rule prevents a labeling lie — if the event is *already* public on a scraped source, defaulting to a lower tier would misrepresent its actual reach.

Organizer override: after the organizer has claimed the Profile (per [ADR-014](ADR-014-profile-claim-flow.md); bead substrate kb-m69 D1), they may set `Event.visibility` to any tier from the Event-edit page. **Manual override is always honored** and survives subsequent re-ingestion — it does not revert to source-derived default.

**Rationale:**
- `direct:` kb-m69 D5 — "max(public) wins" framed by the brainstorm.
- `reasoned:` Source provides default; organizer provides override. The schema cannot guess organizer intent on first ingest, so anchoring to source-observed reach is the least-surprising starting point.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Default all imported Events to `semi_public` (manual review required for `public`) | `reasoned:` Labeling lie when source is already public (e.g., an organizer's public calendar); forces organizer action to restore truthful default. |
| Default all imported Events to `public` (organizer must downgrade) | `reasoned:` Promotes Events from private channels into anonymous discoverability without organizer signal; high blast radius for trust-sensitive contexts. |
| Organizer sets tier on every Event manually (no derivation) | `reasoned:` Friction; admin/scrape ingest path needs a sensible default before organizer claim. Many Events will exist in the system before any organizer has claimed the Profile. |
| Re-derive default on every re-ingestion (organizer override is silently overwritten when source changes) | `reasoned:` Defeats organizer intent; once an organizer has consciously set a tier, ingestion should not silently revert. Override is the conscious act; reverting it is the labeling lie in the opposite direction. |

**What would invalidate this:** A pattern where organizers consistently override the source-derived default on first edit, and the override direction is consistent across organizers (always upgrade or always downgrade) rather than noisy. The consistency-of-direction is what would signal the mapping is mis-calibrated rather than just noisy.

### D3: Viewer-tier × Event-tier access matrix; robot indexing derived from tier

**Firmness: FLEXIBLE** (revised 2026-05-22) — the set of User.status values that
qualify as "trusted viewer" is a configurable knob
(`settings.EVENT_VISIBILITY_TRUSTED_STATUSES`, V0 default `("vouched",)`). The
matrix shape itself remains EXPLORATORY pending dogfooding (per D1).

The access matrix for `Event.visibility` × viewer status (V0 default — trusted
viewers = vouched + staff + superuser):

| Event.visibility | Anonymous | Open-status User (default: NOT trusted) | Vouched User (default: trusted) | URL holder (without User context) |
|---|---|---|---|---|
| `public` | ✓ visible, indexed | ✓ | ✓ | ✓ |
| `semi_public` | ✗ (login redirect) | ✗ (vouching-gate / 404) | ✓ visible, `noindex`, no sitemap | ✗ (URL alone does NOT bypass tier) |
| `unlisted` | ✗ | ✗ | ✓ via URL, `noindex`, no sitemap | ✓ visible (URL-keyed), `noindex`, no sitemap |

`User.status` semantics (`open` vs `vouched` vs `suspended_pending_investigation` vs `banned`) are canonicalized by [ADR-013](ADR-013-user-trust-model.md); this ADR references the terms. Suspended and banned Users are blocked from all non-public reads regardless of URL holding.

**Configurable knob:** `settings.EVENT_VISIBILITY_TRUSTED_STATUSES` (tuple of User.status strings) controls which statuses qualify as trusted viewers. To open semi_public/unlisted to open-signup users later, append `"open"`:

```python
# a_core/settings.py
EVENT_VISIBILITY_TRUSTED_STATUSES = ("open", "vouched")
```

The knob is the **policy** layer (who qualifies); the tier→audience structure (semi_public is gated, unlisted is URL-keyed) is the **structural** layer and lives in D1. Policy changes go through this setting; structural changes go through a D1 evolution.

Robot indexing follows the tier directly:
- `public` → `Allow: /events/<slug>` in `robots.txt`; included in sitemap; no `X-Robots-Tag` suppression.
- `semi_public` → response carries `X-Robots-Tag: noindex, nofollow`; excluded from sitemap.
- `unlisted` → response carries `X-Robots-Tag: noindex, nofollow, noarchive`; excluded from sitemap; not linked from any listing page.

Per ADR-008 D3 (fail loud on data integrity), a missing or invalid `Event.visibility` value MUST raise — no silent fallback to `public`. Migration carrying existing Events into this schema must populate `visibility` for every row before the migration completes.

**Rationale:**
- `direct:` kb-m69 D5 visibility-tier table; access semantics extend to viewer-status via kb-m69 D4 (open/vouched signup distinction).
- `reasoned:` Monotonic on-site tier + orthogonal URL-keyed tier produces a single matrix with no special cases beyond the URL-holder column for `unlisted`. Robot-indexing semantics derive deterministically from tier; no separate per-Event flag is needed.
- `reasoned:` URL alone does NOT bypass tier for `semi_public` — a vouched-User-only Event that leaks its URL stays gated. Only `unlisted` is URL-keyed by design. This preserves the distinction between the two non-public tiers.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| URL alone bypasses tier for `semi_public` (URL = capability token, uniformly) | `reasoned:` Once a `semi_public` event URL leaks, it becomes effectively public. The tier's whole purpose (trust gate) collapses. Capability-token model is what `unlisted` exists for; conflating the two erases the distinction. |
| Per-tier robot indexing controlled by a separate organizer flag, not derived | `reasoned:` Allows incoherent states (e.g., `public` tier with `noindex`); tier IS the indexing decision. Derivation eliminates the inconsistency surface. |
| Allow anonymous viewers to see `semi_public` Event titles in listings (not full pages) | `reasoned:` Listing leakage is its own privacy surface; if anonymous viewers can see titles, the Event is effectively `public` for discovery. Trust gate is binary on visibility. |
| Suspended/banned Users retain URL-keyed access to `unlisted` | `reasoned:` Suspension/ban is a User-level access revocation; tier-keyed bypass would re-grant access. The User-tier ADR will canonicalize this; D3 here states the cross-product. |

**What would invalidate this:** A pattern where the URL-bypass distinction between `semi_public` (gated) and `unlisted` (URL-keyed) is too subtle for organizers to use correctly — e.g., organizers consistently choosing `unlisted` when they meant `semi_public` (or vice versa), with downstream visibility incidents. The signal would pair with D1's invalidation (real-usage exposes the tier shape needs rework).

### D4: Migration backfill must respect de-facto-prior visibility (added 2026-05-22)

**Firmness: FLEXIBLE** — the migration-default discipline is a write-time symmetry of D3's read-time fail-loud spec. FLEXIBLE rather than FIRM because the rule may need refinement on the next concrete migration; the principle is firm but the operationalization is one incident deep.

When a migration introduces a visibility/tier field onto a table that already has rows, the backfill default for each row MUST be at least as public as the row's *observable* visibility under the pre-migration schema. The set of source-derived defaults defined in D2 governs *new* rows; backfilling existing rows requires a separate decision for the "no source signal" branch:

1. **Known source** — apply the D2 mapping.
2. **Unknown source_type** — raise per ADR-008 D3 (already specified in D3 above).
3. **No source linkage at all** (admin-created, manually imported, or schema predates the source-tracking infra) — **MUST default to the de-facto-prior tier**, i.e. whichever tier the row was rendered to under the no-field-yet query path. For Event in V0 that floor is `public` (the pre-migration `/events/` list was anonymously readable for every published row). It is **NOT** the same as D2's manual-creation default (`semi_public`); D2's default applies to new rows created after the field exists.

**Rationale:**
- `direct:` kb-cm5 session (2026-05-22) — `events.0013_event_visibility.backfill_visibility` applied D2's pessimistic default (`semi_public`) uniformly to both new rows and existing-row backfill. All 32 prod Events were admin-created without RawMessage linkage and got reclassified `semi_public`. With `EVENT_VISIBILITY_TRUSTED_STATUSES=("vouched",)` (D3 default) and 0 Users on prod, the events became invisible to everyone — a silent visibility regression that read as "lost events." A bulk UPDATE to `public` restored prior visibility.
- `reasoned:` Defaults serve different purposes at new-row time vs migration time. At new-row time, the absence of source signal is genuine "we don't know what this is" → pessimistic-safe is correct. At migration time, the absence of source signal is "the schema didn't track this yet" → the row's prior render path IS the signal, and ignoring it overrides observable history. The two cases need separate decisions, not a shared default.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Apply D2's default uniformly to backfill (status quo before this decision) | `direct:` kb-cm5 — produced the lost-events incident; the default is a labeling lie in the hidden direction for any row visible under the old schema. |
| Raise on every no-source-linkage row during migration (ADR-008 D3 fail-loud, no exceptions) | `reasoned:` Halts migration for the common case (every admin-created row in V0 had no linkage). Operator triage of N rows is not a scaling story; the migration is supposed to encode the prior-render-path mapping, not punt it. |
| Detect prior-visibility via a separate query during migration | `reasoned:` Brittle (queries the schema the migration is replacing); the prior render path is `Event.objects.all()` with no filter, so the floor is uniformly `public` for V0. A separate query adds complexity without distinguishing rows. |

**What would invalidate this:** A future migration where the pre-migration schema had >1 render path (e.g., a `hidden` flag distinguishing visibility) — then the floor is per-row, not uniform. Re-evaluate D4 when that case arrives; the principle (de-facto-prior visibility as floor) still holds but the operationalization changes.

**Operational discipline (smoke probe):** Any future migration introducing a visibility/tier field MUST be followed by a count-comparison check: rows visible-to-anonymous pre-migration count == rows visible-to-anonymous post-migration count (modulo any explicit data-cleanup the migration owns). The check belongs in the migration's RunPython callable, not in deploy.yml.

## Consequences

### Direct

- New field `Event.visibility` with enum `{'public', 'semi_public', 'unlisted'}`; migration backfills existing rows using D4's de-facto-prior-visibility rule (and D2's source-derived mapping for new rows). Per ADR-008 D3, rows where source_type is *unknown* raise rather than silent-fallback; rows with *no source linkage* fall under D4 (default to `public` for V0, the pre-migration render-path floor).
- `accounts/middleware.py` `LoginWallMiddleware` extends to consult `Event.visibility` for `/events/<slug>` routes; the existing `PUBLIC_READ_PREFIXES` pattern adapts to a per-Event tier check rather than a blanket prefix allow.
- Sitemap generation filters out `semi_public` and `unlisted` Events.
- Response middleware sets `X-Robots-Tag` headers per D3.
- `kb-9hw` (Bundle B public-read flip) is no longer a single master switch over all Event reads. `PUBLIC_READ_ENABLED` retains its role as a site-level kill switch (panic-mode rollback per `docs/runbooks/panic-mode.md`), but per-Event tier governs which Events are anonymously readable when the switch is on. kb-9hw cannot fire until D1–D3 are implemented and Events have populated `visibility` values.

### Carried forward

- ADR-009 D2 (4-tier Profile identity visibility — `public > vouched > friends > private`) holds. This ADR's 3-tier Event visibility uses **different** tier names because the audience semantics differ — Event has the URL-keyed `unlisted` tier that Profile doesn't; Profile has the `friends` tier that Event doesn't. Both ADRs share the `vouched` audience-tier concept, which becomes the bridge term canonicalized by [ADR-013](ADR-013-user-trust-model.md).
- ADR-006 D1 (Art. 9 consent for attendance) holds. Visibility-tier gates *who can see* the Event; attendance-consent gates *whether seeing implies opting into the attendance Art. 9 surface*. The two gates compose orthogonally.
- ADR-001 D1 (curated-trust) holds. The `vouched`-tier audience extends the curation model; this ADR does not expand the trust posture itself.
- ADR-002 D4 (banned-without-flag list) holds. Public share-links with OG previews, public RSS, embed widgets, third-party embedded maps, email notifications, event-level reviews displayed — all remain banned without their own respective flags even when an Event is `public`-tier. `public`-tier means "anonymously readable on-site"; it does not auto-enable cross-platform distribution surfaces.
- ADR-008 D3 (fail loud on data integrity) governs migration and runtime: a missing or invalid `Event.visibility` value raises rather than silent-fallbacks.
- **ADR-016 D4/D5 FLEXIBLE — visibility does NOT gate outbound syndication (clarified 2026-05-26).** `Event.visibility` is a *read-side* control: it governs how the Event renders on switch.berlin (`visible_to`, the D3 matrix, robot indexing). It does **not** restrict where a facilitator may syndicate the Event externally. Outbound projections (ADR-016 D2/D4) are eager-created uniformly across all three tiers; the facilitator controls actual external reach via the explicit, actor-attested publish lifecycle (ADR-016 D5), not via this enum. The earlier working assumption that `unlisted` → no external projections (and `semi_public` → matrix-compatible platforms only) is **superseded** — it conflated read-side Switch visibility with outbound syndication. Switch's own-event-page listing remains governed by the D3 read-side matrix (that is rendering, not a syndication gate).

### Risk

- The 3-tier shape may prove undercut by real usage (see D1 invalidation). EXPLORATORY firmness acknowledges this; mutation to 4-tier is a normal-firmness-path evolution per ADR-011 D1, not a supersession.
- The semantic distinction between `semi_public` (trust-gated) and `unlisted` (URL-keyed) requires organizer UX to communicate clearly; risk of incorrect tier selection. Mitigation: tier-picker copy on the Event-edit page must explain the difference in concrete terms; first-cohort organizer feedback should be observed during the post-flip soak window (per kb-9hw's 2-week soak protocol).
- `PUBLIC_READ_ENABLED` (kb-9hw context) remains site-level; site-level disable still trumps per-Event tier (all reads gated when off). This is intentional: kill switch retains its panic-mode role per `docs/runbooks/panic-mode.md`.

## canonical_refs

- [ADR-001 D1](ADR-001-core-product-and-stack.md) — curated-trust posture; the `vouched` audience-tier extends the curation model.
- [ADR-002 D2 + D4](ADR-002-phased-rollout-and-legal-gate.md) — legal gate at 0.5; banned-without-flag list (D4) constrains what flips at the `public` tier (public share-links with OG previews, public RSS, etc. remain off until separately enabled).
- [ADR-006 D1](ADR-006-legal-gate-execution.md) — Art. 9 attendance consent; orthogonal gate composing with visibility.
- [ADR-007 D1](ADR-007-profile-centric-schema.md) — unified Profile (`kind`); the Event↔Profile relationship that this ADR's tier-on-Event sits alongside.
- [ADR-008 D1, D3](ADR-008-code-posture-refactor-hard-fail-loud.md) — per-decision predicates; fail-loud on missing visibility values.
- [ADR-009 D2](ADR-009-mutual-connection-graph-and-identity-visibility.md) — Profile identity visibility tiers (sibling visibility surface); shared `vouched` audience-tier semantics.
- [ADR-016 D4, D5](ADR-016-outbound-syndication-architecture-event-post-projections.md) — outbound syndication; this ADR's visibility tiers are read-side-only and do NOT gate syndication (clarified 2026-05-26). The orthogonality boundary is owned jointly: read-side here, outbound there.
- `kb-m69` (Identity / trust / visibility-tier substrate) — D5 brainstorm-substrate that this ADR canonicalizes; D1 + D4 + D6 + D9 (User trust model) is the scope of sibling [ADR-013](ADR-013-user-trust-model.md).
- `kb-fx9` D14 — RSVP-visibility downstream surface (FLEXIBLE in the bead); composes on top of this ADR's Event tier.
- `kb-9hw` (Bundle B public-read flip) — operational checklist whose semantics this ADR refines (per-Event tier governs anonymous-read scope, not a single master switch).
- `~/.claude/docs/decisions/ADR-012-substrate-thick-process-thin.md` D6 — dogfooding bar (global ADR; cited by name only — same-number-different-content collision with this project ADR noted in Open questions).
- `~/.claude/docs/decisions/ADR-013-memory-layer-architecture.md` D3 — firmness-governed mutation rule; EXPLORATORY mutation path per noticing.
- `history/scout-features-switch-berlin-2026-05-18.md` — FetLife / Diversia / Bluesky / Partiful / Lu.ma scout grounding the 3-tier external precedent.
- `docs/runbooks/panic-mode.md` — site-level `PUBLIC_READ_ENABLED` kill-switch role preserved alongside per-Event tier.

## Open questions deferred

| Question | Resolution path |
|---|---|
| User trust model (`User.status` enum, signup paths, Vouch graph, invite economy) | Canonicalized in [ADR-013](ADR-013-user-trust-model.md) (2026-05-21). Bead substrate: kb-m69 D1 + D4 + D6 + D9. |
| Profile claim flow (web-first claim + email-domain fast-path + admin-review fallback) | Canonicalized in [ADR-014](ADR-014-profile-claim-flow.md) (2026-05-21). Bead substrate: kb-m69 D1. |
| 4-tier promotion (split `semi_public` into registered-but-not-vouched + vouched-only) | D1 invalidation predicate; promote on real-usage signal. Not blocking V0. |
| Per-Event share-token (capability URL for fine-grained sharing) | Defer; V1+ if `unlisted` proves insufficient for sharing patterns. |
| ACL-style per-User access on individual Events | Defer; V1+ if `unlisted` URL distribution proves insufficient for the share-with-specific-people case. |
| Project-vs-global ADR numbering collision (project ADR-012 `event-visibility-tiers` vs global ADR-012 `substrate-thick-process-thin`, both cited by ADR-009) | Resolved by kb-5xs (2026-05-21) to option (c): accept collision; global references in project ADRs cite by full path (`~/.claude/docs/decisions/ADR-NNN-...md`); same convention applies to project ADR-013 vs global ADR-013. |
