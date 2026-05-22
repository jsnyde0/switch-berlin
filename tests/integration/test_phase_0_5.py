"""
Integration tests for Phase 0.5 — public read, legal gate, ratings, flags.
Covers: docs/plans/2026-04-17-phase-0.5-public-legal-design.md §Test plan
"""

from datetime import timedelta

import django.utils.timezone as tz
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, override_settings

from events.models import Event
from organizers.models import Follow, Profile
from reviews.models import Flag, Review

User = get_user_model()

# ---------------------------------------------------------------------------
# Fixtures local to this test file
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    """Vouched non-staff user (kb-m69.1: status replaces is_approved)."""
    user = User.objects.create_user(
        username="e2e_approved",
        email="e2e_approved@example.com",
        password="x",
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def feature_flag_public_read_on(db):
    """Ensure PUBLIC_READ_ENABLED=True in DB and clear cache."""
    from a_core.models import FeatureFlag

    FeatureFlag.objects.get_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
    )
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=True)
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def feature_flag_public_read_off(db):
    """Set PUBLIC_READ_ENABLED=False in DB and clear cache; restore after test."""
    from a_core.models import FeatureFlag

    FeatureFlag.objects.get_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=False)
    cache.clear()
    yield
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=True)
    cache.clear()


@pytest.fixture
def feature_flag_ratings_off(db):
    """Set RATINGS_ENABLED=False and clear cache; restore after test."""
    from a_core.models import FeatureFlag

    FeatureFlag.objects.get_or_create(key="RATINGS_ENABLED", defaults={"enabled": True})
    FeatureFlag.objects.filter(key="RATINGS_ENABLED").update(enabled=False)
    cache.clear()
    yield
    FeatureFlag.objects.filter(key="RATINGS_ENABLED").update(enabled=True)
    cache.clear()


