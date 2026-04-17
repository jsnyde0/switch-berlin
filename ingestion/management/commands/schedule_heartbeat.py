from django.core.management.base import BaseCommand
from django_q.models import Schedule


class Command(BaseCommand):
    help = "Seed django-q2 schedule entries (idempotent)"

    def handle(self, *args, **options):
        Schedule.objects.update_or_create(
            name="heartbeat",
            defaults=dict(
                func="ingestion.tasks.heartbeat",
                schedule_type=Schedule.MINUTES,
                minutes=5,
                repeats=-1,  # repeat forever
            ),
        )
        self.stdout.write(
            self.style.SUCCESS("Schedule seeded: heartbeat every 5 minutes")
        )
