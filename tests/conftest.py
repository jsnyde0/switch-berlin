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
