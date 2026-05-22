"""
kb-uxb: seed 2 Events per visibility tier (public / semi_public / unlisted).

Idempotent — uses get_or_create on a per-tier slug, so re-running prints
'skipped' for rows that already exist.

Usage:
    uv run python manage.py seed_visibility_demo
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from organizers.models import Profile

_TIERS = [
    (
        "public",
        [
            (
                "Open House — Intro to the Scene",
                "An anonymous-friendly intro evening with talks, Q&A, and a sober"
                " social. No registration; just show up.",
            ),
            (
                "Public Workshop — Consent 101",
                "Drop-in workshop covering consent vocabulary, negotiation, and"
                " aftercare. All audiences welcome.",
            ),
        ],
    ),
    (
        "semi_public",
        [
            (
                "Members Mixer — Berlin Chapter",
                "Casual mixer for vouched members. Bring a friend (must be vouched"
                " too).",
            ),
            (
                "Skillshare Salon — Rope Fundamentals",
                "Hands-on session for vouched members. No spectators; pair up to"
                " learn.",
            ),
        ],
    ),
    (
        "unlisted",
        [
            (
                "Private Playspace — Saturday",
                "Invite-only gathering at a private location. Share the link only with "
                "people you'd personally vouch for.",
            ),
            (
                "Closed-Door Dinner — Organizer Salon",
                "Quiet dinner for trusted organizers. URL-keyed; please don't forward.",
            ),
        ],
    ),
]


class Command(BaseCommand):
    help = "Seed 2 Events per visibility tier for local demo / smoketest."

    def handle(self, *args, **options):
        # Reuse an existing approved Profile or mint one.
        organizer, _ = Profile.objects.get_or_create(
            slug="demo-seed-collective",
            defaults={
                "name": "Demo Seed Collective",
                "kind": "collective",
                "status": "approved",
            },
        )

        now = timezone.now()
        created = 0
        skipped = 0
        offset_days = 7  # first event 7 days out; each subsequent +2 days

        for visibility, events in _TIERS:
            for title, description in events:
                title_part = title.lower().split(" — ")[0].replace(" ", "-")
                slug = f"demo-{visibility}-{title_part}"
                slug = slug.replace("/", "-")[:200]
                start = now + timedelta(days=offset_days, hours=19)
                end = start + timedelta(hours=3)
                event, was_created = Event.objects.get_or_create(
                    slug=slug,
                    defaults={
                        "title": title,
                        "description": description,
                        "start": start,
                        "end": end,
                        "status": "published",
                        "visibility": visibility,
                        "published_at": now,
                    },
                )
                if was_created:
                    event.organizers.add(organizer)
                    created += 1
                    self.stdout.write(self.style.SUCCESS(f"  + {visibility}: {title}"))
                else:
                    skipped += 1
                    self.stdout.write(f"  · {visibility}: {title} (exists)")
                offset_days += 2

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"Done: created {created}, skipped {skipped}.")
        )
