"""
TDD regression tests for kb-x0s: profile page claim button three states.

Covers:
- no claim → 'Claim this profile' button shown
- pending ClaimIntent (unresolved, not rejected) → 'Claim Pending' shown
- approved ProfileClaim (active claimant) → 'You manage this profile' shown
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


def make_profile(slug, **kwargs):
    from organizers.models import Profile

    defaults = {"name": f"Profile {slug}", "slug": slug, "status": "approved"}
    defaults.update(kwargs)
    return Profile.objects.create(**defaults)


def make_user(username, email=None):
    email = email or f"{username}@example.com"
    return User.objects.create_user(username=username, email=email, password="testpass123")


@pytest.mark.django_db
def test_profile_claim_button_no_claim(client):
    """Logged-in user with no claim sees 'Claim this profile' button."""
    user = make_user("user_no_claim")
    profile = make_profile("org-no-claim")
    client.force_login(user)

    url = reverse("organizer-profile", kwargs={"slug": profile.slug})
    response = client.get(url)

    assert response.status_code == 200
    assert b"Claim this profile" in response.content
    assert b"Claim Pending" not in response.content
    assert b"You manage this profile" not in response.content


@pytest.mark.django_db
def test_profile_claim_button_pending_claim(client):
    """Logged-in user with a pending ClaimIntent sees 'Claim Pending' (not 'Claim this profile')."""
    from organizers.models import ClaimIntent

    user = make_user("user_pending_claim")
    profile = make_profile("org-pending-claim")

    # Create a pending ClaimIntent: resolved_at=None, rejected_at=None
    ClaimIntent.objects.create(user=user, profile=profile)

    client.force_login(user)
    url = reverse("organizer-profile", kwargs={"slug": profile.slug})
    response = client.get(url)

    assert response.status_code == 200
    assert b"Claim Pending" in response.content
    assert b"Claim this profile" not in response.content
    assert b"You manage this profile" not in response.content


@pytest.mark.django_db
def test_profile_claim_button_approved_claimant(client):
    """Approved claimant (active ProfileClaim) sees 'You manage this profile'."""
    from organizers.models import ProfileClaim

    user = make_user("user_approved_claim")
    profile = make_profile("org-approved-claim")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_review",
        role="admin",
    )

    client.force_login(user)
    url = reverse("organizer-profile", kwargs={"slug": profile.slug})
    response = client.get(url)

    assert response.status_code == 200
    assert b"You manage this profile" in response.content
    assert b"Claim Pending" not in response.content
    assert b"Claim this profile" not in response.content


@pytest.mark.django_db
def test_profile_claim_button_resolved_intent_not_pending(client):
    """User with a resolved ClaimIntent (resolved_at set) still sees 'Claim this profile'."""
    from django.utils import timezone

    from organizers.models import ClaimIntent

    user = make_user("user_resolved_intent")
    profile = make_profile("org-resolved-intent")

    # resolved_at is set → not pending
    ClaimIntent.objects.create(user=user, profile=profile, resolved_at=timezone.now())

    client.force_login(user)
    url = reverse("organizer-profile", kwargs={"slug": profile.slug})
    response = client.get(url)

    assert response.status_code == 200
    assert b"Claim this profile" in response.content
    assert b"Claim Pending" not in response.content


@pytest.mark.django_db
def test_profile_claim_button_rejected_intent_not_pending(client):
    """User with a rejected ClaimIntent (rejected_at set) still sees 'Claim this profile'."""
    from django.utils import timezone

    from organizers.models import ClaimIntent

    user = make_user("user_rejected_intent")
    profile = make_profile("org-rejected-intent")

    # rejected_at is set → not pending
    ClaimIntent.objects.create(user=user, profile=profile, rejected_at=timezone.now())

    client.force_login(user)
    url = reverse("organizer-profile", kwargs={"slug": profile.slug})
    response = client.get(url)

    assert response.status_code == 200
    assert b"Claim this profile" in response.content
    assert b"Claim Pending" not in response.content
