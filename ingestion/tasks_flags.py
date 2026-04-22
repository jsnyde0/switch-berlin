"""Django-q2 tasks for flag digest and nightly aggregate recomputation."""

import time

import logfire
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Avg, Count

from a_core.models import EmailFailure


def daily_flag_digest():
    """Daily django-q2 task: send summary of unresolved flags to admin."""
    from reviews.models import Flag

    unresolved = Flag.objects.filter(resolved=False).order_by("created_at")
    count = unresolved.count()
    if count == 0:
        return

    lines = [f"Unresolved flags: {count}\n"]
    for flag in unresolved[:50]:
        target = flag.organizer or flag.event or flag.review or "(anonymous takedown)"
        lines.append(f"- [{flag.reason}] {target} (reporter: {flag.reporter})")

    body = "\n".join(lines)
    try:
        send_mail(
            subject=f"[Kinky Bubbles] Daily flag digest — {count} unresolved",
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[settings.DEFAULT_FROM_EMAIL],
            fail_silently=False,
        )
    except Exception as exc:
        EmailFailure.objects.create(
            subject="Daily flag digest",
            body_preview=body[:500],
            error_message=str(exc),
        )


def finalize_attendance():
    """Nightly django-q2 task: flip Attendance status from 'going' to 'went'.

    Flips attendances for events that:
      - status='published' and hidden=False
      - end is set (not None) and end < now() - 24 h

    Events with end=None are intentionally skipped — concerts / parties with no
    stated end time stay at 'going' indefinitely; admins can manually flip.
    Cancelled events are also skipped (filter is status='published').

    Always emits a logfire span — even zero-count runs are logged.
    """
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Attendance, Event

    t0 = time.monotonic()
    cutoff = timezone.now() - timedelta(hours=24)
    past_events = Event.objects.filter(
        status="published",
        hidden=False,
        end__isnull=False,
        end__lt=cutoff,
    )
    updated = Attendance.objects.filter(
        event__in=past_events,
        status="going",
    ).update(status="went")
    duration_ms = int((time.monotonic() - t0) * 1000)
    logfire.info(
        "finalize_attendance.done", updated_count=updated, duration_ms=duration_ms
    )


def recompute_aggregates():
    """Nightly django-q2 task: recompute denormalized aggregate fields (F8).

    Recomputes:
      Organizer.follower_count, Organizer.avg_rating, Organizer.rating_count
      Event.attendance_count, Event.interested_count, Event.rating_count

    attendance_count counts both 'going' and 'went' statuses so that past events
    (whose attendances were finalized by finalize_attendance) retain their counts.

    Does NOT update hidden (set synchronously in flag_target view).
    """
    from events.models import Attendance, Event
    from organizers.models import Organizer, OrganizerFollow
    from reviews.models import Review

    t0 = time.monotonic()

    for org in Organizer.objects.all():
        follower_count = OrganizerFollow.objects.filter(organizer=org).count()
        agg = Review.objects.filter(organizer=org).aggregate(
            count=Count("pk"), avg=Avg("rating")
        )
        Organizer.objects.filter(pk=org.pk).update(
            follower_count=follower_count,
            avg_rating=agg["avg"],
            rating_count=agg["count"] or 0,
        )

    for event in Event.objects.all():
        # Count both 'going' (upcoming) and 'went' (finalized past) attendances
        going_or_went = Attendance.objects.filter(
            event=event, status__in=("going", "went")
        ).count()
        interested = Attendance.objects.filter(event=event, status="interested").count()
        agg = Review.objects.filter(event=event).aggregate(
            count=Count("pk"), avg=Avg("rating")
        )
        rating_count = agg["count"] or 0
        avg = agg["avg"]
        Event.objects.filter(pk=event.pk).update(
            attendance_count=going_or_went,
            interested_count=interested,
            rating_count=rating_count,
            avg_rating=avg,
        )

    event_count = Event.objects.count()
    duration_ms = int((time.monotonic() - t0) * 1000)
    logfire.info(
        "recompute_aggregates.done", event_count=event_count, duration_ms=duration_ms
    )
