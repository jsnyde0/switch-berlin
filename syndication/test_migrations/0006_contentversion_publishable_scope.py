"""No-op replacement for syndication/0006.

Registers the ContentVersion.post FK in the migration state (no DDL — syncdb
builds the table from current model state).  The state must reflect the
post FK being present so that project_state() for migration 0007 returns
a historical apps registry that includes this field.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("syndication", "0005_remove_platformprojection_generated_by_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="contentversion",
                    name="post",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="content_versions",
                        to="syndication.post",
                    ),
                ),
                # AlterField: make event_id nullable (matches live model state after 0006).
                # Represented as plain integer since we can't FK to events in test context.
                migrations.AlterField(
                    model_name="contentversion",
                    name="event_id",
                    field=models.BigIntegerField(
                        db_column="event_id", null=True, blank=True
                    ),
                ),
            ],
        ),
    ]
