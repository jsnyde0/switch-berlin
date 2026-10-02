"""Seed the profiles and venues the collector source config names (sb-7wzb.25).

Collection never creates config-named entities (a typo must not make a public
profile or a second venue), so a fresh database needs them created on purpose.
Idempotent: a name resolves through the merge-aware resolver first, so an
existing row, or the winner of a staff merge, is used and nothing is created.
"""

import tomllib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from ingestion.collected import POSTER, create_collected_profile, find_or_create_venue
from organizers.names import find_profile, find_venue

DEFAULT_CONFIG = Path(settings.BASE_DIR) / "tools" / "switch-cli" / "collector_sources.toml"


class Command(BaseCommand):
    help = "Create the profiles and venues collector_sources.toml names, if missing (idempotent)"

    def add_arguments(self, parser):
        parser.add_argument("--config", default=None, help=f"source config TOML (default {DEFAULT_CONFIG})")

    def handle(self, *args, config=None, **options):
        with open(config or DEFAULT_CONFIG, "rb") as f:
            sources = tomllib.load(f)["source"]
        created = []

        def profile(name, source):
            found = find_profile(name)
            if found is None:
                found = create_collected_profile(name, f"{source} (source config)")
                created.append(f"profile {name!r}")
            return found

        for source in sources:
            organizer = (source.get("default_organizer") or "").strip()
            if organizer and organizer != POSTER:
                profile(organizer, source["name"])
            venue_name = (source.get("venue") or "").strip()
            if not venue_name:
                continue
            venue = find_venue(venue_name)
            if venue is None:
                venue = find_or_create_venue(venue_name)
                created.append(f"venue {venue_name!r}")
            runner_name = (source.get("venue_run_by") or "").strip()
            if runner_name:
                runner = profile(runner_name, source["name"])
                if venue.run_by_id is None:
                    venue.run_by = runner
                    venue.save(update_fields=["run_by"])
                    created.append(f"run-by link {venue.name!r} -> {runner.name!r}")
        for line in created:
            self.stdout.write(f"created {line}")
        if not created:
            self.stdout.write("created nothing")
