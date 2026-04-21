document.addEventListener('DOMContentLoaded', function () {
  var mapEl = document.getElementById('map')
  if (!mapEl) return  // guard: only run on pages with the map

  // Alpine is loaded with defer, so it fires alpine:initialized before DOMContentLoaded.
  // By the time this DOMContentLoaded handler runs, Alpine.store('map') is already set up.
  var store = Alpine.store('map')
  var mapController = window.initMap(mapEl, store)
  store._mapInstance = mapController

  // Restore ?selected= from URL on initial load (e.g. after reload or forward nav)
  var params = new URLSearchParams(window.location.search)
  var selected = params.get('selected')
  if (selected) {
    // Sync store so map highlight is restored (selectEvent would push history; set directly)
    store.selectedKey = selected
    window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { selectedKey: selected } }))
    htmx.ajax('GET', '/events/' + selected + '/drawer/', {
      target: '#drawer',
      swap: 'innerHTML',
    })
  }

  // After HTMX swaps #event-list, tell map.js to re-read marker data from DOM
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

  // Handle browser back/forward nav — sync store and drawer without re-pushing history
  window.addEventListener('popstate', function () {
    var store = Alpine.store('map')
    var params = new URLSearchParams(window.location.search)
    var selected = params.get('selected')
    if (selected) {
      // selected is already a composite key string like "org-slug/event-slug"
      // Set store directly to avoid selectEvent() pushing another history entry
      store.selectedKey = selected
      window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { selectedKey: selected } }))
      htmx.ajax('GET', '/events/' + selected + '/drawer/', {
        target: '#drawer',
        swap: 'innerHTML',
      })
    } else {
      // No selection in new URL — clear drawer and highlight
      if (store) {
        store.selectedKey = null
        window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { selectedKey: null } }))
      }
      var drawerEl = document.getElementById('drawer')
      if (drawerEl) drawerEl.innerHTML = ''
    }
  })
})
