# Fixes: bundle-a-post-0.5-code-sprint
Date: 2026-04-22
Review passes: 2 (architecture + implementation each pass)

## Critical

- **a_core/context_processors.py:6** — `EVENT_REVIEWS_DISPLAYED` and `EVENT_RATING_THRESHOLD` are not in the context processor, but `cotton/event_card.html:34` checks both. Result: star chips never render on organizer profile (`/o/<slug>/`), `/me`, or any page other than `/events/` (which injects them directly). Fix: add `EVENT_REVIEWS_DISPLAYED: get_flag("EVENT_REVIEWS_DISPLAYED", default=False)` and `EVENT_RATING_THRESHOLD: get_numeric("threshold.event_ratings_display", default=3)` to `feature_flags()`. Import `get_numeric` from `a_core.models`.

- **ingestion/tasks_flags.py:142,157** — `recompute_aggregates` computes `rating_count` and `avg_rating` using `Review.objects.filter(event=event)` and `filter(organizer=org)` without `hidden=False`. Soft-deleted reviews inflate both aggregates. The star-chip display gate `event.rating_count >= EVENT_RATING_THRESHOLD` can remain triggered after moderation. Fix: add `.filter(hidden=False)` to both aggregate queries.

- **reviews/views.py:130–131** — `submit_review` event branch updates only `rating_count`, not `avg_rating`. The organizer branch (lines 94–100) updates both. Users see an immediate count increase but a stale `★` value on event cards until the next nightly `recompute_aggregates`. Fix: add `avg=Avg("rating")` to the aggregate and update `Event.avg_rating` in the same `update()` call (mirror organizer path).

- **templates/events/_event_drawer.html:30** — The review form gate reads `{% if user.is_authenticated and user.is_approved and event_past and RATINGS_ENABLED %}` but does NOT include `and user_has_went_attendance`. Users who never attended can see the form on the map-drawer popup (the server-side check in `submit_review` blocks the POST, but the UI is wrong). Fix: add `and user_has_went_attendance` to the condition, and compute it in the `event_drawer` view the same way `event_detail` does.

- **reviews/models.py:96–107** — `Flag` has no `UniqueConstraint` on `(reporter, event)` or `(reporter, organizer)`. A single authenticated user can submit multiple flags against the same target within the rate-limit window (5/h), and all submissions count independently toward the auto-hide threshold (default 3). One malicious approved user can solo-trigger auto-hide in under a minute. Fix: add `UniqueConstraint(fields=["reporter","event"], condition=Q(reporter__isnull=False, event__isnull=False), name="one_flag_per_reporter_per_event")` and the analogous constraint for organizer/review to `Flag.Meta.constraints`. Use `get_or_create` in `flag_target` to gracefully handle the duplicate attempt.

- **reviews/admin.py:83–116** — `process_action` writes three separate DB objects (ModerationAction, target side-effect, flag.resolved) with no `transaction.atomic()`. If any write fails mid-sequence, the state is partial — e.g., ModerationAction recorded but target not hidden, or target hidden but flag still shows in digest. Fix: wrap the entire action block in `with transaction.atomic():`.

## Important

- **reviews/views.py:179–181,190–192** — Auto-hide flag count (`auth_flag_count`) does not filter `resolved=False`. Flags that a moderator already cleared (marked resolved/no_action) continue inflating the count forever. If an admin un-hides an event, future single new flags can immediately re-trigger auto-hide because old resolved flags still count. Fix: add `resolved=False` to both `Flag.objects.filter(event=event, reporter__isnull=False)` and the organizer equivalent.

- **organizers/views.py:57** — Uses imported `MIN_RATINGS_FOR_DISPLAY` constant from `reviews.views` instead of `get_numeric("threshold.organizer_ratings_display", default=3)`. Flipping the DB flag has no effect on organizer profile display threshold — it stays hardcoded at 3. Fix: replace `show_rating = rating_count >= MIN_RATINGS_FOR_DISPLAY` with `show_rating = rating_count >= get_numeric("threshold.organizer_ratings_display", default=3)`. Update the guard test at `reviews/test_flags.py:1014` that currently prevents removing the constant.

- **accounts/views.py:50–59** — `past` queryset in `me_view` is missing `event__hidden=False`. Hidden events (auto-hidden by flags or admin DSA action) appear in a user's past-attendances list. Inconsistent with the `upcoming` queryset which correctly filters `event__hidden=False`. Fix: add `event__hidden=False` to the `past` Attendance filter.

- **accounts/views.py:34–38** — `OrganizerFollow` queryset in `me_view` does not filter `organizer__hidden=False` or `organizer__status="approved"`. Suspended organizers appear in the followed list with live links. Fix: add `organizer__hidden=False, organizer__status="approved"` to the followed queryset.

- **events/views.py:38–62** — `logfire.span("events.trending_query")` wraps only the queryset annotation (lazy — no DB I/O). Actual query execution happens at `paginator.get_page()` on line 119, outside the span. The latency tripwire (design doc §Trending sort: "revisit materialization if P95 > 200ms") will show sub-millisecond values always, making the metric useless. Fix: wrap the span around the paginator call (line 119), or force eager evaluation inside the span with `list(qs)` before returning it.

- **events/views.py:38–62** — Trending sort has no deterministic tiebreaker. Two events with identical `trending_score` float values produce undefined paginator order (same event can appear on page 1 AND page 2). Fix: `.order_by("-trending_score", "-start", "pk")`.

- **ingestion/management/commands/schedule_tasks.py:29** — Comment says `recompute_aggregates` "Must run AFTER finalize_attendance" but `DAILY` schedule type has no ordering guarantee relative to the cron-based `finalize_attendance`. The code is functionally correct (`status__in=('going','went')` makes ordering moot), but the comment is misleading. Fix: either change `recompute_aggregates` to an explicit cron `"30 2 * * *"` (30 min after finalize) and update the comment to say "scheduled to run 30 min after finalize_attendance", OR remove the ordering comment entirely and add a note explaining why ordering is no longer required.

