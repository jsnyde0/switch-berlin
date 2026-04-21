"""No-op replacement for the pgvector migration.

Used in test settings (MIGRATION_MODULES) so tests can run without pgvector.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []
    operations = []
