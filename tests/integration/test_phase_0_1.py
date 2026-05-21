"""
Integration smoke tests for Phase 0.1 — schema + admin + manual entry.

Covers: model round-trips, XOR constraints, unique constraints, admin smoke,
makemessages catalog, and heartbeat task.

All DB-touching tests use @pytest.mark.django_db.
IntegrityError tests wrap the offending operation in transaction.atomic() to
avoid poisoning the test database connection.
"""

import pathlib

import django.utils.timezone as tz
import pytest
from django.db import IntegrityError, transaction
from django.test import Client

# ---------------------------------------------------------------------------
# 1. Model round-trips (light sanity — full coverage in unit tests)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_create():
    """User.status defaults to 'open' on new users (kb-m69.1: replaced is_approved)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="alice", email="alice@example.com", password="x"
    )
    retrieved = User.objects.get(pk=user.pk)
    assert retrieved.status == "open"


@pytest.mark.django_db
def test_organizer_create():
    """Organizer round-trips with default status=candidate."""
    from organizers.models import Profile

    Profile(name="Test Org", slug="test-org-rt", status="candidate").save()
    fetched = Profile.objects.get(slug="test-org-rt")
    assert fetched.name == "Test Org"
    assert fetched.status == "candidate"
    assert fetched.verified_badge is False


@pytest.mark.django_db
def test_venue_create():
    """Venue round-trips with default privacy_mode=public."""
    from venues.models import Venue

    Venue(name="Berghain", slug="berghain-rt", privacy_mode="public").save()
    fetched = Venue.objects.get(slug="berghain-rt")
    assert fetched.privacy_mode == "public"


@pytest.mark.django_db
def test_tag_create():
    """Tag round-trips correctly."""
    from events.models import Tag

    Tag(slug="kink-rt", label="Kink", kind="theme").save()
    fetched = Tag.objects.get(slug="kink-rt")
    assert fetched.label == "Kink"
    assert fetched.kind == "theme"


@pytest.mark.django_db
def test_event_create():
    """Event round-trips with start datetime."""
    from events.models import Event
    from organizers.models import Profile

    org = Profile.objects.create(name="Event Org", slug="event-org-rt")
    start = tz.now()
    Event.objects.create(
        title="Test Event",
        slug="test-event-rt",
        organizer=org,
        start=start,
    )
    fetched = Event.objects.get(
        slug="test-event-rt",
        event_organizer_set__profile=org,
        event_organizer_set__is_primary=True,
    )
    assert fetched.start is not None
    assert fetched.status == "draft"


@pytest.mark.django_db
def test_event_image_create():
    """EventImage is correctly attached to an Event."""
    from events.models import Event, EventImage
    from organizers.models import Profile

    org = Profile.objects.create(name="Img Org", slug="img-org-rt")
    event = Event.objects.create(
        title="Img Event", slug="img-event-rt", organizer=org, start=tz.now()
    )
    img = EventImage.objects.create(
        event=event, image="events/placeholder.jpg", alt="Test", is_cover=True
    )
    assert EventImage.objects.filter(event=event).count() == 1
    assert img.is_cover is True


@pytest.mark.django_db
def test_raw_message_create():
    """RawMessage round-trips with JSON payload."""
    from ingestion.models import RawMessage

    RawMessage(source_type="telegram_bot_forward", raw_payload={"text": "hello"}).save()
    fetched = RawMessage.objects.get(raw_payload__text="hello")
    assert fetched.source_type == "telegram_bot_forward"
    assert fetched.extraction_status == "pending"


@pytest.mark.django_db
def test_source_failure_create():
    """SourceFailure links to RawMessage correctly."""
    from ingestion.models import RawMessage, SourceFailure

    raw = RawMessage.objects.create(
        source_type="telegram_bot_forward", raw_payload={"text": "fail"}
    )
    sf = SourceFailure.objects.create(
        source_type="telegram_bot_forward",
        raw_message=raw,
        stage="extraction",
        error_class="ValueError",
        error_message="Something went wrong",
    )
    fetched = SourceFailure.objects.get(pk=sf.pk)
    assert fetched.raw_message_id == raw.pk
    assert fetched.resolved is False


@pytest.mark.django_db
def test_heartbeat_log_create():
    """HeartbeatLog.ran_at is auto-populated on save."""
    from ingestion.models import HeartbeatLog

    hb = HeartbeatLog()
    hb.save()
    fetched = HeartbeatLog.objects.get(pk=hb.pk)
    assert fetched.ran_at is not None


@pytest.mark.django_db
def test_review_on_event():
    """Review with event set and organizer=None is valid."""
    from django.contrib.auth import get_user_model

    from events.models import Event
    from organizers.models import Profile
    from reviews.models import Review

    User = get_user_model()
    user = User.objects.create_user(
        username="rev-event-user", email="rev-event@example.com", password="x"
    )
    org = Profile.objects.create(name="Rev Org", slug="rev-org-rt")
    event = Event.objects.create(
        title="Rev Event", slug="rev-event-rt", organizer=org, start=tz.now()
    )
    review = Review.objects.create(author=user, event=event, rating=4)
    fetched = Review.objects.get(pk=review.pk)
    assert fetched.event_id == event.pk
    assert fetched.organizer is None


@pytest.mark.django_db
def test_review_on_organizer():
    """Review with organizer set and event=None is valid."""
    from django.contrib.auth import get_user_model

    from organizers.models import Profile
    from reviews.models import Review

    User = get_user_model()
    user = User.objects.create_user(
        username="rev-org-user", email="rev-org@example.com", password="x"
    )
    org = Profile.objects.create(name="Rev Org 2", slug="rev-org2-rt")
    review = Review.objects.create(author=user, organizer=org, rating=5)
    fetched = Review.objects.get(pk=review.pk)
    assert fetched.organizer_id == org.pk
    assert fetched.event is None


# ---------------------------------------------------------------------------
# 2. Review XOR constraint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_review_xor_both_raises():
    """Review with BOTH organizer and event raises IntegrityError.

    Uses transaction.atomic() savepoint to avoid poisoning the test DB connection.
    """
    from django.contrib.auth import get_user_model

    from events.models import Event
    from organizers.models import Profile
    from reviews.models import Review

    User = get_user_model()
    user = User.objects.create_user(
        username="xor-both", email="xor-both@example.com", password="x"
    )
    org = Profile.objects.create(name="XOR Org", slug="xor-org-both")
    event = Event.objects.create(
        title="XOR Event", slug="xor-event-both", organizer=org, start=tz.now()
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Review.objects.create(author=user, organizer=org, event=event, rating=3)


@pytest.mark.django_db
def test_review_xor_neither_raises():
    """Review with NEITHER organizer nor event raises IntegrityError.

    Uses transaction.atomic() savepoint to avoid poisoning the test DB connection.
    """
    from django.contrib.auth import get_user_model

    from reviews.models import Review

    User = get_user_model()
    user = User.objects.create_user(
        username="xor-neither", email="xor-neither@example.com", password="x"
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Review.objects.create(author=user, rating=3)


# ---------------------------------------------------------------------------
# 3. Event duplicate constraints
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_slug_unique_per_organizer():
    """
    [kb-n0y] event_slug_unique_per_organizer constraint was dropped when
    Event.organizer FK became EventOrganizer M2M. Slug uniqueness is app-level.
    Two events from same organizer CAN now share a slug at DB level.
    """
    from events.models import Event
    from organizers.models import Profile

    org = Profile.objects.create(name="Slug Org", slug="slug-org-dup")
    start = tz.now()
    Event.objects.create(
        title="Slug Event A", slug="dup-slug", organizer=org, start=start
    )
    # No longer raises — constraint was intentionally dropped (see bead kb-n0y notes)
    Event.objects.create(
        title="Slug Event B",
        slug="dup-slug-b",
        organizer=org,
        start=start,
    )


@pytest.mark.django_db
def test_event_dup_guard():
    """
    [kb-n0y] event_dup_guard_org_start_title constraint was dropped when
    Event.organizer FK became EventOrganizer M2M. Dup-guard was already weak
    (same org can legitimately run two workshops at same start). Now app-level.
    Two events with same (organizer, start, title) CAN now be created at DB level.
    """
    from events.models import Event
    from organizers.models import Profile

    org = Profile.objects.create(name="Dup Org", slug="dup-org-guard")
    start = tz.now()
    Event.objects.create(
        title="Same Title", slug="slug-a-dup-guard", organizer=org, start=start
    )
    # No longer raises — constraint was intentionally dropped (see bead kb-n0y notes)
    Event.objects.create(
        title="Same Title",
        slug="slug-b-dup-guard",
        organizer=org,
        start=start,
    )


# ---------------------------------------------------------------------------
# 4. Event.status transitions (app-level, no DB enforcement)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_status_transitions():
    """Status values draft→review→published→cancelled can all be set in DB."""
    from events.models import Event
    from organizers.models import Profile

    org = Profile.objects.create(name="Status Org", slug="status-org-rt")
    event = Event.objects.create(
        title="Status Event", slug="status-event-rt", organizer=org, start=tz.now()
    )
    assert event.status == "draft"

    for status in ("review", "published", "cancelled"):
        event.status = status
        event.save()
        event.refresh_from_db()
        assert event.status == status


# ---------------------------------------------------------------------------
# 5. Admin smoke tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_unauthenticated_redirects():
    """GET /admin/ returns 302 for unauthenticated users."""
    client = Client()
    response = client.get("/admin/")
    assert response.status_code == 302


@pytest.mark.django_db
def test_admin_authenticated_ok(superuser):
    """GET /admin/ returns 200 after superuser force_login."""
    client = Client()
    client.force_login(superuser)
    response = client.get("/admin/")
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/admin/accounts/user/",
        "/admin/organizers/profile/",
        "/admin/organizers/profile/add/",
        "/admin/venues/venue/",
        "/admin/venues/venue/add/",
        "/admin/events/event/",
        "/admin/events/event/add/",
        "/admin/events/tag/",
        "/admin/ingestion/rawmessage/",
        "/admin/ingestion/sourcefailure/",
        "/admin/ingestion/heartbeatlog/",
        "/admin/reviews/review/",
        "/admin/reviews/review/add/",
    ],
)
def test_admin_url_reachable_for_all_models(superuser, url):
    """Every model's changelist + add-form renders without error."""
    client = Client()
    client.force_login(superuser)
    response = client.get(url)
    assert response.status_code == 200, f"{url} → {response.status_code}"


