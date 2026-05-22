"""
TDD tests for kb-m69.5: allauth EmailAddress backfill migration.

Per ADR-008 D3: fail loud — if a user has blank email, migration raises
with offending user IDs. Do NOT silently create EmailAddress(verified=False).

Coverage:
(a) User with non-blank email + is_active=True → EmailAddress(verified=True)
(b) User with non-blank email + is_active=False → EmailAddress(verified=False)
(c) User with blank email → migration raises listing offending user IDs
(d) User that already has an EmailAddress → backfill skips them (idempotent)
(e) Migration file exists at the expected path
"""

import pytest

# ---------------------------------------------------------------------------
# Helper: import the backfill functions from the migration
# ---------------------------------------------------------------------------


def get_backfill_functions():
    """Import backfill functions from migration 0006.

    The migration uses standalone functions (forwards/backwards) so they can
    be imported and tested independently.
    """
    import importlib

    migration = importlib.import_module(
        "accounts.migrations.0006_backfill_allauth_email_verification"
    )
    return migration.forwards, migration.backwards


# ---------------------------------------------------------------------------
# (a) Active user with email → EmailAddress(verified=True)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_creates_verified_email_for_active_user():
    """Active user (is_active=True) with email gets EmailAddress(verified=True)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="active_backfill",
        email="active@example.com",
        password="x",
        is_active=True,
    )

    forwards, _ = get_backfill_functions()
    from django.apps import apps

    forwards(apps, None)

    from allauth.account.models import EmailAddress

    addr = EmailAddress.objects.filter(user=user, email="active@example.com").first()
    assert addr is not None
    assert addr.verified is True
    assert addr.primary is True


# ---------------------------------------------------------------------------
# (b) Inactive user with email → EmailAddress(verified=False)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_creates_unverified_email_for_inactive_user():
    """Inactive user (is_active=False) with email gets EmailAddress(verified=False)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="inactive_backfill",
        email="inactive@example.com",
        password="x",
        is_active=False,
    )

    forwards, _ = get_backfill_functions()
    from django.apps import apps

    forwards(apps, None)

    from allauth.account.models import EmailAddress

    addr = EmailAddress.objects.filter(user=user, email="inactive@example.com").first()
    assert addr is not None
    assert addr.verified is False


# ---------------------------------------------------------------------------
# (c) User with blank email → migration raises with offending user IDs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_raises_for_user_with_blank_email():
    """ADR-008 D3: user with blank email causes migration to raise, listing user IDs."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    # Direct DB create to bypass any email-required validators
    user = User.objects.create(
        username="blank_email_user",
        email="",
        password="x",
        is_active=True,
    )

    forwards, _ = get_backfill_functions()
    from django.apps import apps

    with pytest.raises(Exception) as exc_info:
        forwards(apps, None)

    # Error message must include the offending user ID
    error_msg = str(exc_info.value)
    assert str(user.pk) in error_msg, (
        f"Error message should list offending user IDs but got: {error_msg}"
    )


# ---------------------------------------------------------------------------
# (d) User that already has an EmailAddress → skipped (idempotent)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_backfill_skips_users_who_already_have_email_address():
    """If a user already has an allauth EmailAddress, backfill does not duplicate it."""
    from allauth.account.models import EmailAddress
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="already_has_email",
        email="already@example.com",
        password="x",
        is_active=True,
    )
    # Pre-create EmailAddress
    EmailAddress.objects.create(
        user=user,
        email="already@example.com",
        verified=True,
        primary=True,
    )

    forwards, _ = get_backfill_functions()
    from django.apps import apps

    forwards(apps, None)

    # Should still be exactly one EmailAddress for this user
    assert EmailAddress.objects.filter(user=user).count() == 1


# ---------------------------------------------------------------------------
# (e) Migration file exists
# ---------------------------------------------------------------------------


def test_backfill_migration_file_exists():
    """Migration file 0006_backfill_allauth_email_verification.py must exist."""
    from pathlib import Path

    migration_path = (
        Path(__file__).resolve().parent
        / "migrations"
        / "0006_backfill_allauth_email_verification.py"
    )
    assert migration_path.exists(), f"Migration file not found: {migration_path}"
