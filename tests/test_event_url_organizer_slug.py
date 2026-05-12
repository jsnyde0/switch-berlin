"""
TDD tests for kb-8j6: event URL scheme includes organizer slug.

New scheme: /events/<org-slug>/<event-slug>/
Replaces: /events/<event-slug>/

Key scenario: two events with the same slug from different organizers must both
resolve correctly — no 500, each returns its own detail page.
"""

from datetime import timedelta

import django.utils.timezone as tz
import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_user(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="staff_kb8j6",
        email="staff_kb8j6@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def organizer_alpha(db):
    from organizers.models import Profile

    return Profile.objects.create(
        name="Alpha Org",
        slug="alpha-org",
        status="approved",
    )


@pytest.fixture
def organizer_beta(db):
    from organizers.models import Profile

    return Profile.objects.create(
        name="Beta Org",
        slug="beta-org",
        status="approved",
    )


@pytest.fixture
def event_alpha(db, organizer_alpha):
    from events.models import Event

    return Event.objects.create(
        title="Alpha Party",
        slug="summer-party",
        organizer=organizer_alpha,
        status="published",
        start=tz.now() + timedelta(days=7),
    )


@pytest.fixture
def event_beta(db, organizer_beta):
    """Same slug as event_alpha but different organizer."""
    from events.models import Event

    return Event.objects.create(
        title="Beta Party",
        slug="summer-party",
        organizer=organizer_beta,
        status="published",
        start=tz.now() + timedelta(days=14),
    )


# ---------------------------------------------------------------------------
# New URL scheme: /events/<org-slug>/<event-slug>/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_detail_new_url_returns_200(client, staff_user, event_alpha):
    """GET /events/<org-slug>/<event-slug>/ returns 200 for a published event."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{event_alpha.organizer.slug}/{event_alpha.slug}/"
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_event_detail_contains_correct_title(client, staff_user, event_alpha):
    """Event detail page contains the event title."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{event_alpha.organizer.slug}/{event_alpha.slug}/"
    )
    assert event_alpha.title.encode() in response.content


@pytest.mark.django_db
def test_event_detail_404_for_wrong_organizer(
    client, staff_user, event_alpha, organizer_beta
):
    """GET /events/<wrong-org-slug>/<event-slug>/ returns 404 — organizer mismatch."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{organizer_beta.slug}/{event_alpha.slug}/"
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_event_detail_404_for_nonexistent_event(client, staff_user, organizer_alpha):
    """GET /events/<org-slug>/no-such-event/ returns 404."""
    client.force_login(staff_user)
    response = client.get(f"/events/{organizer_alpha.slug}/no-such-event/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_duplicate_slug_different_organizers_both_resolve(
    client, staff_user, event_alpha, event_beta
):
    """Two events with the same slug but different organizers both resolve correctly.

    This is the core regression: the old /events/<slug>/ scheme would return the
    first match for both, causing wrong data. The new scheme must route each to
    its own event detail page.
    """
    client.force_login(staff_user)

    # Alpha org's event
    response_alpha = client.get(
        f"/events/{event_alpha.organizer.slug}/{event_alpha.slug}/"
    )
    assert response_alpha.status_code == 200, (
        f"Expected 200 for alpha event, got {response_alpha.status_code}"
    )
    assert event_alpha.title.encode() in response_alpha.content, (
        "Alpha event detail should show Alpha Party title"
    )

    # Beta org's event — same slug, different organizer
    response_beta = client.get(
        f"/events/{event_beta.organizer.slug}/{event_beta.slug}/"
    )
    assert response_beta.status_code == 200, (
        f"Expected 200 for beta event, got {response_beta.status_code}"
    )
    assert event_beta.title.encode() in response_beta.content, (
        "Beta event detail should show Beta Party title"
    )

    # Ensure they returned different content (different events)
    assert response_alpha.content != response_beta.content, (
        "Events with same slug from different organizers must return different pages"
    )
