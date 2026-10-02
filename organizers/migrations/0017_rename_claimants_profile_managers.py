from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizers", "0016_mergerecord"),
    ]

    operations = [
        migrations.RenameField(
            model_name="profile",
            old_name="claimants",
            new_name="managers",
        ),
        migrations.AlterField(
            model_name="claimintent",
            name="message",
            field=models.TextField(
                blank=True,
                help_text=(
                    "Optional message from the person claiming, explaining who they are. "
                    "Shown to admins in the review queue."
                ),
            ),
        ),
    ]
