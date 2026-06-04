"""
One-off seed script for the local SQLite dev server.
Creates a user, organizer profile, event, and platform connections
so the syndication board renders meaningfully.

Run with:
    DJANGO_SETTINGS_MODULE=a_core.dev_sqlite_settings uv run python seed_dev.py
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "a_core.dev_sqlite_settings")

import django  # noqa: E402

django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from events.models import Event, EventOrganizer  # noqa: E402
from organizers.models import Profile, ProfileClaim  # noqa: E402
from syndication.models import PlatformConnection  # noqa: E402
from syndication.services import create_event, create_post  # noqa: E402

User = get_user_model()

# --- User ---
user, created = User.objects.get_or_create(
    username="demo",
    defaults={
        "email": "demo@switch.berlin",
        "status": "vouched",
    },
)
if created:
    user.set_password("demo")
    user.save()
    print("Created user: demo / demo")
else:
    print("User demo already exists")

# --- Profile ---
profile, _ = Profile.objects.get_or_create(
    slug="demo-organizer",
    defaults={"name": "Demo Organizer"},
)
ProfileClaim.objects.get_or_create(
    profile=profile,
    user=user,
    defaults={"verified_method": "auto_self"},
)
print(f"Profile: {profile.name} ({profile.slug})")

# --- Platform connections ---
conn_switch, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="switch",
    destination_id="own-page",
    defaults={"kinds": ["listing"], "enabled": True},
)
conn_fetlife, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="fetlife",
    destination_id="fl-demo-001",
    defaults={"kinds": ["listing", "promotion"], "enabled": True},
)
conn_telegram, _ = PlatformConnection.objects.get_or_create(
    organizer=profile,
    platform="telegram",
    destination_id="@demo-channel",
    defaults={
        "kinds": ["promotion"],
        "enabled": True,
        "credentials": {"bot_token": "fake-dev-token"},
    },
)
print("Connections: switch, fetlife, telegram")

# --- Event ---
event = Event.objects.filter(slug="demo-nightfall-2026").first()
if not event:
    import datetime  # noqa: PLC0415

    future_start = (timezone.now() + datetime.timedelta(days=14)).replace(hour=22, minute=0, second=0, microsecond=0)
    event = create_event(
        user=user,
        title="Nightfall — Queer Kink Gathering",
        slug="demo-nightfall-2026",
        start=future_start,
    )
    print(f"Created event: {event.title} (pk={event.pk})")
else:
    print(f"Event already exists: {event.title} (pk={event.pk})")

# Ensure EventOrganizer link
EventOrganizer.objects.get_or_create(
    event=event,
    profile=profile,
    defaults={"is_primary": True},
)

# --- Promo post ---
from syndication.models import Post  # noqa: E402

if not Post.objects.filter(event=event).exists():
    post = create_post(
        user=user,
        event=event,
        headline="Join us for Nightfall",
        body=(
            "A queer kink gathering for curious souls. Dress to express.\n\n"
            "Safer sex supplies provided. Consent educators on site."
        ),
    )
    print(f"Created post: {post.headline} (pk={post.pk})")
else:
    print("Post already exists")

print(f"\nHub URL: http://localhost:8000/syndication/events/{event.pk}/")
print("Login: demo / demo")
