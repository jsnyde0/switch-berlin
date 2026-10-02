"""
The nightly run's drain check must see every extraction still running (sb-7wzb.33).

On 2026-10-02 the qcluster pulled all 100 pushed tasks into memory at once; 28 of
them waited past django-q's `retry` (600s), so the ORM broker handed each out a
second time. The first copy's ack deleted the queue row and settled the
RawMessage, so the second copy ran where no query can see it: the drain check read
zero, cleanup stopped the qcluster, and one second copy died at the 300s timeout.
"""

import math
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

from ingestion.models import RawMessage


def _longest_lock_age() -> int:
    """Seconds from a task's dequeue to its ack, at worst: every task the cluster
    holds locked (its in-memory queue, the pusher's bulk in hand, one per worker)
    runs ahead of it to the full timeout, then it runs to the timeout itself."""
    q = settings.Q_CLUSTER
    held = q["queue_limit"] + q["bulk"] + q["workers"]
    return math.ceil(held / q["workers"]) * q["timeout"]


@pytest.mark.django_db
def test_a_task_still_in_flight_is_never_handed_out_a_second_time():
    from django_q.brokers import get_broker

    broker = get_broker()
    broker.enqueue("payload")
    assert len(broker.dequeue()) == 1  # the pusher takes it; the queue row stays until the ack

    later = timezone.now() + timedelta(seconds=_longest_lock_age())
    with patch("django_q.brokers.orm.timezone.now", return_value=later), patch("django_q.brokers.orm.sleep"):
        assert not broker.dequeue(), "a task still running was handed out again (django-q retry too short)"


@pytest.mark.django_db
def test_a_second_copy_of_a_settled_row_does_no_work():
    from ingestion.tasks import process_raw_message

    raw = RawMessage.objects.create(
        source_type="website",
        channel_id="iksk-berlin.de",
        message_id="1",
        raw_payload={},
        text="post",
        extraction_status="duplicate",
        extraction_error="same_listing",
    )
    with (
        patch("ingestion.enrichment.enrich_urls") as enrich,
        patch("ingestion.collected.process_collected_row") as extract,
    ):
        process_raw_message(raw.id)
    enrich.assert_not_called()
    extract.assert_not_called()
    raw.refresh_from_db()
    assert (raw.extraction_status, raw.extraction_error) == ("duplicate", "same_listing")


def test_a_stuck_model_call_fails_inside_the_task_timeout(settings):
    """ADR-008 D4: a hung call is a transport timeout, retried at most twice, and the
    whole climb ends before django-q kills the task, so the row fails loud and the
    next collect run reads it again."""
    from ingestion import extraction

    settings.LLM_API_KEY = "test-key"
    client = extraction.router_model("any-model").client
    attempts = extraction.TRANSPORT_RETRIES + 1
    backoff = sum(extraction.TRANSPORT_BACKOFF_SECONDS * n for n in range(1, attempts))
    assert attempts * client.timeout + backoff < settings.Q_CLUSTER["timeout"]
