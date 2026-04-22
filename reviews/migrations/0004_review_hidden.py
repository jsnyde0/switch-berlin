from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reviews", "0003_flag_review_one_review_per_author_per_organizer_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="hidden",
            field=models.BooleanField(default=False, db_index=True),
        ),
    ]
