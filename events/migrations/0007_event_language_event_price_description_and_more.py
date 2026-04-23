from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0006_event_avg_rating"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="language",
            field=models.CharField(
                blank=True,
                choices=[
                    ("de", "Deutsch"),
                    ("en", "English"),
                    ("bilingual", "DE+EN"),
                ],
                help_text="Primary language(s) of the event",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="price_description",
            field=models.TextField(
                blank=True,
                help_text=(
                    'Free-form price tiers, e.g. "Supporter 250€ / Normal 200€'
                    ' / Social 150€"'
                ),
            ),
        ),
        migrations.AddField(
            model_name="event",
            name="registration_email",
            field=models.EmailField(
                blank=True,
                help_text=(
                    "If organizers take registration by email rather than ticket link"
                ),
                max_length=254,
            ),
        ),
    ]
