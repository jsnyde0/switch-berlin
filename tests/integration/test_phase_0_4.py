"""
Integration tests for Phase 0.4 — cross-feature E2E walkthrough, privacy
enforcement, invite codes, middleware, CSRF, and kill-switches.

This file covers bead kb-2eu.6. It tests CROSS-FEATURE interactions that span
multiple beads and are not covered by per-bead test files.

Test groups:
1. Middleware relaxation (approved/unapproved/staff/public-paths)
2. Invite code redemption via HTTP (GET signup page, POST signup flow)
3. Privacy enforcement — coordinates (markers_geojson context)
4. Privacy enforcement — venue metadata (template rendering)
5. Attend endpoint (auth, idempotency, state transitions)
6. Follow endpoint (auth, toggle, 404)
7. CSRF enforcement on attend/follow
8. Kill-switches (MAP_ENABLED, INVITES_ENABLED)
"""

from datetime import timedelta

import django.utils.timezone as tz
import pytest
from django.test import Client

from accounts.models import InviteCode
from events.models import Attendance
from organizers.models import Follow
from venues.models import Venue

# ---------------------------------------------------------------------------
# Fixtures (new ones for this test file — conftest.py already has
# superuser, staff_user, regular_user, approved_organizer, published_event)
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    """Approved non-staff user — should pass the middleware after 0.4 restructure.

    Art. 9 consent is granted so the attend endpoint can write Attendance rows.
    """
    from django.contrib.auth import get_user_model
    from django.utils import timezone

    User = get_user_model()
    user = User.objects.create_user(
        username="e2e_approved",
        email="e2e_approved@example.com",
        password="x",
        is_staff=False,
    )
    user.status = "vouched"
    user.art9_consent_given_at = timezone.now()
    user.save(update_fields=["status", "art9_consent_given_at"])
    return user


@pytest.fixture
def private_venue(db):
    """A private-mode venue with known coordinates."""
    return Venue.objects.create(
        name="Secret Place",
        slug="secret-place",
        privacy_mode="private",
        latitude="52.5",
        longitude="13.4",
    )


@pytest.fixture
def event_with_private_venue(db, approved_organizer, private_venue):
    """A published event whose venue is private."""
    from events.models import Event

    return Event.objects.create(
        title="Private Event",
        slug="private-event",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=7),
        venue=private_venue,
    )


@pytest.fixture
def valid_invite_code(db, staff_user):
    """An unredeemed, non-expired invite code created by staff_user."""
    return InviteCode.objects.create(created_by=staff_user, notes="test")


