"""No-op replacement for the pg_trgm migration.

Used in test settings (MIGRATION_MODULES) so tests can run without pg_trgm extension.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("ingestion", "0003_approvedsender_extractionattempt_and_more"),
    ]
    operations = []
