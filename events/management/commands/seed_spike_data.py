"""Management command to seed ~500 events for the Phase 0.4 HTMX map spike.

Seeds realistic marker density across Berlin for:
- MapLibre performance measurement (clustering at ~500 pins)
- Privacy-enforcement testing (public/neighborhood_blur/private venues)
- Cross-panel list↔map interaction testing

Tag convention: organizer name prefix ``SpikeSeed-`` marks all seeded rows
so they can be found and wiped cleanly.

Usage::

    python manage.py seed_spike_data            # first run only
    python manage.py seed_spike_data --wipe     # wipe + reseed
    python manage.py seed_spike_data --force    # allow DEBUG=False (CI/staging)
"""

import random
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from events.models import Event, Tag
from organizers.models import Profile
from venues.models import Venue

# ---------------------------------------------------------------------------
# Deterministic name lists — no external faker dep needed
# ---------------------------------------------------------------------------

_ORGANIZER_SUFFIXES = [
    "Kollektiv",
    "Crew",
    "Circle",
    "Posse",
    "Tribe",
    "Network",
    "Queer Fam",
    "Alliance",
    "Assembly",
    "Guild",
]

_EVENT_ADJECTIVES = [
    "Midnight",
    "Neon",
    "Velvet",
    "Sacred",
    "Wild",
    "Deep",
    "Soft",
    "Electric",
    "Tender",
    "Raw",
    "Open",
    "Radical",
    "Gentle",
    "Bold",
    "Fluid",
]

_EVENT_NOUNS = [
    "Play Party",
    "Munch",
    "Workshop",
    "Mixer",
    "Ritual",
    "Gathering",
    "Social",
    "Dungeon Night",
    "Open Space",
    "Community Night",
    "Talk",
    "Skill Share",
    "Film Night",
    "Dance",
    "Salon",
]

_NEIGHBORHOODS = [
    "Mitte",
    "Prenzlauer Berg",
    "Friedrichshain",
    "Kreuzberg",
    "Neukölln",
    "Wedding",
    "Schöneberg",
    "Tempelhof",
    "Charlottenburg",
    "Moabit",
]

# Berlin bounding box: lat 52.45–52.58, lng 13.28–13.48
_LAT_MIN, _LAT_MAX = 52.45, 52.58
_LNG_MIN, _LNG_MAX = 13.28, 13.48

# Seed tag (prefix) used to identify seeded rows
SEED_PREFIX = "SpikeSeed-"

# Target counts
NUM_ORGANIZERS = 10
NUM_VENUES_PER_ORGANIZER = 6  # 10 * 6 = 60 venues
EVENTS_PER_VENUE = 9  # 60 * 9 = 540 events  (≥500)
EVENT_SPREAD_DAYS = 60

# Privacy mix: ~70% public, ~20% neighborhood_blur, ~10% private
_PRIVACY_WEIGHTS = [
    ("public", 70),
    ("neighborhood_blur", 20),
    ("private", 10),
]
_PRIVACY_MODES = [m for m, _ in _PRIVACY_WEIGHTS]
_PRIVACY_PROBS = [w / 100 for _, w in _PRIVACY_WEIGHTS]


_TAG_FIXTURES = [
    {"slug": "bdsm", "label": "BDSM", "kind": "theme"},
    {"slug": "rope", "label": "Rope", "kind": "theme"},
    {"slug": "kink-social", "label": "Kink Social", "kind": "theme"},
    {"slug": "sensation", "label": "Sensation", "kind": "theme"},
    {"slug": "workshop", "label": "Workshop", "kind": "format"},
    {"slug": "party", "label": "Party", "kind": "format"},
    {"slug": "munch", "label": "Munch", "kind": "format"},
    {"slug": "queer", "label": "Queer", "kind": "identity"},
    {"slug": "femme", "label": "Femme", "kind": "identity"},
]


def _rng(seed: int = 42) -> random.Random:
    return random.Random(seed)


def _pick(rng: random.Random, choices: list, weights: list | None = None):
    if weights:
        return rng.choices(choices, weights=weights, k=1)[0]
    return rng.choice(choices)


def _slug_from(name: str) -> str:
    """Minimal slug: lowercase, spaces → hyphens, strip SpikeSeed- prefix for slug."""
    return name.lower().replace(" ", "-").replace("(", "").replace(")", "")


