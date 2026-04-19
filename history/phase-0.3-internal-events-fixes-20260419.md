# Fixes: phase-0.3-internal-events
Date: 2026-04-19
Review passes: 2

## Critical

- **accounts/middleware.py:16,26-27** — Login-wall uses exact path matching (`request.path not in PUBLIC_PATHS`), blocking allauth sub-paths needed for password reset (`/accounts/password/reset/`, `/accounts/password/reset/key/...`, `/accounts/confirm-email/...`). A staff user who forgets their password is locked out. **Fix:** Change `PUBLIC_PATHS` to prefix matching. Replace the set with: `PUBLIC_PREFIXES = ("/accounts/", "/healthz", "/robots.txt")` and the check with `any(request.path.startswith(p) for p in self.PUBLIC_PREFIXES)`. Using `/accounts/` as a prefix is safe because allauth handles its own authorization internally, and the login-wall's `is_staff` check still gates all non-auth routes.

- **events/views.py:100-106** — `event_detail` queries by `slug` alone, but `Event.slug` is only unique per-organizer (`UniqueConstraint(fields=["organizer", "slug"])`). Two organizers with events sharing a slug causes `MultipleObjectsReturned` → unhandled 500. **Fix:** Replace `get_object_or_404(...)` with: `qs = Event.objects.filter(slug=slug, status="published").select_related("organizer", "venue").prefetch_related("tags", "images"); event = qs.first(); if event is None: raise Http404`. This gracefully returns the first match. Add a comment noting the known limitation and that the URL scheme should be revised at 0.4 to include organizer slug.

## Important

- **events/views.py:84 + templates/cotton/filter_chips.html:4** — XSS: `active_tag_slugs` passes raw user input (`tag_slugs`) into Alpine.js `x-data` via `|safe`. A crafted `?tags=` value can inject script. **Fix:** Use `valid_slugs` instead of `tag_slugs` for both `active_tag_slugs` in context (line 84) and `filter_params["tags"]` (line 70). Also use `json_script` or `escapejs` instead of `|safe` in the template — e.g., render the list as a `<script type="application/json">` block and read it in Alpine.

- **accounts/middleware.py:27,29** — X-Robots-Tag header missing on the 302 redirect (line 27) and the 403 response (line 29). Design doc says "on every response." **Fix:** Build the redirect response explicitly: `response = redirect(...); response["X-Robots-Tag"] = "noindex, nofollow, noarchive"; return response`. Same for the 403: `response = HttpResponseForbidden(...); response["X-Robots-Tag"] = "noindex, nofollow, noarchive"; return response`.

- **accounts/middleware.py:27** — `next` param uses `request.path`, dropping query string. A shared link like `/events/?tags=play-party` becomes `/events/` after login. **Fix:** Use `urllib.parse.quote(request.get_full_path(), safe="/")` instead of `request.path`. Add `import urllib.parse` at the top.

- **templates/events/detail.html:41-43 + templates/cotton/event_card.html:22-23** — Price displays raw cents (`"EUR 1500"` instead of `"EUR 15.00"`). The field is `price_min_cents` (integer cents). **Fix:** Add a template filter or model property. Simplest: `{{ event.price_min_cents|divisibleby:1 }}` won't work — use a custom filter `{% load event_tags %}` with `@register.filter def cents_to_display(value): return f"{value / 100:.2f}"`, or add `@property def price_min_display(self)` to the Event model.

- **tests/test_views_csd3.py:17-27** — `approved_user` fixture creates user with `is_approved=True` but NOT `is_staff=True`. LoginWallMiddleware returns 403 for non-staff users, so ALL tests in this file assert wrong status codes (200/404 expectations get 403). **Fix:** Change the fixture to `is_staff=True` (since 0.3 is staff-only), or add `@pytest.fixture(autouse=True)` override that sets `LOGIN_WALL_ENABLED=False` in the test module.

