"""Tests for TrustedProxyIPMiddleware.

Tests verify that the middleware correctly reads REMOTE_ADDR from the
X-Forwarded-For header's last (rightmost) entry — the entry appended by
Caddy, our single trusted upstream proxy.
"""

from django.test import RequestFactory, SimpleTestCase

from a_core.middleware import TrustedProxyIPMiddleware


def _make_middleware():
    """Return middleware instance with an identity get_response."""
    return TrustedProxyIPMiddleware(get_response=lambda r: r)


class TrustedProxyIPMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = _make_middleware()

    def test_no_xff_header_leaves_remote_addr_unchanged(self):
        """Without XFF, REMOTE_ADDR should not be modified."""
        request = self.factory.get("/", REMOTE_ADDR="10.0.0.1")
        result = self.middleware(request)
        self.assertEqual(result.META["REMOTE_ADDR"], "10.0.0.1")

    def test_single_hop_xff_sets_remote_addr(self):
        """Single-entry XFF 'client_ip' → REMOTE_ADDR = client_ip."""
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4",
        )
        result = self.middleware(request)
        self.assertEqual(result.META["REMOTE_ADDR"], "1.2.3.4")

    def test_multi_hop_xff_uses_last_entry(self):
        """Multi-hop XFF 'client, caddy' → REMOTE_ADDR = last entry (Caddy hop)."""
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8",
        )
        result = self.middleware(request)
        self.assertEqual(result.META["REMOTE_ADDR"], "5.6.7.8")

    def test_trailing_whitespace_stripped(self):
        """Trailing/leading whitespace around IP entries is stripped."""
        request = self.factory.get(
            "/",
            REMOTE_ADDR="127.0.0.1",
            HTTP_X_FORWARDED_FOR="1.2.3.4 , 5.6.7.8 ",
        )
        result = self.middleware(request)
        self.assertEqual(result.META["REMOTE_ADDR"], "5.6.7.8")
