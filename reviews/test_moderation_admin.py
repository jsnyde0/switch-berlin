"""
TDD tests for bead kb-8qn.7:
  - FlagAdmin change_view: correct action buttons per target type
  - process_action: ModerationAction creation + side effects
  - process_action: per-target-type action allowlist enforcement (400 on invalid)
  - process_action: non-staff POST → 403
  - ?action= query param passed to template context
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from a_core.models import ModerationAction
from events.models import Event
from organizers.models import Profile
from reviews.models import Flag, Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def staff_client(db):
    """Django test Client logged in as a staff user."""
    User.objects.create_user(
        username="mod_staff",
        email="mod_staff@example.com",
        password="secret",
        is_staff=True,
        is_superuser=True,  # needed to access Django admin
    )
    client = Client()
    client.login(username="mod_staff", password="secret")
    return client


@pytest.fixture
def non_staff_client(db):
    """Django test Client logged in as a non-staff user."""
    User.objects.create_user(
        username="mod_regular",
        email="mod_regular@example.com",
        password="secret",
        is_staff=False,
    )
    client = Client()
    client.login(username="mod_regular", password="secret")
    return client


@pytest.fixture
def mod_organizer(db):
    return Profile.objects.create(
        name="Mod Organizer",
        slug="mod-organizer",
        status="approved",
    )


@pytest.fixture
def mod_event(db, mod_organizer):
    from datetime import timedelta

    from django.utils import timezone

    return Event.objects.create(
        title="Mod Event",
        slug="mod-event",
        organizer=mod_organizer,
        status="published",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def review_author(db):
    user = User.objects.create_user(
        username="review_author",
        email="review_author@example.com",
        password="testpass",
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def mod_review(db, mod_organizer, review_author):
    return Review.objects.create(
        author=review_author,
        organizer=mod_organizer,
        rating=3,
        body="meh",
    )


@pytest.fixture
def event_flag(db, mod_event, review_author):
    return Flag.objects.create(
        reporter=review_author,
        event=mod_event,
        reason="spam",
    )


@pytest.fixture
def organizer_flag(db, mod_organizer, review_author):
    return Flag.objects.create(
        reporter=review_author,
        organizer=mod_organizer,
        reason="spam",
    )


@pytest.fixture
def review_flag(db, mod_review, review_author):
    # We need a second user to report the review flag
    reporter = User.objects.create_user(
        username="flag_reporter",
        email="flag_reporter@example.com",
        password="testpass",
    )
    return Flag.objects.create(
        reporter=reporter,
        review=mod_review,
        reason="spam",
    )


def _action_url(flag_id):
    return reverse("admin:reviews_flag_action", args=[flag_id])


# ---------------------------------------------------------------------------
# Change view: correct action buttons per target type
# ---------------------------------------------------------------------------


class TestFlagAdminChangeView:
    def test_event_flag_shows_correct_actions(self, staff_client, event_flag):
        url = reverse("admin:reviews_flag_change", args=[event_flag.pk])
        response = staff_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        # Should show no_action, hide, resolved
        assert 'value="no_action"' in content
        assert 'value="hide"' in content
        assert 'value="resolved"' in content
        # Should NOT show suspend or delete
        assert 'value="suspend"' not in content
        assert 'value="delete"' not in content

    def test_organizer_flag_shows_correct_actions(self, staff_client, organizer_flag):
        url = reverse("admin:reviews_flag_change", args=[organizer_flag.pk])
        response = staff_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        # Should show no_action, hide, suspend, resolved
        assert 'value="no_action"' in content
        assert 'value="hide"' in content
        assert 'value="suspend"' in content
        assert 'value="resolved"' in content
        # Should NOT show delete
        assert 'value="delete"' not in content

    def test_review_flag_shows_correct_actions(self, staff_client, review_flag):
        url = reverse("admin:reviews_flag_change", args=[review_flag.pk])
        response = staff_client.get(url)
        assert response.status_code == 200
        content = response.content.decode()
        # Should show no_action, delete, resolved
        assert 'value="no_action"' in content
        assert 'value="delete"' in content
        assert 'value="resolved"' in content
        # Should NOT show hide or suspend
        assert 'value="hide"' not in content
        assert 'value="suspend"' not in content

    def test_preselected_action_in_context(self, staff_client, event_flag):
        url = reverse("admin:reviews_flag_change", args=[event_flag.pk])
        response = staff_client.get(url + "?action=hide")
        assert response.status_code == 200
        assert response.context["pre_selected_action"] == "hide"

    def test_preselected_action_empty_by_default(self, staff_client, event_flag):
        url = reverse("admin:reviews_flag_change", args=[event_flag.pk])
        response = staff_client.get(url)
        assert response.status_code == 200
        assert response.context["pre_selected_action"] == ""


# ---------------------------------------------------------------------------
# process_action: ModerationAction creation
# ---------------------------------------------------------------------------


class TestProcessActionModerationActionCreation:
    def test_no_action_on_event_creates_moderation_action(
        self, staff_client, event_flag
    ):
        url = _action_url(event_flag.pk)
        response = staff_client.post(url, {"action": "no_action"})
        assert response.status_code == 302
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.target_type == "event"
        assert ma.target_id == event_flag.event.pk
        assert ma.target_repr == str(event_flag.event)
        assert ma.action == "no_action"

    def test_hide_on_event_creates_moderation_action(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "hide"})
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.target_type == "event"
        assert ma.target_id == event_flag.event.pk
        assert ma.action == "hide"

    def test_hide_on_organizer_creates_moderation_action(
        self, staff_client, organizer_flag
    ):
        url = _action_url(organizer_flag.pk)
        staff_client.post(url, {"action": "hide"})
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.target_type == "organizer"
        assert ma.target_id == organizer_flag.organizer.pk
        assert ma.action == "hide"

    def test_suspend_on_organizer_creates_moderation_action(
        self, staff_client, organizer_flag
    ):
        url = _action_url(organizer_flag.pk)
        staff_client.post(url, {"action": "suspend"})
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.target_type == "organizer"
        assert ma.action == "suspend"

    def test_delete_on_review_creates_moderation_action(
        self, staff_client, review_flag
    ):
        url = _action_url(review_flag.pk)
        staff_client.post(url, {"action": "delete"})
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.target_type == "review"
        assert ma.target_id == review_flag.review.pk
        assert ma.action == "delete"

    def test_resolved_on_event_creates_moderation_action(
        self, staff_client, event_flag
    ):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "resolved"})
        assert ModerationAction.objects.count() == 1
        ma = ModerationAction.objects.first()
        assert ma.action == "resolved"

    def test_moderation_action_records_moderator(self, db, event_flag):
        """ModerationAction.moderator must be the logged-in staff user."""
        mod_user = User.objects.create_user(
            username="specific_mod",
            email="specific_mod@example.com",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client = Client()
        client.login(username="specific_mod", password="secret")
        url = _action_url(event_flag.pk)
        client.post(url, {"action": "no_action"})
        ma = ModerationAction.objects.first()
        assert ma.moderator == mod_user

    def test_moderation_action_records_flag_fk(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "no_action"})
        ma = ModerationAction.objects.first()
        assert ma.flag == event_flag

    def test_exactly_one_moderation_action_per_post(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "no_action"})
        assert ModerationAction.objects.count() == 1


# ---------------------------------------------------------------------------
# process_action: side effects
# ---------------------------------------------------------------------------


class TestProcessActionSideEffects:
    def test_hide_sets_event_hidden(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "hide"})
        event_flag.event.refresh_from_db()
        assert event_flag.event.hidden is True

    def test_hide_sets_organizer_hidden(self, staff_client, organizer_flag):
        url = _action_url(organizer_flag.pk)
        staff_client.post(url, {"action": "hide"})
        organizer_flag.organizer.refresh_from_db()
        assert organizer_flag.organizer.hidden is True

    def test_suspend_sets_organizer_status(self, staff_client, organizer_flag):
        url = _action_url(organizer_flag.pk)
        staff_client.post(url, {"action": "suspend"})
        organizer_flag.organizer.refresh_from_db()
        assert organizer_flag.organizer.status == "suspended"

    def test_delete_sets_review_hidden(self, staff_client, review_flag):
        url = _action_url(review_flag.pk)
        staff_client.post(url, {"action": "delete"})
        review_flag.review.refresh_from_db()
        assert review_flag.review.hidden is True

    def test_no_action_does_not_hide_event(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "no_action"})
        event_flag.event.refresh_from_db()
        assert event_flag.event.hidden is False

    def test_action_sets_flag_resolved(self, staff_client, event_flag):
        assert event_flag.resolved is False
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "no_action"})
        event_flag.refresh_from_db()
        assert event_flag.resolved is True

    def test_resolved_action_marks_flag_resolved(self, staff_client, organizer_flag):
        url = _action_url(organizer_flag.pk)
        staff_client.post(url, {"action": "resolved"})
        organizer_flag.refresh_from_db()
        assert organizer_flag.resolved is True


# ---------------------------------------------------------------------------
# process_action: allowlist enforcement
# ---------------------------------------------------------------------------


class TestProcessActionAllowlist:
    def test_suspend_on_event_flag_returns_400(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        response = staff_client.post(url, {"action": "suspend"})
        assert response.status_code == 400

    def test_delete_on_event_flag_returns_400(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        response = staff_client.post(url, {"action": "delete"})
        assert response.status_code == 400

    def test_hide_on_review_flag_returns_400(self, staff_client, review_flag):
        url = _action_url(review_flag.pk)
        response = staff_client.post(url, {"action": "hide"})
        assert response.status_code == 400

    def test_suspend_on_review_flag_returns_400(self, staff_client, review_flag):
        url = _action_url(review_flag.pk)
        response = staff_client.post(url, {"action": "suspend"})
        assert response.status_code == 400

    def test_delete_on_organizer_flag_returns_400(self, staff_client, organizer_flag):
        url = _action_url(organizer_flag.pk)
        response = staff_client.post(url, {"action": "delete"})
        assert response.status_code == 400

    def test_unknown_action_returns_400(self, staff_client, event_flag):
        url = _action_url(event_flag.pk)
        response = staff_client.post(url, {"action": "nuke"})
        assert response.status_code == 400

    def test_invalid_action_creates_no_moderation_action(
        self, staff_client, event_flag
    ):
        url = _action_url(event_flag.pk)
        staff_client.post(url, {"action": "suspend"})
        assert ModerationAction.objects.count() == 0


# ---------------------------------------------------------------------------
# process_action: permission check
# ---------------------------------------------------------------------------


class TestProcessActionPermissions:
    def test_non_staff_post_returns_302_to_login(self, non_staff_client, event_flag):
        """Non-staff users get redirected (Django admin default)."""
        url = _action_url(event_flag.pk)
        response = non_staff_client.post(url, {"action": "no_action"})
        # Django admin redirects non-staff to login page
        assert response.status_code in (302, 403)

    def test_non_staff_creates_no_moderation_action(self, non_staff_client, event_flag):
        url = _action_url(event_flag.pk)
        non_staff_client.post(url, {"action": "no_action"})
        assert ModerationAction.objects.count() == 0

    def test_anonymous_user_cannot_post(self, db, event_flag):
        client = Client()
        url = _action_url(event_flag.pk)
        response = client.post(url, {"action": "no_action"})
        # Django admin redirects anonymous to login
        assert response.status_code in (302, 403)
        assert ModerationAction.objects.count() == 0
