# ADR-003: Cheap foresight patterns

**Status:** Accepted
**Date:** 2026-04-17
**Design:** [Roadmap 0.1 → 1.0](../plans/2026-04-17-roadmap-0.1-to-1.0.md)
**Parent:** [ADR-002](ADR-002-phased-rollout-and-legal-gate.md)
**Related:** [ADR-001](ADR-001-core-product-and-stack.md)

## Context

The phased roadmap (ADR-002) defers features across multiple milestones. Deferred does not mean ignored. For every feature we don't build in phase N, we can either:

(a) **Stub nothing** — deal with the migration when phase N+2 arrives. Cheapest now, most expensive later.
(b) **Build it fully** — premature. Violates YAGNI. Common solo-project failure mode.
(c) **Cheap foresight** — shape the model, schema, route, or data-capture surface so the future phase is additive, not a rewrite. Zero or near-zero cost now; buys optionality.

This ADR records the cheap-foresight patterns that apply to kinky-bubbles specifically. The default is (c) where the cost is trivial and the optionality is real; (a) where the future need is speculative enough that guessing wrong is likely.

## The principle

> For every deferred feature, ask: **"What shape can I give this now, at zero-to-trivial cost, so phase N+2 is an additive migration, not a rewrite?"** If the answer is obvious and cheap, do it. If it requires guessing at phase N+2's specifics, don't.

Cheap foresight is **data-shape and naming decisions**, not UI, not APIs, not business logic. The minute it costs more than ~1 hour of work, it's no longer cheap.

## Concrete applications

### F1: pgvector — extension on, columns off

**Applies to:** semantic search / similar-events / agent recommendations (V2+ speculation).

**Do now:** Keep the `pgvector/pgvector:pg17` Docker image. Enable the extension via migration in 0.1. No `VectorField` on any model.

**Why this is cheap foresight:** Swapping the Postgres image later is annoying (data migration). Adding an unused extension is free. Adding a `VectorField` column and a backfill later is a trivial additive migration — trivially cheaper than guessing the right dimensionality, index type, and which model's text to embed before there's a feature asking.

---

### F2: Reviews — unified model, phase-gated display

**Applies to:** event-level reviews (displayed at 0.7) and organizer-level reviews (displayed at 0.6).

**Do now in 0.1 schema:**

```python
class Review(models.Model):
    author = FK(User)
    organizer = FK(Organizer, null=True, blank=True)
    event = FK(Event, null=True, blank=True)
    rating = IntegerField()  # 1-5
    body = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            CheckConstraint(
                check=Q(organizer__isnull=False) ^ Q(event__isnull=False),
                name="review_targets_exactly_one",
            ),
        ]
```

One row reviews exactly one target (organizer XOR event). Display logic is phase-gated in templates, not in the model.

**Why this is cheap foresight:** Forcing a polymorphic split later is a schema migration with data movement. Having both FKs from day 1 costs nothing at query time and supports phase-gated UI trivially. User explicitly wants event reviews; this lets them exist in data from 0.5, surface at 0.7.

---

### F3: Tags — `kind` enum sized for future promotion of "bubble"

**Applies to:** ADR-001 open question: bubble as first-class entity vs. Tag.

**Do now:** `Tag.kind` is a `CharField(choices=...)` with initial values `('theme', 'format', 'identity', 'bubble')`. Bubbles are Tags with `kind='bubble'` until there's pressure for dedicated bubble features (bridging UX, membership, per-bubble rules).

**Why this is cheap foresight:** The promotion of `kind='bubble'` Tags to a dedicated `Bubble` model is a well-understood migration: copy rows, update FKs, drop the `kind` value. Starting with a flat `Tag` model with the `kind` field ready avoids a schema migration *and* a code-wide find-replace. Near-zero cost now.

---

### F4: Geography — Decimal lat/lng now, PostGIS later

**Applies to:** ADR-001 open question: PostGIS vs. lat/lng columns.

**Do now:** `Venue.latitude` and `Venue.longitude` as `DecimalField(max_digits=9, decimal_places=6)`. No PostGIS. No `PointField`.

**Why this is cheap foresight:** Simple geometry queries (within-circle, bounding box) work fine in raw lat/lng for Berlin-scale data (~hundreds of venues). Adding PostGIS later is a migration that *adds* a computed `PointField` from existing `latitude`/`longitude` columns — additive, no data movement. Starting with PostGIS means an extra extension to manage for features that don't exist yet.

---

### F5: GDPR consent data — captured from 0.1, consumed from 0.5

**Applies to:** GDPR lawful-basis record per organizer (legal-gate requirement at 0.5).

