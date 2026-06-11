"""
OG-card image resolution for Switch events (kb-6d7o.1).

Single resolution point per ADR-003 cheap-foresight: both the public og:image tag
and the studio preview (kb-6d7o.D) consume card_image_url(), so preview == reality
at zero extra cost.

ADR-008 D3: "event has no cover" is a fact — intentional branding default, NOT a
synthesised/zero-filled cover.
"""

from django.templatetags.static import static

DEFAULT_OG_IMAGE_STATIC = "img/og-default.png"


def card_image_url(event, request) -> str:
    """
    Return the absolute URL for the og:image card of *event*.

    Resolution order:
    1. If the event has an EventImage with is_cover=True, return its absolute URL.
    2. Otherwise, return the absolute URL for the site-level default asset
       (static/img/og-default.png).

    The returned URL is always absolute (scheme + host + path) so it is valid
    as an og:image value and can be embedded directly without further processing.

    Args:
        event: An events.models.Event instance.  The ``images`` prefetch cache
               is used if already loaded (avoids an extra DB query).
        request: The current HttpRequest (used to build the absolute URI).

    Returns:
        str — absolute URL.
    """
    # Use prefetch cache when available (detail view already does
    # .prefetch_related("images")); a live DB hit otherwise. No try/except —
    # a failing relation access is a real error and must surface (ADR-008 D3),
    # not be masked as "no cover".
    cover = next((img for img in event.images.all() if img.is_cover), None)

    if cover is not None:
        # Build absolute URL matching the template pattern:
        # {{ request.scheme }}://{{ request.get_host }}{{ cover_image.image.url }}
        return f"{request.scheme}://{request.get_host()}{cover.image.url}"

    # No cover — return the branded default.
    default_path = static(DEFAULT_OG_IMAGE_STATIC)
    return request.build_absolute_uri(default_path)
