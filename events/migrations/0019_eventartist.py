# EventFacilitator -> EventArtist (ADR-007 D2, sb-x5xh.4): an artist credit is a
# display name, optionally linked to a Profile. The Event.facilitators M2M is
# dropped; rendering reads EventArtist rows so name-only credits show.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0018_location_note_no_street_address"),
    ]

    operations = [
        migrations.RemoveField(model_name="event", name="facilitators"),
        migrations.RenameModel(old_name="EventFacilitator", new_name="EventArtist"),
        migrations.AlterModelOptions(
            name="eventartist",
            options={
                "ordering": ["order", "id"],
                "verbose_name": "event artist",
                "verbose_name_plural": "event artists",
            },
        ),
        migrations.AlterField(
            model_name="eventartist",
            name="event",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="artist_credits",
                to="events.event",
            ),
        ),
        migrations.AlterField(
            model_name="eventartist",
            name="profile",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="artist_credits",
                to="organizers.profile",
            ),
        ),
        # The "" default fills existing rows only (preserve_default=False);
        # 0020 backfills them from profile.name.
        migrations.AddField(
            model_name="eventartist",
            name="name",
            field=models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
    ]
