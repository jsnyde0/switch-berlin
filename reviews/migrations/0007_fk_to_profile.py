# Migration for kb-izj: Update FK references from organizers.Organizer → organizers.Profile
# Django's RenameModel handles the underlying DB constraint rename, but Django's
# migration framework still needs to record the FK target change in each app.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0007_rename_organizer_to_profile"),
        ("reviews", "0006_flag_art16_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="review",
            name="organizer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="reviews",
                to="organizers.profile",
            ),
        ),
        migrations.AlterField(
            model_name="flag",
            name="organizer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="flags",
                to="organizers.profile",
            ),
        ),
    ]
