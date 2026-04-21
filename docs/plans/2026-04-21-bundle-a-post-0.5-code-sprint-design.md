# Bundle A — Post-0.5 code sprint

**Date:** 2026-04-21
**Status:** Draft (ready for `/send-it`)
**Parent roadmap:** [Bundle A in roadmap](2026-04-17-roadmap-0.1-to-1.0.md)
**ADRs:** [ADR-001 D3](../decisions/ADR-001-core-product-and-stack.md), [ADR-002 D4](../decisions/ADR-002-phased-rollout-and-legal-gate.md), [ADR-003 F2, F8, F9](../decisions/ADR-003-cheap-foresight-patterns.md)
**Supersedes in scope:** portions of [phase 0.6](2026-04-17-phase-0.6-signals-design.md), [phase 0.7](2026-04-17-phase-0.7-event-reviews-design.md), [phase 1.0](2026-04-17-phase-1.0-soft-launch-design.md)
**Audience:** current invite cohort — public surface only lights up when maintainer flips flags.
**Risk killed:** "build when I'm in flow" — solo maintainer code sprints should not block on human-time calendar items (event entry, threshold calibration, organizer approvals).

## Why bundle

Phase 0.5 is code-complete (2026-04-21). Everything remaining on the 0.5→1.0 path splits cleanly into two kinds of work:

1. **Code that can be written now** — machinery for signals, reviews, moderation, rate-limiting. Ships behind kill-switches. No dependency on human judgment or real-user data.
2. **Human-gated operations** — entering 30+ real events, legal copy review, 2-week public-read soak, threshold calibration from real data, organizer outreach, admin-reviewed signup decisions. These need wall-clock time and maintainer attention, not a code session.

Running these as two parallel tracks is strictly better than interleaving them by phase:
- The code sprint is one `/send-it` run with no human-time blockers.
- Operations tasks tick off whenever the maintainer has an hour.
- Any "ready to flip" flag waits for an ops-side signal — decoupled.

What Bundle A excludes is equally important. Three areas need real-user feedback before building them well, and we defer them to a "Bundle C" design written after 0.5+Bundle A+0.6-observation:
- **1.0 admin-reviewed signup form** (`SignupApplication` model, reviewer UX) — what motivation/referrer fields actually matter is a judgment call informed by watching invite requests in a Gmail label first.
- **1.0 organizer self-edit** (`OrganizerEdit`, `OrganizerUserLink`, re-review triggers) — "which fields re-trigger review" is an organizer-experience question. Building it before watching 2–3 organizers fumble at "how do I fix a typo?" locks in the wrong assumptions.
- **1.0 bubble-bridging UI** — depends on what `Tag.kind='bubble'` density looks like in live data.

## Scope

### In — 0.5 leftover

- **OG meta tags** on `/events/<org_slug>/<event_slug>/` and `/o/<slug>/` — wrapped in a template conditional on `PUBLIC_READ_ENABLED`. Suppressed during rollback to avoid share-links pointing at a login wall (matches 0.5 design doc §Hardening bullet on OG tags).

### In — 0.6a machinery

- **Trending sort on `/events`** — annotated queryset, no materialized `Signal` table. Score: `interested_count * recency_decay + attendance_count * 2` where `recency_decay = 1 / max(1, days_until_start)`. Default sort stays chronological; trending is a `?sort=trending` toggle via filter chip. Gated by `TRENDING_SORT_ENABLED` (default True, flippable).
- **`/me` page** — logged-in-only. Three sections: followed organizers (list with unfollow button), upcoming attendances (filter `status in (going, interested)`, event date future), past attendances (status=`went`, event date past). Uses existing models, no schema changes.
- **`/events` landing — "From organizers you follow"** section — logged-in users see a collapsed section above the list showing events from `OrganizerFollow` → `Event` (future, status=published, visible). Empty state: "You're not following anyone yet." Implementation: one extra queryset annotation.
- **`ModerationAction` table** (new) — in `a_core` app. See Data model deltas.
- **Admin one-click moderation actions** — on `FlagAdmin` change_view, add buttons: "Approve (no action)", "Hide target", "Delete review", "Mark resolved". Each creates a `ModerationAction` row and updates the flag. No JS — standard Django admin actions.
- **Threshold-config via FeatureFlag** — thresholds currently hardcoded (`AUTO_HIDE_FLAG_THRESHOLD=3`, `MIN_RATINGS_FOR_DISPLAY=3`) move to `FeatureFlag` rows with integer values. Extend `FeatureFlag.enabled:BooleanField` pattern: add `numeric_value:IntegerField(null=True)` and helper `get_numeric(key, default) -> int`. Call sites read via helper. No migrations on existing flag rows.
- **Email digest improvements** — existing `daily_flag_digest` task: add grouping by target, pre-filled admin URLs with `?action=` query params that pre-select the moderation action in admin.
- **Organizer reviews UI upgrade** on `/o/<slug>` — dedicated reviews section (not sidebar). Sortable by `?sort=recent|highest|lowest` (server-side, no JS). Show reviewer's display name + date. Gated by `rating_count >= get_numeric("threshold.organizer_ratings_display", 3)`.

