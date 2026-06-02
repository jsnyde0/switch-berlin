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

# Swap the pgvector/pg_trgm migrations for no-ops so tests run without these extensions.
# Also disable or replace migrations for all local apps whose historical migration files
# carry FKs to renamed models (organizers.Organizer → Profile, rename landed in
# organizers/0007).  SQLite replays every migration from scratch; setting an app to None
# makes Django use run_syncdb (tables built from current model state, bypassing replay).
#
# Why the full local-app set is needed (not just {events, organizers, reviews}):
#   - syndication/migrations/0001 and 0004/0006 depend on events/0014 and events/0015;
#     disabling events without disabling syndication breaks the migration graph.
#   - ingestion/test_migrations/0003 depends on events/0003 and organizers/0007;
#     disabling those apps without also disabling ingestion would break that graph too.
#     Setting ingestion=None is safe: SQLite has no pg_trgm, so the test_migrations
#     no-op shim adds no value here anyway.
#   - All other local apps (accounts, venues, pages, reviews) have no pg-specific
#     migrations and no nodes that depend on other local apps, so None is safe.
#
# syndication uses a test_migrations package (not None) so that MigrationLoader can find
# syndication/0007 for Migration0007BackfillTest, which explicitly tests the RunPython
# data backfill.  syndication/test_migrations/0001-0006 are SeparateDatabaseAndState
# no-ops that register the syndication models in the historical state without running DDL
# (cross-app FKs to events/organizers are replaced with plain BigIntegerField(db_column=)
# stubs — the actual tables are built correctly by syncdb from current model state).
#
# Proven-working reference: a_core/dev_sqlite_settings.py (uses None for all apps).
MIGRATION_MODULES = {
    "a_core": "a_core.test_migrations",
    "ingestion": None,
    "events": None,
    "organizers": None,
    "reviews": None,
    "syndication": "syndication.test_migrations",
    "accounts": None,
    "venues": None,
    "pages": None,
}

# Disable ratelimit during most tests (tests that need it use override_settings)
RATELIMIT_ENABLE = False

# Allow testserver for Django test client
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
