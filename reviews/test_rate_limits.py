"""
TDD tests for bead kb-8qn.11: Rate limiting on write endpoints.

Tests cover:
  - _user_rate_key() helper function
  - flag_target: 5/h + 20/d via django-ratelimit
  - submit_review: 10/d via django-ratelimit
  - RateLimitedSignupView: 3/h per IP
  - RATELIMIT_ENABLE=False disables all limits
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    user = User.objects.create_user(
        username="rl_tester", email="rl_tester@example.com", password="testpass123"
    )
    user.is_approved = True
    user.save()
    return user


@pytest.fixture
def staff_user(db):
    user = User.objects.create_user(
        username="rl_staff", email="rl_staff@example.com", password="testpass123"
    )
    user.is_staff = True
    user.is_approved = True
    user.save()
    return user


@pytest.fixture
def anon_client():
    return Client()


@pytest.fixture
def approved_client(approved_user):
    c = Client()
    c.login(username="rl_tester", password="testpass123")
    return c


@pytest.fixture
def staff_client(staff_user):
    c = Client()
    c.login(username="rl_staff", password="testpass123")
    return c


@pytest.fixture
def rl_organizer(db):
    return Profile.objects.create(
        name="RL Test Organizer",
        slug="rl-test-org",
        status="approved",
    )


@pytest.fixture
def published_event(db, rl_organizer):
    return Event.objects.create(
        title="RL Test Event",
        slug="rl-test-event",
        organizer=rl_organizer,
        status="published",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def went_attendance_for_rl_event(db, approved_user, published_event):
    """Went attendance so the authorship gate doesn't block the rate-limit test."""
    from events.models import Attendance

    return Attendance.objects.create(
        user=approved_user, event=published_event, status="went"
    )


# ---------------------------------------------------------------------------
# Tests: _user_rate_key() helper
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_rate_key_staff_returns_pk(staff_user):
    """Staff user: _user_rate_key returns PK; bypass is in _is_ratelimited_for_user."""
    from reviews.views import _user_rate_key

    rf = RequestFactory()
    request = rf.post("/reviews/flag/")
    request.user = staff_user
    request.META["REMOTE_ADDR"] = "10.0.0.1"

    result = _user_rate_key("group", request)
    assert result == str(staff_user.pk)


@pytest.mark.django_db
def test_user_rate_key_authenticated_returns_pk(approved_user):
    """Authenticated non-staff user returns user PK as string."""
    from reviews.views import _user_rate_key

    rf = RequestFactory()
    request = rf.post("/reviews/flag/")
    request.user = approved_user

    result = _user_rate_key("group", request)
    assert result == str(approved_user.pk)


def test_user_rate_key_anon_returns_ip():
    """Anonymous user returns REMOTE_ADDR."""
    from django.contrib.auth.models import AnonymousUser

    from reviews.views import _user_rate_key

    rf = RequestFactory()
    request = rf.post("/reviews/flag/")
    request.user = AnonymousUser()
    request.META["REMOTE_ADDR"] = "203.0.113.42"

    result = _user_rate_key("group", request)
    assert result == "203.0.113.42"


@pytest.mark.django_db
def test_is_ratelimited_for_user_bypasses_staff(staff_user):
    """_is_ratelimited_for_user returns False for staff regardless of call count."""
    from reviews.views import _is_ratelimited_for_user, flag_target

    rf = RequestFactory()
    request = rf.post("/reviews/flag/")
    request.user = staff_user

    # Calling many times should always return False (bypassed)
    for _ in range(20):
        result = _is_ratelimited_for_user(request, fn=flag_target, rate="5/h")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: flag_target rate limiting (5/h per user)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_flag_target_6th_post_in_hour_returns_429(approved_client, published_event):
    """6th flag POST in same hour from same user -> 429 with _flag_button.html."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("flag-target")

    # First 5 should succeed (rate is 5/h)
    for _ in range(5):
        resp = approved_client.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "reason": "spam",
            },
        )
        assert resp.status_code == 200

    # 6th should be rate-limited
    resp = approved_client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "reason": "spam",
        },
    )
    assert resp.status_code == 429
    assert b"Rate limit" in resp.content or b"rate limit" in resp.content.lower()

    cache.clear()


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_flag_target_staff_never_rate_limited(staff_client, published_event):
    """Staff user can POST flag_target 100 times without being rate-limited."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("flag-target")

    for _ in range(100):
        resp = staff_client.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "reason": "spam",
            },
        )
        # Staff bypass: should never get 429
        assert resp.status_code != 429

    cache.clear()


