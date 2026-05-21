"""
Foundation tests for kb-i45.1 (updated by kb-m69.1):
  - custom User model (AbstractUser subclass with status, approved_at, approved_by)
  - AUTH_USER_MODEL = 'accounts.User'
  - LocaleMiddleware in MIDDLEWARE
  - LANGUAGES includes 'en' and 'de'
  - LOCALE_PATHS configured
  - locale/de/LC_MESSAGES/ directory exists
  - pgvector migration is 0001 (ordering invariant)

These tests are designed to fail FIRST before the implementation exists.
"""

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Settings assertions
# ---------------------------------------------------------------------------


def test_auth_user_model_is_accounts_user():
    """AUTH_USER_MODEL must be set to 'accounts.User' before any migration."""
    from django.conf import settings

    assert settings.AUTH_USER_MODEL == "accounts.User", (
        f"Expected 'accounts.User', got '{settings.AUTH_USER_MODEL}'"
    )


def test_accounts_app_in_installed_apps():
    """'accounts' must appear in INSTALLED_APPS."""
    from django.conf import settings

    assert "accounts" in settings.INSTALLED_APPS, (
        f"'accounts' not in INSTALLED_APPS: {settings.INSTALLED_APPS}"
    )


def test_locale_middleware_present():
    """LocaleMiddleware must be in MIDDLEWARE (for i18n routing)."""
    from django.conf import settings

    assert "django.middleware.locale.LocaleMiddleware" in settings.MIDDLEWARE, (
        f"LocaleMiddleware missing from MIDDLEWARE: {settings.MIDDLEWARE}"
    )


def test_locale_middleware_position():
    """LocaleMiddleware must come immediately after SessionMiddleware."""
    from django.conf import settings

    mw = settings.MIDDLEWARE
    session_idx = mw.index("django.contrib.sessions.middleware.SessionMiddleware")
    locale_idx = mw.index("django.middleware.locale.LocaleMiddleware")
    assert locale_idx == session_idx + 1, (
        f"LocaleMiddleware (idx {locale_idx}) must be immediately after "
        f"SessionMiddleware (idx {session_idx})"
    )


def test_languages_includes_en_and_de():
    """LANGUAGES must contain both 'en' (English) and 'de' (Deutsch)."""
    from django.conf import settings

    codes = [code for code, _label in settings.LANGUAGES]
    assert "en" in codes, f"'en' not in LANGUAGES codes: {codes}"
    assert "de" in codes, f"'de' not in LANGUAGES codes: {codes}"


def test_locale_paths_configured():
    """LOCALE_PATHS must be set and contain BASE_DIR/locale."""
    from django.conf import settings

    assert hasattr(settings, "LOCALE_PATHS"), "LOCALE_PATHS not defined in settings"
    assert len(settings.LOCALE_PATHS) > 0, "LOCALE_PATHS is empty"
    # At least one path should end with 'locale'
    locale_path_names = [Path(p).name for p in settings.LOCALE_PATHS]
    assert "locale" in locale_path_names, (
        f"No 'locale' directory in LOCALE_PATHS: {settings.LOCALE_PATHS}"
    )


# ---------------------------------------------------------------------------
# Locale directory
# ---------------------------------------------------------------------------


def test_locale_de_lc_messages_directory_exists():
    """locale/de/LC_MESSAGES/ must exist in the repo root."""
    from django.conf import settings

    locale_dir = settings.BASE_DIR / "locale" / "de" / "LC_MESSAGES"
    assert locale_dir.exists(), f"Directory does not exist: {locale_dir}"
    assert locale_dir.is_dir(), f"Path exists but is not a directory: {locale_dir}"


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_model_is_custom():
    """Django's get_user_model() should return accounts.User."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    assert User.__module__ == "accounts.models", (
        f"Expected accounts.models.User, got {User.__module__}.{User.__name__}"
    )
    assert User.__name__ == "User"


@pytest.mark.django_db
def test_user_has_status_field():
    """User model must have status CharField defaulting to 'open' (kb-m69.1)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="test_status_field")
    assert hasattr(user, "status"), "User has no status attribute"
    assert user.status == "open", (
        f"status should default to 'open', got {user.status!r}"
    )


