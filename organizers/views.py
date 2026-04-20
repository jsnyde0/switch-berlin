from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_POST

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
    else:
        following = False

    context = {
        "organizer": organizer,
        "upcoming_events": upcoming_events,
        "past_events": past_events,
        "following": following,
    }
    return render(request, "organizers/profile.html", context)


@require_POST
@login_required
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
