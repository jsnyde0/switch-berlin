"""GeoJSON serializer for Venue with privacy enforcement."""
import hashlib


def venue_to_geojson(venue, *, going_venue_ids=None) -> dict | None:
    """Return a GeoJSON Feature dict with privacy enforcement, or None if no coords.

    Args:
        venue: A Venue instance.
        going_venue_ids: frozenset/set of venue PKs where the requesting user has
            Attendance(status='going'). When None, always blur for private venues
            (backward-compatible with prior behaviour).
    """
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
        if going_venue_ids is not None and venue.pk in going_venue_ids:
            # User is going — return exact coords
            return {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(venue.longitude), float(venue.latitude)],
                },
                "properties": {
                    "privacy": "private",
                    "blur_radius_m": None,
                },
            }
        # Not going or anonymous — return blurred center (existing hash logic)
        digest = hashlib.md5(venue.slug.encode(), usedforsecurity=False).digest()
        offset_lat = ((digest[0] / 255) - 0.5) * 0.018
        offset_lng = ((digest[1] / 255) - 0.5) * 0.025
        fake_lat = round(float(venue.latitude) + offset_lat, 3)
        fake_lng = round(float(venue.longitude) + offset_lng, 3)
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
