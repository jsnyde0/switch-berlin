"""Tests for /healthz liveness + data-intact probe (kb-l94)."""

import django.utils.timezone as tz
import pytest
from django.test import Client


@pytest.mark.django_db
def test_healthz_returns_503_when_events_empty():
    response = Client().get("/healthz")
    assert response.status_code == 503
    assert response.json() == {"status": "empty", "has_events": False}


@pytest.mark.django_db
def test_healthz_returns_200_when_events_exist():
    from events.models import Event
    from organizers.models import Profile

    organizer = Profile.objects.create(
        name="Healthz Org",
        slug="healthz-org",
        status="approved",
    )
    Event.objects.create(
        title="Healthz Probe Event",
        slug="healthz-event",
        organizer=organizer,
        start=tz.now() + tz.timedelta(days=7),
        status="published",
    )

    response = Client().get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "has_events": True}