class Command(BaseCommand):
    help = "Seed ~500 events for the Phase 0.4 HTMX map spike."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wipe",
            action="store_true",
            default=False,
            help="Delete previously seeded rows before re-seeding.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            default=False,
            help="Allow running with DEBUG=False (e.g. staging).",
        )

    def handle(self, *args, **options):
        # Guard: refuse on production unless --force
        if not getattr(settings, "DEBUG", False) and not options["force"]:
            raise CommandError(
                "Refusing to seed data with DEBUG=False. "
                "Pass --force to override (e.g. on staging)."
            )

        wipe = options["wipe"]
        verbosity = options["verbosity"]

        seed_data_exists = Profile.objects.filter(name__startswith=SEED_PREFIX).exists()

        if seed_data_exists and not wipe:
            raise CommandError(
                "Seed data already present. Run with --wipe to clear and reseed."
            )

        if seed_data_exists and wipe:
            if verbosity >= 1:
                self.stdout.write("Wiping existing seed data…")
            # Delete tags first (M2M join rows are cleaned up automatically).
            Tag.objects.filter(slug__in=[t["slug"] for t in _TAG_FIXTURES]).delete()
            # Cascade: deleting organizers removes their events (PROTECT on venue,
            # but we delete venues separately after events).
            # Events reference organizers (PROTECT) — delete events first.
            Event.objects.filter(
                event_organizer_set__profile__name__startswith=SEED_PREFIX,
                event_organizer_set__is_primary=True,
            ).delete()
            Venue.objects.filter(name__startswith=SEED_PREFIX).delete()
            Profile.objects.filter(name__startswith=SEED_PREFIX).delete()

        rng = _rng(42)
        now = timezone.now()

        all_tags = []
        for t in _TAG_FIXTURES:
            tag, _ = Tag.objects.get_or_create(
                slug=t["slug"],
                defaults={"label": t["label"], "kind": t["kind"]},
            )
            all_tags.append(tag)

        organizers = []
        for i in range(NUM_ORGANIZERS):
            suffix = _ORGANIZER_SUFFIXES[i % len(_ORGANIZER_SUFFIXES)]
            name = f"{SEED_PREFIX}{i + 1:02d} {suffix}"
            slug = _slug_from(name)
            org = Profile.objects.create(
                name=name,
                slug=slug,
                status="approved",
            )
            organizers.append(org)

        venues = []
        for i, org in enumerate(organizers):
            for j in range(NUM_VENUES_PER_ORGANIZER):
                neighborhood = _NEIGHBORHOODS[
                    (i * NUM_VENUES_PER_ORGANIZER + j) % len(_NEIGHBORHOODS)
                ]
                lat = round(rng.uniform(_LAT_MIN, _LAT_MAX), 6)
                lng = round(rng.uniform(_LNG_MIN, _LNG_MAX), 6)
                privacy = _pick(rng, _PRIVACY_MODES, _PRIVACY_PROBS)
                name = f"{SEED_PREFIX}Venue {i + 1:02d}-{j + 1:02d} {neighborhood}"
                slug = _slug_from(name)
                venue = Venue.objects.create(
                    name=name,
                    slug=slug,
                    neighborhood=neighborhood,
                    latitude=lat,
                    longitude=lng,
                    privacy_mode=privacy,
                )
                venues.append((org, venue))

        event_count = 0
        for idx, (org, venue) in enumerate(venues):
            for k in range(EVENTS_PER_VENUE):
                adj = _pick(rng, _EVENT_ADJECTIVES)
                noun = _pick(rng, _EVENT_NOUNS)
                title = f"{adj} {noun} #{idx * EVENTS_PER_VENUE + k + 1}"
                # Spread starts across next 60 days
                offset_days = rng.randint(0, EVENT_SPREAD_DAYS)
                offset_hours = rng.randint(18, 23)
                start = now + timedelta(days=offset_days, hours=offset_hours)
                slug = f"spike-{idx}-{k}-{rng.randint(1000, 9999)}"
                # Pricing: 40% free, 40% fixed, 20% sliding scale
                roll = rng.random()
                if roll < 0.40:
                    is_free = True
                    sliding_scale = False
                    price_min = 0
                    price_max = 0
                elif roll < 0.80:
                    is_free = False
                    sliding_scale = False
                    price_min = rng.randint(500, 2000)
                    price_max = price_min + rng.randint(0, 1000)
                else:
                    is_free = False
                    sliding_scale = True
                    price_min = rng.randint(0, 500)
                    price_max = rng.randint(1000, 3000)
                event = Event.objects.create(
                    title=title,
                    slug=slug,
                    organizer=org,
                    venue=venue,
                    start=start,
                    status="published",
                    is_free=is_free,
                    sliding_scale=sliding_scale,
                    price_min_cents=price_min,
                    price_max_cents=price_max,
                )
                event.tags.set(rng.sample(all_tags, k=rng.randint(1, 3)))
                event_count += 1

        if verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {len(organizers)} organizers, "
                    f"{len(venues)} venues, "
                    f"{event_count} events."
                )
            )
