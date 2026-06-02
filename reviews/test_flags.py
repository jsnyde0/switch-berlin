"""
TDD tests for bead kb-a4t.6:
  - flag_target view (authenticated, rate-limited, auto-hide)
  - takedown_view (anonymous, rate-limited, URL resolution)
  - organizer_opt_out_view
  - tasks: send_takedown_notification, daily_flag_digest, recompute_aggregates
  - .visible() manager usage in event/organizer public querysets
  - schedule_tasks management command
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, Event
from organizers.models import Follow, Profile
from reviews.models import Flag, Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    user = User.objects.create_user(username="tester", email="tester@example.com", password="testpass123")
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def approved_user2(db):
    user = User.objects.create_user(username="tester2", email="tester2@example.com", password="testpass123")
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def approved_user3(db):
    user = User.objects.create_user(username="tester3", email="tester3@example.com", password="testpass123")
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def organizer(db):
    return Profile.objects.create(
        name="Test Organizer",
        slug="test-org",
        status="approved",
    )


@pytest.fixture
def published_event(db, organizer):
    return Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=organizer,
        status="published",
        start=timezone.now() + timedelta(days=3),
    )


@pytest.fixture
def client_approved(approved_user):
    c = Client()
    c.force_login(approved_user)
    return c


# ---------------------------------------------------------------------------
# Test: flag_target view — functional check (a)
# POST /reviews/flag/ as approved user, target_type=event -> creates Flag row
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_target_creates_flag_for_event(client_approved, published_event):
    """POST flag/ as approved user creates a Flag with reporter set."""
    url = reverse("flag-target")
    resp = client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    assert resp.status_code == 200
    flags = Flag.objects.filter(event=published_event)
    assert flags.count() == 1
    flag = flags.first()
    assert flag.reporter is not None


@pytest.mark.django_db
def test_flag_target_creates_flag_for_organizer(client_approved, organizer):
    """POST flag/ as approved user creates a Flag for organizer with reporter set."""
    url = reverse("flag-target")
    resp = client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "reason": "harmful",
        },
    )
    assert resp.status_code == 200
    flags = Flag.objects.filter(organizer=organizer)
    assert flags.count() == 1
    flag = flags.first()
    assert flag.reporter is not None


@pytest.mark.django_db
def test_flag_target_requires_auth():
    """Unauthenticated POST to flag/ -> 302 redirect to login."""
    c = Client()
    url = reverse("flag-target")
    resp = c.post(url, {"target_type": "event", "target_id": "1", "reason": "spam"})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


@pytest.mark.django_db
def test_flag_target_invalid_target_type_returns_400(client_approved, published_event):
    """POST flag/ with unknown target_type returns 400."""
    url = reverse("flag-target")
    resp = client_approved.post(
        url,
        {
            "target_type": "venue",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Test: auto-hide — functional check (b) + (d)
# POST 3 authenticated flags on same event -> Event.hidden becomes True
# Anonymous flags do NOT count toward threshold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_hide_event_after_threshold_authenticated_flags(
    client_approved, approved_user2, approved_user3, published_event
):
    """3 authenticated-user flags on same event -> Event.hidden becomes True."""
    url = reverse("flag-target")
    client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    c2 = Client()
    c2.force_login(approved_user2)
    c2.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    c3 = Client()
    c3.force_login(approved_user3)
    c3.post(
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
def test_anonymous_flags_do_not_count_toward_auto_hide(published_event):
    """Anonymous flags (reporter=None) do NOT trigger auto-hide."""
    # Create 3 anonymous-style flags (via direct model creation, reporter=None)
    # Only authenticated flags from the view count toward threshold
    # But we can also create them via DB directly to test the view logic
    # Anonymous flags are stored with reporter=None — they must NOT count
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    published_event.refresh_from_db()
    assert published_event.hidden is False


@pytest.mark.django_db
def test_auto_hide_organizer_after_threshold_flags(client_approved, approved_user2, approved_user3, organizer):
    """3 authenticated flags on same organizer -> Organizer.hidden becomes True."""
    url = reverse("flag-target")
    client_approved.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "reason": "harmful",
        },
    )
    c2 = Client()
    c2.force_login(approved_user2)
    c2.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "reason": "harmful",
        },
    )
    c3 = Client()
    c3.force_login(approved_user3)
    c3.post(
        url,
        {
            "target_type": "organizer",
            "target_id": str(organizer.pk),
            "reason": "harmful",
        },
    )
    organizer.refresh_from_db()
    assert organizer.hidden is True


# ---------------------------------------------------------------------------
# Test: takedown_view — functional check (c) + (e) + (f)
# Anonymous takedown resolves URL to Event FK — reporter=null, event FK set
# Unresolvable URL -> form error, NOT a Flag with all-null FKs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_takedown_view_get_returns_200():
    """GET /takedown/ returns the form."""
    url = reverse("takedown")
    resp = Client().get(url)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_takedown_resolves_event_url_and_creates_flag(published_event):
    """POST /takedown/ with resolvable event URL creates Flag with event FK set."""
    event_url = reverse(
        "event-detail",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    resp = Client().post(
        reverse("takedown"),
        {
            "event_url": f"http://testserver{event_url}",
            "reason": "spam",
            "body": "This is spam.",
            "contact_email": "reporter@example.com",
            "good_faith_confirmed": True,
        },
    )
    assert resp.status_code == 200
    flags = Flag.objects.filter(event=published_event)
    assert flags.count() == 1
    flag = flags.first()
    assert flag.reporter is None  # anonymous
    assert flag.event_id == published_event.pk
    assert flag.organizer_id is None


@pytest.mark.django_db
def test_takedown_resolves_organizer_url_and_creates_flag(organizer):
    """POST /takedown/ with resolvable organizer URL creates Flag with organizer FK."""
    organizer_url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = Client().post(
        reverse("takedown"),
        {
            "event_url": f"http://testserver{organizer_url}",
            "reason": "harmful",
            "body": "Harmful content.",
            "contact_email": "",
            "good_faith_confirmed": True,
        },
    )
    assert resp.status_code == 200
    flags = Flag.objects.filter(organizer=organizer)
    assert flags.count() == 1
    flag = flags.first()
    assert flag.reporter is None
    assert flag.organizer_id == organizer.pk
    assert flag.event_id is None


@pytest.mark.django_db
def test_takedown_unresolvable_url_shows_error_not_flag():
    """POST /takedown/ with URL that does not resolve -> form error, NO Flag created."""
    resp = Client().post(
        reverse("takedown"),
        {
            "event_url": "https://example.com/totally/unknown/path/",
            "reason": "spam",
            "body": "Some body.",
            "contact_email": "",
        },
    )
    assert resp.status_code == 200
    # No flags should be created
    assert Flag.objects.count() == 0
    # Response must contain an error message
    content = resp.content.decode()
    assert "error" in content.lower() or "could not" in content.lower()


@pytest.mark.django_db
def test_takedown_no_url_and_no_body_shows_error():
    """POST /takedown/ with neither URL nor body -> form error."""
    resp = Client().post(
        reverse("takedown"),
        {
            "event_url": "",
            "reason": "spam",
            "body": "",
            "contact_email": "",
        },
    )
    assert resp.status_code == 200
    assert Flag.objects.count() == 0


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_takedown_rate_limit_11th_request_returns_429(published_event):
    """POST /takedown/ 11 times from same IP -> 11th blocked by ratelimit (10/h)."""
    from django.core.cache import cache

    cache.clear()

    event_url = reverse(
        "event-detail",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    full_url = f"http://testserver{event_url}"
    url = reverse("takedown")
    c = Client()
    # First 10 should succeed (rate bumped to 10/h)
    for _ in range(10):
        resp = c.post(
            url,
            {
                "event_url": full_url,
                "reason": "spam",
                "body": "test",
                "contact_email": "",
            },
            REMOTE_ADDR="192.0.2.1",
        )
        assert resp.status_code == 200

    # 11th should be blocked
    resp = c.post(
        url,
        {
            "event_url": full_url,
            "reason": "spam",
            "body": "test",
            "contact_email": "",
        },
        REMOTE_ADDR="192.0.2.1",
    )
    assert resp.status_code == 429

    cache.clear()


# ---------------------------------------------------------------------------
# Test: organizer_opt_out_view
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_opt_out_get_returns_200():
    """GET /organizer-opt-out/ returns the form."""
    url = reverse("organizer-opt-out")
    resp = Client().get(url)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_organizer_opt_out_valid_telegram_id_suspends_organizer(organizer):
    """Valid telegram_user_id linked to organizer -> Organizer.status set to
    'suspended'."""
    from ingestion.models import ApprovedSender

    ApprovedSender.objects.create(
        telegram_user_id="123456789",
        telegram_handle="orgadmin",
        organizer=organizer,
    )
    url = reverse("organizer-opt-out")
    resp = Client().post(
        url,
        {
            "telegram_user_id": "123456789",
            "organizer_slug": organizer.slug,
        },
    )
    assert resp.status_code == 200
    organizer.refresh_from_db()
    assert organizer.status == "suspended"


@pytest.mark.django_db
def test_organizer_opt_out_invalid_telegram_id_returns_error(organizer):
    """Invalid telegram_user_id shows error, does NOT suspend organizer."""
    url = reverse("organizer-opt-out")
    resp = Client().post(
        url,
        {
            "telegram_user_id": "99999999",
            "organizer_slug": organizer.slug,
        },
    )
    assert resp.status_code == 200
    organizer.refresh_from_db()
    assert organizer.status == "approved"
    content = resp.content.decode()
    assert "error" in content.lower() or "verification failed" in content.lower()


# ---------------------------------------------------------------------------
# Test: .visible() manager in public querysets — checks (g) + (h)
# GET /events/ -> hidden events not in response
# GET /o/<slug>/ for hidden organizer -> 404
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_list_excludes_hidden_events(client, published_event):
    """event_list view does not show hidden events."""
    published_event.hidden = True
    published_event.save()
    resp = client.get(reverse("event-list"))
    assert resp.status_code == 200
    event_pks = [e.pk for e in resp.context["page_obj"]]
    assert published_event.pk not in event_pks


@pytest.mark.django_db
def test_event_list_shows_visible_events(client, published_event):
    """event_list view shows non-hidden published events."""
    resp = client.get(reverse("event-list"))
    assert resp.status_code == 200
    event_pks = [e.pk for e in resp.context["page_obj"]]
    assert published_event.pk in event_pks


@pytest.mark.django_db
def test_hidden_organizer_profile_returns_404(client, organizer):
    """Hidden organizer -> 404 on profile page."""
    organizer.hidden = True
    organizer.save()
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 404


@pytest.mark.django_db
def test_visible_organizer_profile_returns_200(client, organizer):
    """Non-hidden organizer profile returns 200."""
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200


@pytest.mark.django_db
def test_organizer_profile_upcoming_events_excludes_hidden(client, organizer):
    """Upcoming events on organizer profile exclude hidden events."""
    hidden_event = Event.objects.create(
        title="Hidden Upcoming",
        slug="hidden-upcoming",
        organizer=organizer,
        status="published",
        start=timezone.now() + timedelta(days=5),
        hidden=True,
    )
    visible_event = Event.objects.create(
        title="Visible Upcoming",
        slug="visible-upcoming",
        organizer=organizer,
        status="published",
        start=timezone.now() + timedelta(days=5),
        hidden=False,
    )
    url = reverse("organizer-profile", kwargs={"slug": organizer.slug})
    resp = client.get(url)
    assert resp.status_code == 200
    upcoming_pks = [e.pk for e in resp.context["upcoming_events"]]
    assert visible_event.pk in upcoming_pks
    assert hidden_event.pk not in upcoming_pks


# ---------------------------------------------------------------------------
# Test: recompute_aggregates — functional check (i)
# Call recompute_aggregates() directly -> no exceptions, counts updated
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_recompute_aggregates_runs_without_exception(organizer, published_event, approved_user):
    """recompute_aggregates runs without exception and updates counts."""
    from ingestion.tasks_flags import recompute_aggregates

    # Create some attendance and review data
    Attendance.objects.create(user=approved_user, event=published_event, status="going")
    Review.objects.create(author=approved_user, organizer=organizer, rating=4)
    Follow.objects.create(user=approved_user, profile=organizer)

    # Should not raise
    recompute_aggregates()

    organizer.refresh_from_db()
    published_event.refresh_from_db()
    assert organizer.follower_count == 1
    assert organizer.rating_count == 1
    assert organizer.avg_rating == pytest.approx(4.0)
    assert published_event.attendance_count == 1
    assert published_event.interested_count == 0


@pytest.mark.django_db
def test_recompute_aggregates_no_data_no_exception():
    """recompute_aggregates with no data runs cleanly."""
    from ingestion.tasks_flags import recompute_aggregates

    recompute_aggregates()  # should not raise


# ---------------------------------------------------------------------------
# Test: daily_flag_digest — functional check (j)
# Call daily_flag_digest() directly -> no exceptions when flags exist
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_daily_flag_digest_no_flags_runs_cleanly():
    """daily_flag_digest with no flags returns without error."""
    from ingestion.tasks_flags import daily_flag_digest

    daily_flag_digest()  # should not raise, and not send email (0 flags)


@pytest.mark.django_db
@patch("ingestion.tasks_flags.send_mail")
def test_daily_flag_digest_with_flags_sends_email(mock_send, published_event):
    """daily_flag_digest with unresolved flags sends a digest email."""
    from ingestion.tasks_flags import daily_flag_digest

    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    daily_flag_digest()
    assert mock_send.called


@pytest.mark.django_db
@patch("ingestion.tasks_flags.send_mail", side_effect=Exception("SMTP error"))
def test_daily_flag_digest_email_failure_creates_email_failure_record(mock_send, published_event):
    """daily_flag_digest logs EmailFailure on send exception."""
    from a_core.models import EmailFailure
    from ingestion.tasks_flags import daily_flag_digest

    Flag.objects.create(reporter=None, event=published_event, reason="spam")
    daily_flag_digest()

    assert EmailFailure.objects.count() == 1


# ---------------------------------------------------------------------------
# Test: send_takedown_notification task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@patch("reviews.tasks.send_mail")
def test_send_takedown_notification_sends_email(mock_send):
    """send_takedown_notification sends an email."""
    from reviews.tasks import send_takedown_notification

    send_takedown_notification(
        event_url="https://example.com/events/org/event-slug/",
        reason="spam",
        body="Test body",
        contact_email="test@example.com",
    )
    assert mock_send.called


@pytest.mark.django_db
@patch("reviews.tasks.send_mail", side_effect=Exception("SMTP failure"))
def test_send_takedown_notification_logs_email_failure_on_exception(mock_send):
    """send_takedown_notification creates EmailFailure on send error."""
    from a_core.models import EmailFailure
    from reviews.tasks import send_takedown_notification

    send_takedown_notification(
        event_url="https://example.com/events/org/event-slug/",
        reason="spam",
        body="Test body",
        contact_email="test@example.com",
    )
    assert EmailFailure.objects.count() == 1


# ---------------------------------------------------------------------------
# Test: Flag CheckConstraint — all-null target rejected
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_constraint_rejects_all_null_targets():
    """Flag.CheckConstraint rejects creating a Flag with all-null FKs."""
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        Flag.objects.create(reporter=None, reason="spam")


# ---------------------------------------------------------------------------
# Test: schedule_tasks management command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_schedule_tasks_command_creates_schedules():
    """schedule_tasks management command registers digest + aggregate schedules."""
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("schedule_tasks")

    assert Schedule.objects.filter(name="daily_flag_digest").exists()
    assert Schedule.objects.filter(name="nightly_recompute_aggregates").exists()


@pytest.mark.django_db
def test_schedule_tasks_command_is_idempotent():
    """schedule_tasks is idempotent — running twice does not duplicate schedules."""
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("schedule_tasks")
    call_command("schedule_tasks")

    assert Schedule.objects.filter(name="daily_flag_digest").count() == 1
    assert Schedule.objects.filter(name="nightly_recompute_aggregates").count() == 1


# ---------------------------------------------------------------------------
# Test: IDOR fix — organizer_opt_out cannot suspend unrelated organizer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_organizer_opt_out_cannot_suspend_unrelated_organizer():
    """ApprovedSender linked to org-A cannot opt out org-B (IDOR prevention)."""
    from ingestion.models import ApprovedSender

    organizer_a = Profile.objects.create(name="Organizer A", slug="org-a", status="approved")
    organizer_b = Profile.objects.create(name="Organizer B", slug="org-b", status="approved")
    # Sender is linked to org-A only
    ApprovedSender.objects.create(
        telegram_user_id="sender-idor-test",
        telegram_handle="senderhandle",
        organizer=organizer_a,
    )

    url = reverse("organizer-opt-out")
    # Attempt to suspend org-B using org-A's sender ID
    resp = Client().post(
        url,
        {
            "telegram_user_id": "sender-idor-test",
            "organizer_slug": organizer_b.slug,
        },
    )
    assert resp.status_code == 200
    organizer_b.refresh_from_db()
    # org-B must remain approved
    assert organizer_b.status == "approved"
    content = resp.content.decode()
    assert "verification failed" in content.lower() or "error" in content.lower()


# ---------------------------------------------------------------------------
# Test: organizer_opt_out rate limit — 4th POST blocked
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_organizer_opt_out_rate_limit_4th_request_blocked():
    """POST /organizer-opt-out/ 4 times from same IP -> 4th returns 429."""
    from django.core.cache import cache

    cache.clear()

    url = reverse("organizer-opt-out")
    c = Client()
    # First 3 should return 200 (even with wrong credentials — verification error)
    for _ in range(3):
        resp = c.post(
            url,
            {
                "telegram_user_id": "nonexistent",
                "organizer_slug": "nonexistent-org",
            },
            REMOTE_ADDR="192.0.2.50",
        )
        assert resp.status_code == 200

    # 4th should be blocked
    resp = c.post(
        url,
        {
            "telegram_user_id": "nonexistent",
            "organizer_slug": "nonexistent-org",
        },
        REMOTE_ADDR="192.0.2.50",
    )
    assert resp.status_code == 429

    cache.clear()


# ---------------------------------------------------------------------------
# Test: FeatureFlag cache invalidation on save/delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_feature_flag_save_invalidates_cache():
    """Toggling FeatureFlag via .save() immediately invalidates the cache."""

    from a_core.models import FeatureFlag, get_flag

    # Prime the cache with True
    flag, _ = FeatureFlag.objects.get_or_create(key="TEST_CACHE_INVALIDATION_FLAG", defaults={"enabled": True})
    val = get_flag("TEST_CACHE_INVALIDATION_FLAG", default=False)
    assert val is True

    # Toggle to False via .save() — should bust cache
    flag.enabled = False
    flag.save()

    # get_flag must reflect new value without cache.clear()
    val_after = get_flag("TEST_CACHE_INVALIDATION_FLAG", default=True)
    assert val_after is False

    # Cleanup
    flag.delete()


@pytest.mark.django_db
def test_feature_flag_delete_invalidates_cache():
    """Deleting a FeatureFlag via .delete() falls back to default immediately."""

    from a_core.models import FeatureFlag, get_flag

    flag, _ = FeatureFlag.objects.get_or_create(key="TEST_CACHE_DELETE_FLAG", defaults={"enabled": False})
    # Prime cache
    val = get_flag("TEST_CACHE_DELETE_FLAG", default=True)
    assert val is False

    # Delete the flag — should bust cache; get_flag should return default
    flag.delete()

    val_after = get_flag("TEST_CACHE_DELETE_FLAG", default=True)
    assert val_after is True


# ---------------------------------------------------------------------------
# Test: Review.hidden field (new soft-delete field)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_review_hidden_field_exists_and_defaults_false(approved_user, published_event):
    """Review.hidden field exists and defaults to False."""
    review = Review.objects.create(author=approved_user, event=published_event, rating=4)
    review.refresh_from_db()
    assert review.hidden is False


@pytest.mark.django_db
def test_review_hidden_can_be_set_true(approved_user, published_event):
    """Review.hidden can be set to True (soft-delete)."""
    review = Review.objects.create(author=approved_user, event=published_event, rating=4)
    review.hidden = True
    review.save(update_fields=["hidden"])
    review.refresh_from_db()
    assert review.hidden is True


@pytest.mark.django_db
def test_review_hidden_has_db_index():
    """Review.hidden field has db_index=True."""
    field = Review._meta.get_field("hidden")
    assert field.db_index is True


# ---------------------------------------------------------------------------
# Test: AUTO_HIDE_FLAG_THRESHOLD replaced by get_numeric in reviews/views.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_hide_threshold_from_feature_flag_not_constant(
    client_approved, approved_user2, approved_user3, published_event
):
    """auto-hide threshold is read from get_numeric, not a module constant."""
    from django.core.cache import cache

    from a_core.models import FeatureFlag

    # Set threshold to 5 in DB (higher than default 3; seed row exists from 0005)
    FeatureFlag.objects.update_or_create(
        key="threshold.auto_hide_flag",
        defaults={"enabled": True, "numeric_value": 5},
    )
    cache.clear()

    url = reverse("flag-target")
    # 3 flags — with threshold=5 the event should NOT be hidden
    for user in [client_approved]:
        user.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "reason": "spam",
            },
        )
    c2 = Client()
    c2.force_login(approved_user2)
    c2.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    c3 = Client()
    c3.force_login(approved_user3)
    c3.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    published_event.refresh_from_db()
    # With threshold=5, 3 flags should NOT trigger auto-hide
    assert published_event.hidden is False


@pytest.mark.django_db
def test_reviews_views_has_no_auto_hide_flag_threshold_constant():
    """reviews/views.py must not contain AUTO_HIDE_FLAG_THRESHOLD = 3 constant."""
    import ast
    import pathlib

    source = (pathlib.Path(__file__).parent / "views.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "AUTO_HIDE_FLAG_THRESHOLD":
                    raise AssertionError("AUTO_HIDE_FLAG_THRESHOLD constant still present in reviews/views.py")


@pytest.mark.django_db
def test_reviews_views_uses_get_numeric_for_auto_hide():
    """reviews/views.py must use get_numeric('threshold.auto_hide_flag', ...) not
    hardcoded constant."""
    import pathlib

    source = (pathlib.Path(__file__).parent / "views.py").read_text()
    assert 'get_numeric("threshold.auto_hide_flag"' in source, (
        "reviews/views.py must call get_numeric('threshold.auto_hide_flag', ...) but the call was not found"
    )


# ---------------------------------------------------------------------------
# Test: Event.avg_rating field + recompute_aggregates populates it
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_event_avg_rating_field_exists(published_event):
    """Event.avg_rating field exists and defaults to None."""
    published_event.refresh_from_db()
    assert hasattr(published_event, "avg_rating")
    assert published_event.avg_rating is None


@pytest.mark.django_db
def test_recompute_aggregates_populates_event_avg_rating(approved_user, approved_user2, published_event):
    """recompute_aggregates updates Event.avg_rating from Review ratings."""
    from ingestion.tasks_flags import recompute_aggregates

    Review.objects.create(author=approved_user, event=published_event, rating=4)
    Review.objects.create(author=approved_user2, event=published_event, rating=2)

    recompute_aggregates()

    published_event.refresh_from_db()
    assert published_event.avg_rating == pytest.approx(3.0)


@pytest.mark.django_db
def test_recompute_aggregates_event_avg_rating_none_when_no_reviews(published_event):
    """recompute_aggregates sets Event.avg_rating to None when there are no reviews."""
    from ingestion.tasks_flags import recompute_aggregates

    recompute_aggregates()

    published_event.refresh_from_db()
    assert published_event.avg_rating is None


@pytest.mark.django_db
def test_recompute_aggregates_excludes_hidden_reviews_from_event(approved_user, approved_user2, published_event):
    """recompute_aggregates must exclude hidden=True reviews from event aggregates."""
    from ingestion.tasks_flags import recompute_aggregates

    # One visible review (rating=4), one hidden review (rating=1)
    Review.objects.create(author=approved_user, event=published_event, rating=4)
    Review.objects.create(author=approved_user2, event=published_event, rating=1, hidden=True)

    recompute_aggregates()

    published_event.refresh_from_db()
    # Only the visible review should count
    assert published_event.rating_count == 1
    assert published_event.avg_rating == pytest.approx(4.0)


@pytest.mark.django_db
def test_recompute_aggregates_excludes_hidden_reviews_from_organizer(approved_user, approved_user2, published_event):
    """recompute_aggregates must exclude hidden=True reviews from organizer
    aggregates."""
    from ingestion.tasks_flags import recompute_aggregates

    organizer = published_event.organizer
    # One visible review (rating=5), one hidden review (rating=1)
    Review.objects.create(author=approved_user, organizer=organizer, rating=5)
    Review.objects.create(author=approved_user2, organizer=organizer, rating=1, hidden=True)

    recompute_aggregates()

    organizer.refresh_from_db()
    # Only the visible review should count
    assert organizer.rating_count == 1
    assert organizer.avg_rating == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Test: Flag UniqueConstraint rejects duplicate (reporter, event) pairs
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_unique_constraint_rejects_duplicate_reporter_event(approved_user, published_event):
    """Second flag from same reporter on same event is rejected by UniqueConstraint."""
    from django.db import IntegrityError

    Flag.objects.create(reporter=approved_user, event=published_event, reason="spam")
    with pytest.raises(IntegrityError):
        Flag.objects.create(reporter=approved_user, event=published_event, reason="harmful")


@pytest.mark.django_db
def test_flag_unique_constraint_rejects_duplicate_reporter_organizer(approved_user, published_event):
    """Second flag from same reporter on same organizer is rejected by
    UniqueConstraint."""
    from django.db import IntegrityError

    organizer = published_event.organizer
    Flag.objects.create(reporter=approved_user, organizer=organizer, reason="spam")
    with pytest.raises(IntegrityError):
        Flag.objects.create(reporter=approved_user, organizer=organizer, reason="harmful")


@pytest.mark.django_db
def test_flag_get_or_create_handles_duplicate_gracefully(client_approved, approved_user, published_event):
    """Second flag POST from same user on same event returns 200 without error."""
    url = reverse("flag-target")
    payload = {
        "target_type": "event",
        "target_id": str(published_event.pk),
        "reason": "spam",
    }
    resp1 = client_approved.post(url, payload)
    assert resp1.status_code == 200
    # Second POST: get_or_create returns existing flag; no IntegrityError
    resp2 = client_approved.post(url, payload)
    assert resp2.status_code == 200
    # Only one flag should exist
    assert Flag.objects.filter(reporter=approved_user, event=published_event).count() == 1


# ---------------------------------------------------------------------------
# Test: auto-hide count excludes resolved flags
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_hide_excludes_resolved_flags(
    client_approved, approved_user, approved_user2, approved_user3, published_event
):
    """Resolved flags do not count toward auto-hide threshold."""
    # Create 2 resolved flags (should not count toward threshold of 3)
    Flag.objects.create(reporter=approved_user2, event=published_event, reason="spam", resolved=True)
    Flag.objects.create(reporter=approved_user3, event=published_event, reason="spam", resolved=True)
    # Now post one live flag from approved_user; with threshold=3, only 1 unresolved
    url = reverse("flag-target")
    client_approved.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    published_event.refresh_from_db()
    # Only 1 unresolved flag — event must NOT be hidden
    assert published_event.hidden is False


# ---------------------------------------------------------------------------
# Test: daily_flag_digest appends "and N more" footer when count > 50
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_daily_flag_digest_appends_overflow_footer(approved_user, published_event):
    """When > 50 unresolved flags exist, the digest body includes an overflow footer."""
    from unittest.mock import patch

    from ingestion.tasks_flags import daily_flag_digest

    # Create 51 anonymous takedown flags (reporter=None, anon targets)
    # Anonymous flags bypass the UniqueConstraint (reporter__isnull=False condition).
    for _ in range(51):
        Flag.objects.create(reporter=None, event=published_event, reason="spam")

    captured = {}

    def fake_send_mail(subject, message, from_email, recipient_list, fail_silently):
        captured["message"] = message

    with patch("ingestion.tasks_flags.send_mail", side_effect=fake_send_mail):
        daily_flag_digest()

    assert "more" in captured.get("message", ""), "Overflow footer not found in digest body"
