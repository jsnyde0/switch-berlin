"""
Integration tests for the follow/unfollow feature (kb-ldo: OrganizerFollow → Follow).

Test plan items (updated from kb-2eu.5 to reflect unified Follow model):
1. Follow model exists and has correct fields (user, profile, created_at).
2. POST /o/<slug>/follow/ creates a Follow row (following=True).
3. Second POST to same URL deletes the row (toggle/unfollow, following=False).
4. Unauthenticated POST returns 302 to login page.
5. POST to non-existent organizer returns 404.
6. POST to non-approved organizer returns 404.
7. GET /o/<slug>/ includes follow button for authenticated user.
8. GET /o/<slug>/ shows Following state when user already follows.
9. GET /o/<slug>/ hides follow button section for unauthenticated users.
10. GET /o/<slug>/follow/ (not POST) returns 405.
"""

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_organizer(db):
    """Approved organizer used in follow tests."""
    from organizers.models import Profile

    return Profile.objects.create(
        name="Follow Test Organizer",
        slug="follow-test-organizer",
        status="approved",
    )


@pytest.fixture
def candidate_organizer(db):
    """Non-approved (candidate) organizer — follow endpoint must 404."""
    from organizers.models import Profile

    return Profile.objects.create(
        name="Candidate Organizer",
        slug="candidate-organizer",
        status="candidate",
    )


