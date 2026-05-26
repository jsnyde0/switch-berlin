"""
TDD tests for kb-m69.5: Open signup with Turnstile validation.

Per ADR-013 D2 (open signup path), ADR-014 D4 (Turnstile on public-facing forms),
ADR-008 D3 (fail loud — no silent fallback).

Coverage:
(a) OpenSignupForm has a turnstile_token field
(b) Turnstile validation: valid token → passes; missing/invalid token → form error,
    no User created
(c) Adapter validate_turnstile_token: 4xx/5xx → raises (never silent pass)
(d) Adapter validate_turnstile_token: transport error → 2 retries then raises
(e) ACCOUNT_EMAIL_VERIFICATION setting is 'mandatory'
(f) TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY are read from env
(g) Deploy check E007: PUBLIC_READ_ENABLED=True + Turnstile keys missing → error
(h) auto-Profile creation fires on open signup (adapter hook)
"""

import pytest
from django.test import override_settings

# ---------------------------------------------------------------------------
# (a) OpenSignupForm has turnstile_token field
# ---------------------------------------------------------------------------


def test_open_signup_form_has_turnstile_token_field():
    """OpenSignupForm must include a turnstile_token field."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm()
    assert "turnstile_token" in form.fields


def test_open_signup_form_inherits_allauth_fields():
    """OpenSignupForm must have email, password1, password2 fields."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm()
    for field in ("email", "password1", "password2"):
        assert field in form.fields, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# (b) Turnstile validation in form/adapter
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_signup_turnstile_bypassed_in_debug():
    """In DEBUG the widget is suppressed, so clean_turnstile_token must not flag
    a missing token (no network call) — signup is submittable locally (kb-cyp)."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm(
        data={
            "email": "debugbypass@example.com",
            "password1": "Str0ng!Pass123",
            "password2": "Str0ng!Pass123",
        }
    )
    form.is_valid()
    assert "turnstile_token" not in form.errors


@pytest.mark.django_db
@override_settings(DEBUG=False, TURNSTILE_SECRET_KEY="")
def test_signup_requires_turnstile_when_not_debug():
    """With DEBUG=False the gate is unchanged — a missing secret key fails loud
    rather than bypassing (kb-cyp / ADR-014 D4)."""
    from accounts.forms import OpenSignupForm

    form = OpenSignupForm(
        data={
            "email": "guard@example.com",
            "password1": "Str0ng!Pass123",
            "password2": "Str0ng!Pass123",
        }
    )
    assert not form.is_valid()
    assert "turnstile_token" in form.errors


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
)
def test_signup_without_turnstile_token_fails():
    """POST to signup without a Turnstile token must result in form error, no User
    created."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    User = get_user_model()
    initial_count = User.objects.count()

    client = Client()
    with patch("accounts.adapter.validate_turnstile_token", return_value=False):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "newuser@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                # no turnstile_token
            },
        )

    # Should re-render form (200 or re-render with error), not redirect to success
    assert response.status_code in (200, 302)
    if response.status_code == 302:
        # If it redirected, it must NOT have created a user
        assert User.objects.filter(email="newuser@example.com").count() == 0
    else:
        # 200: form errors shown, no user created
        assert User.objects.count() == initial_count


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
)
def test_signup_with_invalid_turnstile_token_creates_no_user():
    """Submitting signup with an invalid Turnstile token must NOT create a user."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    User = get_user_model()
    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=False):
        client.post(
            "/accounts/signup/",
            {
                "email": "shouldnotexist@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "INVALID_TOKEN",
            },
        )

    assert User.objects.filter(email="shouldnotexist@example.com").count() == 0


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
)
def test_signup_with_valid_turnstile_token_creates_user():
    """Submitting signup with a valid Turnstile token creates a User."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    User = get_user_model()
    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "validuser@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
            },
        )

    # Should redirect on success
    assert response.status_code == 302
    assert User.objects.filter(email="validuser@example.com").exists()


# ---------------------------------------------------------------------------
# (c) validate_turnstile_token: 4xx/5xx → raises (no silent pass)
# ---------------------------------------------------------------------------


def test_validate_turnstile_token_raises_on_4xx():
    """validate_turnstile_token must raise if Cloudflare returns 4xx — no silent
    pass."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    mock_response = httpx.Response(400, json={"success": False})
    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(RuntimeError):
            validate_turnstile_token("any_token", "secret_key")


def test_validate_turnstile_token_raises_on_5xx():
    """validate_turnstile_token must raise if Cloudflare returns 5xx — no silent
    pass."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    mock_response = httpx.Response(500, json={"success": False})
    with patch("httpx.post", return_value=mock_response):
        with pytest.raises(RuntimeError):
            validate_turnstile_token("any_token", "secret_key")


