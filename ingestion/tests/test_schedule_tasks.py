"""Tests for ingestion/management/commands/schedule_tasks.py.

Verifies that running `schedule_tasks` registers the expected Schedule rows
for archive_past_events (daily) and soft_purge_rawmessages (weekly).
"""

import pytest
from django.core.management import call_command
from django_q.models import Schedule


@pytest.mark.django_db
def test_schedule_tasks_registers_archive_past_events():
    """schedule_tasks creates a daily Schedule for archive_past_events."""
    call_command("schedule_tasks")

    schedule = Schedule.objects.get(name="archive_past_events")
    assert schedule.func == "ingestion.tasks.archive_past_events"
    assert schedule.schedule_type == Schedule.DAILY
    assert schedule.repeats == -1


@pytest.mark.django_db
def test_schedule_tasks_registers_soft_purge_rawmessages_weekly():
    """schedule_tasks creates a weekly Schedule for soft_purge_rawmessages."""
    call_command("schedule_tasks")

    schedule = Schedule.objects.get(name="soft_purge_rawmessages")
    assert schedule.func == "ingestion.tasks.soft_purge_rawmessages"
    assert schedule.schedule_type == Schedule.WEEKLY
    assert schedule.repeats == -1


@pytest.mark.django_db
def test_schedule_tasks_is_idempotent():
    """Running schedule_tasks twice does not create duplicate Schedule rows."""
    call_command("schedule_tasks")
    call_command("schedule_tasks")

    assert Schedule.objects.filter(name="archive_past_events").count() == 1
    assert Schedule.objects.filter(name="soft_purge_rawmessages").count() == 1
