"""Events middleware — response-phase headers per ADR-012 D3."""

# X-Robots-Tag values per ADR-012 D3 visibility tiers.
_ROBOTS_BY_VISIBILITY = {
    "semi_public": "noindex, nofollow",
    "unlisted": "noindex, nofollow, noarchive",
}


class XRobotsTagMiddleware:
    """Set X-Robots-Tag response header for non-public Event responses.

    Per ADR-012 D3 robot indexing semantics:
    - public events: no X-Robots-Tag (search engines may index)
    - semi_public events: X-Robots-Tag: noindex, nofollow
    - unlisted events: X-Robots-Tag: noindex, nofollow, noarchive

    The view layer (event_detail) annotates the resolved event on the request
    as ``request._resolved_event`` so this middleware can read the visibility
    tier without a second DB query.

    Must be placed AFTER the view middleware in MIDDLEWARE (response-phase
    middleware runs in reverse MIDDLEWARE order).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        event = getattr(request, "_resolved_event", None)
        if event is None:
            return response
        robots_tag = _ROBOTS_BY_VISIBILITY.get(event.visibility)
        if robots_tag is not None:
            response["X-Robots-Tag"] = robots_tag
        return response
