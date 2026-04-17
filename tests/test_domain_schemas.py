"""
Tests for kb-i45.2: Domain schemas + admin.

Tests are written FIRST (TDD) and are expected to FAIL until implementation is complete.
All five apps: organizers, venues, events, ingestion, reviews.
"""

import pytest
from django.conf import settings


# ---------------------------------------------------------------------------
# INSTALLED_APPS assertions
# ---------------------------------------------------------------------------


def test_domain_apps_in_installed_apps():
    """All 5 domain apps must be in INSTALLED_APPS."""
    required_apps = ["organizers", "venues", "events", "ingestion", "reviews"]
    for app in required_apps:
        assert app in settings.INSTALLED_APPS, (
            f"'{app}' not in INSTALLED_APPS: {settings.INSTALLED_APPS}"
        )


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------


def test_organizer_model_importable():
    from organizers.models import Organizer  # noqa: F401


def test_venue_model_importable():
    from venues.models import Venue  # noqa: F401


def test_event_models_importable():
    from events.models import Event, EventImage, Tag  # noqa: F401


def test_ingestion_models_importable():
    from ingestion.models import HeartbeatLog, RawMessage, SourceFailure  # noqa: F401


def test_review_model_importable():
    from reviews.models import Review  # noqa: F401


# ---------------------------------------------------------------------------
# Organizer model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_create_roundtrip():
    from organizers.models import Organizer

    org = Organizer.objects.create(name="Test Org", slug="test-org")
    fetched = Organizer.objects.get(pk=org.pk)
    assert fetched.name == "Test Org"
    assert fetched.slug == "test-org"
    assert fetched.status == "candidate"
    assert fetched.verified_badge is False
    assert fetched.consent_recorded_at is None
    assert fetched.consent_method == ""
    assert fetched.consent_notes == ""


@pytest.mark.django_db
def test_organizer_slug_is_unique():
    from organizers.models import Organizer
    from django.db import IntegrityError

    Organizer.objects.create(name="Org A", slug="unique-slug")
    with pytest.raises(IntegrityError):
        Organizer.objects.create(name="Org B", slug="unique-slug")


@pytest.mark.django_db
def test_organizer_approved_by_uses_auth_user_model():
    """approved_by FK must point to AUTH_USER_MODEL, not import User directly."""
    from django.contrib.auth import get_user_model
    from organizers.models import Organizer

    User = get_user_model()
    admin_user = User.objects.create_user(
        username="admin_org", email="admin_org@example.com", password="pass"
    )
    org = Organizer.objects.create(name="Approved Org", slug="approved-org")
    org.approved_by = admin_user
    org.save()

    fetched = Organizer.objects.get(pk=org.pk)
    assert fetched.approved_by_id == admin_user.pk


@pytest.mark.django_db
def test_organizer_consent_fields():
    from organizers.models import Organizer
    import django.utils.timezone as tz

    now = tz.now()
    org = Organizer.objects.create(
        name="Consent Org",
        slug="consent-org",
        consent_recorded_at=now,
        consent_method="explicit_opt_in",
        consent_notes="Agreed via form",
    )
    fetched = Organizer.objects.get(pk=org.pk)
    assert fetched.consent_method == "explicit_opt_in"
    assert fetched.consent_notes == "Agreed via form"


# ---------------------------------------------------------------------------
# Venue model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_venue_create_roundtrip():
    from venues.models import Venue

    venue = Venue.objects.create(name="Test Venue", slug="test-venue")
    fetched = Venue.objects.get(pk=venue.pk)
    assert fetched.name == "Test Venue"
    assert fetched.slug == "test-venue"
    assert fetched.privacy_mode == "public"
    assert fetched.blur_radius_m == 250
    assert fetched.latitude is None
    assert fetched.longitude is None


@pytest.mark.django_db
def test_venue_slug_is_unique():
    from venues.models import Venue
    from django.db import IntegrityError

    Venue.objects.create(name="Venue A", slug="venue-slug-unique")
    with pytest.raises(IntegrityError):
        Venue.objects.create(name="Venue B", slug="venue-slug-unique")