# ---------------------------------------------------------------------------
# Group 1: Legal pages return 200 and are linked from footer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_impressum_returns_200(client):
    """GET /impressum/ anonymous -> 200."""
    response = client.get("/impressum/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_privacy_returns_200(client):
    """GET /privacy/ anonymous -> 200."""
    response = client.get("/privacy/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_terms_returns_200(client):
    """GET /terms/ anonymous -> 200."""
    response = client.get("/terms/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_footer_has_legal_links(client, feature_flag_public_read_on):
    """GET /impressum/ -> footer (rendered on all _default.html-extending pages)
    contains links to /impressum/, /privacy/, and /terms/.

    NOTE: The events list (/events/) extends _base.html directly and does not
    include the cotton footer component. Legal-page links are confirmed present
    on pages that use the _default.html layout (impressum, privacy, terms,
    takedown). This is the canonical check that the footer rewrite succeeded.
    """
    response = client.get("/impressum/")
    assert response.status_code == 200
    assert b"/impressum/" in response.content
    assert b"/privacy/" in response.content
    assert b"/terms/" in response.content


@pytest.mark.django_db
def test_footer_no_placeholders(client, feature_flag_public_read_on):
    """GET /impressum/ -> footer does NOT contain placeholder 'About us' or 'Jobs'
    text."""
    response = client.get("/impressum/")
    assert response.status_code == 200
    assert b"About us" not in response.content
    assert b"Jobs" not in response.content


# ---------------------------------------------------------------------------
# Group 2: Age gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_age_gate_redirects_anon(client, published_event, feature_flag_public_read_on):
    """GET /events/ anon, no cookie, PUBLIC_READ_ENABLED=True -> 302 to /age-check/."""
    response = client.get("/events/", HTTP_ACCEPT="text/html,application/xhtml+xml")
    assert response.status_code == 302
    assert "/age-check/" in response["Location"]


@pytest.mark.django_db
def test_age_gate_passes_with_cookie(
    client, published_event, feature_flag_public_read_on
):
    """GET /events/ with age_gate=ok cookie -> 200 (age gate passes)."""
    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_age_gate_bypasses_for_googlebot(
    client, published_event, feature_flag_public_read_on
):
    """Googlebot UA bypasses the age gate (no redirect)."""
    googlebot_ua = (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )
    response = client.get(
        "/events/",
        HTTP_USER_AGENT=googlebot_ua,
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_age_gate_bypassed_when_public_read_off(client, feature_flag_public_read_off):
    """PUBLIC_READ_ENABLED=False -> anon GET /events/ redirects to login, NOT
    age-check."""
    response = client.get("/events/", HTTP_ACCEPT="text/html,application/xhtml+xml")
    assert response.status_code == 302
    location = response["Location"]
    assert "/accounts/login/" in location, (
        f"Expected /accounts/login/ redirect, got: {location}"
    )
    assert "/age-check/" not in location


@pytest.mark.django_db
def test_age_check_post_sets_cookie(client):
    """POST /age-check/ with confirm=yes -> redirects to next and sets age_gate=ok
    cookie."""
    response = client.post(
        "/age-check/",
        {"confirm": "yes", "next": "/"},
        HTTP_ACCEPT="text/html,application/xhtml+xml",
    )
    # Should redirect (302) to /
    assert response.status_code == 302
    assert response["Location"] == "/"
    # Check the Set-Cookie response includes age_gate=ok
    assert "age_gate" in response.cookies
    assert response.cookies["age_gate"].value == "ok"


# ---------------------------------------------------------------------------
# Group 3: Takedown form
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_takedown_creates_anonymous_flag(client, published_event):
    """POST /takedown/ as anon with resolvable event_url -> creates Flag with
    reporter=None."""
    from django.urls import reverse

    event_url = reverse(
        "event-detail",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    response = client.post(
        "/takedown/",
        {
            "event_url": f"http://testserver{event_url}",
            "reason": "spam",
            "body": "This is spam.",
            "contact_email": "reporter@example.com",
            "good_faith_confirmed": True,
        },
    )
    assert response.status_code == 200
    assert Flag.objects.filter(reporter=None).count() == 1


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_takedown_rate_limit(client, published_event):
    """POST /takedown/ 11 times from same IP -> 11th returns 429 (rate 10/h)."""
    from django.urls import reverse

    cache.clear()

    event_url = reverse(
        "event-detail",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    full_url = f"http://testserver{event_url}"

    # First 10 succeed (rate bumped to 10/h)
    for _ in range(10):
        resp = client.post(
            "/takedown/",
            {
                "event_url": full_url,
                "reason": "spam",
                "body": "test",
                "contact_email": "",
            },
            REMOTE_ADDR="192.0.2.99",
        )
        assert resp.status_code == 200

    # 11th must be blocked
    resp = client.post(
        "/takedown/",
        {
            "event_url": full_url,
            "reason": "spam",
            "body": "test",
            "contact_email": "",
        },
        REMOTE_ADDR="192.0.2.99",
    )
    assert resp.status_code == 429, f"Expected 429, got {resp.status_code}"
    cache.clear()


@pytest.mark.django_db
def test_anonymous_flag_does_not_trigger_autohide(published_event):
    """3 anonymous flags (reporter=None) on one event -> Event.hidden stays False."""
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    published_event.refresh_from_db()
    assert published_event.hidden is False


# ---------------------------------------------------------------------------
# Group 4: Privacy enforcement from 0.4 still holds on public routes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_private_venue_blurred_for_anon_public(
    client, published_event, feature_flag_public_read_on
):
    """Anonymous user with age_gate cookie: private venue in GeoJSON has
    blur_radius_m set."""
    from venues.models import Venue

    private_venue = Venue.objects.create(
        name="Secret Club",
        slug="secret-club",
        privacy_mode="private",
        latitude="52.5200",
        longitude="13.4050",
    )
    published_event.venue = private_venue
    published_event.save()

    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200

    markers_geojson = response.context["markers_geojson"]
    feature = next(
        (
            f
            for f in markers_geojson["features"]
            if f["properties"].get("org_slug") == published_event.organizer.slug
            and f["properties"].get("event_slug") == published_event.slug
        ),
        None,
    )
    assert feature is not None, "Event feature not found in markers_geojson"
    assert feature["properties"]["blur_radius_m"] is not None, (
        "Private venue for anonymous user must have blur_radius_m set"
    )


# ---------------------------------------------------------------------------
# Group 5: Auto-hide
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_autohide_activates_on_auth_flags(db, published_event):
    """3 authenticated Flag rows on one event -> event.hidden == True."""
    from django.contrib.auth import get_user_model
    from django.test import Client
    from django.urls import reverse

    User = get_user_model()

    users = []
    for i in range(3):
        u = User.objects.create_user(
            username=f"flag_user_{i}",
            email=f"flag_user_{i}@example.com",
            password="x",
        )
        u.status = "vouched"
        u.save()
        users.append(u)

    url = reverse("flag-target")
    for u in users:
        c = Client()
        c.force_login(u)
        c.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "reason": "spam",
            },
        )

    published_event.refresh_from_db()
    assert published_event.hidden is True


@pytest.mark.django_db
def test_hidden_event_absent_from_list(
    client, approved_organizer, feature_flag_public_read_on
):
    """After auto-hide, GET /events/ -> hidden event title not in response."""
    Event.objects.create(
        title="Hidden Rave Night",
        slug="hidden-rave-night",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=5),
        hidden=True,
    )
    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200
    assert b"Hidden Rave Night" not in response.content


@pytest.mark.django_db
def test_anon_flags_dont_trigger_autohide(published_event):
    """3 anonymous flags (reporter=None) -> Event.hidden stays False."""
    for _ in range(3):
        Flag.objects.create(reporter=None, event=published_event, reason="spam")
    published_event.refresh_from_db()
    assert published_event.hidden is False


# ---------------------------------------------------------------------------
# Group 6: Review uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_review_updates_not_creates(approved_user, approved_organizer):
    """Two reviews by same author for same organizer -> only 1 row in DB
    (update_or_create)."""
    client = Client()
    client.force_login(approved_user)

    url = "/reviews/submit/"
    client.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(approved_organizer.pk),
            "rating": "4",
            "body": "First review",
        },
    )
    client.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(approved_organizer.pk),
            "rating": "5",
            "body": "Updated review",
        },
    )
    count = Review.objects.filter(
        author=approved_user, organizer=approved_organizer
    ).count()
    assert count == 1


