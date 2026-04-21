"""Tests for reviews app — submit_review view and related functionality."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from events.models import Event
from organizers.models import Organizer
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def approved_user(db):
    """Authenticated, approved (is_approved) user."""
    user = User.objects.create_user(
        username="tester", email="tester@example.com", password="testpass123"
    )
    user.is_approved = True
    user.save()
    return user


@pytest.fixture
def unapproved_user(db):
    user = User.objects.create_user(
        username="pending", email="pending@example.com", password="testpass123"
    )
    return user


@pytest.fixture
def organizer(db):
    return Organizer.objects.create(
        name="Test Organizer",
        slug="test-organizer",
        status="approved",
    )


@pytest.fixture
def past_event(db, organizer):
    from datetime import timedelta
    from django.utils import timezone

    return Event.objects.create(
        title="Past Party",
        slug="past-party",
        organizer=organizer,
        status="published",
        start=timezone.now() - timedelta(days=7),
    )


@pytest.fixture
def client_logged_in(approved_user):
    client = Client()
    client.force_login(approved_user)
    return client


# ---------------------------------------------------------------------------
# Test: submit_review — organizer target
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_submit_organizer_review_creates_review(client_logged_in, organizer):
    """POST creates a Review row tied to the organizer."""
    url = reverse("review-submit")
    resp = client_logged_in.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "4",
        "body": "Great party!",
    })
    assert resp.status_code == 200
    assert Review.objects.filter(organizer=organizer).count() == 1
    review = Review.objects.get(organizer=organizer)
    assert review.rating == 4
    assert review.body == "Great party!"


@pytest.mark.django_db
def test_submit_organizer_review_updates_rating_aggregates(client_logged_in, organizer):
    """After review, Organizer.rating_count and avg_rating are updated."""
    url = reverse("review-submit")
    client_logged_in.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "4",
    })
    organizer.refresh_from_db()
    assert organizer.rating_count == 1
    assert organizer.avg_rating == pytest.approx(4.0)


@pytest.mark.django_db
def test_submit_organizer_review_second_time_updates_not_creates(client_logged_in, approved_user, organizer):
    """Second submission updates existing review — does not create a duplicate."""
    url = reverse("review-submit")
    client_logged_in.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "4",
    })
    client_logged_in.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "2",
    })
    # Only one review should exist
    assert Review.objects.filter(organizer=organizer).count() == 1
    review = Review.objects.get(organizer=organizer)
    assert review.rating == 2
    # rating_count should still be 1
    organizer.refresh_from_db()
    assert organizer.rating_count == 1
    assert organizer.avg_rating == pytest.approx(2.0)


@pytest.mark.django_db
def test_submit_review_unauthenticated_redirects_to_login():
    """Unauthenticated POST -> 302 redirect to login."""
    client = Client()
    url = reverse("review-submit")
    resp = client.post(url, {
        "target_type": "organizer",
        "target_id": "1",
        "rating": "4",
    })
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_submit_review_unapproved_user_returns_403(unapproved_user, organizer):
    """Approved=False user gets 403 from approved_required."""
    client = Client()
    client.force_login(unapproved_user)
    url = reverse("review-submit")
    resp = client.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "4",
    })
    assert resp.status_code == 403


@pytest.mark.django_db
def test_submit_review_invalid_rating_returns_400(client_logged_in, organizer):
    """Rating out of range returns 400."""
    url = reverse("review-submit")
    resp = client_logged_in.post(url, {
        "target_type": "organizer",
        "target_id": str(organizer.pk),
        "rating": "99",
    })
    assert resp.status_code == 400


@pytest.mark.django_db
def test_submit_review_invalid_target_type_returns_400(client_logged_in):
    """Unknown target_type returns 400."""
    url = reverse("review-submit")
    resp = client_logged_in.post(url, {
        "target_type": "venue",
        "target_id": "1",
        "rating": "3",
    })
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Test: submit_review — event target
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_submit_event_review_creates_review(client_logged_in, past_event):
    """POST with target_type=event creates a Review row tied to the event."""
    url = reverse("review-submit")
    resp = client_logged_in.post(url, {
        "target_type": "event",
        "target_id": str(past_event.pk),
        "rating": "5",
    })
    assert resp.status_code == 200
    assert Review.objects.filter(event=past_event).count() == 1


@pytest.mark.django_db
def test_submit_event_review_updates_rating_count(client_logged_in, past_event):
    """After event review, Event.rating_count is updated."""
    url = reverse("review-submit")
    client_logged_in.post(url, {
        "target_type": "event",
        "target_id": str(past_event.pk),
        "rating": "3",
    })
    past_event.refresh_from_db()
    assert past_event.rating_count == 1


# ---------------------------------------------------------------------------
# Test: RATINGS_ENABLED flag
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_submit_review_ratings_disabled_returns_503(client_logged_in, organizer):
    """When RATINGS_ENABLED=False, submit returns 503."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="RATINGS_ENABLED", defaults={"enabled": False}
    )
    cache.clear()

    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "4",
        },
    )
    assert resp.status_code == 503
    # Cleanup
    FeatureFlag.objects.filter(key="RATINGS_ENABLED").update(enabled=True)
    cache.clear()


# ---------------------------------------------------------------------------
# Test: MIN_RATINGS_FOR_DISPLAY constant
# ---------------------------------------------------------------------------

def test_min_ratings_for_display_constant():
    """MIN_RATINGS_FOR_DISPLAY is 3 as required."""
    from reviews.views import MIN_RATINGS_FOR_DISPLAY
    assert MIN_RATINGS_FOR_DISPLAY == 3


# ---------------------------------------------------------------------------
# Test: organizer_profile view — rating context
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_organizer_profile_shows_rating_when_count_meets_threshold(client, organizer, approved_user):
    """When rating_count >= 3, show_rating is True in context."""
    organizer.rating_count = 3
    organizer.avg_rating = 4.0
    organizer.save()

    client.force_login(approved_user)
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["show_rating"] is True
    assert resp.context["rating_count"] == 3


@pytest.mark.django_db
def test_organizer_profile_hides_rating_below_threshold(client, organizer):
    """When rating_count < 3, show_rating is False."""
    organizer.rating_count = 2
    organizer.avg_rating = 4.0
    organizer.save()

    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["show_rating"] is False


@pytest.mark.django_db
def test_organizer_profile_includes_user_review_in_context(client_logged_in, approved_user, organizer):
    """user_review context key is the user's existing review when present."""
    review = Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
    )
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client_logged_in.get(url)
    assert resp.status_code == 200
    assert resp.context["user_review"] == review


@pytest.mark.django_db
def test_organizer_profile_user_review_none_when_not_reviewed(client_logged_in, organizer):
    """user_review is None when the user has no review."""
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client_logged_in.get(url)
    assert resp.status_code == 200
    assert resp.context["user_review"] is None


@pytest.mark.django_db
def test_organizer_profile_min_ratings_in_context(client, organizer):
    """MIN_RATINGS_FOR_DISPLAY is passed in context."""
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["MIN_RATINGS_FOR_DISPLAY"] == 3
