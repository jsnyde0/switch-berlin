"""Tests for kb-2xe: takedown_view malformed URL error path (ADR-008 D3).

Acceptance:
- A malformed takedown URL produces a specific 'invalid URL' error response
  (not the generic 'could not identify'), and a logfire.warning is emitted
  with the unresolvable URL string.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile
from reviews.models import Flag

User = get_user_model()


@pytest.fixture
def approved_organizer(db):
    return Profile.objects.create(
        name="Takedown Test Organizer",
        slug="takedown-test-org",
        status="approved",
    )


@pytest.fixture
def published_event(db, approved_organizer):
    return Event.objects.create(
        title="Takedown Test Event",
        slug="takedown-test-event",
        organizer=approved_organizer,
        status="published",
        start=timezone.now() + timedelta(days=7),
    )


_VALID_TAKEDOWN_POST = {
    "reason": "spam",
    "body": "Some body.",
    "contact_email": "",
    "good_faith_confirmed": "on",  # required checkbox
}


@pytest.mark.django_db
def test_malformed_url_shows_invalid_url_error_not_generic():
    """POST with a malformed (Resolver404) URL yields a specific 'invalid URL'
    message, not the generic 'could not identify' message."""
    data = {
        **_VALID_TAKEDOWN_POST,
        "event_url": "https://example.com/totally/unknown/path/",
    }
    resp = Client().post(reverse("takedown"), data)
    assert resp.status_code == 200
    content = resp.content.decode()
    assert "not a valid site URL" in content
    # Must NOT fall through to the generic "could not identify" message
    assert "could not identify" not in content


@pytest.mark.django_db
def test_malformed_url_emits_logfire_warning_with_url():
    """POST with a malformed URL causes logfire.warning to be called with
    the unresolvable URL string in the keyword arguments."""
    bad_url = "https://example.com/no/such/path/"
    data = {**_VALID_TAKEDOWN_POST, "event_url": bad_url}
    with patch("logfire.warning") as mock_warning:
        Client().post(reverse("takedown"), data)
    mock_warning.assert_called_once()
    call_kwargs = mock_warning.call_args
    # The URL must appear somewhere in the warning call
    all_args = str(call_kwargs)
    assert bad_url in all_args


@pytest.mark.django_db
def test_malformed_url_does_not_create_flag():
    """POST with a malformed URL must not create a Flag row."""
    data = {**_VALID_TAKEDOWN_POST, "event_url": "https://example.com/no/such/path/"}
    Client().post(reverse("takedown"), data)
    assert Flag.objects.count() == 0


@pytest.mark.django_db
def test_valid_resolvable_url_does_not_emit_logfire_warning(published_event):
    """POST with a valid, resolvable event URL must NOT trigger the logfire warning."""
    event_url = "http://testserver" + reverse(
        "event-detail",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    data = {**_VALID_TAKEDOWN_POST, "event_url": event_url}
    with patch("logfire.warning") as mock_warning:
        with patch("django_q.tasks.async_task"):
            Client().post(reverse("takedown"), data)
    mock_warning.assert_not_called()
