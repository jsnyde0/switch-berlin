from django.db import migrations

NEW_FLAGS = [
    # Numeric threshold flags (dotted-lowercase convention per design doc)
    ("threshold.organizer_ratings_display", True, 3, "Min reviews before organizer rating display"),
    ("threshold.event_ratings_display", True, 3, "Min reviews before event rating display"),
    ("threshold.auto_hide_flag", True, 3, "Authenticated flags before auto-hide triggers"),
    ("threshold.attendance_display", True, 5, "Min attendees before attendance count displayed"),
    ("threshold.follower_display", True, 5, "Min followers before follower count displayed"),
    # Boolean-only flags (UPPERCASE convention per design doc)
    ("EVENT_REVIEWS_DISPLAYED", False, None, "Show event reviews section (default off until 0.7 go/no-go)"),
    ("TRENDING_SORT_ENABLED", True, None, "Trending sort toggle on /events"),
    ("INGESTION_PAUSED", False, None, "Pause ingestion bot (replaces BOT_ENABLED setting)"),
]


def seed_flags(apps, schema_editor):
    FeatureFlag = apps.get_model("a_core", "FeatureFlag")
    for key, enabled, numeric_value, description in NEW_FLAGS:
        FeatureFlag.objects.get_or_create(
            key=key,
            defaults={
                "enabled": enabled,
                "numeric_value": numeric_value,
                "description": description,
            },
        )


def unseed_flags(apps, schema_editor):
    pass  # safe to leave rows on reverse


class Migration(migrations.Migration):
    dependencies = [
        ("a_core", "0004_featureflag_numeric_value_moderationaction"),
        ("a_core", "0003_seed_featureflags"),
    ]

    operations = [migrations.RunPython(seed_flags, unseed_flags)]
