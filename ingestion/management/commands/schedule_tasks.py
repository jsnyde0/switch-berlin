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
        # Runs at 02:30 UTC — 30 min after finalize_attendance (02:00 UTC).
        # Scheduled to run 30 min after finalize_attendance so that 'went'
        # attendances are already finalized before aggregates are recomputed.
        Schedule.objects.update_or_create(
            name="nightly_recompute_aggregates",
            defaults={
                "func": "ingestion.tasks_flags.recompute_aggregates",
                "schedule_type": Schedule.CRON,
                "cron": "30 2 * * *",
                "repeats": -1,
            },
        )
        # Runs at 02:00 UTC = 03:00 Europe/Berlin CET = 04:00 CEST.
        # django-q2 Schedule has no timezone kwarg; the cron expression is UTC.
        Schedule.objects.update_or_create(
            name="nightly_finalize_attendance",
            defaults={
                "func": "ingestion.tasks_flags.finalize_attendance",
                "schedule_type": Schedule.CRON,
                "cron": "0 2 * * *",
                "repeats": -1,
            },
        )
        self.stdout.write(self.style.SUCCESS("Scheduled tasks registered."))
