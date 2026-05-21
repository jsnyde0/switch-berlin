"""Accounts middleware for Switch."""

import urllib.parse

from django.shortcuts import redirect
from django.template.response import TemplateResponse

from a_core.models import get_flag

_ROBOTS_TAG = "noindex, nofollow, noarchive"

ALWAYS_PUBLIC_PREFIXES = (
    "/accounts/",
    "/healthz",
    "/robots.txt",
    "/impressum",
    "/privacy",
    "/terms",
    "/takedown",
    "/organizer-opt-out",
    "/age-check",
)

# Prefix-based matching — "/" is a special case: match only the exact root path
# to avoid it accidentally matching everything (e.g. /admin/).
PUBLIC_READ_PREFIXES = ("/events", "/o/", "/p/")
# Additional exact-match paths for public-read (not prefix-matched).
PUBLIC_READ_EXACT = ("/",)


class LoginWallMiddleware:
    """Two-tier login wall for Phase 0.5.

    ALWAYS_PUBLIC_PREFIXES: reachable regardless of PUBLIC_READ_ENABLED.
    PUBLIC_READ_PREFIXES: reachable only when PUBLIC_READ_ENABLED=True.

    X-Robots-Tag logic:
    - PUBLIC_READ_ENABLED=True and path in PUBLIC_READ_PREFIXES: no X-Robots-Tag.
    - ALWAYS_PUBLIC_PREFIXES (not also in PUBLIC_READ_PREFIXES): X-Robots-Tag set.
    - Authenticated-only paths: X-Robots-Tag always set.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        public_read = get_flag("PUBLIC_READ_ENABLED", default=True)

        read_public = public_read and (
            any(path.startswith(p) for p in PUBLIC_READ_PREFIXES)
            or path in PUBLIC_READ_EXACT
        )

        if read_public:
            # Public read mode — no X-Robots-Tag on public content
            return self.get_response(request)

        always_public = any(path.startswith(p) for p in ALWAYS_PUBLIC_PREFIXES)
        if always_public:
            response = self.get_response(request)
            response["X-Robots-Tag"] = _ROBOTS_TAG
            return response

        # Auth-required path
        if not request.user.is_authenticated:
            next_url = urllib.parse.quote(request.get_full_path(), safe="/")
            response = redirect(f"/accounts/login/?next={next_url}")
            response["X-Robots-Tag"] = _ROBOTS_TAG
            return response

        if not (request.user.is_staff or request.user.status == "vouched"):
            response = TemplateResponse(
                request,
                "errors/403_pending_approval.html",
                status=403,
            )
            response.render()
            response["X-Robots-Tag"] = _ROBOTS_TAG
            return response

        response = self.get_response(request)
        response["X-Robots-Tag"] = _ROBOTS_TAG
        return response


class AgeGateMiddleware:
    """JuSchG age gate: redirect to /age-check/ on first HTML request without cookie.

    Only active when PUBLIC_READ_ENABLED=True (bypass entirely in closed-beta).
    Exempt: ALWAYS_PUBLIC_PREFIXES routes.
    Bot user-agents bypass so SEO crawling is not blocked.
    Only triggers on text/html responses (not API/JSON/static).
    """

    BOT_AGENTS = (
        "googlebot",
        "bingbot",
        "slurp",
        "duckduckbot",
        "baiduspider",
        "yandexbot",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not get_flag("PUBLIC_READ_ENABLED", default=True):
            return self.get_response(request)

        if any(request.path.startswith(p) for p in ALWAYS_PUBLIC_PREFIXES):
            return self.get_response(request)

        ua = request.META.get("HTTP_USER_AGENT", "").lower()
        if any(bot in ua for bot in self.BOT_AGENTS):
            return self.get_response(request)

        if request.COOKIES.get("age_gate") == "ok":
            return self.get_response(request)

        # Only gate text/html requests (not XHR/JSON/static assets)
        accept = request.META.get("HTTP_ACCEPT", "")
        if "text/html" in accept:
            return redirect("/age-check/")

        return self.get_response(request)
