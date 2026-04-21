# Fixes: phase-0.5-public-legal-design

Date: 2026-04-21
Review passes: 2 (pass 2 reviewers stalled before full completion; pass 1 findings consolidated)

Epic: kb-a4t. Commits under review: 4606453, 58efa69, 60bbf39, be9fe27, fb15fc0, 66eef05, c00fae1, 3261565, ee24902.

## Critical

- **reviews/views.py:269-273 — `organizer_opt_out_view` authorization flaw (IDOR).**
  The view matches `ApprovedSender.objects.get(telegram_user_id=X)` independently from
  `Organizer.objects.get(slug=Y)`, never verifying the sender is linked to that organizer.
  Any approved Telegram sender can suspend any organizer by submitting that organizer's
  public slug. This defeats the "bot-verified, not spoofable" claim in the design doc (line 35)
  and fails the GDPR identity-verification promise.
  Fix: enforce the linkage. Replace the two-step lookup with a single query that requires
  `ApprovedSender.telegram_user_id=X` AND the sender's approved organizer linkage matches the
  submitted `organizer_slug`. If `ApprovedSender` does not yet have an `organizer` FK, fall
  back to verifying via `Organizer.telegram_channel` ↔ approved sender linkage already
  persisted at approval time. Document the fallback path in the view if the ApprovedSender
  model has no direct FK.

- **accounts/adapter.py:15 — `NoSignupAdapter` reads removed `settings.INVITES_ENABLED`.**
  kb-a4t.1 migrated `INVITES_ENABLED` from an env var to a `FeatureFlag`, and kb-a4t.2 removed
  the env-var definition from `a_core/settings.py`. The adapter still reads
  `getattr(settings, "INVITES_ENABLED", True)` — which silently defaults to `True` because
  the attribute no longer exists on `settings`. Flipping `INVITES_ENABLED=False` in the admin
  does nothing. This is a broken kill-switch (ADR-003 F9 compliance) and a concrete risk if
  an operator relies on this flag to stop signups.
  Fix: `from a_core.models import get_flag` in the adapter; replace the `getattr(...)` call
  with `get_flag("INVITES_ENABLED", default=True)`.

- **reviews/views.py:138-154 — `flag_target` auto-hide race + missing `transaction.atomic()`.**
  The sequence `Flag.objects.create → Flag.objects.filter(...).count() → Event.update(hidden=True)`
  is not atomic. Two concurrent flag submissions for the same target at the 2-flag mark can
  both read `count == 2`, neither trigger `hidden=True`, and leave the target unhidden until
  a 4th flag arrives. The adjacent `submit_review` view correctly wraps its equivalent sequence
  in `transaction.atomic()` (line 54) — `flag_target` was missed. The per-user 10/day counter
  has the same atomicity gap (count→create can race).
  Fix: wrap the Flag creation through the auto-hide update in `with transaction.atomic():`.
  Consider `select_for_update()` on the Event/Organizer row if multi-process contention is
  anticipated. For the 10/day counter, either move the check+create into the same atomic block
  or accept the small race as out-of-scope (more important to fix the auto-hide path).

- **a_core/models.py — `get_flag` cache never invalidated on `FeatureFlag.save()`.**
  The helper caches the flag lookup for 60s. No `post_save` signal, no `save()` override, no
  admin `save_model` hook clears the cache. After toggling `PUBLIC_READ_ENABLED=False` in the
  admin, public routes continue serving for up to 60s per worker process. With the default
  `LocMemCache`, each gunicorn worker has its own cache — so flips propagate per-worker at
  TTL boundaries, not in lockstep. The design doc repeatedly describes `PUBLIC_READ_ENABLED`
  as a rollback mechanism and claims "correct by construction" — the cache gap breaks that.
  Fix: override `FeatureFlag.save()` and `FeatureFlag.delete()` to call
  `cache.delete(f"feature_flag:{self.key}")`. If `LocMemCache` is retained, either drop the
  TTL to 5–10s or document the per-worker propagation window in the runbook.