@pytest.mark.django_db
def test_user_has_approved_at_field():
    """User model must have approved_at DateTimeField (null=True)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="test_approved_at_field")
    assert hasattr(user, "approved_at"), "User has no approved_at attribute"
    assert user.approved_at is None, (
        f"approved_at should default to None, got {user.approved_at!r}"
    )


@pytest.mark.django_db
def test_user_has_approved_by_field():
    """User model must have approved_by self-FK (null=True)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="test_approved_by_field")
    assert hasattr(user, "approved_by"), "User has no approved_by attribute"
    assert user.approved_by is None, (
        f"approved_by should default to None, got {user.approved_by!r}"
    )


@pytest.mark.django_db
def test_user_create_and_read_roundtrip():
    """User can be created and retrieved from DB with custom fields."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="roundtrip_user",
        email="roundtrip@example.com",
        password="testpass123",
    )
    fetched = User.objects.get(pk=user.pk)
    assert fetched.username == "roundtrip_user"
    assert fetched.status == "open"
    assert fetched.approved_at is None
    assert fetched.approved_by is None


@pytest.mark.django_db
def test_user_approved_by_self_fk():
    """approved_by FK can point to another User (self-referential)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    admin = User.objects.create_user(
        username="admin_user", email="admin@example.com", password="adminpass"
    )
    regular = User.objects.create_user(
        username="regular_user", email="regular@example.com", password="regpass"
    )
    import django.utils.timezone as tz

    regular.status = "vouched"
    regular.approved_at = tz.now()
    regular.approved_by = admin
    regular.save()

    fetched = User.objects.get(pk=regular.pk)
    assert fetched.status == "vouched"
    assert fetched.approved_by_id == admin.pk


# ---------------------------------------------------------------------------
# Migration ordering invariant
# ---------------------------------------------------------------------------


def test_vector_extension_migration_exists_in_a_core():
    """0001_vector_extension must exist in a_core/migrations/.

    The vector extension lives in a_core (not accounts) so that
    swappable_dependency(AUTH_USER_MODEL) correctly resolves to the accounts User
    model migration (accounts.__first__ = accounts.0001_initial), which then
    explicitly depends on a_core.0001_vector_extension.  This preserves the
    invariant: extension installed before any table migration that may use vector.
    """
    from django.conf import settings

    a_core_migrations_dir = settings.BASE_DIR / "a_core" / "migrations"
    assert a_core_migrations_dir.exists(), (
        f"a_core/migrations/ directory not found at {a_core_migrations_dir}"
    )

    migration_files = sorted(
        f.name
        for f in a_core_migrations_dir.iterdir()
        if f.name.endswith(".py") and f.name != "__init__.py"
    )
    vector_migrations = [f for f in migration_files if "vector_extension" in f]
    assert len(vector_migrations) == 1, (
        f"Expected exactly one vector_extension migration in a_core, "
        f"got: {migration_files}"
    )


def test_user_migration_depends_on_vector_extension():
    """accounts User migration must list a_core.0001_vector_extension as dependency."""
    from django.conf import settings

    accounts_migrations_dir = settings.BASE_DIR / "accounts" / "migrations"
    migration_files = sorted(
        f
        for f in accounts_migrations_dir.iterdir()
        if f.name.endswith(".py") and f.name != "__init__.py"
    )
    file_names = [f.name for f in migration_files]
    assert len(migration_files) >= 1, (
        f"Expected at least 1 migration file in accounts, got {file_names}"
    )
    # The first (and only required) accounts migration is the User model
    user_migration_file = migration_files[0]
    content = user_migration_file.read_text()
    assert "vector_extension" in content, (
        f"accounts User migration {user_migration_file.name} does not depend on "
        f"a_core.0001_vector_extension. Content snippet:\n{content[:500]}"
    )
    assert "a_core" in content, (
        f"accounts User migration {user_migration_file.name} does not reference "
        f"'a_core' app. Content snippet:\n{content[:500]}"
    )