- **templates/events/list.html:14 + templates/cotton/filter_chips.html** — HTMX trigger mismatch. Form has `hx-trigger="change"` but tag buttons call `requestSubmit()` (fires `submit`, not `change`) and price buttons are `type="submit"`. Tags and price filters cause full page reload instead of HTMX partial swap. **Fix:** Change to `hx-trigger="submit"` on the form. Have date inputs trigger submit on change: add `@change="$el.closest('form').requestSubmit()"` to the date inputs.

- **templates/_base.html:19-20** — HTMX loaded twice: `{% django_htmx_script %}` (line 19) AND explicit CDN script (line 20). Double-loading causes duplicate event handlers. **Fix:** Remove line 20 (`<script defer src="https://unpkg.com/htmx.org@2.0.4"></script>`). Verify `{% django_htmx_script %}` loads the core htmx library. If it only loads the extension, keep the CDN line and remove the tag instead.

- **organizers/views.py:4** — Cross-app import: `from events.models import Event` creates circular dependency between `organizers` and `events` apps. **Fix:** Use reverse FK relation: replace `Event.objects.filter(organizer=organizer, ...)` with `organizer.event_set.filter(...)`. Remove the `events.models` import. Add `.select_related("organizer")` to both querysets (currently missing, causing N+1 on event cards that access `event.organizer.name`).

- **events/views.py:107** — `event.images.filter(is_cover=True).first()` bypasses `prefetch_related("images")` cache. Calling `.filter()` on a prefetched manager creates a new DB query. **Fix:** Use `next((img for img in event.images.all() if img.is_cover), None)` to leverage the prefetch cache.

## Minor

- **templates/cotton/filter_chips.html** — Missing hidden input for `organizer` param. When active and user toggles a tag, the organizer filter is lost. **Fix:** Add `{% if organizer_param %}<input type="hidden" name="organizer" value="{{ organizer_param }}">{% endif %}`.

- **templates/account/login.html:11-12** — "Register" link points to closed signup. Confusing UX. **Fix:** Remove or wrap in `{% if ACCOUNT_ALLOW_SIGNUPS %}` (or check adapter).

- **templates/events/detail.html:66-76** — `{% elif event.external_url %}` drops external_url when tickets_url is also present. **Fix:** Use separate `{% if %}` blocks for both, or show both links.

- **organizers/views.py:13-22** — Upcoming events queryset has no limit (past events capped at 20). **Fix:** Add `[:50]` or pagination.

- **docs/plans/2026-04-17-phase-0.3-internal-events-design.md** — Design doc says robots.txt in `pages/urls.py` but implementation is in `a_core/urls.py`. Also, filter contract specifies `to` default as "+14 days" but implementation has no default. **Fix:** Update design doc to match implementation for both.

## ADR Updates

- No ADR changes needed. All findings are implementation issues, not ADR conflicts. The login-wall prefix matching fix aligns with ADR-002 D2 (auth flows through allauth). The slug collision is a known limitation documented in the bead, not an ADR violation.

## Discarded

- **No app_name namespace** — Future concern; adds complexity now and requires updating all `{% url %}` tags across templates. Not worth it for 0.3.
- **Missing hx-swap attributes** — `innerHTML` is the correct HTMX default for this use case. Explicit is marginally better but not worth a fix cycle.
- **Alpine.js version pin** — Pre-existing issue not introduced by 0.3. Note for future cleanup.
- **Server-Timing timer unconditional** — Negligible overhead (`perf_counter()` is nanoseconds).
- **No test for page=0/-1** — `Paginator.get_page()` handles gracefully (returns last page). Edge case is acceptable behavior.
- **No test for suspended organizer** — Covered implicitly by `status="approved"` filter. Adding it would be pure thoroughness, not bug prevention.
- **Wasted prefetch of tags on organizer profile** — event_card doesn't display tags but the overhead is one DB query regardless of event count. Trivial.
- **No navbar on event pages** — `_base.html` doesn't include a nav component. This is a pre-existing design choice (templates extend `_base.html` directly). The event/organizer templates should extend a layout that includes nav, but this is a template hierarchy question for the 0.3 dogfooding period to resolve based on UX feedback, not a code bug.
