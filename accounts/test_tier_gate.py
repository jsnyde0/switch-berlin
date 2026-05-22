"""Tests for kb-m69.6: viewer × event-tier access matrix enforcement.

ADR-012 D3: 4 viewer states × 3 event tiers = 12 access matrix combinations.
Suspended/banned users behave like anonymous (public-only).
Unlisted events accessible by direct URL regardless of viewer status.

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


def make_user(status="open"):
    """Create a user with the given status."""
    import uuid

    username = f"user-{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password="testpass"
    )
    user.status = status
    user.save(update_fields=["status"])
    return user


# ---------------------------------------------------------------------------
# Access matrix tests — event detail URL
# The view already uses Event.objects.visible_to(request.user),
# returning 404 when the event is not in the allowed set.
# Unlisted is accessible by direct URL for *any* authenticated user
# (the queryset passes it through for staff only by default,
# but the middleware/view layer allows direct URL access for all).
# ADR-012 D3 matrix:
#   public:     anon=200, open=200, vouched=200, staff=200
#   semi_public: anon=404, open=404, vouched=200, staff=200
#   unlisted:   anon=404, open=404, vouched=200 (URL direct), staff=200
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAccessMatrixPublicEvent:
    """Public events are visible to all viewer types."""

    def test_anonymous_can_access_public_event(self, client):
        event = make_event(visibility="public")
        org = event.organizer
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_open_user_can_access_public_event(self, client):
        user = make_user(status="open")
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_vouched_user_can_access_public_event(self, client):
        user = make_user(status="vouched")
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_staff_can_access_public_event(self, client):
        user = make_user(status="open")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestAccessMatrixSemiPublicEvent:
    """Semi-public events: only vouched users and staff may access."""

    def test_anonymous_cannot_access_semi_public_event(self, client):
        event = make_event(visibility="semi_public")
        org = event.organizer
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        # Anonymous users: login redirect (302) or 404 — either way not 200
        assert response.status_code in (302, 404)

    def test_open_user_cannot_access_semi_public_event(self, client):
        user = make_user(status="open")
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_vouched_user_can_access_semi_public_event(self, client):
        user = make_user(status="vouched")
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_staff_can_access_semi_public_event(self, client):
        user = make_user(status="open")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestAccessMatrixUnlistedEvent:
    """Unlisted events: accessible by direct URL to vouched/staff, denied to
    anon/open."""

    def test_anonymous_cannot_access_unlisted_event(self, client):
        event = make_event(visibility="unlisted")
        org = event.organizer
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        # Anonymous users: redirect or 404
        assert response.status_code in (302, 404)

    def test_open_user_cannot_access_unlisted_event(self, client):
        user = make_user(status="open")
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_vouched_user_can_access_unlisted_event_by_direct_url(self, client):
        """Unlisted = URL-keyed: vouched user with URL can access it."""
        user = make_user(status="vouched")
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_staff_can_access_unlisted_event(self, client):
        user = make_user(status="open")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200


@pytest.mark.django_db
class TestSuspendedBannedBehaveLikeAnonymous:
    """Suspended and banned users behave like anonymous (public-only access)."""

    def test_suspended_cannot_access_semi_public_event(self, client):
        user = make_user(status="suspended_pending_investigation")
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_banned_cannot_access_semi_public_event(self, client):
        user = make_user(status="banned")
        event = make_event(visibility="semi_public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_suspended_cannot_access_unlisted_event(self, client):
        user = make_user(status="suspended_pending_investigation")
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_banned_cannot_access_unlisted_event(self, client):
        user = make_user(status="banned")
        event = make_event(visibility="unlisted")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 404

    def test_suspended_can_access_public_event(self, client):
        user = make_user(status="suspended_pending_investigation")
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200

    def test_banned_can_access_public_event(self, client):
        user = make_user(status="banned")
        event = make_event(visibility="public")
        org = event.organizer
        client.force_login(user)
        url = f"/events/{org.slug}/{event.slug}/"
        response = client.get(url)
        assert response.status_code == 200
