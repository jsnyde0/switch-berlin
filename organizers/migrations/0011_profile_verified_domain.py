# Migration for kb-m69.4: Profile.verified_domain field
#
# Per ADR-014 D2 (verified_domain admin-set, fast-path).
# Schema migration only — no backfill needed (new optional field, defaults to NULL).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0010_profile_claim_through_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="verified_domain",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text=(
                    "Admin-set domain for email-domain fast-path claim verification "
                    "(ADR-014 D2). If set, users whose email matches this domain can "
                    "claim this profile via magic-link without admin review."
                ),
                max_length=253,
                null=True,
            ),
        ),
    ]