@pytest.mark.django_db
def test_rating_count_correct_after_update(approved_user, approved_organizer):
    """After 2 submissions by same user for same organizer -> organizer.rating_count
    == 1."""
    client = Client()
    client.force_login(approved_user)

    url = "/reviews/submit/"
    client.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(approved_organizer.pk),
            "rating": "3",
            "body": "",
        },
    )
    client.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(approved_organizer.pk),
            "rating": "4",
            "body": "",
        },
    )
    approved_organizer.refresh_from_db()
    assert approved_organizer.rating_count == 1


# ---------------------------------------------------------------------------
# Group 7: Organizer rating display
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rating_hidden_below_threshold(
    client, approved_organizer, feature_flag_public_read_on
):
    """2 reviews -> organizer profile does NOT show rating display (below
    MIN_RATINGS_FOR_DISPLAY=3)."""
    for i in range(2):
        u = User.objects.create_user(
            username=f"reviewer_{i}",
            email=f"reviewer_{i}@example.com",
            password="x",
        )
        Review.objects.create(author=u, organizer=approved_organizer, rating=4)
    # Set rating_count directly as submit_review would
    approved_organizer.rating_count = 2
    approved_organizer.avg_rating = 4.0
    approved_organizer.save()

    client.cookies["age_gate"] = "ok"
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    # show_rating is False below threshold — no rating display
    assert response.context["show_rating"] is False
    # Content should not show the avg_rating display
    assert b"/ 5" not in response.content


@pytest.mark.django_db
def test_rating_shown_at_threshold(
    client, approved_organizer, feature_flag_public_read_on
):
    """3 reviews (at threshold) -> organizer profile shows rating display."""
    for i in range(3):
        u = User.objects.create_user(
            username=f"rater_{i}",
            email=f"rater_{i}@example.com",
            password="x",
        )
        Review.objects.create(author=u, organizer=approved_organizer, rating=4)
    approved_organizer.rating_count = 3
    approved_organizer.avg_rating = 4.0
    approved_organizer.save()

    client.cookies["age_gate"] = "ok"
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    assert response.context["show_rating"] is True
    assert b"/ 5" in response.content


