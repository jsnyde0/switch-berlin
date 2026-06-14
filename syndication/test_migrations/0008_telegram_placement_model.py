"""No-op stub for syndication/0015_telegram_placement_model.

syncdb builds the TelegramPlacement table from current model state.
This stub just registers the dependency in the migration graph so
tests that rely on migration order don't break.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("syndication", "0007_backfill_post_canonical_content_versions"),
    ]

    operations = [
        # No DDL needed — syncdb creates the table from current model state.
        # SeparateDatabaseAndState with empty operations registers the dependency
        # without any database or state changes.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[],
        ),
    ]
