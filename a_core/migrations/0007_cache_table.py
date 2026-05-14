"""Migration: create the DatabaseCache table used for shared rate-limiting.

Background
----------
Django's default cache backend is LocMemCache, which is per-process. When
gunicorn runs with multiple workers each worker has its own independent
rate-limit counter, so the effective limit is N × declared. Switching to
DatabaseCache shares a single counter across all workers via Postgres.

The cache table is named 'cache_table' (see CACHES['default']['LOCATION']
in a_core/settings.py). We create it here via `createcachetable` so that
migrations remain the single deployment step needed after a git pull.

`createcachetable` is idempotent — it checks for table existence before
issuing CREATE TABLE, so running this migration twice is safe.

Reversal drops the table with DROP TABLE IF EXISTS, which is also
idempotent. Dropping the cache table is non-destructive: it contains only
ephemeral rate-limit counters, not application data.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Create the cache_table if it does not already exist."""
    # createcachetable checks for table existence before issuing DDL — safe to
    # call unconditionally.
    call_command("createcachetable", "cache_table", verbosity=0)


def drop_cache_table(apps, schema_editor):
    """Drop the cache_table (reverse migration)."""
    schema_editor.execute("DROP TABLE IF EXISTS cache_table")


class Migration(migrations.Migration):

    dependencies = [
        (
            "a_core",
            "0006_rename_a_core_mode_target__idx_a_core_mode_target__a6ac62_idx",
        ),
    ]

    operations = [
        migrations.RunPython(create_cache_table, reverse_code=drop_cache_table),
    ]