# ---------------------------------------------------------------------------
# Group 8: Event rating collection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_rating_creates_review(approved_user, published_event):
    """POST /reviews/submit/ with target_type=event -> Review row with event FK.

    An Attendance(status='went') record is required by the authorship gate
    added in feat(reviews): step-7b. Without it the view returns 429.
    """
    from events.models import Attendance

    Attendance.objects.create(user=approved_user, event=published_event, status="went")

    c = Client()
    c.force_login(approved_user)
    c.post(
        "/reviews/submit/",
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "rating": "4",
            "body": "Great event",
        },
    )
    assert Review.objects.filter(event=published_event).count() == 1


@pytest.mark.django_db
def test_event_detail_no_rating_display(
    client, published_event, feature_flag_public_read_on
):
    """Event detail page does NOT display any avg_rating or star rating for the
    event."""
    client.cookies["age_gate"] = "ok"
    response = client.get(
        f"/events/{published_event.organizer.slug}/{published_event.slug}/"
    )
    assert response.status_code == 200
    # Event rating is collected but not displayed in Phase 0.5
    assert b"avg_rating" not in response.content


# ---------------------------------------------------------------------------
# Group 9: Feature flag — RATINGS_ENABLED=False hides form
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ratings_flag_off_hides_form(
    client,
    approved_user,
    approved_organizer,
    feature_flag_public_read_on,
    feature_flag_ratings_off,
):
    """RATINGS_ENABLED=False -> organizer profile page does not contain the
    review-submit form."""
    client.force_login(approved_user)
    response = client.get(f"/p/{approved_organizer.slug}/")
    assert response.status_code == 200
    # The rating form posts to /reviews/submit/ — should not be present
    assert b"review-submit" not in response.content


# ---------------------------------------------------------------------------
# Group 10: Nightly aggregate task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recompute_aggregates_runs(approved_user, approved_organizer, published_event):
    """recompute_aggregates() updates follower_count to match Follow count."""
    from ingestion.tasks_flags import recompute_aggregates

    Follow.objects.create(user=approved_user, profile=approved_organizer)

    recompute_aggregates()

    approved_organizer.refresh_from_db()
    actual_count = Follow.objects.filter(profile=approved_organizer).count()
    assert approved_organizer.follower_count == actual_count


# ---------------------------------------------------------------------------
# Group 11: Flag model CheckConstraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_constraint_no_target():
    """Flag with all-null FKs (no target) violates the CheckConstraint ->
    IntegrityError.

    The CheckConstraint 'flag_targets_exactly_one' requires exactly one of
    organizer/event/review to be non-null. A Flag with all three null therefore
    violates the constraint and raises IntegrityError.
    """
    with pytest.raises(IntegrityError):
        Flag.objects.create(reporter=None, reason="spam")


@pytest.mark.django_db
def test_flag_constraint_two_targets(
    approved_user, approved_organizer, published_event
):
    """Flag with two targets set -> IntegrityError (violates exactly-one constraint)."""
    with pytest.raises(IntegrityError):
        Flag.objects.create(
            reporter=approved_user,
            organizer=approved_organizer,
            event=published_event,
            reason="spam",
        )


# ---------------------------------------------------------------------------
# Group 12: Rollback — PUBLIC_READ_ENABLED=False
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rollback_login_wall_reenabled(client, feature_flag_public_read_off):
    """PUBLIC_READ_ENABLED=False -> anon GET /events/ redirects to /accounts/login/,
    not age-check."""
    response = client.get("/events/", HTTP_ACCEPT="text/html,application/xhtml+xml")
    assert response.status_code == 302
    location = response["Location"]
    assert "/accounts/login/" in location
    assert "/age-check/" not in location


@pytest.mark.django_db
def test_rollback_robots_txt(client, feature_flag_public_read_off):
    """PUBLIC_READ_ENABLED=False -> GET /robots.txt returns 'Disallow: /'."""
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert b"Disallow: /" in response.content


@pytest.mark.django_db
def test_rollback_x_robots_header(client, staff_user, feature_flag_public_read_off):
    """PUBLIC_READ_ENABLED=False -> GET /events/ as staff has X-Robots-Tag header."""
    client.force_login(staff_user)
    response = client.get("/events/")
    assert response.status_code == 200
    assert "X-Robots-Tag" in response, (
        "X-Robots-Tag header should be present when PUBLIC_READ_ENABLED=False"
    )
    assert response["X-Robots-Tag"] == "noindex, nofollow, noarchive"


