"""Tests for ingestion/management/commands/schedule_tasks.py.

Verifies that running `schedule_tasks` registers the expected Schedule rows
for archive_past_events (daily) and soft_purge_rawmessages (weekly).
"""

from pathlib import Path

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


# sb-7wzb.8: the purge the privacy page promises only runs if every start path
# registers the schedules before a qcluster can start.
REPO = Path(__file__).resolve().parents[2]


def _command_lines(path):
    return [
        line.strip()
        for line in (REPO / path).read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _first_index(lines, needle):
    return next(i for i, line in enumerate(lines) if needle in line)


def test_compose_bootstrap_registers_schedules_after_migrate():
    """bin/init.sh (compose init: dev, prod, CI) runs schedule_tasks after migrate.

    qcluster depends_on init completing, so the rows exist before the cluster
    starts.
    """
    lines = _command_lines("bin/init.sh")
    assert _first_index(lines, "manage.py migrate") < _first_index(lines, "manage.py schedule_tasks")


def test_nightly_dev_stack_registers_schedules_before_qcluster():
    """The host-side dev stack registers schedules before it starts qcluster."""
    lines = _command_lines("tools/switch-cli/nightly/collect-nightly.sh")
    assert _first_index(lines, "manage schedule_tasks") < _first_index(lines, "manage.py qcluster")