- **tests/integration/test_phase_0_4_auth.py and test_phase_0_4.py — stale `settings.MAP_ENABLED` / `settings.INVITES_ENABLED` refs.**
  Tests still reference `settings.MAP_ENABLED` (test_phase_0_4_auth.py:188) and
  `hasattr(settings, "INVITES_ENABLED")` (test_phase_0_4.py:563). Post-kb-a4t.1 these
  attributes are gone. `assert settings.MAP_ENABLED is True` will AttributeError; the
  `hasattr(...)` check will silently flip to False. Tests must migrate to `get_flag`.
  Fix: replace direct `settings.<FLAG>` reads with `get_flag("<FLAG>")` calls. Tests that
  want to override the flag should do so via `FeatureFlag.objects.filter(key=...).update(enabled=...)`
  + `cache.clear()` (matching the existing Phase 0.5 test pattern).

## Important

- **reviews/views.py:122 — timezone bug in `flag_target` rate limit (UTC vs Berlin).**
  `timezone.now().replace(hour=0, ...)` produces UTC midnight, not `Europe/Berlin` midnight.
  A user can submit 10 flags just before UTC midnight and 10 more just after — staying inside
  a single Berlin calendar day but bypassing the daily cap. The test at
  reviews/test_flags.py:720 replicates the bug (so it passes against broken code).
  Fix: `today_start = timezone.localtime(timezone.now()).replace(hour=0, minute=0, second=0, microsecond=0)`
  — the aware arithmetic converts to local time for the day boundary. Update the test to
  confirm behavior across the UTC-but-not-Berlin-midnight edge.

- **pages/views.py:31 — open redirect in `age_check_view` via protocol-relative `next` URL.**
  `if not next_url.startswith("/")` does NOT block `//evil.com` — it starts with `/` and
  browsers will follow it as `https://evil.com`. An attacker crafts `/age-check/?next=//evil.com`,
  the user confirms age, and gets silently redirected off-site.
  Fix: use Django's `url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure())`.
  Fallback `next_url = "/"` on failure (the existing fallback is correct; only the guard is weak).

- **pages/views.py:46 — duplicate `User-agent: *` block in `robots.txt`.**
  Current public content is two `User-agent: *` stanzas (Allow: / ; then Disallow: /admin/).
  Per RFC 9309, most crawlers apply the MOST-SPECIFIC matching group, so some may honor only
  the first block and ignore the admin disallow.
  Fix: single stanza — `User-agent: *\nAllow: /\nDisallow: /admin/\n`.

- **organizers/views.py:22,32 — organizer_profile uses reverse FK filter instead of `Event.objects.visible()`.**
  Upcoming/past events query `organizer.events.filter(hidden=False, ...)` instead of
  `Event.objects.visible().filter(organizer=organizer, ...)`. Design doc line 76 explicitly
  lists organizer_profile (both upcoming and past events querysets) as an entry point for
  `.visible()`. Functionally equivalent today; silently drifts if `.visible()` later gains
  additional filters (e.g. organizer__status__in=[approved]).
  Fix: swap both queries to `Event.objects.visible().filter(organizer=organizer, ...)`.

