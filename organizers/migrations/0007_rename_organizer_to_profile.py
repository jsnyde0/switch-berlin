# Migration for kb-izj: Rename Organizer → Profile with kind discriminator
#
# Strategy: RenameModel to preserve the organizers_organizer DB table
# (Django will rename it to organizers_profile), plus field additions/renames.
# This preserves all existing rows.
#
# Operations:
# 1. RenameModel: Organizer → Profile
# 2. RenameField: telegram_channel → telegram_link
# 3. AddField: kind (default='collective')
# 4. AddField: pronouns
# 5. AddField: claimed_by FK(User)
# 6. AddField: claimed_at
# 7. AlterField: approved_by related_name change
# 8. AlterModelOptions: update verbose_name

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0006_backfill_consent_method"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Rename the model (renames DB table organizers_organizer → organizers_profile)
        migrations.RenameModel(
            old_name="Organizer",
            new_name="Profile",
        ),

        # Step 2: Rename telegram_channel → telegram_link
        migrations.RenameField(
            model_name="Profile",
            old_name="telegram_channel",
            new_name="telegram_link",
        ),

        # Step 3: Add kind discriminator field
        migrations.AddField(
            model_name="Profile",
            name="kind",
            field=models.CharField(
                max_length=20,
                choices=[("person", "Person"), ("collective", "Collective")],
                default="collective",
            ),
        ),

        # Step 4: Add pronouns field
        migrations.AddField(
            model_name="Profile",
            name="pronouns",
            field=models.CharField(max_length=100, blank=True, default=""),
            preserve_default=False,
        ),

        # Step 5: Add claimed_by FK
        migrations.AddField(
            model_name="Profile",
            name="claimed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="claimed_profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Step 6: Add claimed_at
        migrations.AddField(
            model_name="Profile",
            name="claimed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),

        # Step 7: Update approved_by related_name from 'approved_organizers' to 'approved_profiles'
        migrations.AlterField(
            model_name="Profile",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="approved_profiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Step 8: Update Meta verbose_name
        migrations.AlterModelOptions(
            name="Profile",
            options={
                "ordering": ["name"],
                "verbose_name": "profile",
                "verbose_name_plural": "profiles",
            },
        ),
    ]
