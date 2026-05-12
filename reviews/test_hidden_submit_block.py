"""TDD tests for bead kb-58p: block re-submission of a hidden review.

Policy (2026-04-22): If a user's review was hidden by a moderator, any
subsequent re-submission attempt must return HTTP 403 with an error partial.
The hidden review row must NOT be modified, and no new row is created.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, Event
from organizers.models import Profile
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer(db):
    return Profile.objects.create(
        name="Hidden Review Organizer",
        slug="hidden-review-org",
        status="approved",
    )


@pytest.fixture
def past_event(db, organizer):
    return Event.objects.create(
        title="Hidden Review Past Event",
        slug="hidden-review-past-event",
        organizer=organizer,
        status="published",
        start=timezone.now() - timedelta(days=7),
    )


@pytest.fixture
def approved_user(db):
    user = User.objects.create_user(
        username="hidden_review_tester",
        email="hidden_review_tester@example.com",
        password="testpass123",
    )
    user.is_approved = True
    user.save()
    return user


@pytest.fixture
def client_approved(approved_user):
    c = Client()
    c.force_login(approved_user)
    return c


@pytest.fixture
def went_attendance(db, approved_user, past_event):
    return Attendance.objects.create(
        user=approved_user, event=past_event, status="went"
    )


# ---------------------------------------------------------------------------
# Test: organizer target — user with hidden review re-submits → 403
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_hidden_review_resubmit_returns_403(
    client_approved, approved_user, organizer
):
    """POST submit_review for an organizer when user has a hidden review returns 403."""
    # Create a hidden review for this user/organizer
    Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=True,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "New content",
        },
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_organizer_hidden_review_resubmit_renders_error_partial(
    client_approved, approved_user, organizer
):
    """403 response uses _rating_form.html partial with error text."""
    Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=True,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "New content",
        },
    )
    assert resp.status_code == 403
    assert b"hidden by a moderator" in resp.content
    assert b"Contact support to appeal" in resp.content


@pytest.mark.django_db
def test_organizer_hidden_review_resubmit_does_not_modify_row(
    client_approved, approved_user, organizer
):
    """Hidden review row is NOT modified when re-submission is blocked."""
    original_review = Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=True,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "Attempted new content",
        },
    )

    # Reload from DB and verify unchanged
    original_review.refresh_from_db()
    assert original_review.rating == 3
    assert original_review.body == "Original content"
    assert original_review.hidden is True


@pytest.mark.django_db
def test_organizer_hidden_review_resubmit_does_not_create_new_row(
    client_approved, approved_user, organizer
):
    """No new Review row is created when blocked by hidden-review check."""
    Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=True,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "New content",
        },
    )

    assert Review.objects.filter(author=approved_user, organizer=organizer).count() == 1


# ---------------------------------------------------------------------------
# Test: event target — user with hidden review re-submits → 403
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_hidden_review_resubmit_returns_403(
    client_approved, approved_user, past_event, went_attendance
):
    """POST submit_review for an event when user has a hidden review returns 403."""
    Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=True,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "New event content",
        },
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_event_hidden_review_resubmit_renders_error_partial(
    client_approved, approved_user, past_event, went_attendance
):
    """403 response for event target uses _rating_form.html partial with error text."""
    Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=True,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "New event content",
        },
    )
    assert resp.status_code == 403
    assert b"hidden by a moderator" in resp.content
    assert b"Contact support to appeal" in resp.content


@pytest.mark.django_db
def test_event_hidden_review_resubmit_does_not_modify_row(
    client_approved, approved_user, past_event, went_attendance
):
    """Hidden event review row is NOT modified when re-submission is blocked."""
    original_review = Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=True,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "New event content",
        },
    )

    original_review.refresh_from_db()
    assert original_review.rating == 2
    assert original_review.body == "Original event review"
    assert original_review.hidden is True


@pytest.mark.django_db
def test_event_hidden_review_resubmit_does_not_create_new_row(
    client_approved, approved_user, past_event, went_attendance
):
    """No new Review row is created for event target when hidden-review check blocks."""
    Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=True,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "New event content",
        },
    )

    assert Review.objects.filter(author=approved_user, event=past_event).count() == 1


# ---------------------------------------------------------------------------
# Test: non-hidden review re-submission → 200, row updated normally
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_non_hidden_review_resubmit_returns_200(
    client_approved, approved_user, organizer
):
    """User with non-hidden organizer review can re-submit normally (200)."""
    Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=False,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "Updated content",
        },
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_organizer_non_hidden_review_resubmit_updates_row(
    client_approved, approved_user, organizer
):
    """Non-hidden organizer review row is updated via update_or_create."""
    Review.objects.create(
        author=approved_user,
        organizer=organizer,
        rating=3,
        body="Original content",
        hidden=False,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "5",
            "body": "Updated content",
        },
    )

    review = Review.objects.get(author=approved_user, organizer=organizer)
    assert review.rating == 5
    assert review.body == "Updated content"
    assert review.hidden is False


@pytest.mark.django_db
def test_event_non_hidden_review_resubmit_returns_200(
    client_approved, approved_user, past_event, went_attendance
):
    """User with non-hidden event review can re-submit normally (200)."""
    Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=False,
    )

    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "Updated event review",
        },
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_event_non_hidden_review_resubmit_updates_row(
    client_approved, approved_user, past_event, went_attendance
):
    """Non-hidden event review row is updated via update_or_create."""
    Review.objects.create(
        author=approved_user,
        event=past_event,
        rating=2,
        body="Original event review",
        hidden=False,
    )

    url = reverse("review-submit")
    client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "5",
            "body": "Updated event review",
        },
    )

    review = Review.objects.get(author=approved_user, event=past_event)
    assert review.rating == 5
    assert review.body == "Updated event review"
    assert review.hidden is False


# ---------------------------------------------------------------------------
# Test: user with no prior review → 200, new row created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_no_prior_review_creates_new_row(
    client_approved, approved_user, organizer
):
    """User with no prior organizer review: POST creates a new Review row."""
    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "4",
            "body": "Brand new review",
        },
    )
    assert resp.status_code == 200
    assert Review.objects.filter(author=approved_user, organizer=organizer).count() == 1
    review = Review.objects.get(author=approved_user, organizer=organizer)
    assert review.rating == 4
    assert review.body == "Brand new review"
    assert review.hidden is False


@pytest.mark.django_db
def test_event_no_prior_review_creates_new_row(
    client_approved, approved_user, past_event, went_attendance
):
    """User with no prior event review: POST creates a new Review row."""
    url = reverse("review-submit")
    resp = client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(past_event.pk),
            "rating": "4",
            "body": "Brand new event review",
        },
    )
    assert resp.status_code == 200
    assert Review.objects.filter(author=approved_user, event=past_event).count() == 1
    review = Review.objects.get(author=approved_user, event=past_event)
    assert review.rating == 4
    assert review.body == "Brand new event review"
    assert review.hidden is False
