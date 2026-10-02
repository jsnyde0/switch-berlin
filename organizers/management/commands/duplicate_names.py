"""List "maybe the same" Profile and Venue name pairs for staff review (sb-7wzb.20).

Read-only: prints pairs, writes nothing. Staff merge in the admin.
"""

from django.core.management.base import BaseCommand

from organizers.duplicate_names import HIGH_FLOOR, REVIEW_FLOOR, candidate_pairs
from organizers.models import Profile
from venues.models import Venue


class Command(BaseCommand):
    help = "Print candidate duplicate Profile and Venue names (exact after normalization, or Jaro-Winkler >= 0.85)."

    def handle(self, *args, **options):
        self.stdout.write(
            f"Bands: exact = same after normalization; high >= {HIGH_FLOOR}; review {REVIEW_FLOOR}-{HIGH_FLOOR}."
        )
        for label, model in (("Profile", Profile), ("Venue", Venue)):
            pairs = candidate_pairs(model.objects.order_by("pk").values_list("pk", "name"))
            self.stdout.write(f"\n## {label}: {len(pairs)} candidate pair(s)")
            for p in pairs:
                self.stdout.write(f"{p.band:<6} {p.score:.3f}  #{p.a[0]} {p.a[1]!r} ~ #{p.b[0]} {p.b[1]!r}")