- **reviews/views.py (organizer_opt_out) — no rate limit.**
  The takedown form has `@ratelimit(key="ip", rate="5/h", block=True)`. The opt-out form has
  nothing. Combined with the IDOR (critical #1), an attacker could enumerate
  telegram_user_id ↔ organizer_slug pairs or just spam suspensions.
  Fix: add `@ratelimit(key="ip", rate="3/h", method="POST", block=True)` to organizer_opt_out_view.
  After the IDOR fix, this is defense in depth — with the IDOR fix alone an enumeration attack
  still wastes cycles.

- **reviews/views.py:178 — takedown rate-limit response is 403, not 429.**
  Design doc test plan (line 187) specifies "6th submission from same IP within an hour → 429".
  Code returns `status=403`. Two tests (test_phase_0_5.py and test_flags.py) assert 403 —
  so the tests match the broken code. 429 is the semantically correct status for rate limiting.
  Fix: change the response in `takedown_view` rate-limit branch to `status=429`; update the
  two corresponding tests to assert 429.

## Minor

- **tests/integration/test_phase_0_5.py:634-636 — `test_rollback_x_robots_header` asserts header presence, not value.**
  Header can silently drift to wrong text while the test passes. Assert the value is
  `"noindex, nofollow, noarchive"`.

- **ingestion/management/commands/schedule_tasks.py:11-26 — `get_or_create` won't update stale schedules.**
  If `func` path or `schedule_type` changes later, re-running the command leaves the old row.
  Fix: switch to `update_or_create` with `defaults={"func": ..., "schedule_type": ...}`.

- **ingestion/tasks_flags.py:54-73 — `recompute_aggregates` is O(N) queries with no batching.**
  Acceptable at current Berlin scale; flag as a known-hot path for 0.6/0.7 if event count grows.

- **a_core/settings.py (console backend branch) — no explicit `DEFAULT_FROM_EMAIL`.**
  When SMTP env vars are missing, Django falls back to `webmaster@localhost`. `EmailFailure.recipient`
  records this placeholder — confusing in logs.
  Fix: set `DEFAULT_FROM_EMAIL = "Kinky Bubbles <noreply@localhost>"` (or similar) explicitly
  in the console-backend branch.

## Deferred (filed or tracked, not in this fix bead)

- Reviews app hosts cross-app `takedown_view` + `organizer_opt_out_view` (architectural smell).
  Decision: defer to a later layering pass; current coupling is explicit and documented.
- `recompute_aggregates` + `daily_flag_digest` live in `ingestion` (cross-app coupling).
  Decision: defer; move when a second moderator task forces the split.
- `/hx/test-partial`, `/hx/test-skeleton` reachable only via login wall. Probably DEBUG-gated.
  Follow-up: bead to guard these with `if settings.DEBUG:` in `pages/urls.py`.
- `/admin/` not in ALWAYS_PUBLIC → double redirect. Documentation-only item.
- `Flag.review` branch has no view path. Cheap foresight per ADR-003 F2; deferred to 0.7.
- Daily digest + takedown email recipient is `DEFAULT_FROM_EMAIL`. Add `DSA_INBOX_EMAIL` setting in 0.6.
- Event/organizer autohide has no automated un-hide path when `Flag.resolved=True` flips.
  Design doc does not promise this for 0.5 (email-digest triage); deferred to 0.6 moderation console.
- `MIN_RATINGS_FOR_DISPLAY` / `AUTO_HIDE_FLAG_THRESHOLD` hard-coded as module constants rather
  than FeatureFlags. Design doc explicitly allows either. Deferred unless operator asks.

## ADR Updates

No ADR updates required. The critical findings correct implementation drift from existing
FIRM decisions (ADR-003 F9 "single read path, single toggle mechanism"; design-doc rollback
semantics). The architectural smells that would warrant ADR work (layering of reviews app,
cross-app task placement) are deferred.

## Discarded

- "MIN_RATINGS_FOR_DISPLAY and AUTO_HIDE_FLAG_THRESHOLD should be FeatureFlags" — design doc
  line 140-141 explicitly permits either form. No violation.
- "Takedown resolver strips external host prefix and treats path-only" — this is correct behavior
  (DSA takedown is about content on this site; external URLs that don't map are rejected).
- "daily_flag_digest bare `except Exception`" — Python's Exception excludes SystemExit/KeyboardInterrupt.
  Acceptable; not flagged.
- "flag_target midnight-local vs 24h-rolling window" — acceptable UX for 0.5; rolling window is nice-to-have.

## Autonomous triage notes

- Pass 2 reviewers stalled before returning findings. The fix list draws exclusively from
  pass 1. Given the volume of Critical/Important items already identified, the marginal return
  on retrying pass 2 is low; proceeding with the fix bead is the correct call.
- No ADR conflicts surfaced by pass 1 required escalation — the `INVITES_ENABLED` migration
  gap is an implementation bug, not an ADR challenge.