@pytest.mark.django_db
def test_venue_geo_fields():
    from venues.models import Venue
    from decimal import Decimal

    venue = Venue.objects.create(
        name="Geo Venue",
        slug="geo-venue",
        latitude=Decimal("52.520008"),
        longitude=Decimal("13.404954"),
    )
    fetched = Venue.objects.get(pk=venue.pk)
    assert fetched.latitude == Decimal("52.520008")
    assert fetched.longitude == Decimal("13.404954")


@pytest.mark.django_db
def test_venue_privacy_mode_neighborhood_blur():
    from venues.models import Venue

    venue = Venue.objects.create(
        name="Blurred Venue",
        slug="blurred-venue",
        privacy_mode="neighborhood_blur",
        blur_radius_m=500,
    )
    fetched = Venue.objects.get(pk=venue.pk)
    assert fetched.privacy_mode == "neighborhood_blur"
    assert fetched.blur_radius_m == 500


# ---------------------------------------------------------------------------
# Tag model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_tag_create_roundtrip():
    from events.models import Tag

    tag = Tag.objects.create(slug="kinky", label="Kinky", kind="theme")
    fetched = Tag.objects.get(pk=tag.pk)
    assert fetched.slug == "kinky"
    assert fetched.label == "Kinky"
    assert fetched.kind == "theme"
    assert fetched.description == ""


@pytest.mark.django_db
def test_tag_slug_is_unique():
    from events.models import Tag
    from django.db import IntegrityError

    Tag.objects.create(slug="unique-tag", label="Tag A", kind="theme")
    with pytest.raises(IntegrityError):
        Tag.objects.create(slug="unique-tag", label="Tag B", kind="format")


# ---------------------------------------------------------------------------
# Event model
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer():
    from organizers.models import Organizer
    return Organizer.objects.create(name="Event Organizer", slug="event-organizer")


@pytest.fixture
def venue():
    from venues.models import Venue
    return Venue.objects.create(name="Event Venue", slug="event-venue")


@pytest.mark.django_db
def test_event_create_roundtrip(organizer):
    from events.models import Event
    import django.utils.timezone as tz

    start = tz.now()
    event = Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=organizer,
        start=start,
    )
    fetched = Event.objects.get(pk=event.pk)
    assert fetched.title == "Test Event"
    assert fetched.slug == "test-event"
    assert fetched.status == "draft"
    assert fetched.is_free is False
    assert fetched.sliding_scale is False
    assert fetched.currency == "EUR"
    assert fetched.raw_message is None


@pytest.mark.django_db
def test_event_slug_unique_per_organizer(organizer):
    """Two events from the same organizer cannot share a slug."""
    from events.models import Event
    from django.db import IntegrityError
    import django.utils.timezone as tz

    start = tz.now()
    Event.objects.create(
        title="Event A", slug="shared-slug", organizer=organizer, start=start
    )
    with pytest.raises(IntegrityError):
        Event.objects.create(
            title="Event B", slug="shared-slug", organizer=organizer, start=start
        )


@pytest.mark.django_db
def test_event_slug_can_repeat_across_organizers(organizer):
    """Two events from different organizers CAN share a slug."""
    from organizers.models import Organizer
    from events.models import Event
    import django.utils.timezone as tz

    other_org = Organizer.objects.create(name="Other Org", slug="other-org")
    start = tz.now()
    Event.objects.create(
        title="Event A", slug="shared-slug-2", organizer=organizer, start=start
    )
    # Should not raise
    Event.objects.create(
        title="Event A", slug="shared-slug-2", organizer=other_org, start=start
    )


@pytest.mark.django_db
def test_event_dup_guard_org_start_title(organizer):
    """Same organizer, start, and title combination is rejected."""
    from events.models import Event
    from django.db import IntegrityError
    import django.utils.timezone as tz

    start = tz.now()
    Event.objects.create(
        title="Duplicate Title", slug="slug-a", organizer=organizer, start=start
    )
    with pytest.raises(IntegrityError):
        Event.objects.create(
            title="Duplicate Title", slug="slug-b", organizer=organizer, start=start
        )


