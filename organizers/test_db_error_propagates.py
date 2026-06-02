"""Tests for kb-77h: organizer_profile view user_review DB-error propagation.

ADR-008 D3: no silent fallbacks on data integrity.

Acceptance:
- organizers/views.py except clause catches only Review.DoesNotExist;
  any other exception propagates and is observable in logs.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from organizers.models import Profile

User = get_user_model()


@pytest.fixture
def organizer(db):
    return Profile.objects.create(
        name="DB Error Test Organizer",
        slug="db-error-test-org",
        status="approved",
    )


@pytest.fixture
def auth_user(db):
    user = User.objects.create_user(
        username="auth_db_error_user",
        email="auth_db_error@example.com",
        password="testpass123",
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.mark.django_db
def test_review_does_not_exist_sets_user_review_none(organizer, auth_user):
    """When the authenticated user has no review, Review.DoesNotExist is caught
    and user_review is None (normal path)."""
    client = Client()
    client.force_login(auth_user)
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.context["user_review"] is None


@pytest.mark.django_db
def test_non_does_not_exist_exception_propagates_from_user_review_lookup(organizer, auth_user):
    """A non-DoesNotExist exception raised by organizer.reviews.get() propagates
    out of the view (is NOT silently swallowed by broad except Exception)."""
    client = Client()
    client.force_login(auth_user)
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})

    # Patch the reverse-relation manager's get() method to raise RuntimeError.
    # organizer.reviews is a RelatedManager on the Profile instance; we patch
    # the RelatedManager's .get() on the organizer instance's reviews field.
    fake_manager = MagicMock()
    fake_manager.get.side_effect = RuntimeError("simulated DB error")

    prop = property(lambda self: fake_manager)
    with patch.object(type(organizer), "reviews", new_callable=lambda: prop):
        # With broad `except Exception`, RuntimeError gets swallowed; view returns 200
        # and pytest.raises FAILS because no exception is raised.
        # After the fix (only DoesNotExist caught), RuntimeError propagates.
        with pytest.raises(RuntimeError, match="simulated DB error"):
            client.get(url)
