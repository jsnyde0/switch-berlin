"""
TDD tests for bead kb-8qn.1 — shared pytest fixtures for Bundle A.

These tests verify that the five new fixtures in conftest.py:
  - user_with_went_attendance
  - past_event_fixture
  - review_for_event_with_count
  - organizer_with_rating_count
  - organizer_with_follower_count

...are importable, produce the expected ORM objects, and carry correct field values.
"""

import pytest
from django.contrib.auth import get_user_model

from events.models import Attendance
from organizers.models import Follow, Profile
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# user_with_went_attendance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_with_went_attendance_creates_attendance(
    user_with_went_attendance, published_event
):
    """Fixture creates an approved user + Attendance(status='went')."""
    user, attendance = user_with_went_attendance(published_event)

    assert user.status == "vouched"
    assert attendance.user == user
    assert attendance.event == published_event
    assert attendance.status == "went"


@pytest.mark.django_db
def test_user_with_went_attendance_persisted(
    user_with_went_attendance, published_event
):
    """Attendance row is saved to the database."""
    user, attendance = user_with_went_attendance(published_event)

    assert Attendance.objects.filter(
        user=user, event=published_event, status="went"
    ).exists()


# ---------------------------------------------------------------------------
# past_event_fixture
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_past_event_fixture_creates_event(past_event_fixture, approved_organizer):
    """Fixture creates a published Event with end in the past."""
    from datetime import timedelta

    from django.utils import timezone

    event = past_event_fixture(days_ago=3)

    assert event.status == "published"
    assert event.organizer == approved_organizer
    assert event.end < timezone.now()
    # end should be roughly 3 days ago (within a few seconds)
    expected_end = timezone.now() - timedelta(days=3)
    delta = abs((event.end - expected_end).total_seconds())
    assert delta < 10, f"end time delta too large: {delta}s"


@pytest.mark.django_db
def test_past_event_fixture_different_days_ago(past_event_fixture):
    """Fixture respects the days_ago parameter."""
    from datetime import timedelta

    from django.utils import timezone

    event_7 = past_event_fixture(days_ago=7)
    event_14 = past_event_fixture(days_ago=14)

    expected_7 = timezone.now() - timedelta(days=7)
    expected_14 = timezone.now() - timedelta(days=14)

    assert abs((event_7.end - expected_7).total_seconds()) < 10
    assert abs((event_14.end - expected_14).total_seconds()) < 10


# ---------------------------------------------------------------------------
# review_for_event_with_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_review_for_event_with_count_creates_n_reviews(
    review_for_event_with_count, published_event
):
    """Fixture creates exactly n Review rows for the given event."""
    reviews = review_for_event_with_count(published_event, 3)

    assert len(reviews) == 3
    assert Review.objects.filter(event=published_event).count() == 3


@pytest.mark.django_db
def test_review_for_event_with_count_distinct_authors(
    review_for_event_with_count, published_event
):
    """Each review has a distinct author user."""
    reviews = review_for_event_with_count(published_event, 4)

    author_ids = [r.author_id for r in reviews]
    assert len(set(author_ids)) == 4, "all authors must be distinct"


@pytest.mark.django_db
def test_review_for_event_with_count_returns_list(
    review_for_event_with_count, published_event
):
    """Fixture returns a list of Review instances."""
    reviews = review_for_event_with_count(published_event, 2)

    assert isinstance(reviews, list)
    assert all(isinstance(r, Review) for r in reviews)


# ---------------------------------------------------------------------------
# organizer_with_rating_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_with_rating_count_creates_organizer(organizer_with_rating_count):
    """Fixture creates an Organizer with n Review rows and denormalized rating_count."""
    org = organizer_with_rating_count(5)

    assert isinstance(org, Profile)
    org.refresh_from_db()
    assert org.rating_count == 5
    assert Review.objects.filter(organizer=org).count() == 5


@pytest.mark.django_db
def test_organizer_with_rating_count_zero(organizer_with_rating_count):
    """Edge case: n=0 creates an Organizer with rating_count=0 and no reviews."""
    org = organizer_with_rating_count(0)

    org.refresh_from_db()
    assert org.rating_count == 0
    assert Review.objects.filter(organizer=org).count() == 0


# ---------------------------------------------------------------------------
# organizer_with_follower_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_with_follower_count_creates_organizer(organizer_with_follower_count):
    """Fixture creates an Organizer with n Follow rows."""
    org = organizer_with_follower_count(4)

    assert isinstance(org, Profile)
    org.refresh_from_db()
    assert org.follower_count == 4
    assert Follow.objects.filter(profile=org).count() == 4


@pytest.mark.django_db
def test_organizer_with_follower_count_distinct_users(organizer_with_follower_count):
    """Each follow row has a distinct user."""
    org = organizer_with_follower_count(3)

    follows = Follow.objects.filter(profile=org)
    user_ids = list(follows.values_list("user_id", flat=True))
    assert len(set(user_ids)) == 3, "all follower users must be distinct"


@pytest.mark.django_db
def test_organizer_with_follower_count_zero(organizer_with_follower_count):
    """Edge case: n=0 creates an Organizer with follower_count=0 and no follows."""
    org = organizer_with_follower_count(0)

    org.refresh_from_db()
    assert org.follower_count == 0
    assert Follow.objects.filter(profile=org).count() == 0
