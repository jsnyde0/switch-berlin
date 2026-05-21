"""Tests for ingestion/tasks_flags.py — finalize_attendance and recompute_aggregates.

Bead: kb-8qn.4 — step-3: finalize_attendance task + recompute_aggregates extension.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from events.models import Attendance, Event
from organizers.models import Profile

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer(db):
    return Profile.objects.create(
        name="Test Organizer",
        slug="test-organizer-tasks",
        status="approved",
    )


@pytest.fixture
def make_user(db):
    """Factory: creates a unique approved user each call."""
    _counter = {"n": 0}

    def _factory():
        _counter["n"] += 1
        u = User.objects.create_user(
            username=f"taskuser_{_counter['n']}",
            email=f"taskuser_{_counter['n']}@example.com",
            password="testpass",
        )
        u.status = "vouched"
        u.save()
        return u

    return _factory


@pytest.fixture
def past_event(db, organizer):
    """A published event whose end was >24 h ago."""
    now = timezone.now()
    return Event.objects.create(
        title="Past Event",
        slug="past-event-tasks",
        organizer=organizer,
        status="published",
        start=now - timedelta(days=3),
        end=now - timedelta(hours=25),  # clearly past the 24-h cutoff
    )


@pytest.fixture
def future_event(db, organizer):
    """A published event in the future."""
    now = timezone.now()
    return Event.objects.create(
        title="Future Event",
        slug="future-event-tasks",
        organizer=organizer,
        status="published",
        start=now + timedelta(days=1),
        end=now + timedelta(days=2),
    )


@pytest.fixture
def cancelled_event(db, organizer):
    """A cancelled event that ended >24 h ago."""
    now = timezone.now()
    return Event.objects.create(
        title="Cancelled Event",
        slug="cancelled-event-tasks",
        organizer=organizer,
        status="cancelled",
        start=now - timedelta(days=3),
        end=now - timedelta(hours=25),
    )


@pytest.fixture
def hidden_event(db, organizer):
    """A published but hidden event that ended >24 h ago."""
    now = timezone.now()
    return Event.objects.create(
        title="Hidden Event",
        slug="hidden-event-tasks",
        organizer=organizer,
        status="published",
        hidden=True,
        start=now - timedelta(days=3),
        end=now - timedelta(hours=25),
    )


@pytest.fixture
def no_end_event(db, organizer):
    """A published event with no end time (ongoing / concert type)."""
    now = timezone.now()
    return Event.objects.create(
        title="No-End Event",
        slug="no-end-event-tasks",
        organizer=organizer,
        status="published",
        start=now - timedelta(days=3),
        end=None,
    )


# ---------------------------------------------------------------------------
# Tests: finalize_attendance
# ---------------------------------------------------------------------------


class TestFinalizeAttendance:
    """finalize_attendance() flips eligible attendances from going -> went."""

    def test_flips_going_to_went_for_past_published_event(self, past_event, make_user):
        """Attendance(status='going') on a past published event is updated to 'went'."""
        user = make_user()
        att = Attendance.objects.create(user=user, event=past_event, status="going")

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "went"

    def test_leaves_interested_status_unchanged(self, past_event, make_user):
        """Attendance(status='interested') is not touched."""
        user = make_user()
        att = Attendance.objects.create(
            user=user, event=past_event, status="interested"
        )

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "interested"

    def test_leaves_went_status_unchanged(self, past_event, make_user):
        """Already-went attendances remain 'went' (idempotent)."""
        user = make_user()
        att = Attendance.objects.create(user=user, event=past_event, status="went")

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "went"

    def test_skips_future_event(self, future_event, make_user):
        """Going attendance on a future event is NOT flipped."""
        user = make_user()
        att = Attendance.objects.create(user=user, event=future_event, status="going")

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "going"

    def test_skips_cancelled_event(self, cancelled_event, make_user):
        """Going attendance on a cancelled event is NOT flipped."""
        user = make_user()
        att = Attendance.objects.create(
            user=user, event=cancelled_event, status="going"
        )

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "going"

    def test_skips_hidden_event(self, hidden_event, make_user):
        """Going attendance on a hidden published event is NOT flipped."""
        user = make_user()
        att = Attendance.objects.create(user=user, event=hidden_event, status="going")

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "going"

    def test_skips_no_end_event(self, no_end_event, make_user):
        """Going attendance on an event with end=None is NOT flipped (intentional)."""
        user = make_user()
        att = Attendance.objects.create(user=user, event=no_end_event, status="going")

        from ingestion.tasks_flags import finalize_attendance

        finalize_attendance()

        att.refresh_from_db()
        assert att.status == "going"

    def test_zero_count_run_still_completes(self, db):
        """Zero-count run (no eligible attendances) completes without error."""
        from ingestion.tasks_flags import finalize_attendance

        # No attendances in DB — should just log updated_count=0
        finalize_attendance()  # must not raise

    def test_emits_logfire_done_span(self, past_event, make_user):
        """finalize_attendance emits logfire.info('finalize_attendance.done', ...)."""
        user = make_user()
        Attendance.objects.create(user=user, event=past_event, status="going")

        with patch("logfire.info") as mock_info:
            from ingestion.tasks_flags import finalize_attendance

            finalize_attendance()

        mock_info.assert_called_once()
        call_kwargs = mock_info.call_args
        # First positional arg is the message name
        assert call_kwargs.args[0] == "finalize_attendance.done"
        # keyword args include updated_count and duration_ms
        assert "updated_count" in call_kwargs.kwargs
        assert "duration_ms" in call_kwargs.kwargs
        assert call_kwargs.kwargs["updated_count"] == 1

    def test_emits_logfire_zero_count_span(self, db):
        """Zero-count run still emits the logfire span with updated_count=0."""
        with patch("logfire.info") as mock_info:
            from ingestion.tasks_flags import finalize_attendance

            finalize_attendance()

        mock_info.assert_called_once()
        call_kwargs = mock_info.call_args
        assert call_kwargs.args[0] == "finalize_attendance.done"
        assert call_kwargs.kwargs["updated_count"] == 0
        assert "duration_ms" in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# Tests: recompute_aggregates — attendance_count includes 'went'
# ---------------------------------------------------------------------------


class TestRecomputeAggregatesWithWent:
    """After finalize_attendance, recompute_aggregates still counts 'went'."""

    def test_attendance_count_includes_went_after_finalize(
        self, past_event, make_user
    ):
        """past event with 3 'going' attendees: after finalize+recompute, count==3."""
        users = [make_user() for _ in range(3)]
        for user in users:
            Attendance.objects.create(user=user, event=past_event, status="going")

        from ingestion.tasks_flags import finalize_attendance, recompute_aggregates

        finalize_attendance()
        recompute_aggregates()

        past_event.refresh_from_db()
        assert past_event.attendance_count == 3

    def test_attendance_count_includes_both_going_and_went(
        self, past_event, make_user
    ):
        """recompute_aggregates counts both 'going' and 'went' statuses."""
        user_going = make_user()
        user_went = make_user()
        Attendance.objects.create(user=user_going, event=past_event, status="going")
        Attendance.objects.create(user=user_went, event=past_event, status="went")

        from ingestion.tasks_flags import recompute_aggregates

        recompute_aggregates()

        past_event.refresh_from_db()
        assert past_event.attendance_count == 2

    def test_recompute_does_not_count_interested(self, past_event, make_user):
        """'interested' status is NOT counted in attendance_count."""
        user_interested = make_user()
        user_went = make_user()
        Attendance.objects.create(
            user=user_interested, event=past_event, status="interested"
        )
        Attendance.objects.create(user=user_went, event=past_event, status="went")

        from ingestion.tasks_flags import recompute_aggregates

        recompute_aggregates()

        past_event.refresh_from_db()
        # Only the 'went' attendance should count
        assert past_event.attendance_count == 1

    def test_recompute_emits_logfire_done_span(self, past_event):
        """recompute_aggregates emits logfire.info('recompute_aggregates.done', ...)."""
        with patch("logfire.info") as mock_info:
            from ingestion.tasks_flags import recompute_aggregates

            recompute_aggregates()

        mock_info.assert_called_once()
        call_kwargs = mock_info.call_args
        assert call_kwargs.args[0] == "recompute_aggregates.done"
        assert "event_count" in call_kwargs.kwargs
        assert "duration_ms" in call_kwargs.kwargs


# ---------------------------------------------------------------------------
# Tests: schedule_tasks management command
# ---------------------------------------------------------------------------


class TestScheduleTasksCommand:
    """schedule_tasks management command registers nightly_finalize_attendance."""

    def test_nightly_finalize_attendance_schedule_registered(self, db):
        """Running schedule_tasks creates 'nightly_finalize_attendance' entry."""
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("schedule_tasks")

        assert Schedule.objects.filter(name="nightly_finalize_attendance").exists()

    def test_nightly_finalize_attendance_is_cron_type(self, db):
        """The schedule entry uses CRON type for time-of-day control."""
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("schedule_tasks")

        schedule = Schedule.objects.get(name="nightly_finalize_attendance")
        assert schedule.schedule_type == Schedule.CRON

    def test_nightly_finalize_attendance_func(self, db):
        """The schedule entry points to finalize_attendance task function."""
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("schedule_tasks")

        schedule = Schedule.objects.get(name="nightly_finalize_attendance")
        assert schedule.func == "ingestion.tasks_flags.finalize_attendance"

    def test_schedule_tasks_is_idempotent(self, db):
        """Running schedule_tasks twice does not create duplicate entries."""
        from django.core.management import call_command
        from django_q.models import Schedule

        call_command("schedule_tasks")
        call_command("schedule_tasks")

        count = Schedule.objects.filter(name="nightly_finalize_attendance").count()
        assert count == 1
