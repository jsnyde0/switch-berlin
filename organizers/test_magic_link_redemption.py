"""
TDD tests for kb-m69.8: magic-link redemption view.

RED phase: written BEFORE implementation.
Per ADR-014 D3 — token validates (email, profile_id, user_target=request.user).
Per ADR-008 D3 — fail loud on any mismatch; no silent ProfileClaim creation.
"""

import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_profile(slug, **kwargs):
    from organizers.models import Profile

    defaults = {"name": f"Profile {slug}", "slug": slug, "status": "approved"}
    defaults.update(kwargs)
    return Profile.objects.create(**defaults)


def make_user(username, email=None):
    email = email or f"{username}@example.com"
    return User.objects.create_user(
        username=username, email=email, password="testpass123"
    )


def make_token(user, profile, email=None, hours=24):
    from organizers.models import MagicLinkToken

    email = email or user.email
    return MagicLinkToken.objects.create(
        email=email,
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=hours),
    )


# ---------------------------------------------------------------------------
# Successful redemption
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_creates_profile_claim(client):
    """Valid token redeemed by correct user → ProfileClaim with magic_link method."""
    from organizers.models import ProfileClaim

    profile = make_profile("redeem-ok-profile")
    user = make_user("redeem_ok")
    token = make_token(user, profile)

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    assert response.status_code == 302  # redirect on success

    claim = ProfileClaim.objects.filter(profile=profile, user=user).first()
    assert claim is not None
    assert claim.verified_method == "magic_link"


@pytest.mark.django_db
def test_magic_link_redeem_marks_token_used(client):
    """Valid redemption marks the token as used (single-use)."""
    profile = make_profile("redeem-used-profile")
    user = make_user("redeem_used")
    token = make_token(user, profile)

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    client.get(url)

    token.refresh_from_db()
    assert token.used_at is not None


# ---------------------------------------------------------------------------
# Wrong user — fail loud (ADR-008 D3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_wrong_user_fails_loud(client):
    """Token for user_target A redeemed by user B → 400/403, no ProfileClaim created."""
    from organizers.models import ProfileClaim

    profile = make_profile("wrong-user-profile")
    user_a = make_user("user_a_mlr")
    user_b = make_user("user_b_mlr")
    token = make_token(user_a, profile)

    client.force_login(user_b)  # user B tries to redeem user A's token
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    # Must fail loudly — not silently succeed or create a claim
    assert response.status_code in (400, 403, 404)
    assert not ProfileClaim.objects.filter(profile=profile, user=user_b).exists()
    assert not ProfileClaim.objects.filter(profile=profile, user=user_a).exists()


# ---------------------------------------------------------------------------
# Expired token — fail loud
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_expired_token_fails(client):
    """Expired token → 400/403, no ProfileClaim created."""
    from organizers.models import ProfileClaim

    profile = make_profile("expired-token-profile")
    user = make_user("expired_token_user")
    token = make_token(user, profile, hours=-1)  # already expired

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    assert response.status_code in (400, 403, 404)
    assert not ProfileClaim.objects.filter(profile=profile, user=user).exists()


# ---------------------------------------------------------------------------
# Used token — cannot be re-used
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_used_token_fails(client):
    """Already-used token → 400/403 on second attempt, no second ProfileClaim."""
    from organizers.models import ProfileClaim

    profile = make_profile("used-token-profile")
    user = make_user("used_token_user")
    token = make_token(user, profile)

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})

    # First redemption succeeds
    response1 = client.get(url)
    assert response1.status_code == 302

    # Second attempt must fail
    response2 = client.get(url)
    assert response2.status_code in (400, 403, 404)

    # Still only one ProfileClaim
    assert ProfileClaim.objects.filter(profile=profile, user=user).count() == 1


# ---------------------------------------------------------------------------
# Tampered / non-existent token — fail loud
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_nonexistent_token_fails(client):
    """Non-existent token → 404 or 400, no ProfileClaim created."""
    make_profile("notoken-profile")
    user = make_user("notoken_user")

    client.force_login(user)
    fake_token = str(uuid.uuid4())
    url = reverse("organizer-claim-redeem", kwargs={"token": fake_token})
    response = client.get(url)

    assert response.status_code in (400, 403, 404)


# ---------------------------------------------------------------------------
# Anonymous user tries to redeem — redirect to login
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_magic_link_redeem_anonymous_redirects_to_login(client):
    """Anonymous user trying to redeem token → redirect to login."""
    profile = make_profile("anon-redeem-profile")
    user = make_user("anon_redeem_user")
    token = make_token(user, profile)

    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    assert response.status_code == 302
    assert "login" in response["Location"] or "accounts" in response["Location"]
