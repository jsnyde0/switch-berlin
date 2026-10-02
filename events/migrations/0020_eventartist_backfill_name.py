# Backfill EventArtist.name from the linked profile's name (sb-x5xh.4). Every
# pre-existing row has a profile (it was required before 0019).

from django.db import migrations


def backfill_name(apps, schema_editor):
    EventArtist = apps.get_model("events", "EventArtist")
    for credit in EventArtist.objects.select_related("profile").filter(name=""):
        if credit.profile is None:
            raise RuntimeError(f"EventArtist {credit.pk} has neither a name nor a profile")
        credit.name = credit.profile.name
        credit.save(update_fields=["name"])


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0019_eventartist"),
    ]

    operations = [
        migrations.RunPython(backfill_name, migrations.RunPython.noop),
    ]
