"""Print the most recent claim magic-link redeem URL for local smoke testing.

Claim verification emails are written to the console in DEBUG; this saves you
scraping the runserver output. Prints the newest unused, non-expired token by
default. Local-dev only (guarded against DEBUG=False).
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils import timezone

BASE_URL = "http://localhost:8000"


class Command(BaseCommand):
    help = "Print the latest claim magic-link redeem URL (local smoke testing)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            default=None,
            help="Filter to tokens whose target user has this email.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="List all live tokens instead of just the newest.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Refusing to print magic links with DEBUG=False.")

        from organizers.models import MagicLinkToken

        qs = MagicLinkToken.objects.filter(used_at__isnull=True, expires_at__gt=timezone.now()).order_by("-created_at")
        if options["email"]:
            qs = qs.filter(user_target__email=options["email"])

        tokens = list(qs if options["all"] else qs[:1])
        if not tokens:
            raise CommandError("No live (unused, unexpired) magic-link tokens found.")

        for tok in tokens:
            url = BASE_URL + reverse("organizer-claim-redeem", kwargs={"token": tok.token})
            self.stdout.write(
                f"{url}\n  profile: {tok.profile.slug}  target: {tok.user_target.email}  route: {tok.intended_method}"
            )
