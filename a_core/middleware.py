"""Custom middleware for Switch Berlin's Django application.

TrustedProxyIPMiddleware
------------------------
Switch Berlin's network topology: client → Caddy (TLS termination on host) →
Django (gunicorn in Docker container). Caddy appends the real client IP as the
**last** comma-separated entry in X-Forwarded-For before forwarding the request
to Django.

We trust exactly one upstream hop (Caddy). The last XFF entry is Caddy's
contribution; entries to its left are supplied by the client and are
spoofable. Taking the last entry means a malicious client that injects
X-Forwarded-For: evil-ip will see their own Caddy-reported IP win, not
the injected value.

IMPORTANT — one-hop trust boundary: if a CDN or Cloudflare ever lands in
front of Caddy, this middleware needs revisiting because the trust boundary
moves outward. Do NOT generalise to "trust N hops" via a setting — keep the
trust model explicit and single-hop so it is easy to audit.
"""


class TrustedProxyIPMiddleware:
    """Rewrite REMOTE_ADDR from the last X-Forwarded-For entry.

    Django's rate-limit helpers (django_ratelimit key='ip') and other
    security-sensitive code read request.META['REMOTE_ADDR']. Behind Caddy,
    REMOTE_ADDR is always 127.0.0.1 (the loopback from the container
    network). This middleware corrects REMOTE_ADDR to the real client IP
    that Caddy placed as the rightmost XFF entry before any downstream code
    reads it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if xff:
            # Take the last (rightmost) comma-separated entry — that is the
            # entry our trusted upstream (Caddy) appended. Leftmost entries
            # are supplied by the client and must not be trusted.
            last_ip = xff.split(",")[-1].strip()
            if last_ip:
                request.META["REMOTE_ADDR"] = last_ip
        return self.get_response(request)
