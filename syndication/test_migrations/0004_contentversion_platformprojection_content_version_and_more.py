"""No-op replacement for syndication/0004.

Registers ContentVersion in the migration state (no DDL — syncdb builds the
table from current model state).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("syndication", "0003_agentpairingtoken"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="ContentVersion",
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
                        ("name", models.CharField(max_length=200)),
                        ("headline", models.CharField(blank=True, max_length=300)),
                        ("body", models.TextField(blank=True)),
                        ("imagery", models.JSONField(blank=True, default=None, null=True)),
                        ("cta", models.CharField(blank=True, max_length=500)),
                        ("voice", models.CharField(blank=True, max_length=100)),
                        (
                            "provenance",
                            models.CharField(
                                max_length=20,
                                default="rule_template",
                            ),
                        ),
                        (
                            "generated_by",
                            models.CharField(blank=True, default=None, max_length=300, null=True),
                        ),
                        (
                            "last_generated_at",
                            models.DateTimeField(blank=True, default=None, null=True),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        # events.Event FK represented as plain integer to avoid cross-app dep
                        (
                            "event_id",
                            models.BigIntegerField(
                                db_column="event_id", null=True, blank=True
                            ),
                        ),
                    ],
                ),
                migrations.AddField(
                    model_name="platformprojection",
                    name="content_version",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="projections",
                        to="syndication.contentversion",
                    ),
                ),
            ],
        ),
    ]
