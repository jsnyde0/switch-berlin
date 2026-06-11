# Generated for kb-6d7o.2: add publish_rev to PlatformProjection

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('syndication', '0009_alter_platformprojection_sync_source'),
    ]

    operations = [
        migrations.AddField(
            model_name='platformprojection',
            name='publish_rev',
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Publish revision counter. Incremented at each body-freeze that feeds a send "
                    "(draft→ready and republish_projection). Embedded as ?v=<rev> in the "
                    "promotion body so cached Telegram link previews can be busted."
                ),
            ),
        ),
    ]
