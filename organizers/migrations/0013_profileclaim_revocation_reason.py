# Migration for kb-m69.9: add ProfileClaim.revocation_reason
#
# Cheap-foresight col per ADR-003; populated by S9 admin revoke action.
# Soft-delete audit trail: records admin's reason when revoking an approved claim.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0012_magic_link_token_and_claim_intent"),
    ]

    operations = [
        migrations.AddField(
            model_name="profileclaim",
            name="revocation_reason",
            field=models.CharField(
                blank=True,
                default="",
                max_length=500,
                help_text=(
                    "Optional reason recorded by admin on claim revoke (ADR-003 cheap-foresight; "
                    "kb-m69.9). Populated by S9 admin revoke action."
                ),
            ),
        ),
    ]
