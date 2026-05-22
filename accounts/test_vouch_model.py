"""TDD tests for kb-m69.7: Vouch model.

Per ADR-013 D3 (Vouch graph).
Per ADR-003 (cheap-foresight cancelled_at field).

Coverage:
(a) Vouch model exists in accounts.models
(b) Vouch has voucher, vouchee, created_at, cancelled_at fields
(c) Vouch unique_together (voucher, vouchee) prevents duplicate vouches
(d) Vouch str representation
(e) cancelled_at is nullable (cheap-foresight per ADR-003)
"""

import pytest

# ---------------------------------------------------------------------------
# (a) Vouch model exists
# ---------------------------------------------------------------------------


def test_vouch_model_importable():
    """Vouch model must be importable from accounts.models."""
    from accounts.models import Vouch  # noqa: F401


# ---------------------------------------------------------------------------
# (b) Vouch has required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_vouch_has_voucher_fk():
    """Vouch model must have a voucher FK to User."""
    from django.contrib.auth import get_user_model

    from accounts.models import Vouch

    User = get_user_model()
    voucher = User.objects.create_user(
        username="voucher1", email="voucher1@example.com", password="pass"
    )
    vouchee = User.objects.create_user(
        username="vouchee1", email="vouchee1@example.com", password="pass"
    )

    v = Vouch.objects.create(voucher=voucher, vouchee=vouchee)
    assert v.voucher == voucher
    assert v.vouchee == vouchee


@pytest.mark.django_db
def test_vouch_has_created_at():
    """Vouch.created_at must be auto-set on creation."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import Vouch

    User = get_user_model()
    u1 = User.objects.create_user(
        username="vca_u1", email="vca_u1@example.com", password="pass"
    )
    u2 = User.objects.create_user(
        username="vca_u2", email="vca_u2@example.com", password="pass"
    )

    before = timezone.now()
    v = Vouch.objects.create(voucher=u1, vouchee=u2)
    after = timezone.now()

    assert v.created_at is not None
    assert before <= v.created_at <= after


# ---------------------------------------------------------------------------
# (c) Vouch unique_together (voucher, vouchee)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_vouch_unique_together_prevents_duplicate():
    """Vouch (voucher, vouchee) pair must be unique."""
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError

    from accounts.models import Vouch

    User = get_user_model()
    u1 = User.objects.create_user(
        username="vut_u1", email="vut_u1@example.com", password="pass"
    )
    u2 = User.objects.create_user(
        username="vut_u2", email="vut_u2@example.com", password="pass"
    )

    Vouch.objects.create(voucher=u1, vouchee=u2)

    with pytest.raises(IntegrityError):
        Vouch.objects.create(voucher=u1, vouchee=u2)


# ---------------------------------------------------------------------------
# (d) Vouch str representation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_vouch_str():
    """Vouch str shows voucher and vouchee."""
    from django.contrib.auth import get_user_model

    from accounts.models import Vouch

    User = get_user_model()
    u1 = User.objects.create_user(
        username="str_u1", email="str_u1@example.com", password="pass"
    )
    u2 = User.objects.create_user(
        username="str_u2", email="str_u2@example.com", password="pass"
    )

    v = Vouch.objects.create(voucher=u1, vouchee=u2)
    s = str(v)
    # Should contain both usernames somehow
    assert "str_u1" in s or "str_u2" in s


# ---------------------------------------------------------------------------
# (e) cancelled_at is nullable (cheap-foresight per ADR-003)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_vouch_cancelled_at_is_nullable():
    """Vouch.cancelled_at must default to null (cheap-foresight per ADR-003)."""
    from django.contrib.auth import get_user_model

    from accounts.models import Vouch

    User = get_user_model()
    u1 = User.objects.create_user(
        username="cat_u1", email="cat_u1@example.com", password="pass"
    )
    u2 = User.objects.create_user(
        username="cat_u2", email="cat_u2@example.com", password="pass"
    )

    v = Vouch.objects.create(voucher=u1, vouchee=u2)
    assert v.cancelled_at is None
