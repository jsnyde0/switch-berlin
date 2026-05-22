"""Tests for kb-m69.6: XRobotsTagMiddleware.

ADR-012 D3 robot indexing:
  - public events: no X-Robots-Tag header
  - semi_public events: X-Robots-Tag: noindex, nofollow
  - unlisted events: X-Robots-Tag: noindex, nofollow, noarchive

TDD: all tests written before implementation.
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from events.models import Event

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_org():
    """Create a minimal approved organizer Profile."""
    import uuid

    from organizers.models import Profile

    slug = f"org-{uuid.uuid4().hex[:8]}"
    return Profile.objects.create(name="Test Org", slug=slug, status="approved")


def make_event(title="Test", visibility="public", organizer=None):
    """Create a minimal published event."""
    import uuid

    org = organizer or make_org()
    slug = f"{visibility[:4]}-{uuid.uuid4().hex[:6]}"
    return Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        status="published",
        visibility=visibility,
        organizer=org,
    )


def make_vouched_user():
    """Create a vouched user for authenticated tests."""
    import uuid

    username = f"vouched-{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password="testpass"
    )
    user.status = "vouched"
    user.save(update_fields=["status"])
    return user


# ---------------------------------------------------------------------------
# X-Robots-Tag header tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestXRobotsTagPublicEvent:
    """Public events must NOT carry X-Robots-Tag (search engines may index)."""

    def test_public_event_detail_has_no_x_robots_tag(self, client):
        event = make_event(visibility="public")
        org = event.organizer
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200
        assert "X-Robots-Tag" not in response

    def test_public_event_detail_authenticated_has_no_x_robots_tag(self, client):
        user = make_vouched_user()
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200
        assert "X-Robots-Tag" not in response


@pytest.mark.django_db
class TestXRobotsTagSemiPublicEvent:
    """Semi-public events must carry X-Robots-Tag: noindex, nofollow."""

    def test_semi_public_event_detail_has_noindex_nofollow(self, client):
        user = make_vouched_user()
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200
        assert "X-Robots-Tag" in response
        robots_tag = response["X-Robots-Tag"]
        assert "noindex" in robots_tag
        assert "nofollow" in robots_tag
        # semi_public does NOT include noarchive (that's unlisted-only)
        assert "noarchive" not in robots_tag


@pytest.mark.django_db
class TestXRobotsTagUnlistedEvent:
    """Unlisted events must carry X-Robots-Tag: noindex, nofollow, noarchive."""

    def test_unlisted_event_detail_has_noindex_nofollow_noarchive(self, client):
        user = make_vouched_user()
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200
        assert "X-Robots-Tag" in response
        robots_tag = response["X-Robots-Tag"]
        assert "noindex" in robots_tag
        assert "nofollow" in robots_tag
        assert "noarchive" in robots_tag
