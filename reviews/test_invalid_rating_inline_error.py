"""Regression tests for kb-ikj: invalid rating must render inline form error.

Bug: submitting an invalid/empty rating returned a 400 with only the bare
_rating_form.html fragment rendered in error-only mode (just a <p> tag).
HTMX ignores non-2xx responses by default, so no swap happened; a plain
form POST rendered a blank page with only the error paragraph.

Fix contract:
- invalid rating → 200 + re-rendered form containing the error message
  (the form element must be present so HTMX can swap it back in)
- valid submission → 200 + success response (existing behaviour unchanged)
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from organizers.models import Profile

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    user = User.objects.create_user(
        username="rating_err_tester",
        email="rating_err@example.com",
        password="testpass123",
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def organizer(db):
    return Profile.objects.create(
        name="Inline Error Organizer",
        slug="inline-error-org",
        status="approved",
    )


@pytest.fixture
def client_logged_in(approved_user):
    c = Client()
    c.force_login(approved_user)
    return c


# ---------------------------------------------------------------------------
# RED: invalid rating must return 200 with inline error + form re-rendered
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_invalid_rating_returns_200_not_400(client_logged_in, organizer):
    """Invalid rating submission returns 200 so HTMX can swap the error form in."""
    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "99",
        },
    )
    assert resp.status_code == 200


@pytest.mark.django_db
def test_invalid_rating_response_contains_error_message(client_logged_in, organizer):
    """Invalid rating response body contains the validation error text."""
    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "0",
        },
    )
    assert b"Rating must be between 1 and 5" in resp.content


@pytest.mark.django_db
def test_invalid_rating_response_contains_form_element(client_logged_in, organizer):
    """Invalid rating response re-renders the form element (not just an error <p>).

    This ensures the HTMX outerHTML swap can replace the original form,
    keeping the page chrome intact and the form interactive for retry.
    """
    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "99",
        },
    )
    # The response must contain a <form> element so the HTMX target survives the swap
    assert b"<form" in resp.content


@pytest.mark.django_db
def test_empty_rating_returns_200_with_error(client_logged_in, organizer):
    """Missing/empty rating (rating=0 default) also returns 200 with inline error."""
    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            # no 'rating' key at all
        },
    )
    assert resp.status_code == 200
    assert b"Rating must be between 1 and 5" in resp.content
    assert b"<form" in resp.content


# ---------------------------------------------------------------------------
# GREEN guard: valid submission still succeeds
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_valid_rating_still_succeeds(client_logged_in, organizer):
    """A valid rating (1-5) still returns 200 after the fix."""
    url = reverse("review-submit")
    resp = client_logged_in.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "rating": "4",
            "body": "Great!",
        },
    )
    assert resp.status_code == 200
