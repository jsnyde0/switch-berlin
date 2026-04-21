"""Tests for accounts middleware — LoginWallMiddleware and AgeGateMiddleware.

Uses pytest-django. DB-dependent tests are marked with @pytest.mark.django_db.
Tests that mock get_flag at the middleware level run without a live DB.
"""
from unittest.mock import patch

from django.test import RequestFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_get_flag(public_read: bool):
    """Return a get_flag mock that returns `public_read` for PUBLIC_READ_ENABLED."""

    def _get_flag(key, default=True):
        if key == "PUBLIC_READ_ENABLED":
            return public_read
        return default

    return _get_flag


# ---------------------------------------------------------------------------
# LoginWallMiddleware — structure / settings tests (no DB needed)
# ---------------------------------------------------------------------------


def test_always_public_prefixes_includes_age_check():
    """ALWAYS_PUBLIC_PREFIXES must include /age-check/."""
    from accounts.middleware import ALWAYS_PUBLIC_PREFIXES

    assert "/age-check" in ALWAYS_PUBLIC_PREFIXES


def test_always_public_prefixes_includes_impressum():
    """ALWAYS_PUBLIC_PREFIXES must include /impressum."""
    from accounts.middleware import ALWAYS_PUBLIC_PREFIXES

    assert "/impressum" in ALWAYS_PUBLIC_PREFIXES


def test_always_public_prefixes_includes_legal_pages():
    """ALWAYS_PUBLIC_PREFIXES includes /privacy, /terms, /takedown."""
    from accounts.middleware import ALWAYS_PUBLIC_PREFIXES

    for prefix in ("/privacy", "/terms", "/takedown"):
        assert prefix in ALWAYS_PUBLIC_PREFIXES, (
            f"{prefix!r} missing from ALWAYS_PUBLIC_PREFIXES"
        )


def test_public_read_prefixes_includes_events():
    """PUBLIC_READ_PREFIXES must include /events."""
    from accounts.middleware import PUBLIC_READ_PREFIXES

    assert "/events" in PUBLIC_READ_PREFIXES


def test_public_read_root_is_covered():
    """Root path / must be covered by PUBLIC_READ_PREFIXES or PUBLIC_READ_EXACT."""
    from accounts.middleware import PUBLIC_READ_EXACT, PUBLIC_READ_PREFIXES

    # "/" may be in the exact-match set rather than prefix list
    covered = (
        any("/".startswith(p) for p in PUBLIC_READ_PREFIXES)
        or "/" in PUBLIC_READ_EXACT
    )
    assert covered, (
        "Root path '/' must be covered by PUBLIC_READ_PREFIXES or PUBLIC_READ_EXACT"
    )


def test_agegate_middleware_importable():
    """AgeGateMiddleware must be importable from accounts.middleware."""
    from accounts.middleware import AgeGateMiddleware  # noqa: F401


def test_loginwall_middleware_importable():
    """LoginWallMiddleware must be importable from accounts.middleware."""
    from accounts.middleware import LoginWallMiddleware  # noqa: F401


# ---------------------------------------------------------------------------
# LoginWallMiddleware — request-level unit tests (no DB — get_flag is mocked)
# ---------------------------------------------------------------------------


def test_loginwall_public_read_path_has_no_x_robots_tag():
    """Public-read path (PUBLIC_READ_ENABLED=True, /events/) gets no X-Robots-Tag."""
    from accounts.middleware import LoginWallMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = LoginWallMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get("/events/")
    request.user = type(
        "User",
        (),
        {"is_authenticated": True, "is_staff": True, "is_approved": True},
    )()

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200
    assert "X-Robots-Tag" not in response


def test_loginwall_admin_path_has_x_robots_tag():
    """Admin path is not in public prefixes, so X-Robots-Tag should be set."""
    from accounts.middleware import LoginWallMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = LoginWallMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get("/admin/")
    request.user = type(
        "User",
        (),
        {"is_authenticated": True, "is_staff": True, "is_approved": True},
    )()

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert "X-Robots-Tag" in response
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"


def test_loginwall_public_read_disabled_events_redirects_to_login():
    """With PUBLIC_READ_ENABLED=False, /events/ redirects anon to /accounts/login/."""
    from accounts.middleware import LoginWallMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = LoginWallMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get("/events/")
    request.user = type("User", (), {"is_authenticated": False})()

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(False)):
        response = mw(request)

    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert "/age-check/" not in response["Location"]


def test_loginwall_always_public_path_passes_through():
    """Always-public path (/impressum) passes through for anon."""
    from accounts.middleware import LoginWallMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = LoginWallMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get("/impressum/")
    request.user = type("User", (), {"is_authenticated": False})()

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(False)):
        response = mw(request)

    assert response.status_code == 200


def test_loginwall_public_read_enabled_events_anon_passes_through():
    """With PUBLIC_READ_ENABLED=True, /events/ returns 200 for anon (no auth wall)."""
    from accounts.middleware import LoginWallMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = LoginWallMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get("/events/")
    request.user = type("User", (), {"is_authenticated": False})()

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# AgeGateMiddleware — unit tests (no DB)
# ---------------------------------------------------------------------------


def test_agegate_redirects_html_request_without_cookie():
    """AgeGateMiddleware redirects HTML requests (no age_gate cookie) to /age-check/."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/events/",
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    request.COOKIES = {}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 302
    assert "/age-check/" in response["Location"]


def test_agegate_passes_through_with_valid_cookie():
    """AgeGateMiddleware passes through when age_gate=ok cookie is present."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/events/",
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    request.COOKIES = {"age_gate": "ok"}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200


def test_agegate_bot_bypasses_gate():
    """AgeGateMiddleware bypasses gate for known bot user-agents."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/events/",
        HTTP_ACCEPT="text/html,application/xhtml+xml",
        HTTP_USER_AGENT="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    )
    request.COOKIES = {}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200


def test_agegate_disabled_when_public_read_false():
    """AgeGateMiddleware is bypassed when PUBLIC_READ_ENABLED=False."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/events/",
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    request.COOKIES = {}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(False)):
        response = mw(request)

    # Should pass through (not redirect to age-check)
    assert response.status_code == 200


def test_agegate_skips_non_html_accept():
    """AgeGateMiddleware does not gate requests without text/html Accept header."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/events/",
        HTTP_ACCEPT="application/json",
    )
    request.COOKIES = {}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200


def test_agegate_always_public_prefix_bypasses_gate():
    """AgeGateMiddleware does not gate ALWAYS_PUBLIC_PREFIXES paths."""
    from accounts.middleware import AgeGateMiddleware

    def _get_response(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    mw = AgeGateMiddleware(_get_response)
    factory = RequestFactory()
    request = factory.get(
        "/impressum/",
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    request.COOKIES = {}

    with patch("accounts.middleware.get_flag", side_effect=make_get_flag(True)):
        response = mw(request)

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Settings structure tests (no DB)
# ---------------------------------------------------------------------------


def test_agegate_middleware_in_settings():
    """AgeGateMiddleware must appear in MIDDLEWARE right after LoginWallMiddleware."""
    from django.conf import settings

    mw = settings.MIDDLEWARE
    loginwall_idx = mw.index("accounts.middleware.LoginWallMiddleware")
    agegate_idx = mw.index("accounts.middleware.AgeGateMiddleware")
    assert agegate_idx == loginwall_idx + 1, (
        f"AgeGateMiddleware (idx {agegate_idx}) must be immediately after "
        f"LoginWallMiddleware (idx {loginwall_idx})"
    )
