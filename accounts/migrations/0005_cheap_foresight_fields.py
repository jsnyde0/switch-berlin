"""Migration: Add cheap-foresight scoring fields to User.

Per ADR-003: ship schema now so F1/F2/F4 beads can activate logic without
a second migration.

Fields added:
  - vouch_score     FloatField(default=0.0)           — F1 proportional-consequences bead
  - personal_rating FloatField(null=True, blank=True) — F2 Bayesian rating bead
  - invite_codes_remaining IntegerField(default=0)    — F4 invite-earning formula bead
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_user_status_enum"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="vouch_score",
            field=models.FloatField(
                default=0.0,
                help_text="Proportional trust score accumulated via vouching graph (F1 bead activates).",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="personal_rating",
            field=models.FloatField(
                null=True,
                blank=True,
                help_text="Bayesian-averaged event-review rating (F2 bead activates).",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="invite_codes_remaining",
            field=models.IntegerField(
                default=0,
                help_text="Admin-granted invite codes available to issue (F4 bead activates earning formula).",
            ),
        ),
    ]
