document.addEventListener('alpine:init', function () {
  Alpine.store('map', {
    hoveredEventId: null,
    bounds: null,
    _mapInstance: null,

    hoverEvent: function (eventId, _source) {
      if (this.hoveredEventId === eventId) return
      this.hoveredEventId = eventId
      window.dispatchEvent(new CustomEvent('events:hover-changed', { detail: { hoveredEventId: eventId, source: _source || 'list' } }))
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