# ---------------------------------------------------------------------------
# 1. Middleware relaxation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approved_user_can_access_events(client, approved_user, published_event):
    """Approved non-staff user gets 200 on /events/ (middleware relaxed)."""
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_unapproved_user_sees_pending_page_when_login_wall_active(client, regular_user):
    """Unapproved user gets 403 when PUBLIC_READ_ENABLED=False (login wall active)."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    # In Phase 0.5 with PUBLIC_READ_ENABLED=True, unapproved users CAN access /events/.
    # With PUBLIC_READ_ENABLED=False (rollback mode), unapproved authenticated users
    # are shown the pending-approval page.
    FeatureFlag.objects.update_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    client.force_login(regular_user)
    try:
        response = client.get("/events/")
        assert response.status_code == 403
        assert b"pending" in response.content
    finally:
        FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
def test_staff_user_still_allowed(client, staff_user, published_event):
    """Staff user is still allowed through the middleware (backward-compat)."""
    client.force_login(staff_user)
    response = client.get("/events/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_public_paths_accessible_to_unapproved(client, regular_user):
    """Unapproved user can reach /accounts/logout/ — PUBLIC_PREFIXES not 403'd.

    /accounts/logout/ shows a confirmation page (200) for authenticated users.
    This verifies middleware passes /accounts/ prefix without blocking.
    """
    client.force_login(regular_user)
    response = client.get("/accounts/logout/")
    # Must not be 403 — the /accounts/ prefix is in PUBLIC_PREFIXES
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Invite code redemption (HTTP-level)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_signup_open_with_valid_code(client, valid_invite_code):
    """GET /accounts/signup/?code=<valid> renders a signup form."""
    response = client.get(f"/accounts/signup/?code={valid_invite_code.code}")
    assert response.status_code == 200
    assert b"<form" in response.content


@pytest.mark.django_db
def test_signup_open_without_code(client):
    """GET /accounts/signup/ renders the form — open signup path (kb-m69.5).

    kb-m69.5 replaced the invite-gated path with an always-open signup using
    Turnstile CAPTCHA. The form IS rendered without any invite code.
    """
    response = client.get("/accounts/signup/")
    assert response.status_code == 200
    content = response.content.decode()
    assert 'type="password"' in content, (
        "Signup form was NOT rendered — signup must be open in phase 0.5+"
    )


@pytest.mark.django_db
@pytest.mark.skip(
    reason=(
        "Invite-code redemption is part of the vouched-signup path (kb-m69.7). "
        "OpenSignupAdapter (kb-m69.5) does not process invite codes."
    )
)
def test_invite_code_redeemed_on_signup(client, valid_invite_code):
    """POST to /accounts/signup/ with code in session redeems the InviteCode."""
    # Inject the invite code into the session
    session = client.session
    session["invite_code"] = valid_invite_code.code
    session.save()

    client.post(
        "/accounts/signup/",
        {
            "email": "newuser@example.com",
            "password1": "Testpassword1!",
            "password2": "Testpassword1!",
        },
        follow=True,
    )

    valid_invite_code.refresh_from_db()
    # NOTE: This test is skipped — the canonical check would use used_by (not
    # redeemed_by, which was deleted in kb-m69.12 per ADR-008 D1).
    assert valid_invite_code.used_by is not None

    # Newly created user should be in 'open' status (not vouched)
    from django.contrib.auth import get_user_model

    User = get_user_model()
    new_user = User.objects.get(email="newuser@example.com")
    assert new_user.status == "open"


@pytest.mark.django_db
@pytest.mark.skip(
    reason=(
        "Invite-code rejection is part of the vouched-signup path (kb-m69.7). "
        "OpenSignupAdapter (kb-m69.5) does not gate on invite codes."
    )
)
def test_redeemed_code_rejected(client, staff_user):
    """GET /accounts/signup/?code=<used> does not render a signup form."""
    # NOTE: This test is skipped. The canonical field is used_by (redeemed_by was
    # deleted in kb-m69.12 per ADR-008 D1).
    already_used = InviteCode.objects.create(
        created_by=staff_user, used_by=staff_user, used_at=tz.now()
    )
    response = client.get(f"/accounts/signup/?code={already_used.code}")
    content = response.content.decode()
    assert 'type="password"' not in content


@pytest.mark.django_db
@pytest.mark.skip(
    reason=(
        "Expired invite-code rejection is part of the vouched-signup path (kb-m69.7). "
        "OpenSignupAdapter (kb-m69.5) does not gate on invite codes."
    )
)
def test_expired_code_rejected(client, staff_user):
    """GET /accounts/signup/?code=<expired> does not render a signup form."""
    expired = InviteCode.objects.create(
        created_by=staff_user,
        expires_at=tz.now() - timedelta(days=1),
    )
    response = client.get(f"/accounts/signup/?code={expired.code}")
    content = response.content.decode()
    assert 'type="password"' not in content


# ---------------------------------------------------------------------------
# 3. Privacy enforcement — coordinates (via markers_geojson context)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_private_venue_blurred_without_going(
    client, approved_user, event_with_private_venue
):
    """Approved user without Attendance(going) sees blurred coords in GeoJSON."""
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200

    markers_geojson = response.context["markers_geojson"]
    feature = next(
        (
            f
            for f in markers_geojson["features"]
            if f["properties"]["org_slug"] == event_with_private_venue.organizer.slug
            and f["properties"]["event_slug"] == event_with_private_venue.slug
        ),
        None,
    )
    assert feature is not None, "Event feature not found in markers_geojson"
    assert "event_id" not in feature["properties"], (
        "event_id must not be in GeoJSON properties"
    )

    # Blurred: coords must NOT be exactly [13.4, 52.5]
    coords = feature["geometry"]["coordinates"]
    assert coords != [13.4, 52.5], "Private venue coords must be blurred (not exact)"
    assert feature["properties"]["blur_radius_m"] == 1000


@pytest.mark.django_db
def test_private_venue_exact_with_going(
    client, approved_user, event_with_private_venue, private_venue
):
    """Approved user with Attendance(going) sees exact coords in GeoJSON."""
    Attendance.objects.create(
        user=approved_user, event=event_with_private_venue, status="going"
    )
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200

    markers_geojson = response.context["markers_geojson"]
    feature = next(
        (
            f
            for f in markers_geojson["features"]
            if f["properties"]["org_slug"] == event_with_private_venue.organizer.slug
            and f["properties"]["event_slug"] == event_with_private_venue.slug
        ),
        None,
    )
    assert feature is not None, "Event feature not found in markers_geojson"
    assert "event_id" not in feature["properties"], (
        "event_id must not be in GeoJSON properties"
    )

    coords = feature["geometry"]["coordinates"]
    # Exact coords: longitude first, then latitude (GeoJSON convention)
    assert abs(coords[0] - 13.4) < 0.001, "Longitude not exact for going user"
    assert abs(coords[1] - 52.5) < 0.001, "Latitude not exact for going user"
    assert feature["properties"]["blur_radius_m"] is None


# ---------------------------------------------------------------------------
# 4. Privacy enforcement — venue metadata (template rendering)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_private_venue_name_hidden_in_card(
    client, approved_user, event_with_private_venue
):
    """Event list card shows 'Private venue' not the actual name for private venues."""
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200
    assert b"Secret Place" not in response.content
    assert b"Private venue" in response.content


@pytest.mark.django_db
def test_private_venue_name_shown_with_going(
    client, approved_user, event_with_private_venue
):
    """Event list card shows actual venue name when user has Attendance(going)."""
    Attendance.objects.create(
        user=approved_user, event=event_with_private_venue, status="going"
    )
    client.force_login(approved_user)
    response = client.get("/events/")
    assert response.status_code == 200
    assert b"Secret Place" in response.content


@pytest.mark.django_db
def test_private_venue_name_hidden_in_detail(
    client, approved_user, event_with_private_venue, approved_organizer
):
    """Event detail page shows 'Private venue' for users without going Attendance."""
    client.force_login(approved_user)
    response = client.get(f"/events/{approved_organizer.slug}/private-event/")
    assert response.status_code == 200
    assert b"Private venue" in response.content


@pytest.mark.django_db
def test_private_venue_name_hidden_in_drawer(
    client, approved_user, event_with_private_venue
):
    """Event drawer shows 'Private venue' for users without going Attendance."""
    client.force_login(approved_user)
    org_slug = event_with_private_venue.organizer.slug
    event_slug = event_with_private_venue.slug
    response = client.get(f"/events/{org_slug}/{event_slug}/drawer/")
    assert response.status_code == 200
    assert b"Private venue" in response.content


@pytest.mark.django_db
def test_private_venue_name_shown_in_detail_for_going_user(
    client, approved_user, event_with_private_venue, approved_organizer
):
    """Event detail page shows actual venue name for users WITH going Attendance."""
    Attendance.objects.create(
        user=approved_user, event=event_with_private_venue, status="going"
    )
    client.force_login(approved_user)
    response = client.get(f"/events/{approved_organizer.slug}/private-event/")
    assert response.status_code == 200
    assert b"Secret Place" in response.content
    assert b"Private venue" not in response.content


@pytest.mark.django_db
def test_private_venue_name_shown_in_drawer_for_going_user(
    client, approved_user, event_with_private_venue
):
    """Event drawer shows actual venue name for users WITH going Attendance."""
    Attendance.objects.create(
        user=approved_user, event=event_with_private_venue, status="going"
    )
    client.force_login(approved_user)
    org_slug = event_with_private_venue.organizer.slug
    event_slug = event_with_private_venue.slug
    response = client.get(f"/events/{org_slug}/{event_slug}/drawer/")
    assert response.status_code == 200
    assert b"Secret Place" in response.content
    assert b"Private venue" not in response.content


# ---------------------------------------------------------------------------
# 5. Attend endpoint (cross-feature, uses conftest fixtures)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_requires_login(client, published_event):
    """Unauthenticated POST to attend endpoint redirects to login."""
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_attend_requires_approved(client, regular_user, published_event):
    """Unapproved (regular_user) POST to attend endpoint gets 403 from middleware."""
    client.force_login(regular_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_attend_creates_row(client, approved_user, published_event):
    """Approved user POST to attend creates Attendance row."""
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 200
    assert Attendance.objects.filter(
        user=approved_user, event=published_event, status="going"
    ).exists()


@pytest.mark.django_db
def test_attend_returns_hx_trigger(client, approved_user, published_event):
    """Attend response has HX-Trigger: events:attendance-changed header."""
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    response = client.post(
        f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"}
    )
    assert response.status_code == 200
    assert response["HX-Trigger"] == "events:attendance-changed"


@pytest.mark.django_db
def test_attend_went_before_event_clamped_to_going(
    client, approved_user, published_event
):
    """POST with status='went' on a future event is clamped to status='going'."""
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "went"})
    assert (
        Attendance.objects.get(user=approved_user, event=published_event).status
        == "going"
    )


@pytest.mark.django_db
def test_attend_nonexistent_event_returns_404(
    client, approved_user, approved_organizer
):
    """POST to non-existent event slug returns 404."""
    client.force_login(approved_user)
    response = client.post(
        f"/events/{approved_organizer.slug}/nonexistent-event/attend/",
        {"status": "going"},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_attend_idempotent(client, approved_user, published_event):
    """Two identical attend POSTs result in exactly one row with correct status."""
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})
    assert (
        Attendance.objects.filter(user=approved_user, event=published_event).count()
        == 1
    )
    assert (
        Attendance.objects.get(user=approved_user, event=published_event).status
        == "going"
    )


@pytest.mark.django_db
def test_attend_state_transition(client, approved_user, published_event):
    """POST with status='interested' then status='going' updates the row."""
    client.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "interested"})
    assert (
        Attendance.objects.get(user=approved_user, event=published_event).status
        == "interested"
    )

    client.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})
    assert (
        Attendance.objects.get(user=approved_user, event=published_event).status
        == "going"
    )


# ---------------------------------------------------------------------------
# 6. Follow endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_requires_login(client, approved_organizer):
    """Unauthenticated POST to follow endpoint redirects to login."""
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_follow_creates_row(client, approved_user, approved_organizer):
    """Approved user POST to follow creates Follow row."""
    client.force_login(approved_user)
    response = client.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 200
    assert Follow.objects.filter(
        user=approved_user, profile=approved_organizer
    ).exists()


@pytest.mark.django_db
def test_follow_toggle_unfollow(client, approved_user, approved_organizer):
    """Two POSTs to follow endpoint: first follows, second unfollows."""
    client.force_login(approved_user)
    client.post(f"/o/{approved_organizer.slug}/follow/")
    assert Follow.objects.filter(
        user=approved_user, profile=approved_organizer
    ).exists()
    client.post(f"/o/{approved_organizer.slug}/follow/")
    assert not Follow.objects.filter(
        user=approved_user, profile=approved_organizer
    ).exists()


@pytest.mark.django_db
def test_follow_nonexistent_organizer_returns_404(client, approved_user):
    """POST to a non-existent organizer slug returns 404."""
    client.force_login(approved_user)
    response = client.post("/o/nonexistent-slug/follow/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 7. CSRF enforcement
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_attend_no_csrf_returns_403(approved_user, published_event):
    """Attend POST without CSRF token returns 403 (Django CSRF middleware)."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(approved_user)
    org_slug = published_event.organizer.slug
    event_slug = published_event.slug
    response = c.post(f"/events/{org_slug}/{event_slug}/attend/", {"status": "going"})
    assert response.status_code == 403


