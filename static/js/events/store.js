document.addEventListener('alpine:init', function () {
  Alpine.store('map', {
    selectedEventId: null,
    hoveredEventId: null,
    bounds: null,
    _mapInstance: null,

    selectEvent: function (eventId) {
      this.selectedEventId = eventId
      var url = new URL(window.location)
      if (eventId) {
        url.searchParams.set('selected', eventId)
        history.pushState({}, '', url)
      } else {
        url.searchParams.delete('selected')
        history.replaceState({}, '', url)
      }
      window.dispatchEvent(new CustomEvent('events:selection-changed', { detail: { eventId: eventId } }))
    },

    hoverEvent: function (eventId) {
      this.hoveredEventId = eventId
    },

    setBounds: function (bounds) {
      this.bounds = bounds
      var url = new URL(window.location)
      if (bounds) {
        url.searchParams.set('bounds', [bounds.lat_min, bounds.lng_min, bounds.lat_max, bounds.lng_max].join(','))
      } else {
        url.searchParams.delete('bounds')
      }
      history.replaceState({}, '', url)
      window.dispatchEvent(new CustomEvent('events:bounds-changed', { detail: { bounds: bounds } }))
    },
  })
})
