from django.db import migrations

SEED_FLAGS = [
    ("LOGIN_WALL_ENABLED", True, "Login wall (migrated from env var)"),
    ("MAP_ENABLED", True, "Map on /events (migrated from env var)"),
    ("INVITES_ENABLED", True, "Invite-only signup (migrated from env var)"),
    ("RATINGS_ENABLED", True, "Organizer rating display + event rating collection"),
    ("FLAGS_ENABLED", True, "Flag/report buttons for authenticated users"),
    ("PUBLIC_READ_ENABLED", True, "Anonymous read access to public routes"),
]


def seed_flags(apps, schema_editor):
    FeatureFlag = apps.get_model("a_core", "FeatureFlag")
    for key, enabled, description in SEED_FLAGS:
        FeatureFlag.objects.get_or_create(
            key=key,
            defaults={"enabled": enabled, "description": description},
        )


def unseed_flags(apps, schema_editor):
    pass  # safe to leave rows on reverse


class Migration(migrations.Migration):
    dependencies = [("a_core", "0002_initial")]
    operations = [migrations.RunPython(seed_flags, unseed_flags)]
