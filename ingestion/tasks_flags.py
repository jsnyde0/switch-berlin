"""Django-q2 tasks for flag digest and nightly aggregate recomputation."""

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


def recompute_aggregates():
    """Nightly django-q2 task: recompute denormalized aggregate fields (F8).

    Recomputes:
      Organizer.follower_count, Organizer.avg_rating, Organizer.rating_count
      Event.attendance_count, Event.interested_count, Event.rating_count

    Does NOT update hidden (set synchronously in flag_target view).
    """
    from events.models import Attendance, Event
    from organizers.models import Organizer, OrganizerFollow
    from reviews.models import Review

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
        going = Attendance.objects.filter(event=event, status="going").count()
        interested = Attendance.objects.filter(event=event, status="interested").count()
        agg = Review.objects.filter(event=event).aggregate(
            count=Count("pk"), avg=Avg("rating")
        )
        rating_count = agg["count"] or 0
        avg = agg["avg"]
        Event.objects.filter(pk=event.pk).update(
            attendance_count=going,
            interested_count=interested,
            rating_count=rating_count,
            avg_rating=avg,
        )
