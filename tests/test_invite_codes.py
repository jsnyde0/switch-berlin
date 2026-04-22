"""
Tests for InviteCode model, adapter override, management command, and admin.

Covers bead kb-2eu.2:
- InviteCode model basic behavior
- generate_code produces unique, correct-length tokens
- is_open_for_signup adapter logic (valid code, no code, expired, redeemed)
- save_user atomically redeems code
- generate_invite_codes management command
"""

import secrets
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory
from django.utils import timezone

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def invites_enabled(db):
    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="INVITES_ENABLED", defaults={"enabled": True}
    )
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def invites_disabled(db):
    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="INVITES_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    yield
    cache.clear()


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
def redeemed_invite(creator, db):
    from accounts.models import InviteCode

    redeemer = User.objects.create_user(
        username="redeemer", email="redeemer@example.com", password="x"
    )
    invite = InviteCode.objects.create(
        created_by=creator,
        redeemed_by=redeemer,
        redeemed_at=timezone.now(),
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
def test_invite_code_redeemed_by_nullable(creator):
    """redeemed_by is NULL by default."""
    from accounts.models import InviteCode

    invite = InviteCode.objects.create(created_by=creator)
    assert invite.redeemed_by is None
    assert invite.redeemed_at is None


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
# Adapter: is_open_for_signup tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_adapter_open_with_valid_code_in_get(invites_enabled, invite_code):
    """is_open_for_signup returns True when valid code is in GET params."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": invite_code.code})
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is True


@pytest.mark.django_db
def test_adapter_open_with_valid_code_in_session(invites_enabled, invite_code):
    """is_open_for_signup returns True when valid code is in session."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/")
    request.session = {"invite_code": invite_code.code}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is True


@pytest.mark.django_db
def test_adapter_closed_with_no_code(invites_enabled, invite_code):
    """is_open_for_signup returns False when no code in GET or session."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/")
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_adapter_closed_with_invalid_code(invites_enabled):
    """is_open_for_signup returns False for unknown code."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": "totally-fake-code"})
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_adapter_closed_with_expired_code(invites_enabled, expired_invite):
    """is_open_for_signup returns False for expired code."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": expired_invite.code})
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_adapter_closed_with_redeemed_code(invites_enabled, redeemed_invite):
    """is_open_for_signup returns False when code is already redeemed."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": redeemed_invite.code})
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_adapter_closed_when_invites_disabled(invites_disabled, invite_code):
    """is_open_for_signup returns False when INVITES_ENABLED=False.

    Even a valid invite code is rejected when invites are disabled.
    """
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": invite_code.code})
    request.session = {}
    adapter = NoSignupAdapter()
    assert adapter.is_open_for_signup(request) is False


@pytest.mark.django_db
def test_adapter_stores_code_in_session(invites_enabled, invite_code):
    """is_open_for_signup stores the validated code in session for later redemption."""
    from accounts.adapter import NoSignupAdapter

    factory = RequestFactory()
    request = factory.get("/accounts/signup/", {"code": invite_code.code})
    request.session = {}
    adapter = NoSignupAdapter()
    adapter.is_open_for_signup(request)
    assert request.session.get("invite_code") == invite_code.code


# ---------------------------------------------------------------------------
# Adapter: save_user redeems invite code
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_user_redeems_invite_code(invites_enabled, creator, invite_code):
    """save_user atomically marks the invite code as redeemed."""
    from unittest.mock import MagicMock

    from accounts.adapter import NoSignupAdapter

    new_user = User.objects.create_user(
        username="newuser", email="newuser@example.com", password="x"
    )

    factory = RequestFactory()
    request = factory.post("/accounts/signup/")
    request.session = {"invite_code": invite_code.code}

    adapter = NoSignupAdapter()
    # Mock form and super().save_user() to return new_user
    form = MagicMock()

    with pytest.MonkeyPatch().context() as m:
        # Patch parent save_user to return new_user without touching DB
        m.setattr(
            "allauth.account.adapter.DefaultAccountAdapter.save_user",
            lambda self, req, user, form, commit=True: new_user,
        )
        result = adapter.save_user(request, new_user, form, commit=True)

    invite_code.refresh_from_db()
    assert invite_code.redeemed_by == result
    assert invite_code.redeemed_at is not None


@pytest.mark.django_db
def test_save_user_clears_invite_code_from_session(
    invites_enabled, creator, invite_code
):
    """save_user removes invite_code from session after successful redemption."""
    from unittest.mock import MagicMock

    from accounts.adapter import NoSignupAdapter

    new_user = User.objects.create_user(
        username="newuser2", email="newuser2@example.com", password="x"
    )

    factory = RequestFactory()
    request = factory.post("/accounts/signup/")
    request.session = {"invite_code": invite_code.code}

    adapter = NoSignupAdapter()
    form = MagicMock()

    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            "allauth.account.adapter.DefaultAccountAdapter.save_user",
            lambda self, req, user, form, commit=True: new_user,
        )
        adapter.save_user(request, new_user, form, commit=True)

    assert "invite_code" not in request.session


@pytest.mark.django_db
def test_save_user_race_condition_logs_warning(invites_enabled, creator, invite_code):
    """save_user handles race condition gracefully (logs warning, doesn't crash)."""
    from unittest.mock import MagicMock, patch

    from accounts.adapter import NoSignupAdapter

    # Pre-redeem the code to simulate race condition
    another_user = User.objects.create_user(
        username="another", email="another@example.com", password="x"
    )
    invite_code.redeemed_by = another_user
    invite_code.redeemed_at = timezone.now()
    invite_code.save()

    new_user = User.objects.create_user(
        username="racing", email="racing@example.com", password="x"
    )

    factory = RequestFactory()
    request = factory.post("/accounts/signup/")
    request.session = {"invite_code": invite_code.code}

    adapter = NoSignupAdapter()
    form = MagicMock()

    with pytest.MonkeyPatch().context() as m:
        m.setattr(
            "allauth.account.adapter.DefaultAccountAdapter.save_user",
            lambda self, req, user, form, commit=True: new_user,
        )
        with patch("accounts.adapter.logger") as mock_logger:
            # Should NOT raise — lenient approach
            result = adapter.save_user(request, new_user, form, commit=True)
            mock_logger.warning.assert_called_once()

    assert result == new_user


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
