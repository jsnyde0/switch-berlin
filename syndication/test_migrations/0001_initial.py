"""Test-settings migration for syndication app — SQLite path.

Used in test settings (MIGRATION_MODULES) so tests run without Postgres and
without replaying historical cross-app FK operations that reference the
organizers.Organizer model (renamed to Profile in organizers/0007).

Strategy:
  - database_operations: use RunPython to create all syndication tables from
    the CURRENT model state (bypasses historical FK resolution issues).  This
    is safe because all other apps (events, organizers, etc.) are already
    syncdb-built when this migration runs.
  - state_operations: register the minimal syndication model schema in the
    historical state so that MigrationLoader / project_state() returns a usable
    historical apps registry for tests like Migration0007BackfillTest.

The SeparateDatabaseAndState boundary is the key: database_operations create
the real tables; state_operations register the models in the migration state
graph WITHOUT the cross-app FK dependency edges that would break the graph
when events/organizers are set to None.
"""

import django.db.models.deletion
from django.db import migrations, models


def _create_syndication_tables(apps, schema_editor):
    """Create all syndication tables from the current (live) model state.

    This is called from database_operations, so it runs when the migration
    is applied to the DB.  We use the live models (not historical) to avoid
    any renamed-model FK resolution issue.
    """
    from django.apps import apps as live_apps

    for model_name in [
        "PlatformConnection",
        "Post",
        "AgentCredential",
        "IdentityToken",
        "AgentPairingToken",
        "ContentVersion",
        "PlatformProjection",
        "TelegramPlacement",
    ]:
        try:
            model = live_apps.get_model("syndication", model_name)
            schema_editor.create_model(model)
        except Exception:
            # Table may already exist (e.g., if syncdb ran first) — skip.
            pass


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(_create_syndication_tables, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="PlatformConnection",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("platform", models.CharField(max_length=100)),
                        ("destination_id", models.CharField(max_length=300)),
                        ("credentials", models.JSONField(blank=True, default=dict)),
                        ("enabled", models.BooleanField(default=True)),
                        ("kinds", models.JSONField(blank=True, default=list)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        # organizer FK stub — avoids cross-app dep while keeping column.
                        (
                            "organizer_id",
                            models.BigIntegerField(null=True, db_column="organizer_id"),
                        ),
                    ],
                ),
                migrations.CreateModel(
                    name="Post",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("headline", models.CharField(max_length=300)),
                        ("body", models.TextField()),
                        (
                            "imagery",
                            models.JSONField(blank=True, default=None, null=True),
                        ),
                        ("cta", models.CharField(blank=True, max_length=500)),
                        ("voice", models.CharField(blank=True, max_length=100)),
                        (
                            "sequence_order",
                            models.PositiveIntegerField(blank=True, null=True),
                        ),
                        (
                            "lifecycle_moment",
                            models.CharField(blank=True, max_length=50),
                        ),
                        (
                            "scheduled_for",
                            models.DateTimeField(blank=True, null=True),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        # event FK stub — avoids cross-app dep while keeping column name.
                        ("event_id", models.BigIntegerField(db_column="event_id")),
                    ],
                ),
                migrations.CreateModel(
                    name="PlatformProjection",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "kind",
                            models.CharField(
                                choices=[
                                    ("listing", "Listing"),
                                    ("promotion", "Promotion"),
                                ],
                                max_length=20,
                            ),
                        ),
                        (
                            "status",
                            models.CharField(
                                choices=[
                                    ("draft", "Draft"),
                                    ("ready", "Ready"),
                                    ("published", "Published"),
                                    ("failed", "Failed"),
                                ],
                                default="draft",
                                max_length=20,
                            ),
                        ),
                        ("override_data", models.JSONField(blank=True, default=dict)),
                        (
                            "frozen_content",
                            models.JSONField(blank=True, default=None, null=True),
                        ),
                        (
                            "provenance",
                            models.CharField(max_length=20, default="rule_template"),
                        ),
                        (
                            "generated_by",
                            models.CharField(
                                blank=True, default=None, max_length=300, null=True
                            ),
                        ),
                        (
                            "last_generated_at",
                            models.DateTimeField(
                                blank=True, default=None, null=True
                            ),
                        ),
                        ("external_id", models.CharField(blank=True, max_length=200)),
                        ("external_url", models.URLField(blank=True)),
                        ("syndicated_at", models.DateTimeField(blank=True, null=True)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "connection",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="projections",
                                to="syndication.platformconnection",
                            ),
                        ),
                        # source_event FK stub
                        (
                            "source_event_id",
                            models.BigIntegerField(
                                blank=True, null=True, db_column="source_event_id"
                            ),
                        ),
                        (
                            "source_post",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.CASCADE,
                                related_name="projections",
                                to="syndication.post",
                            ),
                        ),
                    ],
                ),
            ],
        ),
    ]
