# Generated manually for bead kb-9kh.2 (Organizer LIA + consent_method migration)
# Adds "legitimate_interest" to Organizer.consent_method choices.
# No DB column change — choices are only validated by Django, not the DB schema.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0004_organizer_avg_rating_organizer_follower_count_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizer",
            name="consent_method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("legitimate_interest", "Legitimate interest (Art. 6(1)(f))"),
                    ("telegram_forward_implied", "Telegram forward (implied)"),
                    ("explicit_opt_in", "Explicit opt-in"),
                    ("verified_public_source", "Verified public source"),
                ],
            ),
        ),
    ]
