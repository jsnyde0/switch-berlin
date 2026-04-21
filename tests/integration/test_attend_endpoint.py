"""
Integration tests for kb-2eu.4 — Attend interaction UI: endpoint + HTMX button.

Test plan items (from bead kb-2eu.4):
1. POST /events/<org_slug>/<event_slug>/attend/ with status=going updates or creates Attendance row.
2. Response contains HX-Trigger: events:attendance-changed header.
3. 'Went' button does not appear in _attend_button.html when event_past=False.
4. Unauthenticated POST to /events/<org_slug>/<event_slug>/attend/ returns 302 to login page.
5. POST to non-existent event slug returns 404.
6. POST with status='went' on future event clamps to status='going'.
7. _attend_button.html partial is included in detail.html only when user is
   authenticated and MAP_ENABLED=True.
8. Repeat POST with same status is idempotent (200, single row, status unchanged).
9. POST with status='interested' creates/updates Attendance row correctly.
10. GET /events/<org_slug>/<event_slug>/attend/ returns 405 Method Not Allowed.
11. Response body contains the attend button partial HTML.
12. event_detail view passes attendance and event_past to context.
"""

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_organizer(db):
    """Approved organizer for attend tests."""
    from organizers.models import Organizer

    return Organizer.objects.create(
        name="Attend Test Organizer",
        slug="attend-test-organizer",
        status="approved",
    )


@pytest.fixture
def future_event(db, approved_organizer):
    """A published future event — event_past=False."""
    from events.models import Event

    return Event.objects.create(
        title="Future Test Event",
        slug="future-test-event",
        organizer=approved_organizer,
        status="published",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def past_event(db, approved_organizer):
    """A published past event — event_past=True."""
    from events.models import Event

    return Event.objects.create(
        title="Past Test Event",
        slug="past-test-event",
        organizer=approved_organizer,
        status="published",
        start=timezone.now() - timedelta(days=7),
    )


@pytest.fixture
def draft_event(db, approved_organizer):
    """A draft (non-published) event — attend endpoint must 404."""
    from events.models import Event

    return Event.objects.create(
        title="Draft Test Event",
        slug="draft-test-event",
        organizer=approved_organizer,
        status="draft",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def staff_user(db):
    """Staff user that can pass the login wall."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="attend_staff",
        email="attend_staff@example.com",
        password="x",
        is_staff=True,
    )


@pytest.fixture
def approved_user(db):
    """Approved non-staff user."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="attend_approved",
        email="attend_approved@example.com",
        password="x",
        is_staff=False,
        is_approved=True,
    )


# ---------------------------------------------------------------------------
# Endpoint basics: status code and row creation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_post_going_creates_row(client, staff_user, future_event):
    """POST /events/<org_slug>/<event_slug>/attend/ with status=going creates an Attendance row."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 200
    assert Attendance.objects.filter(
        user=staff_user, event=future_event, status="going"
    ).exists()


@pytest.mark.django_db
def test_attend_post_interested_creates_row(client, staff_user, future_event):
    """POST /events/<org_slug>/<event_slug>/attend/ with status=interested creates Attendance row."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "interested"}
    )
    assert response.status_code == 200
    assert Attendance.objects.filter(
        user=staff_user, event=future_event, status="interested"
    ).exists()


@pytest.mark.django_db
def test_attend_post_updates_existing_row(client, staff_user, future_event):
    """POST /events/<org_slug>/<event_slug>/attend/ updates existing Attendance row (no duplicates)."""
    from events.models import Attendance

    # Pre-create an Attendance row
    Attendance.objects.create(user=staff_user, event=future_event, status="interested")

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})

    # Should still be exactly one row, now with status 'going'
    assert Attendance.objects.filter(user=staff_user, event=future_event).count() == 1
    assert Attendance.objects.get(user=staff_user, event=future_event).status == "going"


# ---------------------------------------------------------------------------
# HX-Trigger header
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_response_has_hx_trigger_header(client, staff_user, future_event):
    """POST /events/<org_slug>/<event_slug>/attend/ response has HX-Trigger: events:attendance-changed."""
    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 200
    assert response["HX-Trigger"] == "events:attendance-changed"


# ---------------------------------------------------------------------------
# 'Went' button visibility
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_button_no_went_for_future_event(client, staff_user, future_event):
    """Response partial does not contain 'Went' button for a future event."""
    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 200
    content = response.content.decode()
    # 'Went' button should NOT be in the partial for a future event
    assert 'value="went"' not in content


@pytest.mark.django_db
def test_attend_button_shows_went_for_past_event(client, staff_user, past_event):
    """Response partial contains 'Went' button for a past event."""
    client.force_login(staff_user)
    org_slug = past_event.organizer.slug
    event_slug = past_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "went"}
    )
    assert response.status_code == 200
    content = response.content.decode()
    # 'Went' button SHOULD be in the partial for a past event
    assert 'value="went"' in content


