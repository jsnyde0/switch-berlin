"""Test settings override — uses SQLite for fast, isolated tests."""

from a_core.settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable logfire in tests
LOGFIRE_TOKEN = ""

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Swap the pgvector/pg_trgm migrations for no-ops so tests run without these extensions
MIGRATION_MODULES = {
    "a_core": "a_core.test_migrations",
    "ingestion": "ingestion.test_migrations",
}

# Disable ratelimit during most tests (tests that need it use override_settings)
RATELIMIT_ENABLE = False

# Allow testserver for Django test client
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
