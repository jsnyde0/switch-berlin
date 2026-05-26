"""Seed login-ready accounts for local manual smoke testing.

Idempotent: re-running updates passwords/status/verification in place. Creates
one account per trust tier plus an admin, all with verified emails so they can
log in immediately (ACCOUNT_EMAIL_VERIFICATION is "mandatory"). Local-dev only —
guarded against running with DEBUG=False.
"""

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

DEFAULT_PASSWORD = "switch-smoke-2026"

# (email, status, is_staff, is_superuser, first_name)
ACCOUNTS = [
    ("smoke-admin@switch.test", "vouched", True, True, "Smoke Admin"),
    ("smoke-vouched@switch.test", "vouched", False, False, "Smoke Vouched"),
    ("smoke-open@switch.test", "open", False, False, "Smoke Open"),
]


class Command(BaseCommand):
    help = "Seed login-ready accounts (admin/vouched/open) for manual smoke testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            type=str,
            default=DEFAULT_PASSWORD,
            help=f"Shared password for all seeded accounts (default: {DEFAULT_PASSWORD}).",  # noqa: E501
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("Refusing to seed smoke accounts with DEBUG=False.")

        from accounts.adapter import OpenSignupAdapter

        password = options["password"]
        User = get_user_model()
        adapter = OpenSignupAdapter()

        self.stdout.write("Seeded smoke accounts (log in with EMAIL + password):\n")
        for email, status, is_staff, is_superuser, first_name in ACCOUNTS:
            user, _ = User.objects.get_or_create(
                email=email, defaults={"username": email}
            )
            user.username = email
            user.first_name = first_name
            user.status = status
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.set_password(password)
            user.save()

            EmailAddress.objects.update_or_create(
                user=user,
                email=email,
                defaults={"verified": True, "primary": True},
            )

            # Mirror real signup: give the user their auto-owned person Profile.
            adapter._create_owned_profile(user)

            role = "admin/superuser" if is_superuser else f"status={status}"
            self.stdout.write(f"  {email}  ({role})")

        self.stdout.write(f"\nPassword for all: {password}")
        self.stdout.write("Login URL: http://localhost:8000/accounts/login/")
