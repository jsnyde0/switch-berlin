"""Accounts middleware for kinky-bubbles."""
import urllib.parse

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

_ROBOTS_TAG = "noindex, nofollow, noarchive"


class LoginWallMiddleware:
    """Hard login-wall for Phase 0.3 (staff-only).

    Anonymous users: redirect to /accounts/login/?next=<path>.
    Authenticated non-staff: 403 (will relax to is_approved at 0.4).
    Adds X-Robots-Tag: noindex, nofollow, noarchive to every response.
    Kill-switch: LOGIN_WALL_ENABLED=False in settings bypasses the wall.
    """

    # Prefix matching so all allauth sub-paths (password reset, email confirm, etc.)
    # are reachable without authentication. Using /accounts/ as prefix is safe because
    # allauth handles its own authorization internally.
    PUBLIC_PREFIXES = ("/accounts/", "/healthz", "/robots.txt")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "LOGIN_WALL_ENABLED", True):
            response = self.get_response(request)
            response["X-Robots-Tag"] = _ROBOTS_TAG
            return response
        if not any(request.path.startswith(p) for p in self.PUBLIC_PREFIXES):
            if not request.user.is_authenticated:
                next_url = urllib.parse.quote(request.get_full_path(), safe="/")
                response = redirect(f"/accounts/login/?next={next_url}")
                response["X-Robots-Tag"] = _ROBOTS_TAG
                return response
        if request.user.is_authenticated and not request.user.is_staff:
            response = HttpResponseForbidden("Not available yet.")
            response["X-Robots-Tag"] = _ROBOTS_TAG
            return response
        response = self.get_response(request)
        response["X-Robots-Tag"] = _ROBOTS_TAG
        return response
