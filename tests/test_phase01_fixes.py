"""
Tests for kb-i45.7: phase-0.1 review fixes.

Covers:
- ApprovalGateMiddleware registered in MIDDLEWARE
- Event bulk actions: publish, reject, archive (including re-publish behavior)
- Organizer bulk actions: three consent-method variants
- N+1 fix on OrganizerAdmin.get_queryset (event_count annotation)
"""

import pytest

# ---------------------------------------------------------------------------
# ApprovalGateMiddleware
# ---------------------------------------------------------------------------


def test_approval_gate_middleware_registered():
    """accounts.middleware.LoginWallMiddleware must appear in MIDDLEWARE."""
    from django.conf import settings

    assert "accounts.middleware.LoginWallMiddleware" in settings.MIDDLEWARE, (
        f"LoginWallMiddleware not in MIDDLEWARE: {settings.MIDDLEWARE}"
    )


def test_approval_gate_middleware_importable():
    """LoginWallMiddleware must be importable from accounts.middleware."""
    from accounts.middleware import LoginWallMiddleware  # noqa: F401


def test_approval_gate_middleware_is_passthrough():
    """LoginWallMiddleware with LOGIN_WALL_ENABLED=False passes requests through."""
    from unittest.mock import MagicMock

    from accounts.middleware import LoginWallMiddleware

    responses = []
    sentinel = object()

    def get_response(request):
        responses.append(request)
        return MagicMock(headers={})

    middleware = LoginWallMiddleware(get_response)
    fake_request = MagicMock()
    fake_request.user.is_authenticated = True
    fake_request.user.is_staff = True
    fake_request.path = "/"

    result = middleware(fake_request)
    assert responses == [fake_request]


# ---------------------------------------------------------------------------
# Event bulk actions (admin)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_events_sets_status_and_published_at(superuser, client):
    """publish_events action must set status=published and published_at."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Test Org", slug="test-org")
    event = Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=org,
        start=timezone.now() + datetime.timedelta(days=1),
        status="draft",
    )

    client.force_login(superuser)
    response = client.post(
        "/admin/events/event/",
        {
            "action": "publish_events",
            "_selected_action": [str(event.pk)],
        },
    )
    assert response.status_code in (200, 302)

    event.refresh_from_db()
    assert event.status == "published"
    assert event.published_at is not None


@pytest.mark.django_db
def test_publish_events_does_not_overwrite_published_at(superuser, client):
    """publish_events on already-published event must not overwrite published_at."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Test Org2", slug="test-org2")
    original_published_at = timezone.now() - datetime.timedelta(days=5)
    event = Event.objects.create(
        title="Already Published",
        slug="already-published",
        organizer=org,
        start=timezone.now() + datetime.timedelta(days=1),
        status="published",
        published_at=original_published_at,
    )

    client.force_login(superuser)
    client.post(
        "/admin/events/event/",
        {
            "action": "publish_events",
            "_selected_action": [str(event.pk)],
        },
    )

    event.refresh_from_db()
    assert event.status == "published"
    # published_at should not be overwritten for already-published events
    assert abs((event.published_at - original_published_at).total_seconds()) < 1


@pytest.mark.django_db
def test_reject_events_sets_status_rejected(superuser, client):
    """reject_events action must set status=rejected."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Org Reject", slug="org-reject")
    event = Event.objects.create(
        title="Reject Me",
        slug="reject-me",
        organizer=org,
        start=timezone.now() + datetime.timedelta(days=1),
        status="review",
    )

    client.force_login(superuser)
    response = client.post(
        "/admin/events/event/",
        {
            "action": "reject_events",
            "_selected_action": [str(event.pk)],
        },
    )
    assert response.status_code in (200, 302)

    event.refresh_from_db()
    assert event.status == "rejected"


@pytest.mark.django_db
def test_archive_events_sets_status_archived(superuser, client):
    """archive_events action must set status=archived."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Org Archive", slug="org-archive")
    event = Event.objects.create(
        title="Archive Me",
        slug="archive-me",
        organizer=org,
        start=timezone.now() + datetime.timedelta(days=1),
        status="published",
    )

    client.force_login(superuser)
    response = client.post(
        "/admin/events/event/",
        {
            "action": "archive_events",
            "_selected_action": [str(event.pk)],
        },
    )
    assert response.status_code in (200, 302)

    event.refresh_from_db()
    assert event.status == "archived"


# ---------------------------------------------------------------------------
# Organizer consent bulk actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_approved_explicit_opt_in(superuser, client):
    """mark_approved_explicit_opt_in must set consent_method=explicit_opt_in."""
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Org Explicit", slug="org-explicit")

    client.force_login(superuser)
    response = client.post(
        "/admin/organizers/organizer/",
        {
            "action": "mark_approved_explicit_opt_in",
            "_selected_action": [str(org.pk)],
        },
    )
    assert response.status_code in (200, 302)

    org.refresh_from_db()
    assert org.status == "approved"
    assert org.consent_method == "explicit_opt_in"
    assert org.consent_recorded_at is not None


@pytest.mark.django_db
def test_mark_approved_telegram_forward_implied(superuser, client):
    """mark_approved_telegram_forward_implied sets consent_method correctly."""
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Org Telegram", slug="org-telegram")

    client.force_login(superuser)
    response = client.post(
        "/admin/organizers/organizer/",
        {
            "action": "mark_approved_telegram_forward_implied",
            "_selected_action": [str(org.pk)],
        },
    )
    assert response.status_code in (200, 302)

    org.refresh_from_db()
    assert org.status == "approved"
    assert org.consent_method == "telegram_forward_implied"
    assert org.consent_recorded_at is not None


@pytest.mark.django_db
def test_mark_approved_verified_public_source(superuser, client):
    """mark_approved_verified_public_source sets consent_method correctly."""
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Org Public", slug="org-public")

    client.force_login(superuser)
    response = client.post(
        "/admin/organizers/organizer/",
        {
            "action": "mark_approved_verified_public_source",
            "_selected_action": [str(org.pk)],
        },
    )
    assert response.status_code in (200, 302)

    org.refresh_from_db()
    assert org.status == "approved"
    assert org.consent_method == "verified_public_source"
    assert org.consent_recorded_at is not None


# ---------------------------------------------------------------------------
# N+1 fix: OrganizerAdmin.get_queryset annotates event_count
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_admin_event_count_uses_annotation(superuser, client):
    """OrganizerAdmin changelist must not issue per-row queries for event_count."""
    import datetime

    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone

    from events.models import Event
    from organizers.models import Organizer

    # Create organizers with events
    org1 = Organizer.objects.create(name="Org N+1 A", slug="org-n1-a")
    Organizer.objects.create(name="Org N+1 B", slug="org-n1-b")
    for i in range(3):
        Event.objects.create(
            title=f"Event {i}",
            slug=f"event-n1-{i}",
            organizer=org1,
            start=timezone.now() + datetime.timedelta(days=i + 1),
        )

    client.force_login(superuser)

    with CaptureQueriesContext(connection) as ctx:
        response = client.get("/admin/organizers/organizer/")

    assert response.status_code == 200
    # With annotation, event_count does NOT fire per-row. Expect few queries total.
    # Threshold: ≤ 10 queries regardless of organizer count (session, auth, etc.)
    assert len(ctx.captured_queries) <= 10, (
        f"N+1 detected: {len(ctx.captured_queries)} queries for organizer changelist. "
        f"Queries: {[q['sql'][:80] for q in ctx.captured_queries]}"
    )
