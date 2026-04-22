# Bundle A — Post-0.5 code sprint

**Date:** 2026-04-21
**Status:** Reviewed (ready for `/send-it`)
**Parent roadmap:** [Bundle A in roadmap](2026-04-17-roadmap-0.1-to-1.0.md)
**Decisions:** [ADR-005 Bundle post-0.5 execution](../decisions/ADR-005-bundle-post-0.5-execution.md)
**Upstream ADRs:** [ADR-001 D3](../decisions/ADR-001-core-product-and-stack.md), [ADR-002 D4](../decisions/ADR-002-phased-rollout-and-legal-gate.md), [ADR-003 F2, F6, F8, F9](../decisions/ADR-003-cheap-foresight-patterns.md), [ADR-004 D3](../decisions/ADR-004-htmx-vs-island-default-plus-tripwire.md)
**Supersedes in scope:** code portions of [phase 0.6](2026-04-17-phase-0.6-signals-design.md), [phase 0.7](2026-04-17-phase-0.7-event-reviews-design.md), [phase 1.0](2026-04-17-phase-1.0-soft-launch-design.md) (per ADR-005 D1)
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

## Conventions

- **Flag naming:** booleans use `UPPERCASE_SNAKE` matching existing seed rows (`RATINGS_ENABLED`, `PUBLIC_READ_ENABLED`, …). Numeric threshold flags use dotted-lowercase `threshold.<name>` to signal "looked up via `get_numeric`, not `get_flag`." Mixed-convention is intentional: visually distinct keyspaces prevent accidental `get_flag("threshold.auto_hide_flag")` bugs.
- **i18n:** all new user-visible strings wrapped in `{% trans %}` per ADR-003 F6 (convention is live: 217 usages across 27 templates; `locale/de` is active infrastructure).
- **Accessibility:** new interactive elements follow existing aria patterns in `templates/cotton/filter_chips.html` and neighboring cotton components. Formal a11y audit deferred to Bundle C.
- **HTMX response shape:** all new rate-limited / gated write endpoints return their existing error-partial template with `error=<message>` and HTTP 429/403, matching the `_rating_form.html` / `_flag_button.html` convention. This requires `django-ratelimit` usage with `block=False` + `request.limited` branch (decorator's default-raise-403 yields a bare page that HTMX cannot swap).

## Scope

### In — 0.5 leftover

- **OG meta tags** on `/events/<org_slug>/<event_slug>/` and `/o/<slug>/` — wrapped in a template conditional on `PUBLIC_READ_ENABLED`. Uses the existing `{% block og_meta %}` from `templates/_base.html`. Suppressed during rollback to avoid share-links pointing at a login wall (matches 0.5 design doc §Hardening bullet on OG tags). Note: flipping `PUBLIC_READ_ENABLED=False` stops *new* previews; already-scraped social-cache previews persist 24–48h. The panic-mode runbook (§9a below) includes Facebook/Discord/Telegram refresh URLs for forced cache-bust.

### In — 0.6a machinery

- **Trending sort on `/events`** — annotated queryset, no materialized `Signal` table. Score: `interested_count * recency_decay + attendance_count * 2` where `recency_decay = 1 / max(1, days_until_start)`. Default sort stays chronological; trending is a `?sort=trending` toggle via filter chip. Gated by `TRENDING_SORT_ENABLED` (default True, flippable). Query wrapped in `logfire.span("events.trending_query")` to capture per-request latency — revisit materialization if P95 exceeds 200ms (evidence-based, per ADR-004's tripwire philosophy).
- **`/me` page** — logged-in-only. Three sections: followed organizers (list with unfollow button), upcoming attendances (filter `status in (going, interested)`, event date future), past attendances (status=`went`, event date past). Uses existing models. Unfollow button reuses the existing `organizer-follow` toggle endpoint (`organizers/urls.py:6`); verify toggle semantics match (POST with same org_id un-follows if already followed).
- **`/events` landing — "From organizers you follow"** section — logged-in users see a collapsed section above the list showing events from `OrganizerFollow` → `Event` (future, status=`published`, visible). Ordered by `start` ascending (nearest-future first). Capped at 5 upcoming events with a "View all" link to `/events?filter=following`. Followed organizers whose own `status='suspended'` or `hidden=True` are excluded from the feed. Empty state: "You're not following anyone yet." Implementation: one extra queryset annotation.
- **`ModerationAction` table** (new) — in `a_core` app. See Data model deltas.
- **Admin one-click moderation actions** — on `FlagAdmin` change_view, add buttons: "Approve (no action)", "Hide target", "Delete review", "Suspend organizer", "Mark resolved". The action set surfaced per target type:
  - `target_type='event'` or `'organizer'`: {`no_action`, `hide`, `suspend` (organizer only), `resolved`}
  - `target_type='review'`: {`no_action`, `delete` (soft), `resolved`}
  Each creates a `ModerationAction` row and updates the flag. No JS — standard Django admin actions. "Suspend organizer" keeps parity with the 0.6 contract (explicit rather than silently dropped); it sets `Organizer.status='suspended'` via the same code path the opt-out flow uses (`reviews/views.py:288`).
- **Threshold-config via FeatureFlag** — thresholds currently hardcoded (`AUTO_HIDE_FLAG_THRESHOLD=3`, `MIN_RATINGS_FOR_DISPLAY=3`) move to `FeatureFlag` rows with integer values. Extend `FeatureFlag.enabled:BooleanField` pattern: add `numeric_value:IntegerField(null=True)` and helper `get_numeric(key, default) -> int`. Cache coordination: `get_flag` and `get_numeric` both project from a single `feature_flag_row:{key}` cache entry (whole-row cache, 60s TTL); `FeatureFlag.save()`/`delete()` invalidate that one key. Existing `feature_flag:{key}` callers are migrated to the unified key in the same bead to avoid split-brain. First consumer shipped **in the same bead** as the schema/helper: `reviews/views.py` replaces the `AUTO_HIDE_FLAG_THRESHOLD = 3` module constant with `get_numeric("threshold.auto_hide_flag", default=3)` at both call sites (`:148`, `:157`) — this prevents the "infrastructure that nothing uses yet" antipattern.
- **Email digest improvements** — existing `daily_flag_digest` task (`ingestion/tasks_flags.py:10`): add grouping by target, pre-filled admin URLs with `?action=` query params that pre-select the moderation action in admin. **Intra-step ordering**: admin buttons (bead 6a) ship before digest URL pre-fill (bead 6b), since `?action=` is consumed by the change_view code from 6a.
- **Organizer reviews UI upgrade** on `/o/<slug>` — dedicated reviews section (not sidebar). Sortable by `?sort=recent|highest|lowest` (server-side, no JS). Show reviewer's display name + date. Gated by `rating_count >= get_numeric("threshold.organizer_ratings_display", 3)`.

### In — 0.7 display logic (flag-gated, default OFF)

- **Event rating display** on `/events/<org_slug>/<event_slug>/` — reviews section rendered below description when `event.rating_count >= get_numeric("threshold.event_ratings_display", 3)` AND `FeatureFlag("EVENT_REVIEWS_DISPLAYED")` is True. Flag default: False. Maintainer flips once 0.7 go/no-go is hit (decision-support: see §Readiness check below or defer to Bundle B ops bead).
- **Event card star chip** on `/events` list — `★ 4.2 (N)` rendered per card when same threshold + flag hits. Same conditional.
- **Review authorship gate** (narrows existing gate at `templates/events/detail.html:87`, which today gates on `event_past + RATINGS_ENABLED + is_approved`). Bundle A adds a further requirement: the form only renders if `request.user.is_authenticated AND Attendance.objects.filter(user=user, event=event, status='went').exists()`. Direct POST enforces same check → returns HTTP 429-style error partial (`_rating_form.html` with `error="You can review this event after attending."`) matching existing convention. Test plan acknowledges the behavior change: past-event viewers without `went` attendance lose form access.
- **Auto-finalize attendance task** (new django-q2 nightly, 03:00 Europe/Berlin) — `'going'` → `'went'` for events whose `status='published'`, `hidden=False`, and `end < now() - 24h`. Events with `end=None` are *skipped* and stay at `going` indefinitely — this is intentional for no-end-time events (concerts with no stated end, etc.); the maintainer can manually flip via admin if needed. **This is a Bundle A prerequisite, not a 0.7 deliverable** — `/me` past-attendances depends on it, the review gate at scale depends on it, **and** `recompute_aggregates` must be updated in the same bead (see below) to avoid a silent data bug.
- **`recompute_aggregates` extension** (existing task at `ingestion/tasks_flags.py:66`, updated in the same bead as `finalize_attendance`). Currently `Event.attendance_count = Attendance.filter(status='going').count()`. This must become `status__in=('going','went')`, otherwise the first nightly run after `finalize_attendance` flips past-event attendees zeros out every past event's `attendance_count` — which in turn zeros the `attendance_count * 2` term in trending for recent-past events and breaks `/me` past-event attendance badges.
- **Readiness check for `EVENT_REVIEWS_DISPLAYED` flip** — deferred to Bundle B ops. The Bundle B bead "calibrate review display threshold" covers the decision-support query (count events with ≥3 reviews, review-author spread, flagged-review ratio). Bundle A ships the flag infrastructure only; Bundle A does not ship an admin readiness screen.

### In — 1.0 infra

- **Rate limiting on writes** — `django-ratelimit` is already a dep (`pyproject.toml:34`, used in `reviews/views.py` for organizer opt-out + takedown). Bundle A extends usage to:
  - **Flag submission**: `5/h` per user and `20/d` per user (per Phase 1.0 design). This is a **rewrite** of the existing hand-rolled `FLAG_RATE_LIMIT_PER_USER=10/day` in `reviews/views.py:20` and deletes its test at `reviews/test_flags.py:713`. The two-rate pattern uses stacked `is_ratelimited()` calls (django-ratelimit decorators don't stack). Net effect: peak tightens (5/h vs. 10/day burst), daily cap loosens slightly (120 vs. 10) — peak restriction is the spam defense.
  - **Review submission**: `10/d` per user.
  - **Signup attempts**: `3/h` per IP (already partial from 0.5; extend to allauth signup view).
  - **Takedown form**: already `5/h` per IP in 0.5; bump to `10/h` per IP to match 1.0 spec.
  - **Staff bypass**: implemented via custom key function `key=lambda g, r: None if r.user.is_staff else r.user.pk` applied consistently on all user-keyed limits.
  - **429 response shape**: all endpoints use `block=False` and branch on `request.limited`; on limit-hit, render the endpoint's existing error-partial template (`_rating_form.html`, `_flag_button.html`, or equivalent) with `error="Rate limit reached, try again later."` and HTTP 429.
- **Panic mode runbook** — the existing flags (`PUBLIC_READ_ENABLED`, `SIGNUP_OPEN`/`INVITES_ENABLED`, `RATINGS_ENABLED`, `FLAGS_ENABLED`, `LOGIN_WALL_ENABLED`, `INGESTION_PAUSED`) form the panic-mode surface. Note on flag inventory: of these, only the first four + `LOGIN_WALL_ENABLED` are currently seeded. `INGESTION_PAUSED` is **new** (see below); signup control today runs through `INVITES_ENABLED` + `accounts/adapter.py`, not a standalone `SIGNUP_OPEN`. The runbook at `docs/runbooks/panic-mode.md` includes:
  - **Flag reference table** — what each flag flipping False does
  - **Decision tree** — observed signal → primary flag → secondary flags → verification query. At minimum 4–6 rows: spam surge, regulator complaint, bot noise ingestion, legal notice, compromised account, infrastructure incident.
  - **Cache-TTL lag disclosure** — the 60s `get_flag` cache TTL means a flipped flag takes up to 60s to propagate. Maintainer must expect up to 60s lag, not instant effect.
  - **Social-cache cleanup** — Facebook/Discord/Telegram preview refresh URLs for OG-tag rollback scenarios (per 0.5 leftover §).
  - **Full-panic combination** = 0.4 posture, restorable in ≤60s + cache TTL.
- **`INGESTION_PAUSED` DB flag** — new seeded flag (default False). Replaces the settings-level `BOT_ENABLED` gate at `ingestion/bot.py:28`: `_bot_enabled()` changes from reading `settings.BOT_ENABLED` to reading `get_flag("INGESTION_PAUSED", default=False)` (inverted). `BOT_ENABLED` setting is removed in the same bead to prevent two-control drift. This is scope-sensitive: the bot code touches the ingestion daemon — include in test plan that the bot short-circuits when the DB flag is True.
- **Week-off runbook** — `docs/runbooks/week-off.md` per Phase 1.0 spec §Week-off runbook. Pre-departure checklist, what auto-heals, what to flip. Explicitly covers: background-task health-check query (per §Background tasks observability), which tasks MUST keep running unattended, and how the maintainer knows on return whether a nightly run silently failed.

### Out — explicit deferrals

- **All threshold *values* calibration** — numeric defaults ship as `3`/`5`; tuning happens in Bundle B from real data.
- **1.0 `SignupApplication` + admin-reviewed open signup** — decision-loaded UX, defer to Bundle C.
- **1.0 organizer self-edit (`OrganizerEdit`, `OrganizerUserLink`, re-review triggers)** — decision-loaded UX, defer to Bundle C.
- **1.0 bubble-bridging UI** — data-shape dependent, defer to Bundle C.
- **Logfire dashboards** — observability requires real traffic to design the right panels. Defer to Bundle C; basic Django logging + per-task logfire metric lines stay.
- **Trending `Signal` materialized table** — ship as annotated queryset with latency span; revisit on evidence (P95 > 200ms or ≥1k events).
- **Admin review-readiness screen** — deferred to Bundle B ops bead. Bundle A does not ship a decision-support UI for `EVENT_REVIEWS_DISPLAYED`.
- **Formal a11y audit** — deferred to Bundle C (new UI follows existing aria conventions in the interim).

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
    target_repr = CharField(max_length=200, help_text=(
        "Snapshot of target's human-readable label at action time. "
        "Preserved so audit rows remain interpretable after target deletion."
    ))
    action = CharField(max_length=20, choices=[
        ("no_action", "No action"), ("hide", "Hide target"),
        ("delete", "Delete review (soft)"), ("suspend", "Suspend organizer"),
        ("resolved", "Mark resolved"),
    ])
    reason = TextField(blank=True)
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]
```

Future DSA transparency-report source of truth. `target_id` is a *weak reference* — rows intentionally outlive their targets for audit retention. `target_repr` is captured at action time so a deleted event remains identifiable in the transparency log (otherwise the admin sees `("event", 42)` with no way to know what event 42 was).

### `reviews.Review` — soft-delete field added

```python
# Add to existing model:
hidden = BooleanField(default=False, db_index=True)
```

All review-display queries filter `hidden=False`. Admin "Delete review" action flips `hidden=True` rather than cascading through `Flag` (which has `on_delete=CASCADE`). This gives the maintainer a reversible action within the DSA 6-month internal-complaint-handling window (Art. 20) and preserves the flag trail for transparency reporting. Hard-deletion is off-menu in admin; reserved for direct DB access if ever needed.

### `core.FeatureFlag` — extended

```python
# Add to existing model:
numeric_value = IntegerField(null=True, blank=True,
    help_text="For threshold-style flags; None means boolean-only")

# Add to module:
def get_numeric(key: str, default: int) -> int:
    """Cached numeric-flag lookup; falls back to default if flag or value missing."""
```

**Cache coordination:** both `get_flag` and `get_numeric` project from a single `feature_flag_row:{key}` cache entry (whole-row cache, 60s TTL). `FeatureFlag.save()` and `delete()` invalidate that one key. Existing `feature_flag:{key}` callers migrate to the unified key in the same bead — no split-brain period.

Seed rows (via data migration — uses `get_or_create` with `defaults={...}` to preserve any admin-flipped runtime values on re-run):
- `threshold.organizer_ratings_display = 3`
- `threshold.event_ratings_display = 3`
- `threshold.auto_hide_flag = 3`
- `threshold.attendance_display = 5`
- `threshold.follower_display = 5`
- `EVENT_REVIEWS_DISPLAYED = False` (boolean)
- `TRENDING_SORT_ENABLED = True` (boolean)
- `INGESTION_PAUSED = False` (boolean)

### `events.Event` — `avg_rating` field added

```python
# Add to existing model:
avg_rating = FloatField(null=True, blank=True)
```

Symmetric with the existing `Organizer.avg_rating` field (present since Phase 0.5). Denormalized on `Event` so the step-7a event-card star chip (`★ 4.2 (N)`) reads a precomputed float instead of triggering one `Review.objects.filter(event=...).aggregate(Avg("rating"))` per card on `/events`. `recompute_aggregates` writes this alongside `rating_count` in the same transaction, keeping the two aggregates consistent.

### No other changes to existing models besides `Review` and `Event`

`Attendance`, `Organizer`, `Flag` are unchanged. All remaining Bundle A features compose on existing schema.

## URL + view additions

```
/me                                             → user profile (logged-in only)
/o/<slug>/?sort=recent|highest|lowest           → add query-param sort
/events/?sort=trending                          → add sort toggle
/events/?filter=following                       → (optional) "view all" from /events landing section
```

The `/me` unfollow button reuses the existing `organizer-follow` toggle endpoint; no new write URL. `/events/<org_slug>/<event_slug>/edit` and `/accounts/signup/` (open form) are explicitly Bundle C.

## Template deltas

- `cotton/event_card.html` — add star chip rendering block (gated).
- `events/detail.html` — narrow existing review-form gate; add reviews section (gated).
- `events/detail.html`, `organizers/detail.html` — add OG meta tags in `{% block og_meta %}` overrides.
- `events/list.html` — add sort toggle UI + "From organizers you follow" section.
- `organizers/detail.html` — upgrade reviews-section block.
- New template: `accounts/me.html`.

All new user-visible strings wrapped in `{% trans %}` per ADR-003 F6.

## Background tasks

- **`finalize_attendance`** (new, nightly 03:00 Europe/Berlin) — filter `status='published' AND hidden=False AND end < now()-24h`. Emits `logfire.info("finalize_attendance.done", updated_count=N, duration_ms=...)` on each run — a zero-count run with no exception still logs.
- **`recompute_aggregates`** (existing, **extended** in same bead as `finalize_attendance`) — `attendance_count` changes from `status='going'` to `status__in=('going','went')`. Emits `logfire.info("recompute_aggregates.done", event_count=N, ...)`.
- **`daily_flag_digest`** (existing) — add grouping by target + pre-filled admin URL params.

**Observability approach:** each nightly emits a count metric (`…updated_count`, `…event_count`) via `logfire.info`. The week-off runbook's "on return" checklist includes a logfire query to confirm each task ran at least once per day with sensible counts. No dedicated `BackgroundTaskStatus` model — that's the heavier option; count metrics are sufficient for solo-maintainer scale and can be upgraded later if needed.

## Test plan

**Shared test infrastructure (step 0):** add pytest fixtures (or factory-boy factories if introduced) for: `user_with_went_attendance`, `past_event(days_ago=N)`, `review_for_event_with_count(event, n)`, `organizer_with_rating_count(n)`, `organizer_with_follower_count(n)`. The repo currently uses direct ORM creates in tests; Bundle A introduces enough overlap that a thin shared-fixtures module pays back across 8+ beads. If the step-0 investment proves unnecessary (first 2 beads don't need it), drop it — per ADR-003 philosophy, don't abstract speculatively.

- **Trending sort**: fixture with 5 events (varied counts + dates) → assert ordering matches `score` formula. Flipping `TRENDING_SORT_ENABLED=False` removes the toggle.
- **`/me`**: follows, upcoming (future attendance), past (went + past) — three independent fixtures.
- **ModerationAction**: each admin action creates a row with correct `target_type`/`target_id`/`target_repr`/`action`. Hide-target action sets `.hidden=True` on the target. Delete-review action sets `Review.hidden=True` (soft-delete). Target-type action-menu subsets enforced in admin UI.
- **Threshold flag**: `threshold.organizer_ratings_display` flipped from 3→10 hides displays on `/o/<slug>` until new ratings accumulate. Whole-row cache invalidates correctly. `get_flag` and `get_numeric` on the same key project consistently.
- **Email digest**: mock 5 flags over 24h → 1 email with all 5, grouped by target, each row has pre-filled admin URL. Verify the admin URL resolves to the change_view with the `?action=` param pre-selected.
- **Review-gate**: user without `went` attendance → form hidden + direct POST → 429-style error partial (not bare 403). User with `went` → form renders + POST creates Review.
- **Event rating display gate**: `EVENT_REVIEWS_DISPLAYED=False` → hidden even with `rating_count=10`. Flipped True + count=2 → still hidden. True + count=3 → shown.
- **Auto-finalize attendance**: events with `end < now()-24h` and `status='going'` and `Event.status='published'` → `status='went'`. Events with `end=None` → skipped. Events with `Event.status='cancelled'` → skipped.
- **recompute_aggregates post-finalize**: past event with 3 `going` attendees, run `finalize_attendance` then `recompute_aggregates` → `event.attendance_count == 3` (not 0).
- **Event avg_rating**: event with 3 reviews of ratings (3, 4, 5) → after `recompute_aggregates`, `event.avg_rating == 4.0` and `event.rating_count == 3`. Event with 0 non-hidden reviews → `event.avg_rating` stays `None` (or is set to `None`).
- **Rate limits**: 6th flag in an hour → 429 with rendered error partial. 11th review in a day → 429 partial. Staff user → bypass; 100 requests succeed. Rate-limit bypass for staff uses custom key function.
- **Cache-TTL mid-flip**: flip `RATINGS_ENABLED=False`; in-flight cached read can return stale True for up to 60s (documented, not a bug). Test asserts 60-second-or-less propagation bound.
- **Panic mode**: `docs/runbooks/panic-mode.md` renders; all flags listed with effect; decision tree includes ≥4 scenarios; combined state restores 0.4 posture in integration test.
- **OG tags**: detail page with `PUBLIC_READ_ENABLED=True` renders `og:title/description/image`; `=False` omits them entirely. Template uses `{% block og_meta %}` (not `og`).
- **Bot flag integration**: with `INGESTION_PAUSED=True`, `_bot_enabled()` returns False and bot short-circuits. With `INGESTION_PAUSED=False`, bot runs normally.

## Rollback

Per-feature kill-switches:
- `TRENDING_SORT_ENABLED=False` → chronological-only, toggle hidden.
- `EVENT_REVIEWS_DISPLAYED=False` → event reviews collected, display hidden. (Default state.)
- `RATINGS_ENABLED=False` → review form hidden on event + organizer pages.
- Rate limits disabled via `RATELIMIT_ENABLE=False` (django-ratelimit env).
- `INGESTION_PAUSED=True` → bot short-circuits.
- `/me` isn't flag-gated (logged-in-only, low blast radius); remove route if broken.

Cache-TTL lag (60s) applies to all DB-flag flips.

## Shipping order (suggested bead structure)

0. **Test-fixtures scaffold** — shared pytest fixtures/factories for `went`-attendance users, past events, review fixtures. Tiny bead; drop if first two beads show no reuse.
1. **Schema + config + first consumer** — `ModerationAction` model (w/ `target_repr`), `Review.hidden`, `Event.avg_rating` (symmetric with existing `Organizer.avg_rating`; required by step-7a event-card star chip), `FeatureFlag.numeric_value` + unified whole-row cache + `get_numeric` helper, data migration seeding flag rows, AND the `AUTO_HIDE_FLAG_THRESHOLD` call-site replacement in `reviews/views.py:148,157`. Step 1 also extends `recompute_aggregates` to write `avg_rating` alongside `rating_count` so the two aggregates stay consistent (the going→went change to `attendance_count` stays in step 3 with `finalize_attendance`). Step 1 ships the first consumer alongside the infra so `numeric_value` is not dead code.
2. **OG tags** — smallest, unblocks full public-read flip when ready.
3. **Auto-finalize attendance + `recompute_aggregates` extension** — these ship together to prevent the `attendance_count=0` bug. Unblocks `/me` past-attendances and 0.7 review-gate.
4. **`/me` + followed-organizer section** — pure composition on existing models.
5. **Trending sort + UI toggle + logfire span** — queryset annotation + filter-chip wiring + observability instrumentation.
6. **Moderation tooling** — split into two beads to reduce WIP size:
   - **6a.** `ModerationAction` admin actions — `FlagAdmin.change_view` buttons, per-target-type action menu, reversible soft-delete, suspend-organizer parity. (Schema already in step 1.)
   - **6b.** Email digest enhancements — grouping by target, pre-filled admin URLs with `?action=` param. Depends on 6a shipping the change_view param-consumption code.
7. **0.7 event-review display + review-gate** — flag-gated, default off. Split to manage size:
   - **7a.** Display gates — event card star chip (`events/list.html` + `cotton/event_card.html`), event reviews section (`events/detail.html`), both dual-gated on flag + threshold.
   - **7b.** Authorship gate — narrow existing review-form conditional to require `Attendance(went)`; direct-POST returns error partial.
8. **Rate limiting + `INGESTION_PAUSED` migration** — django-ratelimit across write endpoints (flag/review/signup/takedown) with staff bypass + `block=False` + error-partial 429s; `INGESTION_PAUSED` flag replaces `BOT_ENABLED` setting at `ingestion/bot.py:28`.
9. **Runbooks** — split into two beads:
   - **9a.** `panic-mode.md` — flag reference table + decision tree (≥4 scenarios) + cache-TTL lag disclosure + social-cache cleanup URLs. Depends on all flag-gated features shipping (1, 7, 8).
   - **9b.** `week-off.md` — pre-departure checklist, background-task health-check query (depends on step 3's logfire metric), auto-heal inventory.

Steps 2–9 parallelize heavily once step 1 lands. Splitting 6, 7, 9 into half-beads (6a/6b, 7a/7b, 9a/9b) raises the nominal count from 9 to 12 — still within Bundle A's budgeted footprint. ADR-005 D1's A1/A2 split escape hatch remains available if the actual implementation lands over-budget.

## Go-signal for Bundle A

All steps shipped, review passed, tests green. No traffic gate — Bundle A is a pure code deliverable. Maintainer flips `PUBLIC_READ_ENABLED=True` whenever the Bundle B ops tasks are satisfied.

## What comes after

- **Bundle B** (ops, no design doc — just open beads): event entry, legal copy review, `PUBLIC_READ_ENABLED=True` flip, 2-week soak, threshold calibration, admin review-readiness query/screen (decision-support for flipping `EVENT_REVIEWS_DISPLAYED`).
- **Bundle C** (design after Bundle B observation): 1.0 admin-reviewed signup, organizer self-edit, bubble-bridging, Logfire dashboards, formal a11y audit. Drafted when maintainer has 1+ week of public-read data to inform UX decisions.

## Revision log

- 2026-04-21 — Initial draft (brainstorm output).
- 2026-04-22 — Reconciliation after partial WIP audit: `Event.avg_rating` field documented (symmetric with existing `Organizer.avg_rating`; added during step-1 WIP to support step-7a event-card star chip without N+1 aggregates on `/events`). Step-1 description and test plan updated accordingly. `recompute_aggregates` avg-computation is step-1 scope; the going→went `attendance_count` extension remains step-3. Beads kb-8qn.1 / .2 / .3 are complete; `/send-it` resumes on kb-8qn.4 onward.
- 2026-04-21 — `/send-it` review passes 1–2 folded in (autonomous mode). Load-bearing amendments: soft-delete `Review.hidden` for DSA reversibility; `ModerationAction.target_repr` captured at creation; `recompute_aggregates` extended in same bead as `finalize_attendance` to prevent `attendance_count=0` regression; unified `feature_flag_row:{key}` cache to coordinate `get_flag`/`get_numeric`; `AUTO_HIDE_FLAG_THRESHOLD` call-site replacement bundled into step 1; flag-naming convention codified (UPPERCASE booleans, `threshold.*` numerics); `INGESTION_PAUSED` DB flag replaces `BOT_ENABLED` setting; rate-limit rewrite acknowledged (deletes hand-rolled code + test); 429 response shape specified (`block=False` + error partial); steps 6, 7, 9 split into a/b sub-beads; step 0 test-fixtures scaffold added; admin readiness screen deferred to Bundle B; formal a11y audit deferred to Bundle C. No ADR-005 decisions overturned; ADR-005 D1's A1/A2 escape hatch remains available but is not being exercised pre-implementation.
