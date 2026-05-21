"""TDD tests for kb-m69.7: InviteGrant audit-log model.

Per ADR-013 D4 (InviteGrant audit-log model).
Per ADR-003 (cheap-foresight — grantor nullable for admin-grants).

Coverage:
(a) InviteGrant model importable
(b) InviteGrant has grantor (nullable), recipient, invite_code, granted_at, reason fields
(c) grantor is nullable (cheap-foresight / admin-grants per ADR-003)
(d) InviteGrant.granted_at auto-set on creation
(e) reason is blank=True (optional for admin-grants)
"""

import pytest


# ---------------------------------------------------------------------------
# (a) InviteGrant model importable
# ---------------------------------------------------------------------------


def test_invite_grant_model_importable():
    """InviteGrant must be importable from accounts.models."""
    from accounts.models import InviteGrant  # noqa: F401


# ---------------------------------------------------------------------------
# (b) InviteGrant has required fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_grant_can_be_created():
    """InviteGrant can be created with all required fields."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import InviteCode, InviteGrant

    User = get_user_model()
    grantor = User.objects.create_user(username="ig_grantor", email="ig_grantor@example.com", password="pass")
    recipient = User.objects.create_user(username="ig_recip", email="ig_recip@example.com", password="pass")

    ic = InviteCode.objects.create(created_by=grantor)
    ig = InviteGrant.objects.create(
        grantor=grantor,
        recipient=recipient,
        invite_code=ic,
        granted_at=timezone.now(),
    )
    assert ig.pk is not None
    assert ig.grantor == grantor
    assert ig.recipient == recipient
    assert ig.invite_code == ic


# ---------------------------------------------------------------------------
# (c) grantor is nullable (admin-grants per ADR-003)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_grant_grantor_nullable():
    """InviteGrant.grantor must be nullable (for admin-grants per ADR-003)."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import InviteCode, InviteGrant

    User = get_user_model()
    # Create an admin/staff user as created_by for the InviteCode
    staff = User.objects.create_user(username="ig_staff", email="ig_staff@example.com", password="pass", is_staff=True)
    recipient = User.objects.create_user(username="ig_recip2", email="ig_recip2@example.com", password="pass")

    ic = InviteCode.objects.create(created_by=staff)
    ig = InviteGrant.objects.create(
        grantor=None,  # admin-grant has no grantor
        recipient=recipient,
        invite_code=ic,
        granted_at=timezone.now(),
    )
    assert ig.grantor is None


# ---------------------------------------------------------------------------
# (d) InviteGrant.granted_at auto-set on creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_grant_granted_at_auto_set():
    """InviteGrant.granted_at must be auto-set via auto_now_add."""
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    from accounts.models import InviteCode, InviteGrant

    User = get_user_model()
    grantor = User.objects.create_user(username="igat_grantor", email="igat_grantor@example.com", password="pass")
    recipient = User.objects.create_user(username="igat_recip", email="igat_recip@example.com", password="pass")

    ic = InviteCode.objects.create(created_by=grantor)
    before = timezone.now()
    ig = InviteGrant.objects.create(
        grantor=grantor,
        recipient=recipient,
        invite_code=ic,
    )
    after = timezone.now()

    assert ig.granted_at is not None
    assert before <= ig.granted_at <= after


# ---------------------------------------------------------------------------
# (e) reason is blank=True (optional)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_grant_reason_optional():
    """InviteGrant.reason must be optional (blank=True)."""
    from django.contrib.auth import get_user_model

    from accounts.models import InviteCode, InviteGrant

    User = get_user_model()
    grantor = User.objects.create_user(username="igr_grantor", email="igr_grantor@example.com", password="pass")
    recipient = User.objects.create_user(username="igr_recip", email="igr_recip@example.com", password="pass")

    ic = InviteCode.objects.create(created_by=grantor)
    ig = InviteGrant.objects.create(
        grantor=grantor,
        recipient=recipient,
        invite_code=ic,
    )
    assert ig.reason == ""