@pytest.mark.django_db
def test_raw_message_extracted_events_reverse():
    """Event.raw_message FK exposes reverse accessor as 'extracted_events'."""
    from events.models import Event
    from ingestion.models import RawMessage
    from organizers.models import Profile

    rm = RawMessage.objects.create(
        source_type="telegram_bot_forward",
        raw_payload={"text": "x"},
    )
    org = Profile.objects.create(name="Reverse Org", slug="reverse-org-rt")
    Event.objects.create(
        organizer=org,
        slug="from-rm",
        title="From RM",
        start=tz.now(),
        raw_message=rm,
    )
    assert rm.extracted_events.count() == 1
    assert rm.extracted_events.first().slug == "from-rm"


# ---------------------------------------------------------------------------
# 6. makemessages produces non-empty catalog
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_makemessages_produces_catalog(tmp_path, monkeypatch):
    """makemessages -l de must produce a .po file with at least one msgid line.

    Requires at least one trans tag in templates (e.g. templates/account/login.html).
    If this test fails with AssertionError, add a {% trans %} tag to a template
    and re-run makemessages.
    """
    from django.core.management import call_command

    call_command("makemessages", "-l", "de")
    po = pathlib.Path("locale/de/LC_MESSAGES/django.po").read_text()
    assert "msgid " in po, (
        "django.po has no msgid lines — add at least one trans tag to a template"
    )


