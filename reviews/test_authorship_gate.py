"""Tests for review authorship gate — step-7b (kb-8qn.10).

Gate logic:
- Template only shows the review form when user_has_went_attendance=True
- Direct POST to submit_review without went attendance returns HTTP 429
- All existing gate conditions (event_past, RATINGS_ENABLED, is_approved) still apply
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, Event
from organizers.models import Organizer
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer(db):
    return Organizer.objects.create(
        name="Gate Test Organizer",
        slug="gate-test-organizer",
        status="approved",
    )


@pytest.fixture
def past_event(db, organizer):
    from datetime import timedelta

    return Event.objects.create(
        title="Gate Past Event",
        slug="gate-past-event",
        organizer=organizer,
        status="published",
        start=timezone.now() - timedelta(days=7),
    )


@pytest.fixture
def approved_user(db):
    user = User.objects.create_user(
        username="gate_tester",
        email="gate_tester@example.com",
        password="testpass123",
    )
    user.is_approved = True
    user.save()
    return user


@pytest.fixture
def approved_user_without_attendance(approved_user):
    """Approved user with NO Attendance record for any event."""
    return approved_user


@pytest.fixture
def approved_user_with_went_attendance(db, approved_user, past_event):
    """Approved user who has Attendance(status='went') for past_event."""
    Attendance.objects.create(user=approved_user, event=past_event, status="went")
    return approved_user


# ---------------------------------------------------------------------------
# Test: event detail view context — user_has_went_attendance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_detail_context_false_when_no_attendance(
    approved_user_without_attendance, past_event
):
    """event_detail view sets user_has_went_attendance=False when no went attendance."""
    client = Client()
    client.force_login(approved_user_without_attendance)
    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": past_event.organizer.slug,
            "event_slug": past_event.slug,
        },
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["user_has_went_attendance"] is False


@pytest.mark.django_db
def test_event_detail_context_true_when_went_attendance(
    approved_user_with_went_attendance, past_event
):
    """event_detail view sets user_has_went_attendance=True when went attendance exists."""
    client = Client()
    client.force_login(approved_user_with_went_attendance)
    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": past_event.organizer.slug,
            "event_slug": past_event.slug,
        },
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["user_has_went_attendance"] is True


@pytest.mark.django_db
def test_event_detail_context_false_for_anonymous(past_event):
    """event_detail view sets user_has_went_attendance=False for anonymous users."""
    client = Client()
    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": past_event.organizer.slug,
            "event_slug": past_event.slug,
        },
    )
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["user_has_went_attendance"] is False


# ---------------------------------------------------------------------------
# Test: direct POST to submit_review without went attendance → 429
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_review_without_went_attendance_returns_429(
    approved_user_without_attendance, past_event
):
    """Direct POST to submit_review without went attendance returns HTTP 429."""
    client = Client()
    client.force_login(approved_user_without_attendance)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
        },
    )
    assert resp.status_code == 429


@pytest.mark.django_db
def test_submit_review_without_went_attendance_renders_rating_form(
    approved_user_without_attendance, past_event
):
    """429 response uses _rating_form.html template (HTMX swap compatible)."""
    client = Client()
    client.force_login(approved_user_without_attendance)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
        },
    )
    assert resp.status_code == 429
    assert b"You can review this event after attending" in resp.content


@pytest.mark.django_db
def test_submit_review_without_went_attendance_does_not_create_review(
    approved_user_without_attendance, past_event
):
    """No Review row is created when attendance gate blocks the submission."""
    client = Client()
    client.force_login(approved_user_without_attendance)
    url = reverse("review-submit")
    client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
        },
    )
    assert Review.objects.filter(event=past_event).count() == 0


# ---------------------------------------------------------------------------
# Test: user WITH went attendance can submit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_review_with_went_attendance_returns_200(
    approved_user_with_went_attendance, past_event
):
    """User with went attendance can POST successfully (200)."""
    client = Client()
    client.force_login(approved_user_with_went_attendance)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
        },
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_submit_review_with_went_attendance_creates_review(
    approved_user_with_went_attendance, past_event
):
    """User with went attendance: POST creates a Review row."""
    client = Client()
    client.force_login(approved_user_with_went_attendance)
    url = reverse("review-submit")
    client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "Loved it!",
        },
    )
    assert Review.objects.filter(event=past_event).count() == 1
    review = Review.objects.get(event=past_event)
    assert review.rating == 5
    assert review.body == "Loved it!"


# ---------------------------------------------------------------------------
# Test: 'going' status is NOT enough — only 'went' passes the gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_review_with_going_attendance_returns_429(db, past_event):
    """Attendance(status='going') does not satisfy the went gate → 429."""
    user = User.objects.create_user(
        username="going_user", email="going@example.com", password="testpass123"
    )
    user.is_approved = True
    user.save()
    Attendance.objects.create(user=user, event=past_event, status="going")

    client = Client()
    client.force_login(user)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "3",
        },
    )
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# Test: RATINGS_ENABLED=False still blocks (regression)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_review_ratings_disabled_blocks_even_with_went_attendance(
    approved_user_with_went_attendance, past_event
):
    """RATINGS_ENABLED=False → 503 regardless of attendance status."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="RATINGS_ENABLED", defaults={"enabled": False}
    )
    cache.clear()

    client = Client()
    client.force_login(approved_user_with_went_attendance)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
        },
    )
    assert resp.status_code == 503

    # Cleanup
    FeatureFlag.objects.filter(key="RATINGS_ENABLED").update(enabled=True)
    cache.clear()


# ---------------------------------------------------------------------------
# Test: organizer target_type unaffected by event attendance gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_submit_organizer_review_unaffected_by_attendance_gate(
    approved_user_without_attendance,
):
    """Attendance gate only applies to event target_type; organizer reviews still work."""
    org = Organizer.objects.create(
        name="Unrelated Organizer", slug="unrelated-org", status="approved"
    )
    client = Client()
    client.force_login(approved_user_without_attendance)
    url = reverse("review-submit")
    resp = client.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(org.pk),
            "rating": "3",
        },
    )
    assert resp.status_code == 200
    assert Review.objects.filter(organizer=org).count() == 1
