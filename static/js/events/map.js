window.initMap = function (containerEl, store) {
  // While tiles load, the container shows its own dark background (set in CSS
  // on #map) — on the dark-matter basemap this is seamless, so no loading
  // overlay is needed. A prior skeleton overlay could linger over an
  // already-rendered map if its removal event raced; dropping it removes that
  // failure mode entirely.

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
    style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
    bounds: initialBounds,
    fitBoundsOptions: { padding: 20 },
  })

  // Track current hover state for paint expressions
  var _hoveredKey = null

  // Debounce timer for moveend → filter
  var _moveendTimer = null
  var _DEBOUNCE_MS = 400

  // Helper: build the current URL with updated bounds param
  function _urlWithBounds(bounds) {
    var url = new URL(window.location.href)
    if (bounds) {
      url.searchParams.set('bounds', [bounds.lat_min, bounds.lng_min, bounds.lat_max, bounds.lng_max].join(','))
    } else {
      url.searchParams.delete('bounds')
    }
    return url.toString()
  }

  // Helper: push bounds to URL + update store + reload #event-list via htmx
  function _applyBoundsFilter(bounds) {
    store.setBounds(bounds)
    var href = _urlWithBounds(bounds)
    htmx.ajax('GET', href, { target: '#event-list', swap: 'innerHTML' })
  }

  function buildMarkerRadiusExpression(hoveredKey) {
    if (!hoveredKey) return 8
    return [
      'case',
      ['==', ['concat', ['get', 'org_slug'], '/', ['get', 'event_slug']], hoveredKey],
      12,
      8,
    ]
  }

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

    // kb-0da: cursor affordance for event-markers
    map.on('mouseenter', 'event-markers', function (e) {
      map.getCanvas().style.cursor = 'pointer'
      var feature = e.features && e.features[0]
      if (!feature) return
      var key = feature.properties.org_slug + '/' + feature.properties.event_slug
      // source='map' prevents the hover-changed listener from re-dispatching
      store.hoverEvent(key, 'map')
    })

    map.on('mouseleave', 'event-markers', function () {
      map.getCanvas().style.cursor = ''
      store.hoverEvent(null, 'map')
    })

    map.on('mouseenter', 'event-clusters', function () {
      map.getCanvas().style.cursor = 'pointer'
    })

    map.on('mouseleave', 'event-clusters', function () {
      map.getCanvas().style.cursor = ''
    })
  })

  // ── moveend: user-initiated pan/zoom → debounced area filter ─────────────
  // Guard: e.originalEvent is truthy only for user gestures.
  // Programmatic easeTo / fitBounds calls have no originalEvent, so they
  // won't trigger the filter loop.
  map.on('moveend', function (e) {
    if (!e.originalEvent) return  // programmatic camera move — skip

    clearTimeout(_moveendTimer)
    _moveendTimer = setTimeout(function () {
      var b = map.getBounds()
      var bounds = {
        lat_min: b.getSouth(),
        lng_min: b.getWest(),
        lat_max: b.getNorth(),
        lng_max: b.getEast(),
      }
      _applyBoundsFilter(bounds)
    }, _DEBOUNCE_MS)
  })

  // ── Single marker click → filter list to vicinity ────────────────────────
  // NO list autoscroll, NO auto-expand of cards (per D3).
  // Reload is EXPLICIT (one per click), not via moveend.
  map.on('click', 'event-markers', function (e) {
    var feature = e.features && e.features[0]
    if (!feature) return

    var lngLat = e.lngLat
    // Neighborhood zoom — show ~1km radius
    var NEIGHBORHOOD_ZOOM = 15

    map.easeTo({ center: lngLat, zoom: NEIGHBORHOOD_ZOOM })

    // Compute explicit bounds at neighborhood zoom (roughly ±0.005° lat/lng ≈ 500m)
    var DELTA = 0.008
    var bounds = {
      lat_min: lngLat.lat - DELTA,
      lng_min: lngLat.lng - DELTA,
      lat_max: lngLat.lat + DELTA,
      lng_max: lngLat.lng + DELTA,
    }
    _applyBoundsFilter(bounds)
  })

  // ── Cluster click → easeTo/zoom-expand + filter ──────────────────────────
  // Replace old popup. One explicit reload per click (not via moveend).
  // kb-6ow: maplibre-gl 5.x returns Promises from getClusterLeaves /
  // getClusterExpansionZoom — await/then only, no callbacks.
  map.on('click', 'event-clusters', function (e) {
    var feature = e.features && e.features[0]
    if (!feature) return

    var clusterId = feature.properties.cluster_id
    var pointCount = feature.properties.point_count
    var clusterCoord = e.lngLat

    var eventsSource = map.getSource('events')
    if (!eventsSource) return

    eventsSource.getClusterLeaves(clusterId, pointCount, 0).then(function (leaves) {
      if (!leaves || !leaves.length) return

      // Check if all leaves share the same coordinate (within ~0.00001 deg ≈ 1 m)
      var firstLng = leaves[0].geometry.coordinates[0]
      var firstLat = leaves[0].geometry.coordinates[1]
      var allSameCoord = leaves.every(function (leaf) {
        return (
          Math.abs(leaf.geometry.coordinates[0] - firstLng) < 0.00001 &&
          Math.abs(leaf.geometry.coordinates[1] - firstLat) < 0.00001
        )
      })

      if (allSameCoord) {
        // Co-located cluster: zoom in to neighborhood around the shared point
        // and filter to that tight vicinity. No popup.
        map.easeTo({ center: clusterCoord, zoom: 15 })
        var DELTA = 0.008
        var bounds = {
          lat_min: clusterCoord.lat - DELTA,
          lng_min: clusterCoord.lng - DELTA,
          lat_max: clusterCoord.lat + DELTA,
          lng_max: clusterCoord.lng + DELTA,
        }
        _applyBoundsFilter(bounds)
      } else {
        // Spread cluster: zoom to expansion zoom, then filter to the expanded viewport.
        eventsSource.getClusterExpansionZoom(clusterId).then(function (zoom) {
          map.easeTo({ center: clusterCoord, zoom: zoom + 1 })
          // Compute bounds around the cluster's center at expansion zoom.
          // We fire immediately (don't rely on moveend — programmatic camera).
          // Use a moderate bounding box; user can pan/zoom to refine.
          var zoomDelta = Math.pow(2, 15 - (zoom + 1)) * 0.008
          var delta = Math.max(zoomDelta, 0.004)
          var bounds = {
            lat_min: clusterCoord.lat - delta,
            lng_min: clusterCoord.lng - delta,
            lat_max: clusterCoord.lat + delta,
            lng_max: clusterCoord.lng + delta,
          }
          _applyBoundsFilter(bounds)
        }).catch(function () { /* ignore — cluster may have changed */ })
      }
    }).catch(function () { /* ignore — cluster may have changed */ })
  })

  // kb-0da: react to hover-changed from the list (source='list'), update map paint
  window.addEventListener('events:hover-changed', function (e) {
    // Only react when the source is the list to avoid loop
    // (map→store→event→here→map would loop; we guard via source flag)
    if (e.detail.source === 'map') return
    _hoveredKey = e.detail.hoveredEventId || null
    map.setPaintProperty('event-markers', 'circle-radius', buildMarkerRadiusExpression(_hoveredKey))
  })

  window.addEventListener('events:filter-changed', function () {
    var el = document.getElementById('markers-data')
    if (!el) return
    var newGeoJSON = JSON.parse(el.textContent)
    var src = map.getSource('events')
    if (src) src.setData(newGeoJSON)
    // setData does NOT move the camera — no moveend triggered — no reload loop
  })

  return {
    destroy: function () { map.remove() },
    resize: function () { map.resize() },
  }
}