### In — 0.7 display logic (flag-gated, default OFF)

- **Event rating display** on `/events/<org_slug>/<event_slug>/` — reviews section rendered below description when `event.rating_count >= get_numeric("threshold.event_ratings_display", 3)` AND `FeatureFlag("event_reviews_displayed")` is True. Flag default: False. Maintainer flips once 0.7 go/no-go is hit.
- **Event card star chip** on `/events` list — `★ 4.2 (N)` rendered per card when same threshold + flag hits. Same conditional.
- **Review authorship gate** — review form on `/events/<org_slug>/<event_slug>/` only renders if `request.user.is_authenticated AND Attendance.objects.filter(user=user, event=event, status='went').exists()`. Direct POST enforces same check → 403 otherwise. Copy for unauthenticated/unqualified: "You can review this event after attending."
- **Auto-finalize attendance task** (new django-q2 nightly) — `'going'` → `'went'` for events whose `end < now() - 24h`. Skip events with `end=None`. This is a Bundle A prerequisite, not a 0.7 deliverable — `/me` past-attendances depends on it, and so does the review gate at scale.

### In — 1.0 infra

- **Rate limiting on writes** — `django-ratelimit` on:
  - Flag submission: `5/h` per user, `20/d` per user (per Phase 1.0 design).
  - Review submission: `10/d` per user.
  - Signup attempts: `3/h` per IP (already partial from 0.5; extend to allauth signup view).
  - Takedown form: already `5/h` per IP in 0.5; bump to `10/h` per IP to match 1.0 spec.
- **Panic mode documentation** — the existing flags (`PUBLIC_READ_ENABLED`, `SIGNUP_OPEN`, `RATINGS_ENABLED`, `FLAGS_ENABLED`, `LOGIN_WALL_ENABLED`, `INGESTION_PAUSED`) form the panic-mode surface. Document in `docs/runbooks/panic-mode.md`: what each flag flipping False does, combined "full panic" = 0.4 posture in ≤60s. Add `INGESTION_PAUSED=True` handling to the ingestion bot loop (check at top of each task, no-op if paused).
- **Week-off runbook** — `docs/runbooks/week-off.md` per Phase 1.0 spec §Week-off runbook. Pre-departure checklist, what auto-heals, what to flip.

### Out — explicit deferrals

- **All threshold *values* calibration** — numeric defaults ship as `3`/`5`; tuning happens in Bundle B from real data.
- **1.0 `SignupApplication` + admin-reviewed open signup** — decision-loaded UX, defer to Bundle C.
- **1.0 organizer self-edit (`OrganizerEdit`, `OrganizerUserLink`, re-review triggers)** — decision-loaded UX, defer to Bundle C.
- **1.0 bubble-bridging UI** — data-shape dependent, defer to Bundle C.
- **Logfire dashboards** — observability requires real traffic to design the right panels. Defer to Bundle C; basic Django logging stays.
- **Trending `Signal` materialized table** — ship as annotated queryset; revisit if slow at ≥1k events.

## Data model deltas

### `core.ModerationAction` (new)

```python
class ModerationAction(models.Model):
    moderator = FK(User, on_delete=PROTECT)
    flag = FK("reviews.Flag", null=True, blank=True, on_delete=SET_NULL)
    target_type = CharField(max_length=20, choices=[
        ("event", "Event"), ("organizer", "Organizer"), ("review", "Review")
    ])
    target_id = IntegerField()
    action = CharField(max_length=20, choices=[
        ("no_action", "No action"), ("hide", "Hide target"),
        ("delete", "Delete review"), ("resolved", "Mark resolved"),
    ])
    reason = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]
```

Future DSA transparency-report source of truth.

### `core.FeatureFlag` — extended

```python
# Add to existing model:
numeric_value = IntegerField(null=True, blank=True,
    help_text="For threshold-style flags; None means boolean-only")

# Add to module:
def get_numeric(key: str, default: int) -> int:
    """Cached numeric-flag lookup; falls back to default if flag or value missing."""
```

Seed rows (via data migration):
- `threshold.organizer_ratings_display = 3`
- `threshold.event_ratings_display = 3`
- `threshold.auto_hide_flag = 3`
- `threshold.attendance_display = 5`
- `threshold.follower_display = 5`
- `event_reviews_displayed = False` (boolean)
- `trending_sort_enabled = True` (boolean)

### No changes to existing models

`Review`, `Attendance`, `Organizer`, `Event`, `Flag` are unchanged. All Bundle A features compose on existing schema.