@pytest.fixture
def staff_user(db):
    """Staff user that can pass the login wall."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="follow_staff",
        email="follow_staff@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def regular_approved_user(db):
    """Vouched non-staff user (kb-m69.1: status replaces is_approved)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="follow_approved",
        email="follow_approved@example.com",
        password="x",
        is_staff=False,
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def open_tier_user(db):
    """Open-tier user (plain signup, status='open', not vouched, not staff).

    Following is a private subscription, not a vouched-gated capability per
    ADR-013 (vouched buys restricted-event reads, rating signals, invites —
    not follow). This fixture guards that an open-tier user can follow.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="follow_open",
        email="follow_open@example.com",
        password="x",
        is_staff=False,
    )
    user.status = "open"
    user.save()
    return user


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_model_exists():
    """Follow model is importable from organizers.models."""
    from organizers.models import Follow

    assert Follow is not None


@pytest.mark.django_db
def test_follow_model_fields(approved_organizer, staff_user):
    """Follow has user, profile, created_at fields."""
    from organizers.models import Follow

    follow = Follow.objects.create(user=staff_user, profile=approved_organizer)
    assert follow.user == staff_user
    assert follow.profile == approved_organizer
    assert follow.created_at is not None


@pytest.mark.django_db
def test_follow_unique_together(approved_organizer, staff_user):
    """Creating duplicate Follow raises IntegrityError."""
    from django.db import IntegrityError, transaction

    from organizers.models import Follow

    Follow.objects.create(user=staff_user, profile=approved_organizer)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Follow.objects.create(user=staff_user, profile=approved_organizer)


@pytest.mark.django_db
def test_follow_get_or_create_does_not_raise(approved_organizer, staff_user):
    """get_or_create on Follow is idempotent."""
    from organizers.models import Follow

    follow1, created1 = Follow.objects.get_or_create(user=staff_user, profile=approved_organizer)
    follow2, created2 = Follow.objects.get_or_create(user=staff_user, profile=approved_organizer)
    assert created1 is True
    assert created2 is False
    assert follow1.pk == follow2.pk


# ---------------------------------------------------------------------------
# Follow endpoint: POST /o/<slug>/follow/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_post_creates_row(client, staff_user, approved_organizer):
    """POST /o/<slug>/follow/ creates a Follow row."""
    from organizers.models import Follow

    client.force_login(staff_user)
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 200
    assert Follow.objects.filter(user=staff_user, profile=approved_organizer).exists()


@pytest.mark.django_db
def test_follow_post_open_tier_user_can_follow(client, open_tier_user, approved_organizer):
    """Open-tier (non-vouched, non-staff) users can follow.

    Following is a private subscription powering the personalized feed, not a
    vouched-gated capability per ADR-013. An open-tier user POSTing to the
    follow endpoint must succeed (200) and create the Follow row — not 403.
    """
    from organizers.models import Follow

    client.force_login(open_tier_user)
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 200
    assert Follow.objects.filter(user=open_tier_user, profile=approved_organizer).exists()


@pytest.mark.django_db
def test_follow_post_returns_following_true(client, staff_user, approved_organizer):
    """First POST returns the button partial with Following state."""
    client.force_login(staff_user)
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 200
    content = response.content.decode()
    # "Following" button text indicates "Following" state
    assert "Following" in content


@pytest.mark.django_db
def test_follow_post_twice_deletes_row(client, staff_user, approved_organizer):
    """Second POST to the follow endpoint removes the Follow row."""
    from organizers.models import Follow

    client.force_login(staff_user)
    # First POST — creates the follow
    client.post(f"/o/{approved_organizer.slug}/follow/")
    assert Follow.objects.filter(user=staff_user, profile=approved_organizer).exists()
    # Second POST — deletes the follow (unfollow)
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 200
    assert not Follow.objects.filter(user=staff_user, profile=approved_organizer).exists()


@pytest.mark.django_db
def test_follow_post_unfollow_returns_follow_button(client, staff_user, approved_organizer):
    """After unfollow, response shows Follow (not Following) button."""
    client.force_login(staff_user)
    client.post(f"/o/{approved_organizer.slug}/follow/")
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    content = response.content.decode()
    # "Following" button text should NOT be present after unfollow
    assert "Following" not in content


@pytest.mark.django_db
def test_follow_unauthenticated_redirects_to_login(client, approved_organizer):
    """Unauthenticated POST /o/<slug>/follow/ returns 302 to login page."""
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_follow_nonexistent_organizer_returns_404(client, staff_user):
    """POST /o/nonexistent/follow/ returns 404."""
    client.force_login(staff_user)
    response = client.post("/o/nonexistent-organizer/follow/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_follow_non_approved_organizer_returns_404(client, staff_user, candidate_organizer):
    """POST /o/<slug>/follow/ for non-approved organizer returns 404."""
    client.force_login(staff_user)
    response = client.post(f"/o/{candidate_organizer.slug}/follow/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_follow_get_method_not_allowed(client, staff_user, approved_organizer):
    """GET /o/<slug>/follow/ returns 405 Method Not Allowed."""
    client.force_login(staff_user)
    response = client.get(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# Organizer profile page: follow button display
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_shows_follow_button_for_authenticated_user(client, staff_user, approved_organizer):
    """GET /p/<slug>/ shows a Follow button for authenticated users."""
    client.force_login(staff_user)
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    # The follow button partial should be included
    assert f"follow-{approved_organizer.slug}" in content


@pytest.mark.django_db
def test_profile_follow_button_shows_following_when_followed(client, staff_user, approved_organizer):
    """GET /p/<slug>/ shows Following button when user already follows."""
    from organizers.models import Follow

    Follow.objects.create(user=staff_user, profile=approved_organizer)
    client.force_login(staff_user)
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Following" in content


@pytest.mark.django_db
def test_profile_follow_button_shows_follow_when_not_followed(client, staff_user, approved_organizer):
    """GET /p/<slug>/ shows Follow (no btn-active) when user does not follow."""
    client.force_login(staff_user)
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    # The follow button id should be there
    assert f"follow-{approved_organizer.slug}" in content
    # "Following" text should not be present (not following, showing Follow state)
    assert "Following" not in content


@pytest.mark.django_db
def test_profile_hides_follow_button_for_anonymous_user(client, approved_organizer):
    """GET /p/<slug>/ for anonymous user shows profile but no follow button."""
    # In Phase 0.5, anonymous users can view organizer profiles (public read mode)
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    # Follow button requires authentication — should not appear for anonymous user
    assert "hx-post" not in content or "/follow/" not in content
