"""Django-q2 tasks for flag digest and nightly aggregate recomputation."""

import time
from collections import defaultdict

import logfire
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Avg, Count
from django.urls import reverse

from a_core.models import EmailFailure


def _suggest_action(target_type, reason):
    """Return a suggested admin action string for a flag.

    Used to pre-fill the ?action= query param in the daily digest admin URLs.
    The admin can override this suggestion in the change view.
    """
    if target_type == "review":
        return "delete"
    if target_type == "organizer" and reason == "harmful":
        return "suspend"
    return "hide"


def daily_flag_digest():
    """Daily django-q2 task: send summary of unresolved flags to admin.

    Flags are grouped by target in the email body. Each flag entry includes
    a pre-filled admin URL with ?action= for quick triage.
    """
    from reviews.models import Flag

    unresolved = Flag.objects.filter(resolved=False).order_by("created_at")
    count = unresolved.count()
    if count == 0:
        return

    groups = defaultdict(list)
    for flag in unresolved[:50]:
        if flag.event:
            key = ("event", flag.event.pk, str(flag.event))
        elif flag.organizer:
            key = ("organizer", flag.organizer.pk, str(flag.organizer))
        elif flag.review:
            key = ("review", flag.review.pk, str(flag.review))
        else:
            key = ("unknown", 0, "(anonymous takedown)")
        groups[key].append(flag)

    lines = [f"Unresolved flags: {count}\n"]
    for (target_type, _target_id, target_label), flags_in_group in groups.items():
        lines.append(f'\n{target_type.title()} "{target_label}" ({len(flags_in_group)} flags):')
        for flag in flags_in_group:
            admin_url = reverse("admin:reviews_flag_change", args=[flag.pk])
            suggested = _suggest_action(target_type, flag.reason)
            lines.append(f"  - [{flag.reason}] reporter: {flag.reporter or 'anonymous'}")
            lines.append(f"    Admin: {settings.SITE_URL}{admin_url}?action={suggested}")
    if count > 50:
        lines.append(f"\n… and {count - 50} more. Visit admin to see all.")

    body = "\n".join(lines)
    try:
        send_mail(
            subject=f"[Switch Berlin] Daily flag digest — {count} unresolved",
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
    logfire.info("finalize_attendance.done", updated_count=updated, duration_ms=duration_ms)


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
    from organizers.models import Follow, Profile
    from reviews.models import Review

    t0 = time.monotonic()

    for org in Profile.objects.all():
        follower_count = Follow.objects.filter(profile=org).count()
        agg = Review.objects.filter(organizer=org, hidden=False).aggregate(count=Count("pk"), avg=Avg("rating"))
        Profile.objects.filter(pk=org.pk).update(
            follower_count=follower_count,
            avg_rating=agg["avg"],
            rating_count=agg["count"] or 0,
        )

    for event in Event.objects.all():
        # Count both 'going' (upcoming) and 'went' (finalized past) attendances
        going_or_went = Attendance.objects.filter(event=event, status__in=("going", "went")).count()
        interested = Attendance.objects.filter(event=event, status="interested").count()
        agg = Review.objects.filter(event=event, hidden=False).aggregate(count=Count("pk"), avg=Avg("rating"))
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
    logfire.info("recompute_aggregates.done", event_count=event_count, duration_ms=duration_ms)
