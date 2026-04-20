# Fixes: phase-0-4-htmx-map-spike
Date: 2026-04-20
Review passes: 1

## Critical

- **events/views.py:147-152** — `event_drawer` view fetches any event by PK without `status="published"` filter. An authenticated user who enumerates PKs can view drafts/cancelled events in the drawer. Both `event_list` and `event_detail` filter by published status; drawer is the only endpoint that does not. **Fix:** Add `.filter(status="published")` to the queryset: `get_object_or_404(Event.objects.filter(status="published").select_related(...), pk=event_id)`.

- **static/js/events/map.js:93-98** — `events:filter-changed` listener calls `map.getSource('events').setData(...)` but the source is registered inside `map.on('load', ...)`. If an HTMX swap fires before map tiles load, `getSource('events')` returns `undefined` and `.setData()` throws an uncaught TypeError. **Fix:** Guard: `var src = map.getSource('events'); if (src) src.setData(newGeoJSON);`

## Important

- **static/js/events/bridge.js + store.js** — No `popstate` event handler. `selectEvent()` pushes history entries but back/forward never updates store, drawer, or marker highlight. QA checklist items 4 and 5 will fail. T3 tripwire risk. **Fix:** Add `window.addEventListener('popstate', ...)` in `bridge.js` that reads `?selected=` from the new URL and calls `store.selectEvent()` (or clears selection), and reads `?tags=` etc. to sync filter state.

- **templates/events/_event_drawer.html:6** — Drawer close button does raw `innerHTML=''` without clearing `store.selectedEventId` or `?selected=` from URL. Marker stays highlighted, URL is stale, reload re-opens the closed drawer. **Fix:** Replace onclick with `Alpine.store('map').selectEvent(null); document.getElementById('drawer').innerHTML=''`.

- **templates/events/list.html:19 + static/js/events/bridge.js:22-26** — `events:filter-changed` dispatched twice per filter action: once by `hx-on::after-request` on the form, once by `htmx:afterSwap` in bridge.js. Double GeoJSON parse + map re-render. `hx-on::after-request` also fires on failed requests (unlike afterSwap). **Fix:** Remove `hx-on::after-request` from the form in list.html. The bridge.js afterSwap handler is sufficient and correct.

- **static/js/events/map.js** — Private venue obfuscation circles never rendered client-side. Server correctly returns `geometry: null` + `fake_center` for private venues and blurred coords + `blur_radius_m` for neighborhood_blur, but map.js has no circle/fill layer to visualize these. Design doc acceptance criterion 7 not fully met (server enforcement is correct; visual rendering is missing). **Fix:** Add a circle rendering layer for features with `privacy != 'public'`. For private: use `fake_center` as point, render 1000m radius circle. For neighborhood_blur: render `blur_radius_m` circle around the blurred pin. Can use MapLibre expressions or a simple circle-radius paint property scaled by zoom.

- **events/tests/test_views_markers.py** — No test for bounds filtering. The coordinate order (`lat_min,lng_min,lat_max,lng_max`) is non-obvious and an inversion risk. Also no test for drawer status filter (once the critical fix above is applied). **Fix:** Add tests: in-bounds included, out-of-bounds excluded, malformed bounds ignored, and drawer returns 404 for unpublished events.

## Minor

- **events/views.py:105** — Redundant `.select_related("venue", "organizer")` on `markers_qs` (already inherited from `qs`). Also `prefetch_related("tags")` inherited but never used for markers. **Fix:** Build `markers_qs` from a clean queryset or remove the redundant select_related.

- **templates/events/list.html:7,41** — MapLibre loaded from unpkg.com without version pinning or SRI hash. Alpine similarly uses loose `@3.x.x` range. Supply chain risk for production. **Fix:** Pin exact versions and add `integrity` + `crossorigin` attributes before Phase 0.4 graduation.

- **docs/plans design doc** — File layout lists `_event_markers.html` as a separate template, but markers are inlined in `_event_list.html`. The implementation is correct (simpler). **Fix:** Update design doc file layout to match.

## ADR Updates

- No ADR changes needed. All ADR-004 FIRM tripwires pass (T1=166 LOC, T4=bridge in one place, T5=no setTimeout). T3 has a gap (no popstate handler) that must be fixed before manual QA, but is not an ADR violation until the QA checklist actually fails.

## Discarded

- PK-based drawer URL leaks sequential IDs in GeoJSON (Arch): Internal HTMX partial, not user-facing. PKs already in markers payload. Not worth changing for spike scope.
- Per-event venue serialization computes redundant MD5 hashes (Arch): Negligible at 500 events. Optimization not warranted.
- Venue.privacy_mode CharField missing max_length (Impl): Pre-existing model issue from phase 0.1, not introduced by this change.
- event.pk in inline onclick handler (Impl): Integer PK, no XSS risk. Alpine x-on is nicer but not worth a fix-pass change.
