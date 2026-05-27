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


# ---------------------------------------------------------------------------
# Successful redemption
# ---------------------------------------------------------------------------


def make_token(user, profile, email=None, hours=24, intended_method="email_domain"):
    """Make a token with intended_method (required by ADR-014 D1 correction)."""
    from organizers.models import MagicLinkToken

    email = email or user.email
    return MagicLinkToken.objects.create(
        email=email,
        profile=profile,
        user_target=user,
        expires_at=timezone.now() + timedelta(hours=hours),
        intended_method=intended_method,
    )


@pytest.mark.django_db
def test_magic_link_redeem_fast_path_creates_profile_claim_with_email_domain(client):
    """Valid fast-path token redeemed → ProfileClaim with
    verified_method='email_domain'.

    ADR-014 D1: 'magic_link' is not a valid verified_method. Fast-path redemption
    produces verified_method='email_domain'.
    """
    from organizers.models import ProfileClaim

    profile = make_profile("redeem-ok-profile")
    user = make_user("redeem_ok")
    token = make_token(user, profile, intended_method="email_domain")

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    assert response.status_code == 302  # redirect on success

    claim = ProfileClaim.objects.filter(profile=profile, user=user).first()
    assert claim is not None
    assert claim.verified_method == "email_domain", (
        f"Expected verified_method='email_domain' for fast-path token,"
        f" got '{claim.verified_method}'"
    )


@pytest.mark.django_db
def test_magic_link_redeem_admin_review_marks_claim_intent_verified(client):
    """Valid admin-review token redeemed → ClaimIntent.submitter_verified_at stamped,
    no ProfileClaim.

    ADR-014 D2: admin-review track → magic-link redemption marks ClaimIntent verified;
    admin must then approve to create ProfileClaim.
    """
    from organizers.models import ClaimIntent, ProfileClaim

    profile = make_profile("redeem-admin-profile")
    user = make_user("redeem_admin_user")

    # Create ClaimIntent for admin-review track
    intent = ClaimIntent.objects.create(user=user, profile=profile)

    token = make_token(user, profile, intended_method="admin_review")

    client.force_login(user)
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(url)

    assert response.status_code == 302  # redirect on success

    # ClaimIntent.submitter_verified_at must be stamped
    intent.refresh_from_db()
    assert intent.submitter_verified_at is not None, (
        "ClaimIntent.submitter_verified_at should be stamped after magic-link"
        " redemption"
    )

    # No ProfileClaim created (admin must approve first)
    assert not ProfileClaim.objects.filter(profile=profile, user=user).exists(), (
        "ProfileClaim should NOT be created on admin-review path until admin approves"
    )


@pytest.mark.django_db
def test_check_email_page_shows_verified_state_after_admin_review_redeem(client):
    """After redeeming an admin-review token, the check-email page must reflect
    the verified/pending-review state — NOT tell the user to check their inbox
    for a link they just used.

    Regression: redeem redirects back to check-email; before the fix the page
    rendered the pre-redeem 'check your inbox' copy, implying nothing happened.
    """
    from organizers.models import ClaimIntent

    profile = make_profile("redeem-verified-copy")
    user = make_user("redeem_verified_copy")
    ClaimIntent.objects.create(user=user, profile=profile)
    token = make_token(user, profile, intended_method="admin_review")

    client.force_login(user)
    redeem_url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    # follow=True walks the 302 to the check-email page
    response = client.get(redeem_url, follow=True)

    assert response.status_code == 200
    body = response.content.decode().lower()
    assert "verified" in body, "post-redeem page must say the email is verified"
    assert "pending" in body, "post-redeem page must say the claim is pending review"
    assert "inbox" not in body, (
        "post-redeem page must NOT show the pre-redeem 'check your inbox' copy"
    )


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
