document.addEventListener('DOMContentLoaded', function () {
  var mapEl = document.getElementById('map')
  if (!mapEl) return  // guard: only run on pages with the map

  document.addEventListener('alpine:initialized', function () {
    var store = Alpine.store('map')
    var mapController = window.initMap(mapEl, store)
    store._mapInstance = mapController

    // Restore ?selected= from URL on initial load (e.g. after reload or forward nav)
    var params = new URLSearchParams(window.location.search)
    var selected = params.get('selected')
    if (selected) {
      htmx.ajax('GET', '/events/' + selected + '/drawer/', {
        target: '#drawer',
        swap: 'innerHTML',
      })
    }
  })

  // After HTMX swaps #event-list, tell map.js to re-read marker data from DOM
  document.body.addEventListener('htmx:afterSwap', function (evt) {
    if (evt.detail.target.id === 'event-list') {
      window.dispatchEvent(new CustomEvent('events:filter-changed', {}))
    }
  })

  // Handle browser back/forward nav — sync store and drawer without re-pushing history
  window.addEventListener('popstate', function () {
    var store = Alpine.store('map')
    var params = new URLSearchParams(window.location.search)
    var selected = params.get('selected')
    if (selected) {
      var eventId = parseInt(selected, 10)
      // Directly update store state — do NOT call store.selectEvent() as it pushes history
      store.selectedEventId = eventId
      window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { eventId: eventId } }))
      htmx.ajax('GET', '/events/' + eventId + '/drawer/', {
        target: '#drawer',
        swap: 'innerHTML',
      })
    } else {
      // No selection in new URL — clear drawer and highlight
      if (store) {
        store.selectedEventId = null
        window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { eventId: null } }))
      }
      var drawerEl = document.getElementById('drawer')
      if (drawerEl) drawerEl.innerHTML = ''
    }
  })
})