## URL + view additions

```
/me                                             → user profile (logged-in only)
/o/<slug>/?sort=recent|highest|lowest           → add query-param sort
/events/?sort=trending                          → add sort toggle
```

No new public URLs. `/events/<org_slug>/<event_slug>/edit` and `/accounts/signup/` (open form) are explicitly Bundle C.

## Template deltas

- `cotton/event_card.html` — add star chip rendering block (gated).
- `events/detail.html` — add reviews section + review form (gated).
- `events/detail.html`, `organizers/detail.html` — add OG meta tags in `{% block og %}` overrides.
- `events/list.html` — add sort toggle UI + "From organizers you follow" section.
- `organizers/detail.html` — upgrade reviews-section block.
- New template: `accounts/me.html`.

## Background tasks

- **`finalize_attendance`** (new, nightly 03:00 Europe/Berlin) — `'going'` → `'went'` for events ended >24h ago.
- **`daily_flag_digest`** (existing) — add grouping by target + pre-filled admin URL params.
- **`recompute_aggregates`** (existing) — no changes.

## Test plan

- **Trending sort**: fixture with 5 events (varied counts + dates) → assert ordering matches `score` formula. Flipping `trending_sort_enabled=False` removes the toggle.
- **`/me`**: follows, upcoming (future attendance), past (went + past) — three independent fixtures.
- **ModerationAction**: each admin action creates a row with correct target_type/target_id/action. Hide-target action sets `.hidden=True` on the target.
- **Threshold flag**: `threshold.organizer_ratings_display` flipped from 3→10 hides displays on `/o/<slug>` until new ratings accumulate. Cache respects 60s TTL.
- **Email digest**: mock 5 flags over 24h → 1 email with all 5, grouped by target, each row has pre-filled admin URL.
- **Review-gate**: user without `went` attendance → form hidden + direct POST → 403. User with `went` → form renders + POST creates Review.
- **Event rating display gate**: `event_reviews_displayed=False` → hidden even with rating_count=10. Flipped True + count=2 → still hidden. True + count=3 → shown.
- **Auto-finalize attendance**: events with `end < now()-24h` and `status='going'` → `status='went'`. Events with `end=None` → skipped.
- **Rate limits**: 6th flag in an hour → 429. 11th review in a day → 429. Rate-limit bypass for staff.
- **Panic mode**: docs/runbooks/panic-mode.md renders; all flags listed with effect; combined state restores 0.4 posture in integration test.
- **OG tags**: detail page with `PUBLIC_READ_ENABLED=True` renders `og:title/description/image`; `=False` omits them entirely.

## Rollback

Per-feature kill-switches:
- `TRENDING_SORT_ENABLED=False` → chronological-only, toggle hidden.
- `event_reviews_displayed=False` → event reviews collected, display hidden. (Default state.)
- `RATINGS_ENABLED=False` → review form hidden on event + organizer pages.
- Rate limits disabled via `RATELIMIT_ENABLE=False` (django-ratelimit env).
- `/me` isn't flag-gated (logged-in-only, low blast radius); remove route if broken.

## Shipping order (suggested bead structure)

1. **Schema + config** — `ModerationAction` model, `FeatureFlag.numeric_value` + `get_numeric` helper, data migration seeding threshold rows.
2. **0.5 leftover** — OG tags. Smallest, unblocks full public-read flip when ready.
3. **Auto-finalize attendance task** — unblocks `/me` past-attendances and 0.7 review-gate.
4. **`/me` + followed-organizer section** — pure composition on existing models.
5. **Trending sort + UI toggle** — queryset annotation + filter-chip wiring.
6. **Moderation tooling** — `ModerationAction` + admin actions + digest improvements.
7. **0.7 event-review display logic + review-gate** — flag-gated, default off.
8. **Rate limiting** — apply django-ratelimit across write endpoints.
9. **Runbooks** — `panic-mode.md` + `week-off.md`.

Steps 2–9 can parallelize heavily once step 1 lands. `/send-it` expected to batch into ~6–8 beads (smaller than Phase 0.5's 6 beads of scope because each item here is a narrower slice).

## Go-signal for Bundle A

All steps shipped, review passed, tests green. No traffic gate — Bundle A is a pure code deliverable. Maintainer flips `PUBLIC_READ_ENABLED=True` whenever the Bundle B ops tasks are satisfied.

## What comes after

- **Bundle B** (ops, no design doc — just open beads): event entry, legal copy review, `PUBLIC_READ_ENABLED=True` flip, 2-week soak, threshold calibration.
- **Bundle C** (design after Bundle B observation): 1.0 admin-reviewed signup, organizer self-edit, bubble-bridging, Logfire dashboards. Drafted when maintainer has 1+ week of public-read data to inform UX decisions.
