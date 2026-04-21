from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import approved_required
from events.models import Attendance
from reviews.views import MIN_RATINGS_FOR_DISPLAY

from .models import Organizer, OrganizerFollow


def organizer_profile(request, slug):
    organizer = get_object_or_404(Organizer, slug=slug, status="approved")
    now = timezone.now()

    upcoming_events = (
        organizer.events.filter(
            status="published",
            start__gte=now,
        )
        .select_related("organizer", "venue")
        .prefetch_related("tags")
        .order_by("start")[:50]
    )
    past_events = (
        organizer.events.filter(
            status="published",
            start__lt=now,
        )
        .select_related("organizer", "venue")
        .prefetch_related("tags")
        .order_by("-start")[:20]
    )

    if request.user.is_authenticated:
        following = OrganizerFollow.objects.filter(
            user=request.user, organizer=organizer
        ).exists()
        going_venue_ids = list(
            Attendance.objects.filter(
                user=request.user, status="going", event__venue__isnull=False
            ).values_list("event__venue_id", flat=True)
        )
    else:
        following = False
        going_venue_ids = []

    rating_count = organizer.rating_count
    avg_rating = organizer.avg_rating
    show_rating = rating_count >= MIN_RATINGS_FOR_DISPLAY

    user_review = None
    if request.user.is_authenticated:
        try:
            user_review = organizer.reviews.get(author=request.user)
        except Exception:
            user_review = None

    context = {
        "organizer": organizer,
        "upcoming_events": upcoming_events,
        "past_events": past_events,
        "following": following,
        "going_venue_id_list": going_venue_ids,
        "rating_count": rating_count,
        "avg_rating": avg_rating,
        "show_rating": show_rating,
        "user_review": user_review,
        "MIN_RATINGS_FOR_DISPLAY": MIN_RATINGS_FOR_DISPLAY,
    }
    return render(request, "organizers/profile.html", context)


@require_POST
@login_required
@approved_required
def organizer_follow(request, slug):
    organizer = get_object_or_404(Organizer, slug=slug, status="approved")
    follow, created = OrganizerFollow.objects.get_or_create(
        user=request.user, organizer=organizer
    )
    if not created:
        follow.delete()
        following = False
    else:
        following = True
    return render(request, "organizers/_follow_button.html", {
        "organizer": organizer,
        "following": following,
    })
