from django.db import migrations


class Migration(migrations.Migration):
    """Install pgvector extension.

    Lives in a_core (not accounts) so that swappable_dependency(AUTH_USER_MODEL)
    resolves to accounts.0001_initial (the User model migration), not this extension
    migration.  The accounts User migration depends on this migration, preserving the
    invariant: extension is installed before any table that might use vector types.
    """

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,  # do NOT drop on reverse — data-loss risk on shared DB
        ),
    ]
