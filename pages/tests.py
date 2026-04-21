"""Tests for pages views — robots_txt_view, age_check_view.

Uses pytest-django. All tests here mock get_flag so no live DB is required.
"""
from contextlib import contextmanager
from unittest.mock import patch

from django.test import Client, RequestFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_get_flag(public_read: bool):
    """Return a get_flag mock for pages.views."""

    def _get_flag(key, default=True):
        if key == "PUBLIC_READ_ENABLED":
            return public_read
        return default

    return _get_flag


@contextmanager
def mock_all_get_flags(public_read: bool = True):
    """Mock get_flag everywhere (middleware + context processors)."""
    _fn = make_get_flag(public_read)
    with patch("accounts.middleware.get_flag", side_effect=_fn):
        with patch("a_core.models.get_flag", side_effect=_fn):
            with patch("a_core.context_processors.get_flag", side_effect=_fn):
                yield


# ---------------------------------------------------------------------------
# robots_txt_view tests (no DB)
# ---------------------------------------------------------------------------


def test_robots_txt_view_importable():
    """robots_txt_view must be importable from pages.views."""
    from pages.views import robots_txt_view  # noqa: F401


def test_age_check_view_importable():
    """age_check_view must be importable from pages.views."""
    from pages.views import age_check_view  # noqa: F401


def test_robots_txt_url_resolves():
    """robots.txt URL resolves to robots_txt_view."""
    from django.urls import reverse

    url = reverse("robots-txt")
    assert url == "/robots.txt"


def test_age_check_url_resolves():
    """age-check URL resolves to age_check_view."""
    from django.urls import reverse

    url = reverse("age-check")
    assert url == "/age-check/"


def test_robots_txt_public_read_enabled_contains_allow():
    """GET /robots.txt with PUBLIC_READ_ENABLED=True -> 'Allow: /' in body."""
    factory = RequestFactory()
    request = factory.get("/robots.txt")

    from pages.views import robots_txt_view

    with patch("pages.views.get_flag", side_effect=make_get_flag(True)):
        response = robots_txt_view(request)

    assert response.status_code == 200
    assert "Allow: /" in response.content.decode()


def test_robots_txt_public_read_disabled_contains_disallow():
    """GET /robots.txt with PUBLIC_READ_ENABLED=False -> 'Disallow: /' in body."""
    factory = RequestFactory()
    request = factory.get("/robots.txt")

    from pages.views import robots_txt_view

    with patch("pages.views.get_flag", side_effect=make_get_flag(False)):
        response = robots_txt_view(request)

    assert response.status_code == 200
    assert "Disallow: /" in response.content.decode()


def test_robots_txt_content_type_is_text_plain():
    """robots.txt response must have content-type text/plain."""
    factory = RequestFactory()
    request = factory.get("/robots.txt")

    from pages.views import robots_txt_view

    with patch("pages.views.get_flag", side_effect=make_get_flag(True)):
        response = robots_txt_view(request)

    assert "text/plain" in response["Content-Type"]


# ---------------------------------------------------------------------------
# age_check_view GET tests (no DB)
# ---------------------------------------------------------------------------


def test_age_check_get_renders_200():
    """GET /age-check/ renders 200 with next_url context."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.get(
            "/age-check/?next=/events/",
            HTTP_ACCEPT="text/html,application/xhtml+xml",
        )
    assert response.status_code == 200


def test_age_check_get_has_form_with_csrf():
    """age_check template must include CSRF token and confirm button."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.get(
            "/age-check/",
            HTTP_ACCEPT="text/html,application/xhtml+xml",
        )
    content = response.content.decode()
    assert "csrfmiddlewaretoken" in content
    assert 'name="confirm"' in content


# ---------------------------------------------------------------------------
# age_check_view POST tests (no DB)
# ---------------------------------------------------------------------------


def test_age_check_post_confirm_yes_redirects():
    """POST /age-check/ with confirm=yes -> 302 redirect."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/events/"},
        )
    assert response.status_code == 302
    assert "/events/" in response["Location"]


def test_age_check_post_sets_age_gate_cookie():
    """POST /age-check/ with confirm=yes -> sets age_gate=ok cookie."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/"},
        )
    assert "age_gate" in response.cookies
    assert response.cookies["age_gate"].value == "ok"


def test_age_check_post_remember_sets_max_age():
    """POST /age-check/ with remember=1 -> cookie max_age = 365*24*3600."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/", "remember": "1"},
        )
    assert response.cookies["age_gate"]["max-age"] == 365 * 24 * 3600


def test_age_check_post_no_remember_is_session_cookie():
    """POST /age-check/ without remember -> session cookie (max-age empty)."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/"},
        )
    # Session cookie: max-age should be empty string (not set)
    assert response.cookies["age_gate"]["max-age"] == ""


def test_age_check_post_cookie_is_httponly():
    """age_gate cookie must be httponly."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/"},
        )
    assert response.cookies["age_gate"]["httponly"]


def test_age_check_post_cookie_samesite_lax():
    """age_gate cookie must have SameSite=Lax."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "/"},
        )
    assert response.cookies["age_gate"]["samesite"].lower() == "lax"


def test_age_check_post_next_url_sanitized():
    """POST /age-check/ with external next param -> redirects to / (sanitized)."""
    client = Client()
    with mock_all_get_flags(True):
        response = client.post(
            "/age-check/",
            data={"confirm": "yes", "next": "https://evil.com/"},
        )
    assert response.status_code == 302
    assert response["Location"] == "/"


# ---------------------------------------------------------------------------
# Template structure test (no DB)
# ---------------------------------------------------------------------------


def test_age_check_template_exists():
    """age_check.html template must exist."""
    from django.template.loader import get_template

    # This will raise TemplateDoesNotExist if missing
    get_template("age_check.html")


def test_base_html_has_og_meta_block():
    """_base.html must contain og_meta block wrapped in PUBLIC_READ_ENABLED check."""
    from django.conf import settings

    base_html = settings.BASE_DIR / "templates" / "_base.html"
    content = base_html.read_text()
    assert "og_meta" in content, "_base.html must define og_meta block"
    assert "PUBLIC_READ_ENABLED" in content, (
        "_base.html og_meta must be wrapped in PUBLIC_READ_ENABLED check"
    )