# ---------------------------------------------------------------------------
# Tests: flag_target RATELIMIT_ENABLE=False disables limit
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_flag_target_ratelimit_disabled_allows_many_posts(
    approved_client, published_event
):
    """RATELIMIT_ENABLE=False means no rate limit is enforced."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("flag-target")

    # Post 10 times — all should succeed (no 429) when RATELIMIT_ENABLE=False
    for _ in range(10):
        resp = approved_client.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "reason": "spam",
            },
        )
        assert resp.status_code != 429

    cache.clear()


# ---------------------------------------------------------------------------
# Tests: submit_review rate limiting (10/d)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    RATINGS_ENABLED=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_submit_review_11th_post_returns_429(approved_client, published_event, went_attendance_for_rl_event):
    """11th review POST in same day -> 429 with _rating_form.html."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("review-submit")

    # First 10 should succeed
    for _ in range(10):
        resp = approved_client.post(
            url,
            {
                "target_type": "event",
                "target_id": str(published_event.pk),
                "rating": "4",
                "body": "test",
            },
        )
        # 200 or 400 (dup), but not 429
        assert resp.status_code != 429

    # 11th should be rate-limited
    resp = approved_client.post(
        url,
        {
            "target_type": "event",
            "target_id": str(published_event.pk),
            "rating": "4",
            "body": "test",
        },
    )
    assert resp.status_code == 429

    cache.clear()


# ---------------------------------------------------------------------------
# Tests: RateLimitedSignupView
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_signup_4th_attempt_from_same_ip_returns_429():
    """4th signup POST from same IP in same hour -> 429."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("account_signup")
    c = Client()

    # First 3 should pass through (even if signup fails due to adapter)
    for i in range(3):
        resp = c.post(
            url,
            {
                "email": f"newuser{i}@example.com",
                "password1": "Str0ngPass!123",
                "password2": "Str0ngPass!123",
            },
            REMOTE_ADDR="198.51.100.1",
        )
        # Not 429 — even if signup is blocked by adapter, rate limit not triggered
        assert resp.status_code != 429

    # 4th should be rate-limited
    resp = c.post(
        url,
        {
            "email": "newuser4@example.com",
            "password1": "Str0ngPass!123",
            "password2": "Str0ngPass!123",
        },
        REMOTE_ADDR="198.51.100.1",
    )
    assert resp.status_code == 429
    content = resp.content
    assert b"Too many" in content or b"Rate limit" in content

    cache.clear()


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=False,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_signup_ratelimit_disabled_allows_many_attempts():
    """RATELIMIT_ENABLE=False means signup rate limit is not enforced."""
    from django.core.cache import cache

    cache.clear()
    url = reverse("account_signup")
    c = Client()

    # Post 5 times — none should be 429 when RATELIMIT_ENABLE=False
    for i in range(5):
        resp = c.post(
            url,
            {
                "email": f"disabledtest{i}@example.com",
                "password1": "Str0ngPass!123",
                "password2": "Str0ngPass!123",
            },
            REMOTE_ADDR="198.51.100.2",
        )
        assert resp.status_code != 429

    cache.clear()


# ---------------------------------------------------------------------------
# Tests: takedown_view rate bumped to 10/h
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    RATELIMIT_ENABLE=True,
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
def test_takedown_11th_request_returns_429(published_event):
    """After takedown bump to 10/h, 11th POST from same IP -> 429."""
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

    # First 10 should succeed (rate is now 10/h)
    for _ in range(10):
        resp = c.post(
            url,
            {
                "event_url": full_url,
                "reason": "spam",
                "body": "test",
                "contact_email": "",
            },
            REMOTE_ADDR="192.0.2.99",
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
        REMOTE_ADDR="192.0.2.99",
    )
    assert resp.status_code == 429

    cache.clear()