@pytest.mark.django_db
def test_event_with_venue_and_tags(organizer, venue):
    from events.models import Event, Tag
    import django.utils.timezone as tz

    tag = Tag.objects.create(slug="bubble-1", label="Bubble Party", kind="bubble")
    start = tz.now()
    event = Event.objects.create(
        title="Tagged Event",
        slug="tagged-event",
        organizer=organizer,
        venue=venue,
        start=start,
    )
    event.tags.add(tag)

    fetched = Event.objects.get(pk=event.pk)
    assert fetched.venue == venue
    assert tag in fetched.tags.all()


@pytest.mark.django_db
def test_event_raw_message_fk_string_reference(organizer):
    """Event.raw_message uses string FK 'ingestion.RawMessage' (no direct import)."""
    from events.models import Event
    from ingestion.models import RawMessage
    import django.utils.timezone as tz

    raw = RawMessage.objects.create(
        source_type="telegram_bot_forward",
        raw_payload={"text": "hello"},
    )
    start = tz.now()
    event = Event.objects.create(
        title="Event With Raw",
        slug="event-with-raw",
        organizer=organizer,
        start=start,
        raw_message=raw,
    )
    fetched = Event.objects.get(pk=event.pk)
    assert fetched.raw_message_id == raw.pk


# ---------------------------------------------------------------------------
# EventImage model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_image_create(organizer):
    from events.models import Event, EventImage
    import django.utils.timezone as tz

    event = Event.objects.create(
        title="Image Event",
        slug="image-event",
        organizer=organizer,
        start=tz.now(),
    )
    img = EventImage.objects.create(
        event=event,
        image="events/test.jpg",
        alt="Test image",
        is_cover=True,
        order=1,
    )
    fetched = EventImage.objects.get(pk=img.pk)
    assert fetched.is_cover is True
    assert fetched.order == 1
    assert fetched in event.images.all()


# ---------------------------------------------------------------------------
# RawMessage model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_rawmessage_create_roundtrip():
    from ingestion.models import RawMessage

    raw = RawMessage.objects.create(
        source_type="telegram_bot_forward",
        raw_payload={"msg": "test"},
        text="Hello world",
    )
    fetched = RawMessage.objects.get(pk=raw.pk)
    assert fetched.source_type == "telegram_bot_forward"
    assert fetched.extraction_status == "pending"
    assert fetched.enriched_payload == {}
    assert fetched.text == "Hello world"


# ---------------------------------------------------------------------------
# SourceFailure model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sourcefailure_create_roundtrip():
    from ingestion.models import SourceFailure

    sf = SourceFailure.objects.create(
        source_type="telegram_bot_forward",
        stage="extraction",
        error_class="ValueError",
        error_message="Something went wrong",
    )
    fetched = SourceFailure.objects.get(pk=sf.pk)
    assert fetched.resolved is False
    assert fetched.raw_message is None


# ---------------------------------------------------------------------------
# HeartbeatLog model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_heartbeatlog_create_roundtrip():
    from ingestion.models import HeartbeatLog

    hb = HeartbeatLog.objects.create(note="test heartbeat")
    fetched = HeartbeatLog.objects.get(pk=hb.pk)
    assert fetched.note == "test heartbeat"
    assert fetched.ran_at is not None


# ---------------------------------------------------------------------------
# Review model
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_review_for_organizer(organizer):
    from reviews.models import Review
    from django.contrib.auth import get_user_model
    import django.utils.timezone as tz

    User = get_user_model()
    user = User.objects.create_user(
        username="reviewer_org", email="rev_org@example.com", password="pass"
    )
    review = Review.objects.create(
        author=user,
        organizer=organizer,
        rating=4,
        body="Great organizer",
    )
    fetched = Review.objects.get(pk=review.pk)
    assert fetched.rating == 4
    assert fetched.organizer == organizer
    assert fetched.event is None


@pytest.mark.django_db
def test_review_for_event(organizer):
    from reviews.models import Review
    from events.models import Event
    from django.contrib.auth import get_user_model
    import django.utils.timezone as tz

    User = get_user_model()
    user = User.objects.create_user(
        username="reviewer_evt", email="rev_evt@example.com", password="pass"
    )
    event = Event.objects.create(
        title="Reviewed Event",
        slug="reviewed-event",
        organizer=organizer,
        start=tz.now(),
    )
    review = Review.objects.create(
        author=user,
        event=event,
        rating=5,
    )
    fetched = Review.objects.get(pk=review.pk)
    assert fetched.event == event
    assert fetched.organizer is None


