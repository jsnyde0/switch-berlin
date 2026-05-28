document.addEventListener('DOMContentLoaded', function () {
  var mapEl = document.getElementById('map')
  if (!mapEl) return  // guard: only run on pages with the map

  // Alpine is loaded with defer, so it fires alpine:initialized before DOMContentLoaded.
  // By the time this DOMContentLoaded handler runs, Alpine.store('map') is already set up.
  var store = Alpine.store('map')
  var mapController = window.initMap(mapEl, store)
  store._mapInstance = mapController

  // After HTMX swaps #event-list, tell map.js to re-read marker data from DOM.
  // setData() does NOT move the camera — no loop risk.
  document.body.addEventListener('htmx:afterSwap', function (evt) {
    if (evt.detail.target && evt.detail.target.id === 'event-list') {
      window.dispatchEvent(new CustomEvent('events:filter-changed', {}))
    }
  })

  // When user marks attendance on a private-venue event, re-fetch #event-list
  // (which contains #markers-data) so exact coords are shown if user just
  // marked 'going'. Dispatching filter-changed alone only re-reads stale DOM.
  // ADR-004 D3: event-bus.
  document.body.addEventListener('events:attendance-changed', function () {
    htmx.ajax('GET', window.location.href, { target: '#event-list', swap: 'innerHTML' })
  })
})
