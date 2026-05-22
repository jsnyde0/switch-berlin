"""TDD tests for kb-m69.7: InviteCode model extensions.

Per ADR-013 D6 (V0 admin-grant invite economy).
Per ADR-008 D3 (fail loud on invalid invite).

Coverage:
(a) InviteCode has used_at + used_by fields for single-use enforcement
(b) InviteCode.usable() predicate — unused, unexpired → True
(c) InviteCode.usable() predicate — already used → False
(d) InviteCode.usable() predicate — expired → False
(e) InviteCode has grantor FK (owner — vouched user or staff for admin-grants)
(f) InviteCode.usable() predicate — code is valid when used_at is None and not expired
"""

import pytest

# ---------------------------------------------------------------------------
# (a) InviteCode has used_at + used_by fields
# ---------------------------------------------------------------------------


def test_invite_code_has_used_at_field():
    """InviteCode.used_at field must exist."""
    from accounts.models import InviteCode

    assert hasattr(InviteCode, "used_at") or "used_at" in [
        f.name for f in InviteCode._meta.get_fields()
    ]


def test_invite_code_has_used_by_field():
    """InviteCode.used_by field must exist."""
    from accounts.models import InviteCode

    field_names = [f.name for f in InviteCode._meta.get_fields()]
    assert "used_by" in field_names


# ---------------------------------------------------------------------------
# (b) InviteCode.usable() — unused, unexpired → True
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_usable_when_fresh():
    """InviteCode.usable() returns True when not used and not expired."""
    from django.contrib.auth import get_user_model

    from accounts.models import InviteCode

    User = get_user_model()
    grantor = User.objects.create_user(
        username="icu_grantor", email="icu_grantor@example.com", password="pass"
    )

    ic = InviteCode.objects.create(created_by=grantor)
    assert ic.usable() is True


# ---------------------------------------------------------------------------
# (c) InviteCode.usable() — already used → False
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_not_usable_when_used():
    """InviteCode.usable() returns False when already used."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import InviteCode

    User = get_user_model()
    grantor = User.objects.create_user(
        username="icnu_grantor", email="icnu_grantor@example.com", password="pass"
    )
    recipient = User.objects.create_user(
        username="icnu_recip", email="icnu_recip@example.com", password="pass"
    )

    ic = InviteCode.objects.create(
        created_by=grantor, used_by=recipient, used_at=timezone.now()
    )
    assert ic.usable() is False


# ---------------------------------------------------------------------------
# (d) InviteCode.usable() — expired → False
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_not_usable_when_expired():
    """InviteCode.usable() returns False when expires_at is in the past."""
    from datetime import timedelta

    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import InviteCode

    User = get_user_model()
    grantor = User.objects.create_user(
        username="ice_grantor", email="ice_grantor@example.com", password="pass"
    )

    past = timezone.now() - timedelta(days=1)
    ic = InviteCode.objects.create(created_by=grantor, expires_at=past)
    assert ic.usable() is False


# ---------------------------------------------------------------------------
# (e) InviteCode has grantor FK (null for admin-grants is acceptable via created_by)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_has_created_by():
    """InviteCode must have a created_by (grantor) FK."""
    from django.contrib.auth import get_user_model

    from accounts.models import InviteCode

    User = get_user_model()
    staff = User.objects.create_user(
        username="staff1", email="staff1@example.com", password="pass", is_staff=True
    )

    ic = InviteCode.objects.create(created_by=staff)
    assert ic.created_by == staff


# ---------------------------------------------------------------------------
# (f) InviteCode.usable() — valid when used_at is None and not expired
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_usable_predicate_with_no_expiry():
    """InviteCode.usable() returns True when used_at is None and expires_at is None."""
    from django.contrib.auth import get_user_model

    from accounts.models import InviteCode

    User = get_user_model()
    grantor = User.objects.create_user(
        username="icp_grantor", email="icp_grantor@example.com", password="pass"
    )

    ic = InviteCode.objects.create(created_by=grantor)
    assert ic.used_at is None
    assert ic.expires_at is None
    assert ic.usable() is True