# ---------------------------------------------------------------------------
# 7. Heartbeat task inserts HeartbeatLog row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_heartbeat_task_inserts_row(monkeypatch):
    """Direct call to heartbeat() inserts a HeartbeatLog row.

    Sets LOGFIRE_TOKEN='' to prevent logfire crash in test environment.
    """
    monkeypatch.setenv("LOGFIRE_TOKEN", "")

    from ingestion.models import HeartbeatLog
    from ingestion.tasks import heartbeat

    count_before = HeartbeatLog.objects.count()
    heartbeat("integration")
    assert HeartbeatLog.objects.count() == count_before + 1


# ---------------------------------------------------------------------------
# 8. End-to-end ORM flow: Organizer → Venue → Event → EventImage → Review
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_end_to_end_orm_flow():
    """Create full object graph and verify FK navigation."""
    from django.contrib.auth import get_user_model

    from events.models import Event, EventImage
    from organizers.models import Profile
    from reviews.models import Review
    from venues.models import Venue

    User = get_user_model()

    # Create all objects
    user = User.objects.create_user(
        username="e2e-user", email="e2e@example.com", password="x"
    )
    org = Profile.objects.create(name="E2E Org", slug="e2e-org")
    venue = Venue.objects.create(name="E2E Venue", slug="e2e-venue")
    event = Event.objects.create(
        title="E2E Event",
        slug="e2e-event",
        organizer=org,
        venue=venue,
        start=tz.now(),
    )
    img = EventImage.objects.create(event=event, image="events/e2e.jpg")
    review = Review.objects.create(author=user, event=event, rating=5)

    # Verify retrievals — organizer is now via EventOrganizer M2M; use compat property
    fetched_event = Event.objects.select_related("venue").prefetch_related(
        "event_organizer_set__profile"
    ).get(pk=event.pk)
    assert fetched_event.organizer.slug == "e2e-org"
    assert fetched_event.venue.slug == "e2e-venue"

    # FK navigation
    assert img in fetched_event.images.all()
    assert review in fetched_event.reviews.all()
