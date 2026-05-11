window.initMap = function (containerEl, store) {
  // kb-xia: tile-loading skeleton — injected as sibling, removed on map load
  var skeletonEl = document.createElement('div')
  skeletonEl.setAttribute('style',
    'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;' +
    'pointer-events:none;background:#f3f4f6;z-index:10;'
  )
  skeletonEl.innerHTML = '<span style="color:#9ca3af;font-size:0.875rem;font-family:sans-serif;">Loading map…</span>'
  var mapParent = containerEl.parentElement || containerEl
  mapParent.style.position = mapParent.style.position || 'relative'
  mapParent.appendChild(skeletonEl)

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

  // Track current hover / selection state for paint expressions
  var _hoveredKey = null
  var _selectedKey = ''

  function buildMarkerRadiusExpression(hoveredKey) {
    if (!hoveredKey) return 8
    return [
      'case',
      ['==', ['concat', ['get', 'org_slug'], '/', ['get', 'event_slug']], hoveredKey],
      12,
      8,
    ]
  }

  function buildMarkerColorExpression(selectedKey) {
    if (!selectedKey) return '#a855f7'
    return [
      'case',
      ['==', ['concat', ['get', 'org_slug'], '/', ['get', 'event_slug']], selectedKey],
      '#f59e0b',
      '#a855f7',
    ]
  }

  // Active popup reference so we can close on next cluster click
  var _clusterPopup = null

  map.on('load', function () {
    // kb-xia: remove skeleton once tiles are ready
    if (skeletonEl.parentElement) skeletonEl.remove()

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
    var orgSlug = feature.properties.org_slug
    var eventSlug = feature.properties.event_slug
    var compositeKey = orgSlug + '/' + eventSlug
    store.selectEvent(compositeKey)
    htmx.ajax('GET', '/events/' + orgSlug + '/' + eventSlug + '/drawer/', {
      target: '#drawer',
      swap: 'innerHTML',
    })
  })

  // kb-k7a: cluster click — popup for co-located events, zoom for spread clusters.
  // kb-6ow: maplibre-gl 5.x dropped the callback signature on getClusterLeaves /
  // getClusterExpansionZoom — they only return Promises now. Trailing callbacks
  // are silently ignored, so the previous version silently no-opped on prod.
  map.on('click', 'event-clusters', function (e) {
    var feature = e.features && e.features[0]
    if (!feature) return

    var clusterId = feature.properties.cluster_id
    var pointCount = feature.properties.point_count
    var clusterCoord = e.lngLat

    if (_clusterPopup) { _clusterPopup.remove(); _clusterPopup = null }

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
        var listItems = leaves.map(function (leaf) {
          var p = leaf.properties
          var href = '/events/' + p.org_slug + '/' + p.event_slug + '/'
          var title = p.title || (p.org_slug + '/' + p.event_slug)
          return (
            '<li>' +
            '<a href="' + href + '" ' +
            'class="block py-1 text-indigo-600 hover:text-indigo-800 hover:underline text-sm" ' +
            'onclick="event.preventDefault();Alpine.store(\'map\').selectEvent(\'' + p.org_slug + '/' + p.event_slug + '\');' +
            'htmx.ajax(\'GET\',\'' + href + 'drawer/\',{target:\'#drawer\',swap:\'innerHTML\'});">' +
            _escapeHtml(title) +
            '</a>' +
            '</li>'
          )
        }).join('')

        var popupHtml =
          '<div style="max-height:240px;overflow-y:auto;min-width:180px;">' +
          '<p class="text-xs font-semibold text-base-content/60 mb-1">' + leaves.length + ' events at this venue</p>' +
          '<ul class="list-none m-0 p-0">' + listItems + '</ul>' +
          '</div>'

        _clusterPopup = new maplibregl.Popup({ closeButton: true, maxWidth: '260px' })
          .setLngLat(clusterCoord)
          .setHTML(popupHtml)
          .addTo(map)
      } else {
        eventsSource.getClusterExpansionZoom(clusterId).then(function (zoom) {
          map.easeTo({ center: clusterCoord, zoom: zoom + 1 })
        }).catch(function () { /* ignore — cluster may have changed */ })
      }
    }).catch(function () { /* ignore — cluster may have changed */ })
  })

  window.addEventListener('events:selection-changed', function (e) {
    _selectedKey = e.detail.selectedKey || ''
    map.setPaintProperty('event-markers', 'circle-color', buildMarkerColorExpression(_selectedKey))
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
  })

  return {
    destroy: function () { map.remove() },
  }
}

// kb-k7a: minimal HTML escaping for popup content
function _escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}
