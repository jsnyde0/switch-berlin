"""
Tests for kb-i45.3: django-q2 heartbeat task + 5-minute schedule.

Tests are written FIRST (TDD) and are expected to FAIL until implementation is complete.
"""

import pytest

# ---------------------------------------------------------------------------
# heartbeat() task function
# ---------------------------------------------------------------------------


def test_heartbeat_task_importable():
    """ingestion.tasks module must exist and export heartbeat."""
    from ingestion.tasks import heartbeat  # noqa: F401


@pytest.mark.django_db
def test_heartbeat_inserts_heartbeatlog():
    """Calling heartbeat() must create exactly one HeartbeatLog row."""
    from ingestion.models import HeartbeatLog
    from ingestion.tasks import heartbeat

    count_before = HeartbeatLog.objects.count()
    heartbeat(note="test")
    assert HeartbeatLog.objects.count() == count_before + 1


@pytest.mark.django_db
def test_heartbeat_stores_note():
    """heartbeat(note='foo') must store that note on the created HeartbeatLog."""
    from ingestion.models import HeartbeatLog
    from ingestion.tasks import heartbeat

    heartbeat(note="smoke-test")
    log = HeartbeatLog.objects.latest("ran_at")
    assert log.note == "smoke-test"


@pytest.mark.django_db
def test_heartbeat_default_note():
    """heartbeat() with no args must store the default note value."""
    from ingestion.models import HeartbeatLog
    from ingestion.tasks import heartbeat

    heartbeat()
    log = HeartbeatLog.objects.latest("ran_at")
    # default note is "scheduled heartbeat"
    assert log.note == "scheduled heartbeat"


# ---------------------------------------------------------------------------
# schedule_heartbeat management command
# ---------------------------------------------------------------------------


def test_schedule_heartbeat_command_importable():
    """The schedule_heartbeat management command module must be importable."""
    from ingestion.management.commands.schedule_heartbeat import Command  # noqa: F401


@pytest.mark.django_db
def test_schedule_heartbeat_creates_schedule():
    """schedule_heartbeat must create a Schedule for ingestion.tasks.heartbeat."""
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("schedule_heartbeat")

    assert Schedule.objects.filter(func="ingestion.tasks.heartbeat").exists()


@pytest.mark.django_db
def test_schedule_heartbeat_schedule_is_every_5_minutes():
    """The created schedule must be type MINUTES with minutes=5."""
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("schedule_heartbeat")

    s = Schedule.objects.get(func="ingestion.tasks.heartbeat")
    assert s.schedule_type == Schedule.MINUTES
    assert s.minutes == 5
    assert s.repeats == -1


@pytest.mark.django_db
def test_schedule_heartbeat_is_idempotent():
    """Running schedule_heartbeat twice must not create duplicate Schedule rows."""
    from django.core.management import call_command
    from django_q.models import Schedule

    call_command("schedule_heartbeat")
    call_command("schedule_heartbeat")

    count = Schedule.objects.filter(func="ingestion.tasks.heartbeat").count()
    assert count == 1
