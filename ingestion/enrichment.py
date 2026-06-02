import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
import logfire
import markdownify


def _is_safe_url(url: str) -> bool:
    """
    Return True only if the URL uses http/https and its hostname resolves
    exclusively to public, routable IP addresses.

    Blocks private, loopback, link-local, reserved, and multicast IPs to
    prevent SSRF attacks. Also blocks non-http(s) schemes and unresolvable hosts.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        results = socket.getaddrinfo(hostname, parsed.port or 80)
    except socket.gaierror:
        logfire.warning("enrichment.url_blocked_unresolvable", url=url)
        return False

    for _family, _type, _proto, _canonname, sockaddr in results:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            return False

        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast:
            logfire.warning("enrichment.url_blocked_ssrf", url=url, ip=ip_str)
            return False

    return True


def enrich_urls(text: str) -> dict:
    """
    Extract URLs from text, fetch each with httpx (timeout=10s),
    convert HTML to markdown via markdownify, cap total at 20KB.
    Returns dict with key 'url_content' (str).
    Best-effort: failed URLs are logged and skipped.
    """
    urls = re.findall(r"https?://\S+", text)
    parts = []
    total = 0
    for url in urls:
        if not _is_safe_url(url):
            continue
        try:
            # follow_redirects=False: _is_safe_url() validates only the input
            # URL's host; a 30x to RFC1918 / 169.254.169.254 would bypass the
            # SSRF guard. Treat redirect responses as non-content.
            resp = httpx.get(
                url,
                timeout=10,
                follow_redirects=False,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if resp.is_redirect:
                logfire.warning(
                    "enrichment.url_skipped_redirect",
                    url=url,
                    status_code=resp.status_code,
                    location=resp.headers.get("location", ""),
                )
                continue
            md = markdownify.markdownify(resp.text)
            if total + len(md) > 20_000:
                remaining = 20_000 - total
                parts.append(md[:remaining] + "...[truncated at 20KB]")
                total = 20_000
                logfire.info(
                    "enrichment.url_fetched",
                    url=url,
                    status_code=resp.status_code,
                    content_length=len(md),
                    truncated=True,
                )
                break
            parts.append(md)
            total += len(md)
            logfire.info(
                "enrichment.url_fetched",
                url=url,
                status_code=resp.status_code,
                content_length=len(md),
            )
        except Exception as e:
            logfire.warning("enrichment.url_failed", url=url, error=str(e))
            continue
    return {"url_content": "\n\n".join(parts)}
