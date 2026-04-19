"""Accounts middleware for kinky-bubbles."""
from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect


class LoginWallMiddleware:
    """Hard login-wall for Phase 0.3 (staff-only).

    Anonymous users: redirect to /accounts/login/?next=<path>.
    Authenticated non-staff: 403 (will relax to is_approved at 0.4).
    Adds X-Robots-Tag: noindex, nofollow, noarchive to every response.
    Kill-switch: LOGIN_WALL_ENABLED=False in settings bypasses the wall.
    """

    PUBLIC_PATHS = {"/accounts/login/", "/accounts/logout/", "/healthz", "/robots.txt"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "LOGIN_WALL_ENABLED", True):
            response = self.get_response(request)
            response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
            return response
        if request.path not in self.PUBLIC_PATHS and not request.user.is_authenticated:
            return redirect(f"/accounts/login/?next={request.path}")
        if request.user.is_authenticated and not request.user.is_staff:
            return HttpResponseForbidden("Not available yet.")
        response = self.get_response(request)
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
        return response