# ---------------------------------------------------------------------------
# 'Went' status clamping on future event
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_went_on_future_event_clamped_to_going(
    client, staff_user, future_event
):
    """POST with status='went' on future event clamps Attendance to status='going'."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "went"})

    attendance = Attendance.objects.get(user=staff_user, event=future_event)
    assert attendance.status == "going"


@pytest.mark.django_db
def test_attend_went_on_past_event_not_clamped(client, staff_user, past_event):
    """POST with status='went' on a past event creates Attendance with status='went'."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = past_event.organizer.slug
    event_slug = past_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "went"})

    attendance = Attendance.objects.get(user=staff_user, event=past_event)
    assert attendance.status == "went"


# ---------------------------------------------------------------------------
# Auth and access control
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_unauthenticated_redirects_to_login(client, future_event):
    """Unauthenticated POST /events/<org_slug>/<event_slug>/attend/ returns 302 to login page."""
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_attend_nonexistent_event_returns_404(client, staff_user, approved_organizer):
    """POST to non-existent event slug returns 404."""
    client.force_login(staff_user)
    response = client.post(
        f"/events/{approved_organizer.slug}/nonexistent-event/attend/",
        {"status": "going"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_attend_unpublished_event_returns_404(client, staff_user, draft_event):
    """POST to draft (non-published) event returns 404."""
    client.force_login(staff_user)
    org_slug = draft_event.organizer.slug
    event_slug = draft_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_attend_get_method_not_allowed(client, staff_user, future_event):
    """GET /events/<org_slug>/<event_slug>/attend/ returns 405 Method Not Allowed."""
    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.get(f"/events/{org_slug}/{event_slug}/attend/")
    assert response.status_code == 405


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_idempotent_same_status(client, staff_user, future_event):
    """Posting the same status twice is idempotent: one row, status unchanged."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})
    response = client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})

    assert response.status_code == 200
    assert Attendance.objects.filter(user=staff_user, event=future_event).count() == 1
    assert Attendance.objects.get(user=staff_user, event=future_event).status == "going"


# ---------------------------------------------------------------------------
# Invalid status clamping
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_invalid_status_clamped_to_interested(
    client, staff_user, future_event
):
    """POST with invalid status value creates Attendance with status='interested'."""
    from events.models import Attendance

    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "invalid_value"}
    )
    assert response.status_code == 200
    attendance = Attendance.objects.get(user=staff_user, event=future_event)
    assert attendance.status == "interested"


# ---------------------------------------------------------------------------
# Response body: attend button partial
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_response_contains_attend_button_partial(
    client, staff_user, future_event
):
    """Response body contains the attend button partial HTML."""
    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    content = response.content.decode()
    # The partial should have the attend div wrapper
    assert f'id="attend-{future_event.pk}"' in content


@pytest.mark.django_db
def test_attend_response_shows_active_button_for_current_status(
    client, staff_user, future_event
):
    """Response partial shows btn-active on the button matching current status."""
    client.force_login(staff_user)
    org_slug = future_event.organizer.slug
    event_slug = future_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    content = response.content.decode()
    assert "btn-active" in content


# ---------------------------------------------------------------------------
# event_detail view: attendance and event_past context
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_detail_passes_attendance_to_context(
    client, staff_user, future_event
):
    """event_detail view passes attendance object to context when user has row."""
    from events.models import Attendance

    Attendance.objects.create(user=staff_user, event=future_event, status="going")
    client.force_login(staff_user)
    response = client.get(
        f"/events/{future_event.organizer.slug}/{future_event.slug}/"
    )
    assert response.status_code == 200
    # attendance context should be rendered (btn-active class in attend button)
    content = response.content.decode()
    assert "btn-active" in content


@pytest.mark.django_db
def test_event_detail_attendance_is_none_when_no_row(
    client, staff_user, future_event
):
    """event_detail view context: attendance is None when user has no Attendance row."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{future_event.organizer.slug}/{future_event.slug}/"
    )
    assert response.status_code == 200
    # No btn-active since user hasn't attended
    content = response.content.decode()
    assert "btn-active" not in content


@pytest.mark.django_db
@override_settings(MAP_ENABLED=True)
def test_event_detail_includes_attend_button_when_authenticated_and_map_enabled(
    client, staff_user, future_event
):
    """event_detail includes attend button for authenticated user (MAP_ENABLED=True)."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{future_event.organizer.slug}/{future_event.slug}/"
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert f'id="attend-{future_event.pk}"' in content


@pytest.mark.django_db
@override_settings(MAP_ENABLED=False)
def test_event_detail_hides_attend_button_when_map_disabled(
    client, staff_user, future_event
):
    """event_detail hides attend button when MAP_ENABLED=False."""
    client.force_login(staff_user)
    response = client.get(
        f"/events/{future_event.organizer.slug}/{future_event.slug}/"
    )
    assert response.status_code == 200
    content = response.content.decode()
    assert f'id="attend-{future_event.pk}"' not in content