**Do now in 0.1** (pulled forward from 0.2 during design review 2026-04-17)**:** `Organizer` gets `consent_recorded_at`, `consent_method` (e.g., 'telegram_forward_implied', 'explicit_opt_in', 'verified_public_source'), `consent_notes` (free-text). Fields are populated during organizer approval in admin even though no user-facing endpoint reads them until 0.5.

**Why this is cheap foresight:** Capturing consent *as it happens* is correct; backfilling consent records for organizers approved 3 months ago is either impossible or a lie. The data has to be captured at the moment of approval or the compliance posture at 0.5 is fictional. Capturing without consumption costs nothing.

---

### F6: Internationalization — {% trans %} wrappers from 0.1

**Applies to:** future multi-language UI (German alongside English).

**Do now:** All user-facing strings in templates wrapped in `{% trans %}` / `{% blocktrans %}` from phase 0.1, even though only English translations exist. No `.po` files needed until there's a translator.

**Why this is cheap foresight:** Retrofitting `{% trans %}` across a template base is tedious and error-prone (easy to miss strings). Writing `{% trans "Save" %}` instead of `Save` costs 10 characters. No runtime cost, no build complexity, zero risk of missing strings later. Berlin audience contains native German speakers; a translator appearing at 1.5 is plausible.

---

### F7: Telegram ingestion — schema supports Telethon-later

**Applies to:** ADR-001 open question: bot-forward only vs. Telethon user-session scraping.

**Do now:** `RawMessage` has `source_type` ('telegram_bot_forward', future: 'telegram_telethon', 'email_submission', 'web_form'), `sender_id`, `channel_id`, `message_id`, `raw_payload` (JSONField). Bot-forward ingestion populates these fields as naturally available.

**Why this is cheap foresight:** Telethon ingestion, if added at V1+, produces the same field set (sender, channel, message ID, raw payload). Schema is identical; only the ingestion adapter differs. No migration required to enable a second adapter. Zero cost now.

---

### F8: Signal aggregates — nightly recompute, not signal-driven caches

**Applies to:** follower counts, attendance counts, rating averages.

**Do now at 0.5/0.6:** Denormalized aggregate columns (`Organizer.follower_count`, `Event.attendance_count`, `Organizer.avg_rating`) recomputed by a nightly `django-q2` scheduled task. No Django signal handlers updating counts on each change.

**Why this is cheap foresight:** Signal-driven cache invalidation is a classic source of drift bugs and silent failures — exactly the kind of thing that eats a solo maintainer's weekends when a transaction rolls back or a signal handler throws. Nightly recompute is correct-enough for display purposes (invalidation happens at most once/day), observable (one query, one log line), and restartable (re-run the job fixes any drift).

---

### F9: Kill-switches as Django settings *and* DB flags

**Applies to:** signup, signals, flags, organizer self-edit, public/invite toggle.

**Do now as each feature ships:** Each toil feature gets a `feature_flags` row (or a settings entry) checked at the request-path level. Admin has a one-page "feature switches" view. Each flag defaults to its release-phase state; flipping it off degrades the UI gracefully (button hidden, "temporarily disabled" message, 503 on the endpoint).

**Why this is cheap foresight:** Kill-switches added retrofitting require touching every request path that uses the feature. Baking the check in from the start costs ~3 lines per feature. ADR-002 D4 makes these mandatory; this pattern makes them cheap.

## What this does NOT include

Things we explicitly do NOT build foresight for, because the shape of the future need is too speculative:

- **Payments / ticketing** (V4+) — no fields, no hooks, no stub. Too many possible integrations (Stripe, ticket providers, EU-specific) to shape sensibly in advance.
- **Multi-city support** (post-12-month per ADR-001 D2) — no `city` field on models, no geocoding abstraction. Berlin is hardcoded. When city #2 arrives, it's a real migration, and that's correct.
- **LLM recommendations** (V3+) — beyond F1's unused pgvector extension, no prompt templates, no embedding generation pipeline, no user-profile-vector schema.
- **Mobile app** — no mobile API layer, no DRF scaffolding. The V0 Django + HTMX + island monolith does not shape itself around an API that may never exist.

The rule: if imagining the feature requires inventing half the product decisions, don't pretend to foresee it. Ship the current phase well.

## Consequences

**Easier:**
- Future phases are additive migrations, not rewrites.
- Compliance data (F5) is correct by construction rather than backfilled.
- Feature decisions (F2, F3) that user demand might accelerate don't block on a schema migration.

**Harder:**
- Reviewer has to remember which deferred features have foresight shape and which don't (documented here).
- Some fields (GDPR consent, i18n wrappers) have no consumer in their introduction phase — looks like dead code until 0.5+.

**Tradeoffs:**
- Every foresight pattern above assumes the product actually reaches the phase that consumes it. If the project dies at 0.3, F5–F9's cost (small) is wasted. Acceptable — the cost is small enough that the expected value is positive even at low completion probability.
