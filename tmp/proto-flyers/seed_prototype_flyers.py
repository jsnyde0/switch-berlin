"""PROTOTYPE — sb-7wzb.12 — wipe me.

Throwaway fixture for the card-variant prototype. Attaches the real flyer of a
collected event's own source page as an EventImage(is_cover=True): the photo of
a public Telegram post, or a website's og:image when that image is unique to the
page (a shared og:image is a site logo, not a flyer, and is skipped). Events
whose source has no flyer get nothing — never a placeholder (ADR-008 D3).

Run:   DATABASE_URL=... uv run python manage.py shell < tmp/proto-flyers/seed_prototype_flyers.py
Wipe:  EventImage.objects.filter(alt__startswith="PROTOTYPE").delete()
"""

import collections
import io
import re
import urllib.request

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image

from events.models import Event, EventImage

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) switch-prototype"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def flyer_url(src):
    if "t.me/" in src:
        html = get(src + "?embed=1").decode("utf-8", "replace")
        m = re.search(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)", html)
        return m.group(1) if m else None
    html = get(src).decode("utf-8", "replace")
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html) or re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image', html
    )
    return m.group(1) if m else None


events = list(
    Event.objects.filter(status="published", start__gte=timezone.now(), raw_message__isnull=False)
    .select_related("raw_message")
    .order_by("start")[:40]
)
found = {}
for e in events:
    src = (e.raw_message.raw_payload or {}).get("url")
    if not src:
        continue
    try:
        found[e.pk] = flyer_url(src)
    except Exception as exc:  # throwaway: log and move on
        print("skip", e.pk, src, exc)

counts = collections.Counter(u for u in found.values() if u)
made = 0
for e in events:
    u = found.get(e.pk)
    if not u or counts[u] > 1 or e.images.exists():
        continue
    try:
        img = Image.open(io.BytesIO(get(u))).convert("RGB")
    except Exception as exc:
        print("bad image", e.pk, exc)
        continue
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82)
    EventImage.objects.create(
        event=e,
        image=ContentFile(buf.getvalue(), name=f"proto-{e.pk}.webp"),
        alt=f"PROTOTYPE flyer — {e.title}"[:300],
        is_cover=True,
    )
    made += 1
    print("cover", e.pk, img.size, u[:80])
print("covers made:", made, "of", len(events))
