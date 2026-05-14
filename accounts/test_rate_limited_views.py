"""Tests for RateLimitedLoginView and RateLimitedPasswordResetView.

These tests use RequestFactory + mocking to avoid needing a live database
connection. Rate-limit state lives in the cache (not the DB), so tests
exercise the 429 branch without requiring allauth's full DB setup.

The `render` call in the rate-limit branch is patched to skip template
rendering (which would require DB access via the feature_flags context
processor).
"""

from unittest.mock import patch

from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from a_core.middleware import TrustedProxyIPMiddleware
from accounts.views import RateLimitedLoginView, RateLimitedPasswordResetView


def _make_render_429(message_fragment):
    """Return a mock for accounts.views.render that checks 429 context."""

    def _render(request, template_name, context=None, status=None):
        assert status == 429
        assert message_fragment in (context or {}).get("error", "")
        return HttpResponse(
            content=(context or {}).get("error", ""),
            status=status or 200,
        )

    return _render


# ---------------------------------------------------------------------------
# RateLimitedLoginView
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    },
)
class RateLimitedLoginViewTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def _post(self, render_mock=None):
        request = self.factory.post(
            "/accounts/login/",
            data={"login": "user@example.com", "password": "x"},
            REMOTE_ADDR="127.0.0.1",
        )
        view = RateLimitedLoginView.as_view()
        patches = [
            patch(
                "allauth.account.views.LoginView.dispatch",
                return_value=HttpResponse("ok", status=200),
            ),
        ]
        if render_mock is not None:
            patches.append(patch("accounts.views.render", side_effect=render_mock))
        with patches[0]:
            if len(patches) > 1:
                with patches[1]:
                    return view(request)
            return view(request)

    def test_under_limit_allows_post(self):
        """POST within the rate limit delegates to LoginView (not 429)."""
        response = self._post()
        self.assertNotEqual(response.status_code, 429)

    def test_over_limit_returns_429(self):
        """POST exceeding rate limit (5/h) returns 429 with error message."""
        render_mock = _make_render_429("Too many login attempts")
        # Exhaust the 5/h limit
        for _ in range(5):
            self._post()
        # 6th request should be rate-limited
        response = self._post(render_mock=render_mock)
        self.assertEqual(response.status_code, 429)
        self.assertIn(b"Too many login attempts", response.content)


# ---------------------------------------------------------------------------
# RateLimitedPasswordResetView
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    },
)
class RateLimitedPasswordResetViewTest(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def _post(self, render_mock=None):
        request = self.factory.post(
            "/accounts/password/reset/",
            data={"email": "user@example.com"},
            REMOTE_ADDR="127.0.0.1",
        )
        view = RateLimitedPasswordResetView.as_view()
        patches = [
            patch(
                "allauth.account.views.PasswordResetView.dispatch",
                return_value=HttpResponse("ok", status=200),
            ),
        ]
        if render_mock is not None:
            patches.append(patch("accounts.views.render", side_effect=render_mock))
        with patches[0]:
            if len(patches) > 1:
                with patches[1]:
                    return view(request)
            return view(request)

    def test_under_limit_allows_post(self):
        """POST within the rate limit delegates to PasswordResetView (not 429)."""
        response = self._post()
        self.assertNotEqual(response.status_code, 429)

    def test_over_limit_returns_429(self):
        """POST exceeding rate limit (3/h) returns 429 with error message."""
        render_mock = _make_render_429("Too many password-reset attempts")
        # Exhaust the 3/h limit
        for _ in range(3):
            self._post()
        # 4th request should be rate-limited
        response = self._post(render_mock=render_mock)
        self.assertEqual(response.status_code, 429)
        self.assertIn(b"Too many password-reset attempts", response.content)


# ---------------------------------------------------------------------------
# XFF per-IP bucket isolation
# ---------------------------------------------------------------------------


@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    },
)
class XFFBucketIsolationTest(SimpleTestCase):
    """Verify that two clients with different X-Forwarded-For IPs each have
    their own independent rate-limit bucket.

    The test routes each request through TrustedProxyIPMiddleware (which
    rewrites REMOTE_ADDR from the last XFF hop) before passing it to the
    RateLimitedLoginView. This mirrors the production path:
      client → Caddy (sets XFF) → TrustedProxyIPMiddleware → view.

    Flow:
      1. Client A (XFF last hop = 10.0.0.1) exhausts the 5/h login limit.
      2. Client B (XFF last hop = 10.0.0.2) makes its first attempt.
      3. Client B's first attempt must NOT be rate-limited (status ≠ 429),
         proving that A's exhausted bucket did not bleed into B's bucket.
    """

    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()
        self.xff_middleware = TrustedProxyIPMiddleware(get_response=lambda r: r)

    def tearDown(self):
        cache.clear()

    def _post_with_xff(self, xff_last_hop, render_mock=None):
        """POST to login endpoint with XFF header set to simulate Caddy."""
        # Build an XFF that looks like: <spoofable-client-ip>, <caddy-hop>
        # We only care about the last entry (Caddy's contribution).
        request = self.factory.post(
            "/accounts/login/",
            data={"login": "user@example.com", "password": "x"},
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR=f"192.168.1.1, {xff_last_hop}",
        )
        # Route through middleware to rewrite REMOTE_ADDR
        request = self.xff_middleware(request)

        view = RateLimitedLoginView.as_view()
        patches = [
            patch(
                "allauth.account.views.LoginView.dispatch",
                return_value=HttpResponse("ok", status=200),
            ),
        ]
        if render_mock is not None:
            patches.append(patch("accounts.views.render", side_effect=render_mock))
        with patches[0]:
            if len(patches) > 1:
                with patches[1]:
                    return view(request)
            return view(request)

    def test_xff_clients_have_independent_buckets(self):
        """Client A exhausting its bucket must not affect Client B's bucket."""
        render_mock = _make_render_429("Too many login attempts")

        # Client A (10.0.0.1) exhausts the 5/h limit
        for _ in range(5):
            self._post_with_xff("10.0.0.1")

        # Client A's 6th request should be rate-limited
        response_a = self._post_with_xff("10.0.0.1", render_mock=render_mock)
        self.assertEqual(response_a.status_code, 429)

        # Client B (10.0.0.2) makes its first attempt — must NOT be rate-limited
        response_b = self._post_with_xff("10.0.0.2")
        self.assertNotEqual(
            response_b.status_code,
            429,
            "Client B was rate-limited by Client A's bucket — XFF isolation broken",
        )
