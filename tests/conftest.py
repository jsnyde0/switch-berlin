"""Shared pytest fixtures for the kinky-bubbles test suite."""

import pytest


@pytest.fixture
def superuser(db):
    """Create a superuser for admin smoke tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser("admin", "admin@example.com", "password")


@pytest.fixture(autouse=True)
def isolate_logfire_token(monkeypatch):
    """Ensure LOGFIRE_TOKEN is always empty during tests.

    Prevents tests from accidentally emitting real Logfire events when a
    contributor has a real LOGFIRE_TOKEN set in their environment or .env file.
    Scoped to the whole test suite via autouse=True.
    """
    monkeypatch.setenv("LOGFIRE_TOKEN", "")


@pytest.fixture
def staff_user(db):
    """Staff user for login-wall tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="staff", email="staff@example.com", password="x", is_staff=True
    )


@pytest.fixture
def regular_user(db):
    """Authenticated but non-staff user — should get 403 from login-wall."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="regular", email="regular@example.com", password="x", is_staff=False
    )


@pytest.fixture
def approved_organizer(db):
    """Approved organizer for view smoke tests."""
    from organizers.models import Organizer

    return Organizer.objects.create(
        name="Test Organizer",
        slug="test-organizer",
        status="approved",
    )


@pytest.fixture
def published_event(db, approved_organizer):
    """A single published future event."""
    from datetime import timedelta

    import django.utils.timezone as tz

    from events.models import Event

    return Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=7),
    )
