from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0007_event_language_event_price_description_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="capacity",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="Max attendees; null = no cap / drop-in",
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="registration_required",
            field=models.BooleanField(
                default=False,
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="registration_url",
            field=models.URLField(
                blank=True,
                help_text="External registration page distinct from tickets_url",
            ),
        ),
    ]
