import socket
from unittest.mock import MagicMock, patch

from ingestion.enrichment import _is_safe_url, enrich_urls


class TestIsSafeUrl:
    def _make_addrinfo(self, ip: str):
        """Return a fake getaddrinfo result for the given IP string."""
        # getaddrinfo returns list of (family, type, proto, canonname, sockaddr)
        # sockaddr for IPv4 is (address, port), for IPv6 is (address, port, flow, scope)
        if ":" in ip:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 80, 0, 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]

    def test_private_ip_is_blocked(self):
        """10.x.x.x addresses must be rejected."""
        with patch("socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.1")):
            assert _is_safe_url("http://internal.example.com/") is False

    def test_loopback_ip_is_blocked(self):
        """127.x.x.x addresses must be rejected."""
        with patch("socket.getaddrinfo", return_value=self._make_addrinfo("127.0.0.1")):
            assert _is_safe_url("http://localhost/") is False

    def test_link_local_is_blocked(self):
        """169.254.x.x (AWS metadata etc.) must be rejected."""
        with patch(
            "socket.getaddrinfo", return_value=self._make_addrinfo("169.254.169.254")
        ):
            assert _is_safe_url("http://metadata.internal/") is False

    def test_rfc1918_172_is_blocked(self):
        """172.16–31.x.x must be rejected."""
        addrinfo = self._make_addrinfo("172.16.0.1")
        with patch("socket.getaddrinfo", return_value=addrinfo):
            assert _is_safe_url("http://172.16.0.1/") is False

    def test_rfc1918_192_is_blocked(self):
        """192.168.x.x must be rejected."""
        with patch(
            "socket.getaddrinfo", return_value=self._make_addrinfo("192.168.1.1")
        ):
            assert _is_safe_url("http://192.168.1.1/") is False

    def test_ipv6_loopback_is_blocked(self):
        """IPv6 loopback ::1 must be rejected."""
        with patch("socket.getaddrinfo", return_value=self._make_addrinfo("::1")):
            assert _is_safe_url("http://[::1]/") is False

    def test_ipv6_link_local_is_blocked(self):
        """IPv6 link-local fe80::1 must be rejected."""
        with patch("socket.getaddrinfo", return_value=self._make_addrinfo("fe80::1")):
            assert _is_safe_url("http://[fe80::1]/") is False

    def test_public_ip_is_allowed(self):
        """A regular public IP must be accepted."""
        with patch(
            "socket.getaddrinfo", return_value=self._make_addrinfo("93.184.216.34")
        ):
            assert _is_safe_url("https://example.com/") is True

    def test_unresolvable_host_is_blocked(self):
        """If DNS resolution fails the URL must be rejected."""
        with patch("socket.getaddrinfo", side_effect=socket.gaierror("nxdomain")):
            assert _is_safe_url("http://this-does-not-exist.invalid/") is False

    def test_non_http_scheme_is_blocked(self):
        """ftp:// and other non-http(s) schemes must be rejected."""
        assert _is_safe_url("ftp://example.com/file.txt") is False

    def test_https_scheme_is_allowed(self):
        """https scheme passes scheme check (IP check still runs)."""
        with patch(
            "socket.getaddrinfo", return_value=self._make_addrinfo("93.184.216.34")
        ):
            assert _is_safe_url("https://example.com/") is True


class TestEnrichUrlsSkipsUnsafe:
    def _make_addrinfo(self, ip: str):
        if ":" in ip:
            return [(socket.AF_INET6, socket.SOCK_STREAM, 0, "", (ip, 80, 0, 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 80))]

    def test_unsafe_url_is_skipped(self):
        """enrich_urls must skip URLs that resolve to private IPs."""
        with patch("socket.getaddrinfo", return_value=self._make_addrinfo("10.0.0.1")):
            result = enrich_urls("See http://internal/ for details")
        assert result["url_content"] == ""

    def test_safe_url_is_fetched(self):
        """enrich_urls must fetch URLs that resolve to public IPs."""
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><h1>Hello</h1></body></html>"
        mock_resp.status_code = 200

        with (
            patch(
                "socket.getaddrinfo",
                return_value=self._make_addrinfo("93.184.216.34"),
            ),
            patch("ingestion.enrichment.httpx.get", return_value=mock_resp),
        ):
            result = enrich_urls("See https://example.com/ for details")
        assert "Hello" in result["url_content"]

    def test_mixed_urls_skips_unsafe_continues_safe(self):
        """enrich_urls must skip the private URL and still fetch the public one."""
        mock_resp = MagicMock()
        mock_resp.text = "<html><body><p>Public page</p></body></html>"
        mock_resp.status_code = 200

        def fake_getaddrinfo(host, port, *args, **kwargs):
            if "internal" in host:
                return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.1", 80))]
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 80))]

        with (
            patch("socket.getaddrinfo", side_effect=fake_getaddrinfo),
            patch("ingestion.enrichment.httpx.get", return_value=mock_resp),
        ):
            result = enrich_urls("Bad http://internal/secret Good https://example.com/")
        assert "Public page" in result["url_content"]