@pytest.mark.django_db
def test_legal_pages_reachable_in_rollback(client, feature_flag_public_read_off):
    """PUBLIC_READ_ENABLED=False -> /impressum/ still returns 200 (always public)."""
    response = client.get("/impressum/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Group 13: Slug migration verification
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_slug_drawer_url_works(client, published_event, feature_flag_public_read_on):
    """GET /events/<org_slug>/<event_slug>/drawer/ with slug-based URL -> 200."""
    client.cookies["age_gate"] = "ok"
    response = client.get(
        f"/events/{published_event.organizer.slug}/{published_event.slug}/drawer/"
    )
    assert response.status_code == 200


@pytest.mark.django_db
def test_pk_drawer_url_gone(client, published_event, feature_flag_public_read_on):
    """GET /events/<int:pk>/drawer/ (PK-based URL) -> 404 (route no longer exists)."""
    client.cookies["age_gate"] = "ok"
    response = client.get(f"/events/{published_event.pk}/drawer/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_geojson_no_event_id(client, published_event, feature_flag_public_read_on):
    """GET /events/ -> markers_geojson features have no 'event_id' property."""
    from venues.models import Venue

    venue = Venue.objects.create(
        name="Test Venue",
        slug="test-venue",
        latitude="52.5200",
        longitude="13.4050",
    )
    published_event.venue = venue
    published_event.save()

    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200

    markers_geojson = response.context["markers_geojson"]
    for feature in markers_geojson["features"]:
        assert "event_id" not in feature["properties"], (
            f"Feature has 'event_id' which should have been removed:"
            f" {feature['properties']}"
        )


@pytest.mark.django_db
def test_geojson_has_slug_fields(client, published_event, feature_flag_public_read_on):
    """GET /events/ -> each marker feature has 'org_slug' and 'event_slug'
    properties."""
    from venues.models import Venue

    venue = Venue.objects.create(
        name="Test Venue 2",
        slug="test-venue-2",
        latitude="52.5100",
        longitude="13.4100",
    )
    published_event.venue = venue
    published_event.save()

    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200

    markers_geojson = response.context["markers_geojson"]
    assert len(markers_geojson["features"]) > 0, "Expected at least one marker feature"

    for feature in markers_geojson["features"]:
        assert "org_slug" in feature["properties"], (
            "Missing 'org_slug' in feature properties"
        )
        assert "event_slug" in feature["properties"], (
            "Missing 'event_slug' in feature properties"
        )


# ---------------------------------------------------------------------------
# Group 14: Hidden filter .visible()
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hidden_event_absent_from_list_visible_manager(
    client, approved_organizer, feature_flag_public_read_on
):
    """Hidden event (hidden=True) is absent from /events/ list via .visible()."""
    hidden_event = Event.objects.create(
        title="Should Not Appear",
        slug="should-not-appear",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=3),
        hidden=True,
    )
    client.cookies["age_gate"] = "ok"
    response = client.get("/events/")
    assert response.status_code == 200
    event_pks = [e.pk for e in response.context["page_obj"]]
    assert hidden_event.pk not in event_pks


@pytest.mark.django_db
def test_hidden_organizer_returns_404(client, feature_flag_public_read_on):
    """Hidden organizer (hidden=True) returns 404 on their profile page."""
    hidden_org = Profile.objects.create(
        name="Hidden Organizer",
        slug="hidden-organizer",
        status="approved",
        hidden=True,
    )
    client.cookies["age_gate"] = "ok"
    response = client.get(f"/p/{hidden_org.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_hidden_event_drawer_404(
    client, approved_organizer, feature_flag_public_read_on
):
    """Hidden event returns 404 on the drawer endpoint."""
    hidden_event = Event.objects.create(
        title="Hidden Drawer Event",
        slug="hidden-drawer-event",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=3),
        hidden=True,
    )
    client.cookies["age_gate"] = "ok"
    response = client.get(
        f"/events/{approved_organizer.slug}/{hidden_event.slug}/drawer/"
    )
    assert response.status_code == 404
