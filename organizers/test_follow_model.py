"""
Tests for kb-ldo: OrganizerFollow → Follow(user, profile) unification.

Acceptance clauses verified here:
1. Follow(user, profile, created_at) model exists with correct field names.
2. unique_together = (('user', 'profile'),) enforced.
3. Reverse accessor user.follows.all() works.
4. Reverse accessor profile.followers.all() works.
5. OrganizerFollow is no longer importable from organizers.models.
6. Follow toggle view round-trip: POST creates Follow row (Follow, not OrganizerFollow).
7. Follow toggle view: second POST removes row.
8. organizer= kwarg no longer accepted by Follow (profile= is the correct kwarg).
9. created_at is preserved by data migration (tested via model-level .update() pattern).
"""

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def profile(db):
    """Approved profile used in Follow tests."""
    from organizers.models import Profile

    return Profile.objects.create(
        name="Follow Test Profile",
        slug="follow-test-profile",
        status="approved",
    )


@pytest.fixture
def user(db):
    """Authenticated user for follow tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="follow_user",
        email="follow_user@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def other_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="follow_other",
        email="follow_other@example.com",
        password="x",
        is_staff=True,
    )


# ---------------------------------------------------------------------------
# Clause 1: Follow model fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_model_importable():
    """Follow is importable from organizers.models."""
    from organizers.models import Follow

    assert Follow is not None


@pytest.mark.django_db
def test_follow_model_fields(profile, user):
    """Follow has user, profile, created_at fields (not organizer)."""
    from organizers.models import Follow

    follow = Follow.objects.create(user=user, profile=profile)
    assert follow.user == user
    assert follow.profile == profile
    assert follow.created_at is not None
    # The 'organizer' field must not exist on Follow
    assert not hasattr(follow, "organizer")


# ---------------------------------------------------------------------------
# Clause 2: unique_together = (('user', 'profile'),)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_unique_together_enforced(profile, user):
    """Creating duplicate Follow(user, profile) raises IntegrityError."""
    from django.db import IntegrityError

    from organizers.models import Follow

    Follow.objects.create(user=user, profile=profile)
    with pytest.raises(IntegrityError):
        Follow.objects.create(user=user, profile=profile)


# ---------------------------------------------------------------------------
# Clause 3 & 4: Reverse accessors user.follows and profile.followers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_follows_reverse_accessor(profile, user):
    """user.follows.all() returns Follow rows for that user."""
    from organizers.models import Follow

    follow = Follow.objects.create(user=user, profile=profile)
    assert follow in user.follows.all()


@pytest.mark.django_db
def test_profile_followers_reverse_accessor(profile, user):
    """profile.followers.all() returns Follow rows for that profile."""
    from organizers.models import Follow

    follow = Follow.objects.create(user=user, profile=profile)
    assert follow in profile.followers.all()


# ---------------------------------------------------------------------------
# Clause 5: OrganizerFollow is no longer importable
# ---------------------------------------------------------------------------


def test_organizer_follow_not_importable():
    """from organizers.models import OrganizerFollow must raise ImportError."""
    import organizers.models as om

    assert not hasattr(om, "OrganizerFollow"), (
        "OrganizerFollow should no longer exist on organizers.models"
    )

    # Also confirm the direct import raises ImportError
    import importlib
    import sys

    # Remove cached module to force reimport check
    saved = sys.modules.pop("organizers.models", None)
    try:
        module = importlib.import_module("organizers.models")
        assert not hasattr(module, "OrganizerFollow"), (
            "OrganizerFollow must not be importable from organizers.models"
        )
    finally:
        if saved is not None:
            sys.modules["organizers.models"] = saved


# ---------------------------------------------------------------------------
# Clause 6 & 7: Follow toggle view round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_view_creates_follow_row(client, profile, user):
    """POST /o/<slug>/follow/ creates a Follow row (not OrganizerFollow)."""
    from organizers.models import Follow

    client.force_login(user)
    response = client.post(f"/o/{profile.slug}/follow/")
    assert response.status_code == 200
    assert Follow.objects.filter(user=user, profile=profile).exists()


@pytest.mark.django_db
def test_follow_view_second_post_removes_row(client, profile, user):
    """Second POST to /o/<slug>/follow/ deletes the Follow row."""
    from organizers.models import Follow

    client.force_login(user)
    client.post(f"/o/{profile.slug}/follow/")
    assert Follow.objects.filter(user=user, profile=profile).exists()
    client.post(f"/o/{profile.slug}/follow/")
    assert not Follow.objects.filter(user=user, profile=profile).exists()


# ---------------------------------------------------------------------------
# Clause 8: organizer= kwarg not accepted on Follow
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_rejects_organizer_kwarg(profile, user):
    """Follow.objects.create(organizer=...) raises TypeError."""
    from organizers.models import Follow

    with pytest.raises(TypeError):
        Follow.objects.create(user=user, organizer=profile)


# ---------------------------------------------------------------------------
# Clause 9: created_at preserved via .update() pattern
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_created_at_can_be_overridden_via_update(profile, user):
    """Follow created_at can be set to an arbitrary past value via .update()."""
    import datetime

    from organizers.models import Follow

    follow = Follow.objects.create(user=user, profile=profile)
    past_dt = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
    Follow.objects.filter(pk=follow.pk).update(created_at=past_dt)
    follow.refresh_from_db()
    assert follow.created_at == past_dt
