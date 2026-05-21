"""
Tests for InviteCode model, management command, and admin.

Covers bead kb-2eu.2:
- InviteCode model basic behavior
- generate_code produces unique, correct-length tokens
- generate_invite_codes management command
- InviteCode.usable() predicate

NoSignupAdapter (phase 0.4) has been deleted per ADR-008 D1 (kb-m69.12).
OpenSignupAdapter is the canonical adapter.
"""

import secrets
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def creator(db):
    return User.objects.create_user(
        username="creator",
        email="creator@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def invite_code(creator):
    from accounts.models import InviteCode

    return InviteCode.objects.create(created_by=creator)


@pytest.fixture
def expired_invite(creator):
    from accounts.models import InviteCode

    return InviteCode.objects.create(
        created_by=creator,
        expires_at=timezone.now() - timedelta(hours=1),
    )


@pytest.fixture
def used_invite(creator, db):
    from accounts.models import InviteCode

    redeemer = User.objects.create_user(
        username="redeemer", email="redeemer@example.com", password="x"
    )
    invite = InviteCode.objects.create(
        created_by=creator,
        used_by=redeemer,
        used_at=timezone.now(),
    )
    return invite


# ---------------------------------------------------------------------------
# InviteCode model tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_can_be_created(creator):
    """InviteCode is creatable with minimal fields."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert invite.pk is not None


@pytest.mark.django_db
def test_generate_code_returns_string():
    """generate_code() returns a non-empty string."""
    from accounts.models import generate_code

    code = generate_code()
    assert isinstance(code, str)
    assert len(code) > 0


@pytest.mark.django_db
def test_generate_code_uses_secrets():
    """generate_code() produces tokens consistent with secrets.token_urlsafe(24)."""
    from accounts.models import generate_code

    # token_urlsafe(24) produces ~32 char base64url string
    code = generate_code()
    # Length should be at most 48 (model's max_length) and at least 20
    assert 20 <= len(code) <= 48


@pytest.mark.django_db
def test_generate_code_is_unique():
    """generate_code() produces unique values on repeated calls."""
    from accounts.models import generate_code

    codes = {generate_code() for _ in range(20)}
    assert len(codes) == 20


@pytest.mark.django_db
def test_invite_code_default_code_is_auto_generated(creator):
    """InviteCode.code is auto-populated from generate_code() if not provided."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert len(invite.code) > 10  # auto-generated, not empty


@pytest.mark.django_db
def test_invite_code_str(creator):
    """InviteCode.__str__ returns first 12 chars of code."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert str(invite) == invite.code[:12]


@pytest.mark.django_db
def test_invite_code_used_by_nullable(creator):
    """used_by and used_at are NULL by default on a fresh invite code."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert invite.used_by is None
    assert invite.used_at is None


@pytest.mark.django_db
def test_invite_code_expires_at_nullable(creator):
    """expires_at is NULL by default (never expires)."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert invite.expires_at is None


@pytest.mark.django_db
def test_invite_code_notes_blank(creator):
    """notes is blank by default."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert invite.notes == ""


@pytest.mark.django_db
def test_invite_code_unique_code(creator):
    """Two InviteCode rows cannot share the same code."""
    from django.db import IntegrityError

    from accounts.models import InviteCode

    code = secrets.token_urlsafe(24)
    InviteCode.objects.create(created_by=creator, code=code)
    with pytest.raises(IntegrityError):
        InviteCode.objects.create(created_by=creator, code=code)


# ---------------------------------------------------------------------------
# InviteCode.usable() predicate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_usable_returns_true_for_fresh_code(invite_code):
    """A freshly created code with no used_at and no expiry is usable."""
    assert invite_code.usable() is True


@pytest.mark.django_db
def test_usable_returns_false_for_used_code(used_invite):
    """A code with used_at set is no longer usable."""
    assert used_invite.usable() is False


@pytest.mark.django_db
def test_usable_returns_false_for_expired_code(expired_invite):
    """A code past its expires_at is no longer usable."""
    assert expired_invite.usable() is False


# ---------------------------------------------------------------------------
# Management command: generate_invite_codes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_generate_invite_codes_creates_codes(creator):
    """generate_invite_codes --count 3 creates 3 InviteCode rows."""
    from io import StringIO

    from django.core.management import call_command

    from accounts.models import InviteCode

    out = StringIO()
    call_command(
        "generate_invite_codes",
        count=3,
        notes="test batch",
        created_by_username=creator.username,
        stdout=out,
    )
    assert InviteCode.objects.filter(created_by=creator).count() == 3


@pytest.mark.django_db
def test_generate_invite_codes_prints_codes(creator):
    """generate_invite_codes --count 2 prints 2 codes to stdout."""
    from io import StringIO

    from django.core.management import call_command

    out = StringIO()
    call_command(
        "generate_invite_codes",
        count=2,
        notes="",
        created_by_username=creator.username,
        stdout=out,
    )
    output = out.getvalue().strip()
    lines = output.split("\n")
    assert len(lines) == 2


@pytest.mark.django_db
def test_generate_invite_codes_sets_notes(creator):
    """generate_invite_codes --notes '...' sets notes on each code."""
    from io import StringIO

    from django.core.management import call_command

    from accounts.models import InviteCode

    out = StringIO()
    call_command(
        "generate_invite_codes",
        count=1,
        notes="for April meetup",
        created_by_username=creator.username,
        stdout=out,
    )
    invite = InviteCode.objects.filter(created_by=creator).first()
    assert invite.notes == "for April meetup"


@pytest.mark.django_db
def test_generate_invite_codes_missing_user_raises(db):
    """generate_invite_codes with unknown username raises CommandError."""
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    out = StringIO()
    with pytest.raises(CommandError):
        call_command(
            "generate_invite_codes",
            count=1,
            notes="",
            created_by_username="nonexistent",
            stdout=out,
        )


# ---------------------------------------------------------------------------
# Admin: InviteCodeAdmin is registered
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invite_code_admin_is_registered():
    """InviteCode is registered with the admin site."""
    from django.contrib import admin

    from accounts.models import InviteCode

    assert admin.site.is_registered(InviteCode)