- **reviews/admin.py:83** — `process_action` is missing HTTP method enforcement. A crafted GET from a staff session won't trigger side-effects (because `request.POST.get("action")` returns `None` → `HttpResponseBadRequest`), but the contract is implicit. Fix: add `from django.views.decorators.http import require_POST` and decorate `process_action` with `@method_decorator(require_POST)`.

- **ingestion/tasks_flags.py:15–25 + reviews/admin.py:14–18** — `_suggest_action` and `ALLOWED_ACTIONS` are independently maintained constants that must stay in sync. If a new target type or action is added to one, the other silently drifts. Fix: import `ALLOWED_ACTIONS` from `reviews.admin` in `tasks_flags.py` and have `_suggest_action` assert its return value is in `ALLOWED_ACTIONS.get(target_type, set())`.

- **reviews/test_flags.py:712–748** — Duplicate rate-limit test. The design doc specified this test should be deleted when hand-rolled rate limiting was replaced by `django-ratelimit`. The new canonical test is in `reviews/test_rate_limits.py`. Fix: delete the duplicate `test_flag_target_rate_limit_per_hour` from `reviews/test_flags.py`.

## Minor

- **a_core/settings.py:29** — `SITE_URL = os.environ.get("SITE_URL", ...)` is inconsistent with the rest of the file which uses `env = Env()` / `env.str(...)`. Fix: `SITE_URL = env.str("SITE_URL", default="http://localhost:8000")`.

- **a_core/migrations/0005_seed_bundle_a_flags.py:35–37** — Redundant dependency on `("a_core", "0003_seed_featureflags")` — already transitive via `0004`. Fix: remove the `0003` line from `dependencies`.

- **templates/_base.html + templates/events/detail.html + templates/organizers/profile.html** — OG meta block is double-gated: `_base.html` wraps `{% block og_meta %}` in `{% if PUBLIC_READ_ENABLED %}`, and child templates repeat the same condition around their content. One gate is redundant. Fix: remove the `{% if PUBLIC_READ_ENABLED %}` wrapper from child templates and let the base gate be the single enforcement point.

- **a_core/urls.py:16** — `path('accounts/signup/', RateLimitedSignupView.as_view(), name='account_signup')` declares the same URL name as allauth's internal `account_signup`. Django's last-registered wins for `reverse()`, which can diverge from the first-match-wins routing. Fix: give the override a stable internal name (e.g., `name="account_signup"`) and explicitly exclude the allauth signup path from the include, or use `namespace=` on the allauth include to isolate its names.

- **ingestion/tasks_flags.py:42** — `unresolved[:50]` silently truncates. Email header reports the full unresolved count but body shows at most 50 entries. A maintainer sees "Unresolved flags: 73" with only 50 entries below. Fix: append `f"\n… and {count - 50} more. Visit admin to see all."` after the loop when `count > 50`.

- **a_core/models.py:89** — `ModerationAction.target_id = IntegerField()` overflows at 2.1B rows. Events and other models use `BigAutoField`. Fix: change to `BigIntegerField()` and add a migration. Trivial now; painful later.

## Scope Gap (surface for alignment)

- **Organizer reviews UI upgrade** — The design doc (line 54) specifies a dedicated sortable reviews section on `/o/<slug>/` gated by `threshold.organizer_ratings_display`. No bead was created for this, and `organizers/views.py` still uses the old sidebar / single-review pattern. Either implement the sortable reviews section, or explicitly de-scope from Bundle A with a design-doc amendment and file a follow-up bead.

- **Re-submission of a hidden review** — `submit_review` uses `update_or_create` with `defaults={"rating":..., "body":...}` but no `hidden=False`. If a user re-submits after their review was hidden by moderation, the content updates but `hidden` stays `True` (user gets 200 with no feedback). Correct policy is ambiguous: restoring visibility on edit may conflict with DSA moderation intent. Needs explicit policy decision before implementing a fix.

## ADR Updates
No ADR changes needed. All critical/important findings are implementation gaps vs. the Bundle A design doc's own stated conventions — none contradict FIRM ADR decisions.

## Discarded
- **Cache bypass via queryset.update()** — Only occurs in test helpers that intentionally bypass ORM save() hooks to simulate stale state; production writes go through Django admin forms which call save(). Not a real production bug.
- **Staff bypass on IP-keyed rate limits (signup, takedown)** — Design doc says "user-keyed" limits get staff bypass. IP-keyed limits intentionally do not — this is correct behavior, not an oversight.
- **Organizer suspend path via post_save signals** — No post_save signals are currently wired to Organizer; the divergence between .update() and .save() is purely theoretical until signals exist. Premature fix.
- **N+1 in recompute_aggregates** — Explicitly acceptable per ADR-003 evidence-based philosophy at solo-maintainer scale. The logfire metric will surface it when it matters.
- **RawSQL injection risk in trending sort** — Verified safe: uses parameterized `%s` binding, not string interpolation.
- **RATELIMIT_ENABLE handling in RateLimitedSignupView** — Verified correct: django-ratelimit checks the setting internally before recording.
- **avg=None in recompute_aggregates** — Verified correct: FloatField(null=True) accepts None → NULL.
- **429 vs 403 for non-attendee review gate** — Bead spec explicitly says `status=429` to maintain HTMX swap compatibility with `_rating_form.html`. Intentional, documented.
- **_derive_target with all-null flags** — Data integrity edge case blocked by CheckConstraint on new rows; pre-constraint data handled gracefully (no action buttons shown). Not a code bug.
