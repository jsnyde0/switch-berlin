"""Dev settings for local SQLite-based server (no Postgres required)."""
from a_core.settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "dev_local.db",  # noqa: F405
    }
}

# Skip ALL app migrations — use syncdb to create tables directly from models.
# This avoids broken migration references to renamed models (e.g. organizers.Organizer → Profile).
MIGRATION_MODULES = {
    "a_core": "a_core.test_migrations",
    "ingestion": None,
    "events": None,
    "organizers": None,
    "syndication": None,
    "accounts": None,
    "reviews": None,
    "venues": None,
    "pages": None,
}

# Force DEBUG mode.
DEBUG = True

# The base settings pin an explicit django `cached.Loader`, which caches compiled
# templates regardless of DEBUG — so template edits don't show up on the running
# dev server. Drop the cached layer for local visual iteration: read templates
# fresh on every request (slower, but no restart needed to see markup changes).
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa: F405
    (
        "template_partials.loader.Loader",
        [
            "django_cotton.cotton_loader.Loader",
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    )
]

# Bypass system checks that require production env vars
PUBLIC_READ_ENABLED = False
TURNSTILE_SITE_KEY = "1x00000000000000000000AA"
TURNSTILE_SECRET_KEY = "1x0000000000000000000000000000000AA"

LOGFIRE_TOKEN = ""
RATELIMIT_ENABLE = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1", "*"]
