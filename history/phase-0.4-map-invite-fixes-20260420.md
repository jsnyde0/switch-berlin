# Fixes: phase-0.4-map-invite
Date: 2026-04-20
Review passes: 2

## Critical

- **static/js/events/bridge.js:30-32** — `events:attendance-changed` listener dispatches `events:filter-changed`, which re-reads `#markers-data` from the DOM — but the attend POST only swaps the attend button div, never refreshing `#markers-data`. The map reads stale GeoJSON and never updates after attendance changes. Fix: the `events:attendance-changed` handler should trigger an HTMX re-fetch of `#event-list` (which contains `#markers-data`) via `htmx.ajax('GET', window.location.href, { target: '#event-list', swap: 'innerHTML' })`, or fetch marker data from a dedicated endpoint.

- **static/js/events/map.js:49-79** — Map layer filters only show pins for `privacy == 'public'` and circles for all non-public. When a going user has a private venue with exact coords (`blur_radius_m: null`), `['coalesce', ['get', 'blur_radius_m'], 1000]` falls back to 1000, drawing a misleading 1000m circle around the exact location instead of a pin. Fix: update `privacy-circles` filter to require `blur_radius_m > 0`, and `event-markers` filter to include private venues where `blur_radius_m` is null: `['any', ['==', ['get', 'privacy'], 'public'], ['!', ['has', 'blur_radius_m']]]`.

- **events/views.py:216-242, organizers/views.py:48-63** — `event_attend` and `organizer_follow` use `@login_required` but do not check `is_approved`. They rely solely on `LoginWallMiddleware` which will be relaxed when public browse is added at 0.5. Write endpoints must enforce their own authorization. Fix: add an `is_approved or is_staff` check at the top of both views (or create a shared `@approved_required` decorator). Return 403 for unapproved users.

## Important

- **organizers/views.py:39-44** — `organizer_profile` does not compute or pass `going_venue_id_list` to template context. Private venue names always show as "Private venue" on organizer profiles even for users with `going` attendance. Fix: add the same `going_venue_ids` computation from `event_list` (lines 106-113 of events/views.py) to `organizer_profile` and pass `going_venue_id_list` in context.

- **templates/events/_event_drawer.html** — Drawer lacks attend button. The designed flow is: click pin → see drawer → mark going → map updates with exact coords. Without attend button in drawer, users must navigate to detail page. Fix: include `_attend_button.html` in the drawer template for authenticated users, passing `event`, `attendance`, `event_past` from the `event_drawer` view context.

- **events/views.py:194-201** — Two redundant DB queries for Attendance in `event_detail`. Fix: single `.get()` call, derive `user_going` from the result: `user_going = attendance is not None and attendance.status == "going"`.

- **accounts/management/commands/generate_invite_codes.py:17** — `User.objects.get(username=...)` raises raw `DoesNotExist` with full traceback. Fix: wrap in `try/except` and `raise CommandError(f"User '{username}' does not exist.")`.

- **tests/integration/test_phase_0_4.py** — Missing positive test case: private venue name shown on detail page and drawer for users WITH `going` attendance. Only the negative case (hidden without going) is tested. Fix: add `test_private_venue_name_shown_in_detail_for_going_user` and `test_private_venue_name_shown_in_drawer_for_going_user`.

- **templates/events/detail.html:64** — Attend button is gated on `MAP_ENABLED`, coupling attendance to map feature flag. Design doc rollback section treats them as separate concerns. Fix: remove `MAP_ENABLED` from the attend button guard (keep `user.is_authenticated` only). Attendance should work independently of the map.

- **templates/cotton/navbar.html:57-65** — Unauthenticated `<li>` elements are outside a `<ul>`, invalid HTML. Fix: wrap in `<ul class="menu menu-sm">` to match the authenticated branch structure.

## Minor

- **venues/serializers.py:61** — `hashlib.md5(venue.slug.encode())` missing `usedforsecurity=False`. Would crash on FIPS-compliant systems. Fix: add `usedforsecurity=False` parameter.

- **accounts/admin.py:8-13** — `CustomUserAdmin` missing `is_approved` in `list_filter`. Staff cannot easily find unapproved users for the approval queue. Fix: add `list_filter = UserAdmin.list_filter + ("is_approved",)`.

- **organizers/models.py:59-70** — `OrganizerFollow` missing `__str__` method (inconsistent with `Attendance` and `InviteCode`). Fix: add `def __str__(self): return f"{self.user} follows {self.organizer}"`.

## ADR Updates

- No ADR changes needed. All findings are implementation-level; none require revising ADR decisions.

## Design Doc Updates

- **Line 110**: Update serializer signature from `venue_to_geojson(venue, *, user=None)` to `venue_to_geojson(venue, *, going_venue_ids=None)` to match the implemented (better) API.
- **Line 140**: Update atomic redemption section to reflect the lenient approach actually implemented: log warning and continue on race (allauth's `save_user` cannot safely reject after user creation without causing 500s). Staff reconcile manually at 0.4 scale.

## Discarded

- **neighborhood_blur indistinguishable from public in templates**: No address field is rendered anywhere, so suppression is vacuously satisfied. Not a bug.
- **N+1 marker serialization**: Architecturally correct — map needs all markers. Not a bug.
- **unique_together deprecated**: Cosmetic; codebase uses both patterns. Not worth changing now.
- **_attend_button.html lacks {% load event_tags %}**: Latent issue, not a runtime bug. Template doesn't use event_tags currently.
- **Test fixture duplication**: Maintenance concern, not a correctness issue.
- **is_open_for_signup double DB query**: Negligible at scale, intentional double-check.
- **Pagination implicit context dependency**: Cotton inherits parent context by design.
- **InviteCodeAdmin list_filter UX**: Functional at current scale (5-15 users).
- **HX-Trigger unconsumed on detail page**: Correct behavior, no map to update there.
- **going_venue_ids query when MAP_ENABLED=False**: Minor performance waste, not worth fixing at 0.4 scale.
- **Middleware ordering comment**: Too minor.
- **Invite code race condition — reject vs lenient**: Beadify pass 4 deliberately changed to lenient because raising ValidationError from allauth's save_user causes 500. The implementation is correct; design doc updated to match.
