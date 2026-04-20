from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import InviteCode


class Command(BaseCommand):
    help = "Generate InviteCode rows"

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1)
        parser.add_argument("--notes", type=str, default="")
        parser.add_argument("--created-by-username", type=str, required=True)

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["created_by_username"]
        try:
            creator = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{username}' does not exist.") from exc
        for _ in range(options["count"]):
            invite = InviteCode.objects.create(
                created_by=creator,
                notes=options["notes"],
            )
            self.stdout.write(invite.code)
