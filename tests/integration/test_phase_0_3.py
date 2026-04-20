"""
Integration tests for Phase 0.3 — login-wall, views, filters, robots.txt.

Test plan items (from design doc):
- View smoke tests: /events, /events/<slug>, /o/<slug> return 200 for staff
- Login-wall: anon GET /events -> 302 to /accounts/login/
- Login-wall: non-staff authenticated user -> 403
- Signup closed: GET /accounts/signup/ -> not a working form (302 or 403)
- Filter correctness: ?tags=X filters queryset (OR semantics)
- Pagination + filter interaction: changing filter resets to page 1
- robots.txt: served disallow-all, no auth required
- X-Robots-Tag: present on all responses
- HTMX partial: HX-Request header returns partial not full HTML shell
"""

from datetime import timedelta

import django.utils.timezone as tz
import pytest

# ---------------------------------------------------------------------------
# Login-wall tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_loginwall_anon_redirects_to_login(client):
    """Anonymous GET /events/ -> 302 redirect to /accounts/login/."""
    response = client.get("/events/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


@pytest.mark.django_db
def test_loginwall_anon_next_param(client):
    """Redirect includes ?next=/events/ so login returns user to intended page."""
    response = client.get("/events/")
    assert "next=" in response["Location"]


@pytest.mark.django_db
def test_loginwall_nonstaff_gets_403(client, regular_user):
    """Authenticated non-staff user receives 403 from login-wall."""
    client.force_login(regular_user)
    response = client.get("/events/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_loginwall_staff_gets_through(client, staff_user, published_event):
    """Staff user can access /events/."""
    client.force_login(staff_user)
    response = client.get("/events/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Signup closed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_signup_closed(client):
    """GET /accounts/signup/ must not return a working form (302 or 403 expected)."""
    response = client.get("/accounts/signup/")
    assert response.status_code in (302, 403), (
        f"Expected 302 or 403 but got {response.status_code} — "
        "signup must be closed via NoSignupAdapter"
    )


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_robots_txt_no_auth_required(client):
    """GET /robots.txt is in PUBLIC_PATHS — anon returns 200."""
    response = client.get("/robots.txt")
    assert response.status_code == 200


@pytest.mark.django_db
def test_robots_txt_disallow_all(client):
    """robots.txt body disallows all crawlers."""
    response = client.get("/robots.txt")
    content = response.content.decode()
    assert "Disallow: /" in content


# ---------------------------------------------------------------------------
# X-Robots-Tag header
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_x_robots_tag_on_login_page(client):
    """X-Robots-Tag header present on the login page itself."""
    response = client.get("/accounts/login/")
    assert "X-Robots-Tag" in response
    assert "noindex" in response["X-Robots-Tag"]


@pytest.mark.django_db
def test_x_robots_tag_on_events_page(client, staff_user, published_event):
    """X-Robots-Tag header present on authenticated page responses."""
    client.force_login(staff_user)
    response = client.get("/events/")
    assert "X-Robots-Tag" in response
    assert "noindex" in response["X-Robots-Tag"]


# ---------------------------------------------------------------------------
# View smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_list_smoke(client, staff_user, published_event):
    """GET /events/ returns 200 for staff user."""
    client.force_login(staff_user)
    response = client.get("/events/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_event_detail_smoke(client, staff_user, published_event):
    """GET /events/<org-slug>/<event-slug>/ returns 200 for staff user with published event."""
    client.force_login(staff_user)
    org_slug = published_event.organizer.slug
    response = client.get(f"/events/{org_slug}/{published_event.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_event_detail_404_for_missing(client, staff_user, approved_organizer):
    """GET /events/<org-slug>/nonexistent/ returns 404."""
    client.force_login(staff_user)
    response = client.get(f"/events/{approved_organizer.slug}/nonexistent-slug/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_organizer_profile_smoke(
    client, staff_user, approved_organizer, published_event
):
    """GET /o/<slug>/ returns 200 for staff user with approved organizer."""
    client.force_login(staff_user)
    response = client.get(f"/o/{approved_organizer.slug}/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_organizer_profile_404_for_missing(client, staff_user):
    """GET /o/nonexistent/ returns 404."""
    client.force_login(staff_user)
    response = client.get("/o/nonexistent-organizer/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Filter correctness — OR semantics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_filter_tags_or_semantics(client, staff_user, approved_organizer):
    """?tags=X,Y returns events tagged with X OR Y (union, not intersection)."""
    from events.models import Event, Tag

    tag_a = Tag.objects.create(slug="tag-a", label="Tag A", kind="theme")
    tag_b = Tag.objects.create(slug="tag-b", label="Tag B", kind="theme")

    future = tz.now() + timedelta(days=5)
    event_a = Event.objects.create(
        title="Event A",
        slug="event-a",
        organizer=approved_organizer,
        status="published",
        start=future,
    )
    event_a.tags.add(tag_a)

    event_b = Event.objects.create(
        title="Event B",
        slug="event-b",
        organizer=approved_organizer,
        status="published",
        start=future + timedelta(hours=1),
    )
    event_b.tags.add(tag_b)

    client.force_login(staff_user)
    response = client.get("/events/?tags=tag-a,tag-b")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Event A" in content
    assert "Event B" in content


@pytest.mark.django_db
def test_filter_unknown_tag_silently_ignored(client, staff_user, published_event):
    """?tags=nonexistent-tag returns 200 without crashing."""
    client.force_login(staff_user)
    response = client.get("/events/?tags=this-tag-does-not-exist")
    assert response.status_code == 200


@pytest.mark.django_db
def test_filter_price_free(client, staff_user, approved_organizer):
    """?price=free returns only free events, excludes paid events."""
    from events.models import Event

    future = tz.now() + timedelta(days=5)
    Event.objects.create(
        title="Free Event",
        slug="free-event",
        organizer=approved_organizer,
        status="published",
        start=future,
        is_free=True,
    )
    Event.objects.create(
        title="Paid Event",
        slug="paid-event",
        organizer=approved_organizer,
        status="published",
        start=future + timedelta(hours=1),
        is_free=False,
        price_min_cents=1500,
    )

    client.force_login(staff_user)
    response = client.get("/events/?price=free")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Free Event" in content
    assert "Paid Event" not in content


@pytest.mark.django_db
def test_filter_bad_date_falls_back_gracefully(client, staff_user, published_event):
    """?from=not-a-date returns 200 (invalid date silently ignored, no crash)."""
    client.force_login(staff_user)
    response = client.get("/events/?from=not-a-date")
    assert response.status_code == 200


@pytest.mark.django_db
def test_filter_bad_page_falls_back_to_1(client, staff_user, published_event):
    """?page=banana returns 200 (invalid page falls back to page 1)."""
    client.force_login(staff_user)
    response = client.get("/events/?page=banana")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Pagination + filter interaction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pagination_preserves_filter_params(client, staff_user, approved_organizer):
    """Pagination links include filter query params.

    Creates 25 published future events (> page size of 20) all tagged with tag-c,
    requests page 2 with ?tags=tag-c, and verifies 200 + the tag param is preserved
    in the rendered pagination HTML.
    """
    from events.models import Event, Tag

    tag = Tag.objects.create(slug="tag-c", label="Tag C", kind="theme")
    future = tz.now() + timedelta(days=1)
    events = []
    for i in range(25):
        e = Event.objects.create(
            title=f"Paginated Event {i}",
            slug=f"paginated-event-{i}",
            organizer=approved_organizer,
            status="published",
            start=future + timedelta(hours=i),
        )
        e.tags.add(tag)
        events.append(e)

    client.force_login(staff_user)
    # Page 2 with filter — return 200 and contain pagination links preserving tags=tag-c
    response = client.get("/events/?tags=tag-c&page=2")
    assert response.status_code == 200
    content = response.content.decode()
    # Pagination links should reference tags=tag-c
    assert "tags=tag-c" in content


# ---------------------------------------------------------------------------
# HTMX partial rendering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_htmx_partial_response(client, staff_user, published_event):
    """HTMX request (HX-Request header) returns partial, not full HTML shell."""
    client.force_login(staff_user)
    response = client.get("/events/", HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    content = response.content.decode()
    assert "<!DOCTYPE html>" not in content
    assert "<html" not in content
