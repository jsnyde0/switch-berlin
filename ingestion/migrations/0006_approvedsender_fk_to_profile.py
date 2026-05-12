# Migration for kb-izj: Update ApprovedSender.organizer FK to point to organizers.Profile

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0007_rename_organizer_to_profile"),
        ("ingestion", "0005_rejected_message_attempt"),
    ]

    operations = [
        migrations.AlterField(
            model_name="approvedsender",
            name="organizer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to="organizers.profile",
            ),
        ),
    ]
