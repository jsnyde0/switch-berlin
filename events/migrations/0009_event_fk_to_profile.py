# Migration for kb-izj: Update Event.organizer FK to point to organizers.Profile

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0007_rename_organizer_to_profile"),
        ("events", "0008_event_capacity_registration_required_registration_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="event",
            name="organizer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="events",
                to="organizers.profile",
            ),
        ),
    ]
