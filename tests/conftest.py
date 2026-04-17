"""Shared pytest fixtures for the kinky-bubbles test suite."""

import pytest


@pytest.fixture
def superuser(db):
    """Create a superuser for admin smoke tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser("admin", "admin@example.com", "password")
