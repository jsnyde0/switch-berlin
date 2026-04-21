"""Register django-q2 scheduled tasks (idempotent)."""

from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Register django-q2 scheduled tasks"

    def handle(self, *args, **options):
        Schedule.objects.update_or_create(
            name="daily_flag_digest",
            defaults={
                "func": "ingestion.tasks_flags.daily_flag_digest",
                "schedule_type": Schedule.DAILY,
                "repeats": -1,
            },
        )
        Schedule.objects.update_or_create(
            name="nightly_recompute_aggregates",
            defaults={
                "func": "ingestion.tasks_flags.recompute_aggregates",
                "schedule_type": Schedule.DAILY,
                "repeats": -1,
            },
        )
        self.stdout.write(self.style.SUCCESS("Scheduled tasks registered."))
