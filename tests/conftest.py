"""Shared pytest fixtures for the Switch test suite."""

import pytest

# ---------------------------------------------------------------------------
# Bundle A shared fixtures (bead kb-8qn.1)
# ---------------------------------------------------------------------------


@pytest.fixture
def user_with_went_attendance(db):
    """Factory fixture: creates an approved User + Attendance(status='went').

    Usage::

        def test_foo(user_with_went_attendance, some_event):
            user, attendance = user_with_went_attendance(some_event)

    The returned user has ``is_approved=True``. Each call generates a unique
    username so multiple calls within the same test are safe.
    """
    from django.contrib.auth import get_user_model

    from events.models import Attendance

    User = get_user_model()
    _counter = {"n": 0}

    def _factory(event):
        _counter["n"] += 1
        user = User.objects.create_user(
            username=f"went_user_{_counter['n']}",
            email=f"went_user_{_counter['n']}@example.com",
            password="testpass123",
        )
        user.is_approved = True
        user.save()
        attendance = Attendance.objects.create(user=user, event=event, status="went")
        return user, attendance

    return _factory


@pytest.fixture
def past_event_fixture(db, approved_organizer):
    """Factory fixture: creates a published Event with ``end`` in the past.

    Named ``past_event_fixture`` (not ``past_event``) to avoid collision with
    the local ``past_event`` fixture defined in ``reviews/tests.py``.

    Usage::

        def test_foo(past_event_fixture):
            event = past_event_fixture(days_ago=3)
    """
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Event

    _counter = {"n": 0}

    def _factory(days_ago=7):
        _counter["n"] += 1
        now = timezone.now()
        return Event.objects.create(
            title=f"Past Event {_counter['n']}",
            slug=f"past-event-{_counter['n']}",
            organizer=approved_organizer,
            status="published",
            start=now - timedelta(days=days_ago + 1),
            end=now - timedelta(days=days_ago),
        )

    return _factory


@pytest.fixture
def review_for_event_with_count(db):
    """Factory fixture: creates ``n`` Review rows for a given event.

    Each review is authored by a distinct user (auto-generated). Returns the
    list of created Review instances.

    Usage::

        def test_foo(review_for_event_with_count, some_event):
            reviews = review_for_event_with_count(some_event, 3)
    """
    from django.contrib.auth import get_user_model

    from reviews.models import Review

    User = get_user_model()
    _counter = {"n": 0}

    def _factory(event, n):
        reviews = []
        for _ in range(n):
            _counter["n"] += 1
            author = User.objects.create_user(
                username=f"reviewer_{_counter['n']}",
                email=f"reviewer_{_counter['n']}@example.com",
                password="testpass123",
            )
            review = Review.objects.create(
                author=author,
                event=event,
                rating=4,
                body="",
            )
            reviews.append(review)
        return reviews

    return _factory


@pytest.fixture
def organizer_with_rating_count(db):
    """Factory fixture: creates an Organizer with ``n`` Review rows.

    Calls ``Organizer.objects.filter(pk=org.pk).update(rating_count=n)`` to
    set the denormalized count without touching ``avg_rating`` logic.

    Usage::

        def test_foo(organizer_with_rating_count):
            org = organizer_with_rating_count(5)
    """
    from django.contrib.auth import get_user_model

    from organizers.models import Profile
    from reviews.models import Review

    User = get_user_model()
    _counter = {"n": 0}

    def _factory(n):
        _counter["n"] += 1
        org = Profile.objects.create(
            name=f"Rated Organizer {_counter['n']}",
            slug=f"rated-org-{_counter['n']}",
            status="approved",
        )
        for i in range(n):
            author = User.objects.create_user(
                username=f"rater_{_counter['n']}_{i}",
                email=f"rater_{_counter['n']}_{i}@example.com",
                password="testpass123",
            )
            Review.objects.create(author=author, organizer=org, rating=4, body="")
        Profile.objects.filter(pk=org.pk).update(rating_count=n)
        org.refresh_from_db()
        return org

    return _factory


@pytest.fixture
def organizer_with_follower_count(db):
    """Factory fixture: creates an Organizer with ``n`` OrganizerFollow rows.

    Each follow row uses a distinct auto-generated user. Calls
    ``Organizer.objects.filter(pk=org.pk).update(follower_count=n)`` to set
    the denormalized count.

    Usage::

        def test_foo(organizer_with_follower_count):
            org = organizer_with_follower_count(4)
    """
    from django.contrib.auth import get_user_model

    from organizers.models import Follow, Profile

    User = get_user_model()
    _counter = {"n": 0}

    def _factory(n):
        _counter["n"] += 1
        org = Profile.objects.create(
            name=f"Followed Organizer {_counter['n']}",
            slug=f"followed-org-{_counter['n']}",
            status="approved",
        )
        for i in range(n):
            user = User.objects.create_user(
                username=f"follower_{_counter['n']}_{i}",
                email=f"follower_{_counter['n']}_{i}@example.com",
                password="testpass123",
            )
            Follow.objects.create(user=user, profile=org)
        Profile.objects.filter(pk=org.pk).update(follower_count=n)
        org.refresh_from_db()
        return org

    return _factory


@pytest.fixture
def superuser(db):
    """Create a superuser for admin smoke tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_superuser("admin", "admin@example.com", "password")


@pytest.fixture(autouse=True)
def isolate_logfire_token(monkeypatch):
    """Ensure LOGFIRE_TOKEN is always empty during tests.

    Prevents tests from accidentally emitting real Logfire events when a
    contributor has a real LOGFIRE_TOKEN set in their environment or .env file.
    Scoped to the whole test suite via autouse=True.
    """
    monkeypatch.setenv("LOGFIRE_TOKEN", "")


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Clear Django's cache before every test.

    django-ratelimit stores counters in the default cache (LocMemCache in tests).
    Without this fixture, rate-limit state leaks across tests because the
    in-process cache is never reset between test functions, causing false 429
    responses when tests share rate-limit keys (e.g. same user PK across DB
    resets).
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def staff_user(db):
    """Staff user for login-wall tests."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="staff", email="staff@example.com", password="x", is_staff=True
    )


@pytest.fixture
def regular_user(db):
    """Authenticated but non-staff user — should get 403 from login-wall."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="regular", email="regular@example.com", password="x", is_staff=False
    )


@pytest.fixture
def approved_organizer(db):
    """Approved organizer for view smoke tests."""
    from organizers.models import Profile

    return Profile.objects.create(
        name="Test Organizer",
        slug="test-organizer",
        status="approved",
    )


@pytest.fixture
def published_event(db, approved_organizer):
    """A single published future event."""
    from datetime import timedelta

    import django.utils.timezone as tz

    from events.models import Event

    return Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=approved_organizer,
        status="published",
        start=tz.now() + timedelta(days=7),
    )
