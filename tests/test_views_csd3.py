"""
TDD tests for kb-csd.3: event_detail and organizer_profile views.

RED phase: these tests will fail until the views and templates are implemented.
"""

import django.utils.timezone as tz
import pytest
from django.test import Client

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="viewer",
        email="viewer@example.com",
        password="password",
        is_staff=True,
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def organizer(db):
    from organizers.models import Profile

    return Profile.objects.create(
        name="Test Organizer",
        slug="test-organizer",
        status="approved",
    )


@pytest.fixture
def published_event(db, organizer):
    from events.models import Event

    return Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=organizer,
        start=tz.now() + tz.timedelta(days=7),
        status="published",
    )


@pytest.fixture
def draft_event(db, organizer):
    from events.models import Event

    return Event.objects.create(
        title="Draft Event",
        slug="draft-event",
        organizer=organizer,
        start=tz.now() + tz.timedelta(days=7),
        status="draft",
    )


@pytest.fixture
def candidate_organizer(db):
    from organizers.models import Profile

    return Profile.objects.create(
        name="Candidate Org",
        slug="candidate-org",
        status="candidate",
    )


# ---------------------------------------------------------------------------
# event_detail tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_detail_returns_200_for_published(approved_user, published_event):
    """GET /events/<org-slug>/<event-slug>/ returns 200 for a published event."""
    client = Client()
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    response = client.get(f"/events/{org_slug}/{published_event.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_event_detail_returns_404_for_nonexistent(approved_user, organizer):
    """GET /events/<org-slug>/nonexistent-slug/ returns 404."""
    client = Client()
    client.force_login(approved_user)
    response = client.get(f"/events/{organizer.slug}/does-not-exist/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_event_detail_returns_404_for_draft(approved_user, draft_event):
    """GET /events/<org-slug>/<draft-slug>/ returns 404 (draft is not published)."""
    client = Client()
    client.force_login(approved_user)
    org_slug = draft_event.organizer.slug
    response = client.get(f"/events/{org_slug}/{draft_event.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_event_detail_contains_title(approved_user, published_event):
    """Event detail page contains the event title."""
    client = Client()
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    response = client.get(f"/events/{org_slug}/{published_event.slug}/")
    assert published_event.title.encode() in response.content


# ---------------------------------------------------------------------------
# organizer_profile tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_profile_returns_200_for_approved(approved_user, organizer):
    """GET /p/<slug>/ returns 200 for an approved organizer."""
    client = Client()
    client.force_login(approved_user)
    response = client.get(f"/p/{organizer.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_organizer_profile_returns_404_for_nonexistent(approved_user):
    """GET /p/<nonexistent-slug>/ returns 404."""
    client = Client()
    client.force_login(approved_user)
    response = client.get("/p/does-not-exist/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_organizer_profile_returns_404_for_candidate(
    approved_user, candidate_organizer
):
    """GET /p/<candidate-slug>/ returns 404 (not approved)."""
    client = Client()
    client.force_login(approved_user)
    response = client.get(f"/p/{candidate_organizer.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_organizer_profile_contains_name(approved_user, organizer):
    """Organizer profile page contains the organizer name."""
    client = Client()
    client.force_login(approved_user)
    response = client.get(f"/p/{organizer.slug}/")
    assert organizer.name.encode() in response.content
