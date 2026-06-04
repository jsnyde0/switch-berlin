"""
Event service layer (kb-shzi.1).

ADR-008 D2: a second writer of Event.status exists (events/admin.py already
writes Event.status in publish_events). Extracting the shared logic here is
justified — not speculative abstraction.

ADR-016 D5: 'published' means the event is actually out there. When the Switch
own-page adapter confirms publication, it calls publish_event() so the canonical
Event record reflects that truth.
"""

from django.utils import timezone


def publish_event(event) -> None:
    """
    Promote the canonical Event to 'published'.

    Idempotent first-publish pattern (mirrors events/admin.py:208-209):
    - Always sets event.status = 'published'.
    - Only sets event.published_at on the FIRST publish (published_at is None).
      A subsequent call preserves the original published_at timestamp.

    Direct CharField assignment (no state machine on Event.status — plain field).
    ADR-008 D3: no silent no-op — always writes status=published; caller is
    responsible for calling only when appropriate.

    Args:
        event: An events.models.Event instance (any status).
    """
    update_fields = ["status", "updated_at"]
    event.status = "published"

    if event.published_at is None:
        # First publish: stamp the timestamp
        event.published_at = timezone.now()
        update_fields.append("published_at")

    event.save(update_fields=update_fields)
