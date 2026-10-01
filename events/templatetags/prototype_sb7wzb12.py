"""PROTOTYPE — sb-7wzb.12 card variants — delete when the answer is captured.

Throwaway helpers for the ?variant= switcher on /events and /organizers/<slug>/.
N+1 queries on purpose; nothing here ships (ADR-016 D3).
"""

from urllib.parse import urlparse

from django import template

register = template.Library()

CARD_VARIANTS = ["I", "J", "K", "L"]
PROFILE_VARIANTS = ["A"]


@register.simple_tag
def proto_variant(request, kind="card"):
    keys = CARD_VARIANTS if kind == "card" else PROFILE_VARIANTS
    v = request.GET.get("variant") or request.COOKIES.get("proto_variant") or "A"
    return v if v in keys else keys[0]


@register.filter
def proto_cover(event):
    for img in event.images.all():
        if img.is_cover:
            return img
    return None


@register.filter
def proto_verified(profile):
    if profile is None:
        return False
    return profile.profileclaim_set.filter(rejected_at__isnull=True).exists()


@register.filter
def proto_sources(profile):
    """Public sources the collector took this organizer's events from."""
    out = {}
    if profile.website:
        out[profile.website] = ("Website", urlparse(profile.website).netloc.removeprefix("www."))
    if profile.telegram_link:
        out[profile.telegram_link] = ("Telegram", profile.telegram_link)
    for eo in profile.event_organizer_set.select_related("event__raw_message"):
        raw = eo.event.raw_message
        url = (raw.raw_payload or {}).get("url") if raw else None
        if not url or raw.source_type not in ("website", "telegram_telethon"):
            continue
        u = urlparse(url)
        if u.netloc == "t.me":
            chan = u.path.strip("/").split("/")[0]
            out.setdefault(f"https://t.me/{chan}", ("Telegram", f"@{chan}"))
        else:
            # website rows carry the event's "Details" link, which can be another
            # organizer's site (collector bug, logged) — list only the profile's own host
            host = u.netloc.removeprefix("www.")
            own = urlparse(profile.website).netloc.removeprefix("www.") if profile.website else None
            if host == own:
                out.setdefault(f"https://{host}", ("Website", host))
    seen, rows = set(), []
    for href, (kind, label) in out.items():
        if label not in seen:
            seen.add(label)
            rows.append((href, kind, label))
    return rows


@register.simple_tag
def proto_enabled():
    from django.conf import settings

    return settings.DEBUG


@register.filter
def proto_price(event):
    if event.is_free:
        return "Free"
    lo, hi = event.price_min_cents, event.price_max_cents
    if lo is not None:
        cur = "€" if (event.currency or "EUR") == "EUR" else f"{event.currency} "
        fmt = lambda c: f"{c // 100}" if c % 100 == 0 else f"{c / 100:.2f}"  # noqa: E731
        return f"{cur}{fmt(lo)}" + (f"–{fmt(hi)}" if hi and hi != lo else "")
    return (event.price_description or "")[:40] or None


@register.filter
def proto_summary(event):
    """Stand-in for a collector-generated one-liner: first sentence, capped."""
    d = (event.description or "").strip()
    if not d:
        return ""
    first = d.split(". ")[0].rstrip(".")
    words = first.split()
    return " ".join(words[:16]) + ("…" if len(words) > 16 else "")
