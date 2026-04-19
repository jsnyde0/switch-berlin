from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from events.models import Event

from .models import Organizer


def organizer_profile(request, slug):
    organizer = get_object_or_404(Organizer, slug=slug, status="approved")
    now = timezone.now()

    upcoming_events = (
        Event.objects.filter(
            organizer=organizer,
            status="published",
            start__gte=now,
        )
        .select_related("venue")
        .prefetch_related("tags")
        .order_by("start")
    )
    past_events = (
        Event.objects.filter(
            organizer=organizer,
            status="published",
            start__lt=now,
        )
        .select_related("venue")
        .prefetch_related("tags")
        .order_by("-start")[:20]
    )

    context = {
        "organizer": organizer,
        "upcoming_events": upcoming_events,
        "past_events": past_events,
    }
    return render(request, "organizers/profile.html", context)