@pytest.mark.django_db
def test_review_constraint_both_targets_rejected(organizer):
    """Review with both organizer AND event must raise IntegrityError."""
    from reviews.models import Review
    from events.models import Event
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError
    import django.utils.timezone as tz

    User = get_user_model()
    user = User.objects.create_user(
        username="reviewer_both", email="rev_both@example.com", password="pass"
    )
    event = Event.objects.create(
        title="Both Event",
        slug="both-event",
        organizer=organizer,
        start=tz.now(),
    )
    with pytest.raises(IntegrityError):
        Review.objects.create(
            author=user,
            organizer=organizer,
            event=event,
            rating=3,
        )


@pytest.mark.django_db
def test_review_constraint_no_targets_rejected(organizer):
    """Review with neither organizer nor event must raise IntegrityError."""
    from reviews.models import Review
    from django.contrib.auth import get_user_model
    from django.db import IntegrityError

    User = get_user_model()
    user = User.objects.create_user(
        username="reviewer_none", email="rev_none@example.com", password="pass"
    )
    with pytest.raises(IntegrityError):
        Review.objects.create(
            author=user,
            rating=3,
        )


# ---------------------------------------------------------------------------
# Constraint presence in DB
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_unique_constraints_in_db():
    """Verify UniqueConstraints exist in pg_constraint."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conname IN "
            "('event_slug_unique_per_organizer', 'event_dup_guard_org_start_title')"
        )
        names = [r[0] for r in cursor.fetchall()]
    assert "event_slug_unique_per_organizer" in names, (
        f"UniqueConstraint 'event_slug_unique_per_organizer' not in pg_constraint: {names}"
    )
    assert "event_dup_guard_org_start_title" in names, (
        f"UniqueConstraint 'event_dup_guard_org_start_title' not in pg_constraint: {names}"
    )


@pytest.mark.django_db
def test_review_check_constraint_in_db():
    """Verify CheckConstraint exists in pg_constraint."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conname FROM pg_constraint WHERE conname = 'review_targets_exactly_one'"
        )
        names = [r[0] for r in cursor.fetchall()]
    assert "review_targets_exactly_one" in names, (
        f"CheckConstraint 'review_targets_exactly_one' not in pg_constraint: {names}"
    )


# ---------------------------------------------------------------------------
# Admin registrations
# ---------------------------------------------------------------------------


def test_organizer_admin_registered():
    from django.contrib import admin
    from organizers.models import Organizer

    assert admin.site.is_registered(Organizer), "Organizer not registered in admin"


def test_venue_admin_registered():
    from django.contrib import admin
    from venues.models import Venue

    assert admin.site.is_registered(Venue), "Venue not registered in admin"


def test_event_admin_registered():
    from django.contrib import admin
    from events.models import Event

    assert admin.site.is_registered(Event), "Event not registered in admin"


def test_tag_admin_registered():
    from django.contrib import admin
    from events.models import Tag

    assert admin.site.is_registered(Tag), "Tag not registered in admin"


def test_rawmessage_admin_registered():
    from django.contrib import admin
    from ingestion.models import RawMessage

    assert admin.site.is_registered(RawMessage), "RawMessage not registered in admin"


def test_review_admin_registered():
    from django.contrib import admin
    from reviews.models import Review

    assert admin.site.is_registered(Review), "Review not registered in admin"


# ---------------------------------------------------------------------------
# FK convention: no direct User import in models
# ---------------------------------------------------------------------------


def test_organizer_approved_by_fk_uses_settings_auth_user_model():
    """Organizer.approved_by FK must reference settings.AUTH_USER_MODEL string."""
    from organizers.models import Organizer

    field = Organizer._meta.get_field("approved_by")
    # The related model should be the AUTH_USER_MODEL (accounts.User)
    assert field.related_model._meta.label == "accounts.User"


def test_review_author_fk_uses_settings_auth_user_model():
    """Review.author FK must reference settings.AUTH_USER_MODEL string."""
    from reviews.models import Review

    field = Review._meta.get_field("author")
    assert field.related_model._meta.label == "accounts.User"
