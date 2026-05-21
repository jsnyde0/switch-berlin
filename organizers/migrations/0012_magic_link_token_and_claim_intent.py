# Migration for kb-m69.8: MagicLinkToken + ClaimIntent models
#
# Per ADR-014 D2 (ClaimIntent — admin-review path, cheap-foresight cols).
# Per ADR-014 D3 (MagicLinkToken — (email, profile_id, user_target) envelope;
#                 user_target NEVER NULL — auth-before-claim invariant).

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0011_profile_verified_domain"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # MagicLinkToken — security envelope per ADR-014 D3
        migrations.CreateModel(
            name="MagicLinkToken",
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
                    "email",
                    models.CharField(
                        max_length=254,
                        help_text="The email address the user submitted in the claim form.",
                    ),
                ),
                (
                    "token",
                    models.UUIDField(
                        default=uuid.uuid4,
                        unique=True,
                        db_index=True,
                    ),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        help_text="Expiry timestamp — must be ≤24h from creation (ADR-014 D3).",
                    ),
                ),
                (
                    "used_at",
                    models.DateTimeField(
                        null=True,
                        blank=True,
                        help_text="Stamped on first valid redemption — NULL means unused.",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="magic_link_tokens",
                        to="organizers.profile",
                    ),
                ),
                (
                    "user_target",
                    models.ForeignKey(
                        # NEVER NULL — auth-before-claim invariant per ADR-014 D3
                        null=False,
                        blank=False,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="magic_link_tokens",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        # ClaimIntent — admin-review track per ADR-014 D2
        migrations.CreateModel(
            name="ClaimIntent",
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
                    "created_at",
                    models.DateTimeField(auto_now_add=True),
                ),
                # Cheap-foresight soft-delete / rejection cols (ADR-003)
                (
                    "rejected_at",
                    models.DateTimeField(null=True, blank=True),
                ),
                (
                    "rejection_reason",
                    models.CharField(max_length=500, blank=True),
                ),
                (
                    "resolved_at",
                    models.DateTimeField(null=True, blank=True),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="claim_intents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "profile",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="claim_intents",
                        to="organizers.profile",
                    ),
                ),
                (
                    "rejected_by_admin",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="rejected_claim_intents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
