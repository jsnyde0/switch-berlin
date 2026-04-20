"""GeoJSON serializer for Venue with privacy enforcement."""
import hashlib


def venue_to_geojson(venue) -> dict | None:
    """Return a GeoJSON Feature dict with privacy enforcement, or None if coords are missing."""
    if venue.latitude is None or venue.longitude is None:
        return None

    if venue.privacy_mode == "public":
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(venue.longitude), float(venue.latitude)],
            },
            "properties": {
                "privacy": "public",
                "blur_radius_m": None,
            },
        }

    elif venue.privacy_mode == "neighborhood_blur":
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [
                    round(float(venue.longitude), 3),
                    round(float(venue.latitude), 3),
                ],
            },
            "properties": {
                "privacy": "neighborhood_blur",
                "blur_radius_m": venue.blur_radius_m,
            },
        }

    else:  # 'private'
        digest = hashlib.md5(venue.slug.encode()).digest()
        offset_lat = ((digest[0] / 255) - 0.5) * 0.018
        offset_lng = ((digest[1] / 255) - 0.5) * 0.025
        fake_lat = round(float(venue.latitude) + offset_lat, 4)
        fake_lng = round(float(venue.longitude) + offset_lng, 4)
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [fake_lng, fake_lat],
            },
            "properties": {
                "privacy": "private",
                "blur_radius_m": 1000,
            },
        }
