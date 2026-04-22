from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0005_event_attendance_count_event_hidden_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="event",
            name="avg_rating",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
