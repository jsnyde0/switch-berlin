from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("a_core", "0003_seed_featureflags"),
        ("reviews", "0003_flag_review_one_review_per_author_per_organizer_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="featureflag",
            name="numeric_value",
            field=models.IntegerField(
                blank=True,
                null=True,
                help_text="For threshold-style flags; None means boolean-only",
            ),
        ),
        migrations.CreateModel(
            name="ModerationAction",
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
                    "target_type",
                    models.CharField(
                        choices=[
                            ("event", "Event"),
                            ("organizer", "Organizer"),
                            ("review", "Review"),
                        ],
                        max_length=20,
                    ),
                ),
                ("target_id", models.IntegerField()),
                (
                    "target_repr",
                    models.CharField(
                        max_length=200,
                        help_text=(
                            "Snapshot of target's human-readable label at action time. "
                            "Preserved so audit rows remain interpretable after target deletion."
                        ),
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("no_action", "No action"),
                            ("hide", "Hide target"),
                            ("delete", "Delete review (soft)"),
                            ("suspend", "Suspend organizer"),
                            ("resolved", "Mark resolved"),
                        ],
                        max_length=20,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "flag",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="reviews.flag",
                    ),
                ),
                (
                    "moderator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["target_type", "target_id"],
                        name="a_core_mode_target__idx",
                    )
                ],
            },
        ),
    ]
