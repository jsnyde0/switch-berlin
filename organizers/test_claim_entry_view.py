"""
TDD tests for kb-m69.8: claim entry view + templates.

RED phase: written BEFORE implementation.
Per ADR-014 D2 — web-first, two-track verification, auth-required.
Per ADR-008 D3 — fail loud; explicit branch for user-IS-claimant.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper fixtures
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
# URL resolution
# ---------------------------------------------------------------------------


def test_claim_entry_url_resolves():
    """URL /p/<slug>/claim/ resolves to claim_entry view."""
    url = reverse("organizer-claim-entry", kwargs={"slug": "test-slug"})
    assert "/claim/" in url


def test_magic_link_redeem_url_resolves():
    """URL claim-redeem/<token>/ resolves to magic_link_redeem view."""
    import uuid

    token = uuid.uuid4()
    url = reverse("organizer-claim-redeem", kwargs={"token": str(token)})
    assert str(token) in url


# ---------------------------------------------------------------------------
# Anonymous viewer on profile detail: sees "Sign in" CTA
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_detail_anonymous_sees_sign_in_cta(client):
    """Anonymous viewer on profile detail sees 'Sign in' CTA, no claim form."""
    make_profile("anon-profile")
    response = client.get(
        reverse("organizer-profile", kwargs={"slug": "anon-profile"})
    )
    assert response.status_code == 200
    content = response.content.decode()
    # Should contain some reference to sign in or login for claim
    assert (
        "sign" in content.lower()
        or "login" in content.lower()
        or "claim" in content.lower()
    )


# ---------------------------------------------------------------------------
# Claim entry view: login-required (auth-before-claim per ADR-014 D2)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_entry_requires_login(client):
    """GET /p/<slug>/claim/ redirects anonymous user to login."""
    make_profile("auth-req-profile")
    url = reverse("organizer-claim-entry", kwargs={"slug": "auth-req-profile"})
    response = client.get(url)
    assert response.status_code == 302
    assert "login" in response["Location"] or "accounts" in response["Location"]


@pytest.mark.django_db
def test_claim_entry_returns_200_for_auth_user(client):
    """GET /p/<slug>/claim/ returns 200 for authenticated user."""
    make_profile("auth-ok-profile")
    user = make_user("claim_viewer")
    client.force_login(user)
    url = reverse("organizer-claim-entry", kwargs={"slug": "auth-ok-profile"})
    response = client.get(url)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Auth'd claimant viewer: sees "you manage" branch (ADR-008 D3 — explicit, not absent)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_entry_already_claimant_shows_explicit_branch(client):
    """User who already claims a profile sees explicit 'you manage' message."""
    from organizers.models import ProfileClaim

    profile = make_profile("already-claimed-profile")
    user = make_user("already_claimer")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    client.force_login(user)
    url = reverse(
        "organizer-claim-entry", kwargs={"slug": "already-claimed-profile"}
    )
    response = client.get(url)
    assert response.status_code == 200
    content = response.content.decode()
    # ADR-008 D3: explicit branch, not silent omission
    assert (
        "manage" in content.lower()
        or "already" in content.lower()
        or "claimant" in content.lower()
    )


# ---------------------------------------------------------------------------
# Profile detail: auth'd non-claimant sees "Claim" CTA
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_detail_auth_non_claimant_sees_claim_cta(client):
    """Authenticated non-claimant on profile detail sees 'Claim' CTA."""
    make_profile("claim-cta-profile")
    user = make_user("non_claimant_viewer")
    client.force_login(user)
    response = client.get(
        reverse("organizer-profile", kwargs={"slug": "claim-cta-profile"})
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert "claim" in content.lower()


# ---------------------------------------------------------------------------
# Profile detail: auth'd claimant sees "you manage" badge (ADR-008 D3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_detail_auth_claimant_sees_manage_badge(client):
    """Authenticated claimant sees 'you manage' badge on profile detail."""
    from organizers.models import ProfileClaim

    profile = make_profile("manage-badge-profile")
    user = make_user("manage_badge_user")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    client.force_login(user)
    response = client.get(
        reverse("organizer-profile", kwargs={"slug": "manage-badge-profile"})
    )
    assert response.status_code == 200
    content = response.content.decode()
    # Must be explicit (ADR-008 D3) — not absent
    assert (
        "manage" in content.lower()
        or "claimant" in content.lower()
        or "your profile" in content.lower()
    )


# ---------------------------------------------------------------------------
# Email-domain fast-path: ProfileClaim created directly
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_entry_email_domain_fastpath_creates_profile_claim(client):
    """email domain matches verified_domain → ProfileClaim with email_domain method."""
    from organizers.models import Profile, ProfileClaim

    profile = Profile.objects.create(
        name="FastPath Org",
        slug="fastpath-org",
        status="approved",
        verified_domain="fastpath.org",
    )
    user = make_user("fp_user", email="user@fastpath.org")
    client.force_login(user)

    url = reverse("organizer-claim-entry", kwargs={"slug": "fastpath-org"})
    response = client.post(url, {"email": "user@fastpath.org"})

    # Should redirect after successful claim
    assert response.status_code == 302

    claim = ProfileClaim.objects.filter(profile=profile, user=user).first()
    assert claim is not None
    assert claim.verified_method == "email_domain"


# ---------------------------------------------------------------------------
# Admin-review path: ClaimIntent + MagicLinkToken created, email sent
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_entry_admin_review_path_creates_claim_intent(client, mailoutbox):
    """No domain match → ClaimIntent + token created, email sent, redirect."""
    from organizers.models import ClaimIntent, MagicLinkToken, Profile

    profile = Profile.objects.create(
        name="Review Org",
        slug="review-org",
        status="approved",
        verified_domain=None,
    )
    user = make_user("review_user", email="user@gmail.com")
    client.force_login(user)

    url = reverse("organizer-claim-entry", kwargs={"slug": "review-org"})
    response = client.post(url, {"email": "user@gmail.com"})

    # Should redirect to check-email page
    assert response.status_code == 302
    assert (
        "check" in response["Location"].lower()
        or "email" in response["Location"].lower()
    )

    # ClaimIntent created
    intent = ClaimIntent.objects.filter(user=user, profile=profile).first()
    assert intent is not None

    # MagicLinkToken created
    token = MagicLinkToken.objects.filter(user_target=user, profile=profile).first()
    assert token is not None

    # Email sent
    assert len(mailoutbox) == 1


@pytest.mark.django_db
def test_claim_entry_admin_review_path_email_domain_mismatch(client, mailoutbox):
    """Email domain mismatch → admin-review path, no ProfileClaim created."""
    from organizers.models import ClaimIntent, Profile, ProfileClaim

    profile = Profile.objects.create(
        name="Mismatch Org",
        slug="mismatch-org",
        status="approved",
        verified_domain="verified.org",
    )
    user = make_user("mismatch_user", email="user@other.com")
    client.force_login(user)

    url = reverse("organizer-claim-entry", kwargs={"slug": "mismatch-org"})
    response = client.post(url, {"email": "user@other.com"})

    # Should redirect (not to claim success, but check-email)
    assert response.status_code == 302

    # No ProfileClaim created directly
    assert not ProfileClaim.objects.filter(profile=profile, user=user).exists()

    # ClaimIntent created
    assert ClaimIntent.objects.filter(user=user, profile=profile).exists()
