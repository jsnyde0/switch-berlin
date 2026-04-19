from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the Telegram bot polling loop"

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        from ingestion.bot import run_bot

        self.stdout.write("Starting Telegram bot...")
        run_bot(token)
