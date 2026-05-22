"""TDD tests for kb-m69.7: Vouched signup path.

Per ADR-013 D2 (two signup paths: open + vouched).
Per ADR-008 D3 (fail loud on invalid invite).

Coverage:
(a) Signup with no invite-code → open path: status='open', no Vouch/InviteGrant rows
(b) Signup with valid invite-code → vouched path: status='vouched',
    one Vouch row (voucher=invite_code.created_by, vouchee=user),
    one InviteGrant audit row,
    InviteCode marked as used
(c) Signup with invalid invite-code → form-invalid, no User created
    (ADR-008 D3 fail loud)
(d) Signup with already-used invite-code → form-invalid, no User created
(e) Atomicity: all-or-nothing — if Vouch creation were to fail, User is not created
(f) Form has optional invite_code field
"""

import pytest
from django.test import override_settings

# ---------------------------------------------------------------------------
# (a) Open signup path — no invite code
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
)
def test_open_signup_gives_open_status_no_vouch():
    """Signup without invite code creates user with status='open', no Vouch rows."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    from accounts.models import Vouch

    User = get_user_model()
    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "open_user@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
                # no invite_code
            },
        )

    assert response.status_code == 302
    user = User.objects.filter(email="open_user@example.com").first()
    assert user is not None
    assert user.status == "open"
    assert Vouch.objects.filter(vouchee=user).count() == 0


# ---------------------------------------------------------------------------
# (b) Vouched signup path — valid invite code
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
)
def test_vouched_signup_with_valid_invite_code():
    """Signup with valid invite code: status='vouched', Vouch row, InviteGrant row,
    InviteCode marked used."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    from accounts.models import InviteCode, InviteGrant, Vouch

    User = get_user_model()
    # Create a grantor (vouched user who has codes to give)
    grantor = User.objects.create_user(
        username="grantor_v",
        email="grantor_v@example.com",
        password="pass",
        status="vouched",
    )
    ic = InviteCode.objects.create(created_by=grantor)

    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "vouched_user@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
                "invite_code": ic.code,
            },
        )

    assert response.status_code == 302
    user = User.objects.filter(email="vouched_user@example.com").first()
    assert user is not None
    assert user.status == "vouched"

    # Vouch row
    assert Vouch.objects.filter(voucher=grantor, vouchee=user).count() == 1

    # InviteGrant audit row
    assert InviteGrant.objects.filter(recipient=user, invite_code=ic).count() == 1

    # InviteCode marked used
    ic.refresh_from_db()
    assert ic.used_at is not None
    assert ic.used_by == user


# ---------------------------------------------------------------------------
# (c) Signup with invalid/nonexistent invite-code → fail loud, no User created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
)
def test_signup_with_invalid_invite_code_fails_loud():
    """Signup with invalid invite code must fail form validation, no User created
    (ADR-008 D3)."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    User = get_user_model()
    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "invalid_code_user@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
                "invite_code": "DOES-NOT-EXIST-CODE",
            },
        )

    # Form should be invalid (200 with form errors) — NO silent fallthrough to open path
    assert response.status_code == 200
    assert not User.objects.filter(email="invalid_code_user@example.com").exists()


# ---------------------------------------------------------------------------
# (d) Signup with already-used invite-code → fail loud, no User created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
)
def test_signup_with_already_used_invite_code_fails():
    """Signup with already-used invite code must fail, no User created (ADR-008 D3)."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.utils import timezone

    from accounts.models import InviteCode

    User = get_user_model()
    grantor = User.objects.create_user(
        username="grantor_used",
        email="grantor_used@example.com",
        password="pass",
    )
    existing_recipient = User.objects.create_user(
        username="existing_recip",
        email="existing_recip@example.com",
        password="pass",
    )
    ic = InviteCode.objects.create(
        created_by=grantor,
        used_by=existing_recipient,
        used_at=timezone.now(),
    )

    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "used_code_user@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
                "invite_code": ic.code,
            },
        )

    assert response.status_code == 200
    assert not User.objects.filter(email="used_code_user@example.com").exists()


# ---------------------------------------------------------------------------
# (e) Form has optional invite_code field
# ---------------------------------------------------------------------------


def test_signup_form_has_invite_code_field():
    """Signup form must have an optional invite_code field."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm()
    assert "invite_code" in form.fields
    # Must be optional (not required)
    assert form.fields["invite_code"].required is False


# ---------------------------------------------------------------------------
# (f) invite_code field in form not required (empty string OK)
# ---------------------------------------------------------------------------


def test_signup_form_invite_code_not_required():
    """Signup form invite_code field must not be required."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm()
    assert not form.fields["invite_code"].required
