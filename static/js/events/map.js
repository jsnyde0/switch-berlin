window.initMap = function (containerEl, store) {
  // Read initial markers from DOM data island
  var markersDataEl = document.getElementById('markers-data')
  var markersGeoJSON = markersDataEl
    ? JSON.parse(markersDataEl.textContent)
    : { type: 'FeatureCollection', features: [] }

  // Read initial bounds from URL
  var params = new URLSearchParams(window.location.search)
  var boundsParam = params.get('bounds')
  var initialBounds = [13.28, 52.45, 13.48, 52.58]  // Berlin fallback
  if (boundsParam) {
    var parts = boundsParam.split(',').map(Number)
    if (parts.length === 4 && parts.every(function (n) { return !isNaN(n) })) {
      // bounds param is lat_min,lng_min,lat_max,lng_max
      initialBounds = [parts[1], parts[0], parts[3], parts[2]]  // [lng_min, lat_min, lng_max, lat_max]
    }
  }

  var map = new maplibregl.Map({
    container: containerEl,
    style: 'https://tiles.openfreemap.org/styles/liberty',
    bounds: initialBounds,
    fitBoundsOptions: { padding: 20 },
  })

  map.on('load', function () {
    map.addSource('events', {
      type: 'geojson',
      data: markersGeoJSON,
      cluster: true,
      clusterMaxZoom: 14,
      clusterRadius: 50,
    })

    map.addLayer({
      id: 'event-clusters',
      type: 'circle',
      source: 'events',
      filter: ['has', 'point_count'],
      paint: {
        'circle-color': '#6366f1',
        'circle-radius': 18,
        'circle-opacity': 0.8,
      },
    })

    // Privacy obfuscation circles: blurred venues where blur_radius_m > 0.
    // Private venues where user is going have blur_radius_m: null and are
    // shown as pins (event-markers layer), not circles.
    map.addLayer({
      id: 'privacy-circles',
      type: 'circle',
      source: 'events',
      filter: ['all',
        ['!', ['has', 'point_count']],
        ['>', ['coalesce', ['get', 'blur_radius_m'], 0], 0],
      ],
      paint: {
        'circle-color': '#a855f7',
        'circle-opacity': 0.15,
        'circle-stroke-color': '#a855f7',
        'circle-stroke-width': 1,
        'circle-stroke-opacity': 0.4,
        // Scale radius by zoom: approximate 1000 m at zoom 13 ≈ 40 px; scale proportionally
        'circle-radius': [
          'interpolate', ['exponential', 2], ['zoom'],
          10, ['/', ['get', 'blur_radius_m'], 75],
          14, ['/', ['get', 'blur_radius_m'], 5],
        ],
      },
    })

    map.addLayer({
      id: 'event-markers',
      type: 'circle',
      source: 'events',
      // Show pin when blur_radius_m is null: public venues and private venues
      // where server revealed exact coords (user has going attendance).
      filter: ['all',
        ['!', ['has', 'point_count']],
        ['==', ['get', 'blur_radius_m'], null],
      ],
      paint: {
        'circle-color': '#a855f7',
        'circle-radius': 8,
        'circle-opacity': 0.9,
      },
    })
  })

  map.on('moveend', function () {
    var b = map.getBounds()
    store.setBounds({
      lat_min: b.getSouth(),
      lng_min: b.getWest(),
      lat_max: b.getNorth(),
      lng_max: b.getEast(),
    })
  })

  map.on('click', 'event-markers', function (e) {
    var feature = e.features[0]
    if (!feature) return
    var eventId = feature.properties.event_id
    store.selectEvent(eventId)
    htmx.ajax('GET', '/events/' + eventId + '/drawer/', {
      target: '#drawer',
      swap: 'innerHTML',
    })
  })

  window.addEventListener('events:selection-changed', function (e) {
    // Visual highlight — set feature state on the selected event marker
    // MapLibre feature state requires a numeric feature id; use a filter layer instead
    map.setPaintProperty('event-markers', 'circle-color', [
      'case',
      ['==', ['get', 'event_id'], e.detail.eventId || -1],
      '#f59e0b',
      '#a855f7',
    ])
  })

  window.addEventListener('events:filter-changed', function () {
    var el = document.getElementById('markers-data')
    if (!el) return
    var newGeoJSON = JSON.parse(el.textContent)
    var src = map.getSource('events')
    if (src) src.setData(newGeoJSON)
  })

  return {
    destroy: function () { map.remove() },
  }
}