@pytest.mark.django_db
def test_follow_no_csrf_returns_403(approved_user, approved_organizer):
    """Follow POST without CSRF token returns 403 (Django CSRF middleware)."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(approved_user)
    response = c.post(f"/o/{approved_organizer.slug}/follow/")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 8. Kill-switches
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_map_enabled_false_hides_map(client, staff_user, published_event):
    """MAP_ENABLED=False FeatureFlag: response does not contain the map div."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(key="MAP_ENABLED", defaults={"enabled": False})
    cache.clear()
    client.force_login(staff_user)
    try:
        response = client.get("/events/")
        assert b'id="map"' not in response.content
    finally:
        FeatureFlag.objects.filter(key="MAP_ENABLED").delete()
        cache.clear()


@pytest.mark.django_db
@pytest.mark.skip(
    reason=(
        "INVITES_ENABLED kill-switch is part of the vouched-signup path (kb-m69.7). "
        "OpenSignupAdapter (kb-m69.5) does not check INVITES_ENABLED flag."
    )
)
def test_invites_enabled_false_rejects_signup(client, valid_invite_code):
    """INVITES_ENABLED=False FeatureFlag: even a valid code does not open signup."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    FeatureFlag.objects.update_or_create(
        key="INVITES_ENABLED", defaults={"enabled": False}
    )
    cache.clear()
    try:
        response = client.get(f"/accounts/signup/?code={valid_invite_code.code}")
        content = response.content.decode()
        assert 'type="password"' not in content
    finally:
        FeatureFlag.objects.filter(key="INVITES_ENABLED").delete()
        cache.clear()