def test_validate_turnstile_token_returns_true_on_success():
    """validate_turnstile_token returns True when Cloudflare says success=true."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    mock_response = httpx.Response(200, json={"success": True})
    with patch("httpx.post", return_value=mock_response):
        result = validate_turnstile_token("valid_token", "secret_key")

    assert result is True


def test_validate_turnstile_token_returns_false_on_fail():
    """validate_turnstile_token returns False when Cloudflare says success=false."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    mock_response = httpx.Response(200, json={"success": False})
    with patch("httpx.post", return_value=mock_response):
        result = validate_turnstile_token("bad_token", "secret_key")

    assert result is False


# ---------------------------------------------------------------------------
# (d) validate_turnstile_token: transport error → 2 retries then raises
# ---------------------------------------------------------------------------


def test_validate_turnstile_token_retries_on_transport_error():
    """ADR-008 D4: transport error gets 2 retries, then raises."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    call_count = {"n": 0}

    def failing_post(*args, **kwargs):
        call_count["n"] += 1
        raise httpx.TransportError("connection refused")

    with patch("httpx.post", side_effect=failing_post):
        with pytest.raises(RuntimeError):
            validate_turnstile_token("token", "secret")

    # Should have been called 3 times total (1 original + 2 retries)
    assert call_count["n"] == 3


def test_validate_turnstile_token_succeeds_after_one_transport_error():
    """If transport error on first attempt, succeeds on retry (within 2 retries)."""
    from unittest.mock import patch

    import httpx

    from accounts.adapter import validate_turnstile_token

    attempts = {"n": 0}

    def flaky_post(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.TransportError("blip")
        return httpx.Response(200, json={"success": True})

    with patch("httpx.post", side_effect=flaky_post):
        result = validate_turnstile_token("token", "secret")

    assert result is True
    assert attempts["n"] == 2


# ---------------------------------------------------------------------------
# (e) ACCOUNT_EMAIL_VERIFICATION is 'mandatory'
# ---------------------------------------------------------------------------


def test_account_email_verification_is_mandatory():
    """settings.ACCOUNT_EMAIL_VERIFICATION must be 'mandatory'."""
    from django.conf import settings

    assert settings.ACCOUNT_EMAIL_VERIFICATION == "mandatory"


# ---------------------------------------------------------------------------
# (f) TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY in settings
# ---------------------------------------------------------------------------


def test_turnstile_settings_present():
    """TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY must be present in settings."""
    from django.conf import settings

    assert hasattr(settings, "TURNSTILE_SITE_KEY"), (
        "TURNSTILE_SITE_KEY missing from settings"
    )
    assert hasattr(settings, "TURNSTILE_SECRET_KEY"), (
        "TURNSTILE_SECRET_KEY missing from settings"
    )


# ---------------------------------------------------------------------------
# (g) Deploy check E007: Turnstile keys missing when PUBLIC_READ_ENABLED=True
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deploy_check_e007_fires_when_public_read_and_turnstile_keys_missing():
    """E007 fires when PUBLIC_READ_ENABLED=True and Turnstile keys are absent."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    cache.clear()
    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
    )

    from a_core.checks import check_turnstile_keys

    with override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY=""):
        errors = check_turnstile_keys(app_configs=None)

    assert any(e.id == "a_core.E007" for e in errors), (
        f"Expected E007 error, got: {errors}"
    )


@pytest.mark.django_db
def test_deploy_check_e007_silent_when_turnstile_keys_present():
    """E007 does not fire when Turnstile keys are set."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    cache.clear()
    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
    )

    from a_core.checks import check_turnstile_keys

    with override_settings(
        TURNSTILE_SITE_KEY="1x00000000000000000000AA",
        TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ):
        errors = check_turnstile_keys(app_configs=None)

    assert not any(e.id == "a_core.E007" for e in errors)


@pytest.mark.django_db
def test_deploy_check_e007_silent_when_public_read_disabled():
    """E007 does not fire when PUBLIC_READ_ENABLED=False even if keys missing."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    cache.clear()
    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )

    from a_core.checks import check_turnstile_keys

    with override_settings(TURNSTILE_SITE_KEY="", TURNSTILE_SECRET_KEY=""):
        errors = check_turnstile_keys(app_configs=None)

    assert not any(e.id == "a_core.E007" for e in errors)


# ---------------------------------------------------------------------------
# (h) auto-Profile creation fires on open signup
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
)
def test_open_signup_creates_profile_and_claim():
    """Open signup with valid Turnstile creates Profile(kind=person) + ProfileClaim."""
    from unittest.mock import patch

    from django.contrib.auth import get_user_model
    from django.test import Client

    from organizers.models import Profile, ProfileClaim

    User = get_user_model()
    client = Client()

    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        client.post(
            "/accounts/signup/",
            {
                "email": "withprofile@example.com",
                "password1": "Str0ng!Pass123",
                "password2": "Str0ng!Pass123",
                "turnstile_token": "VALID_TOKEN",
            },
        )

    user = User.objects.filter(email="withprofile@example.com").first()
    assert user is not None
    assert Profile.objects.filter(claimants=user, kind="person").count() == 1
    assert (
        ProfileClaim.objects.filter(user=user, verified_method="auto_self").count() == 1
    )
