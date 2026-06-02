"""
TDD tests for kb-m69.8: MagicLinkToken model.

RED phase: written BEFORE implementation.
Per ADR-014 D3 — magic-link security envelope:
- (email, profile_id, user_id) triple (user_target NEVER NULL — auth-before-claim)
- 24h expiry
- single-use (used_at nullable, stamp on use)
- stored token (UUID or signed)

Per ADR-008 D3 — fail loud on token misuse.
"""

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


# ---------------------------------------------------------------------------
# Model importable + fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_token_importable():
    """MagicLinkToken is importable from organizers.models."""
    from organizers.models import MagicLinkToken

    assert MagicLinkToken is not None


@pytest.mark.django_db
def test_magic_link_token_fields():
    """MagicLinkToken has the required fields per ADR-014 D3."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="mlt_user", email="mlt_user@example.com", password="x")
    profile = Profile.objects.create(name="MLT Profile", slug="mlt-profile")

    token = MagicLinkToken.objects.create(
        email="mlt_user@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    assert token.email == "mlt_user@example.com"
    assert token.profile == profile
    assert token.user_target == user
    assert token.token is not None
    assert token.expires_at is not None
    assert token.used_at is None  # initially unused


@pytest.mark.django_db
def test_magic_link_token_auto_token_generated():
    """MagicLinkToken.token is auto-generated if not provided."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="mlt_autotok", email="mlt_autotok@example.com", password="x")
    profile = Profile.objects.create(name="AutoTok Profile", slug="autotok-profile")

    token = MagicLinkToken.objects.create(
        email="mlt_autotok@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    # token field should be a valid UUID
    assert token.token is not None
    # Should be parseable as UUID
    try:
        uuid.UUID(str(token.token))
    except ValueError:
        pytest.fail(f"token is not a valid UUID: {token.token!r}")


# ---------------------------------------------------------------------------
# user_target NEVER NULL (ADR-014 D3 — auth-before-claim invariant)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_token_user_target_not_null():
    """MagicLinkToken.user_target cannot be NULL (DB constraint — ADR-014 D3)."""
    from django.db import IntegrityError

    from organizers.models import MagicLinkToken, Profile

    profile = Profile.objects.create(name="NullUser Profile", slug="nulluser-profile")

    with pytest.raises((IntegrityError, ValueError, TypeError)):
        MagicLinkToken.objects.create(
            email="nouser@example.com",
            profile=profile,
            user_target=None,
            expires_at=timezone.now() + timedelta(hours=24),
        )


# ---------------------------------------------------------------------------
# Expiry: ≤ 24h envelope per ADR-014 D3
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_token_is_expired_when_past():
    """MagicLinkToken is expired when expires_at is in the past."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="expired_user", email="expired@example.com", password="x")
    profile = Profile.objects.create(name="Expired Profile", slug="expired-profile")

    token = MagicLinkToken.objects.create(
        email="expired@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() - timedelta(hours=1),
    )

    assert token.is_expired is True


@pytest.mark.django_db
def test_magic_link_token_is_not_expired_when_future():
    """MagicLinkToken is not expired when expires_at is in the future."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="valid_user_exp", email="valid_exp@example.com", password="x")
    profile = Profile.objects.create(name="Valid Profile", slug="valid-profile-exp")

    token = MagicLinkToken.objects.create(
        email="valid_exp@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=23),
    )

    assert token.is_expired is False


# ---------------------------------------------------------------------------
# Single-use enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_token_is_used_false_initially():
    """MagicLinkToken.is_used is False when used_at is None."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="unused_user", email="unused@example.com", password="x")
    profile = Profile.objects.create(name="Unused Profile", slug="unused-profile")

    token = MagicLinkToken.objects.create(
        email="unused@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    assert token.is_used is False


@pytest.mark.django_db
def test_magic_link_token_is_used_true_after_marking():
    """MagicLinkToken.is_used is True after marking used."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="used_user", email="used@example.com", password="x")
    profile = Profile.objects.create(name="Used Profile", slug="used-profile")

    token = MagicLinkToken.objects.create(
        email="used@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    token.mark_used()
    token.refresh_from_db()

    assert token.is_used is True
    assert token.used_at is not None


@pytest.mark.django_db
def test_magic_link_token_is_valid_when_fresh():
    """MagicLinkToken.is_valid is True when not expired and not used."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="fresh_user", email="fresh@example.com", password="x")
    profile = Profile.objects.create(name="Fresh Profile", slug="fresh-profile")

    token = MagicLinkToken.objects.create(
        email="fresh@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    assert token.is_valid is True


@pytest.mark.django_db
def test_magic_link_token_is_valid_false_when_expired():
    """MagicLinkToken.is_valid is False when expired."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="exp_valid", email="exp_valid@example.com", password="x")
    profile = Profile.objects.create(name="Exp Valid Profile", slug="exp-valid-profile")

    token = MagicLinkToken.objects.create(
        email="exp_valid@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() - timedelta(minutes=1),
    )

    assert token.is_valid is False


@pytest.mark.django_db
def test_magic_link_token_is_valid_false_when_used():
    """MagicLinkToken.is_valid is False when used."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="used_valid", email="used_valid@example.com", password="x")
    profile = Profile.objects.create(name="Used Valid Profile", slug="used-valid-profile")

    token = MagicLinkToken.objects.create(
        email="used_valid@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    token.mark_used()
    token.refresh_from_db()

    assert token.is_valid is False


# ---------------------------------------------------------------------------
# ADR-014 D1: verified_method vocabulary — exactly 4 values, no magic_link
# ---------------------------------------------------------------------------


def test_verified_method_choices_has_exactly_4_values():
    """VERIFIED_METHOD_CHOICES must have exactly 4 canonical values per ADR-014 D1.

    The allowed values are: email_domain, admin_review, admin_legacy, auto_self.
    'magic_link' is NOT a verified_method — it is a confirmation mechanism, not
    a verification method.
    """
    from organizers.models import ProfileClaim

    choices = dict(ProfileClaim.VERIFIED_METHOD_CHOICES)
    assert len(choices) == 4, (
        f"Expected exactly 4 VERIFIED_METHOD_CHOICES per ADR-014 D1, got {len(choices)}: {list(choices.keys())}"
    )
    assert "magic_link" not in choices, (
        "'magic_link' must NOT be in VERIFIED_METHOD_CHOICES — it is not a valid verified_method (ADR-014 D1)"
    )
    for expected in ("email_domain", "admin_review", "admin_legacy", "auto_self"):
        assert expected in choices, f"Expected '{expected}' in VERIFIED_METHOD_CHOICES but it is missing"


# ---------------------------------------------------------------------------
# ADR-014 D1: MagicLinkToken.intended_method field
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_token_intended_method_field_exists():
    """MagicLinkToken.intended_method field exists and accepts 'email_domain' or
    'admin_review'."""
    from organizers.models import MagicLinkToken, Profile

    user = User.objects.create_user(username="intended_user", email="intended@example.com", password="x")
    profile = Profile.objects.create(name="Intended Profile", slug="intended-profile")

    token = MagicLinkToken.objects.create(
        email="intended@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
        intended_method="email_domain",
    )
    assert token.intended_method == "email_domain"

    token2 = MagicLinkToken.objects.create(
        email="intended@example.com",
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=24),
        intended_method="admin_review",
    )
    assert token2.intended_method == "admin_review"
