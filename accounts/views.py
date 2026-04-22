from allauth.account.views import SignupView
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.utils.translation import gettext as _
from django_ratelimit.core import is_ratelimited

from events.models import Attendance
from organizers.models import OrganizerFollow


class RateLimitedSignupView(SignupView):
    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST" and is_ratelimited(
            request,
            group="accounts.signup",
            key="ip",
            rate="3/h",
            method="POST",
            increment=True,
        ):
            return render(
                request,
                "account/signup.html",
                {"error": _("Too many signup attempts. Try again later.")},
                status=429,
            )
        return super().dispatch(request, *args, **kwargs)


@login_required
def me_view(request):
    now = timezone.now()
    followed = (
        OrganizerFollow.objects.filter(user=request.user)
        .select_related("organizer")
        .order_by("organizer__name")
    )
    upcoming = (
        Attendance.objects.filter(
            user=request.user,
            status__in=("going", "interested"),
            event__start__gte=now,
            event__status="published",
            event__hidden=False,
        )
        .select_related("event", "event__organizer")
        .order_by("event__start")
    )
    past = (
        Attendance.objects.filter(
            user=request.user,
            status="went",
            event__start__lt=now,
            event__status="published",
        )
        .select_related("event", "event__organizer")
        .order_by("-event__start")
    )
    return render(
        request,
        "accounts/me.html",
        {
            "followed": followed,
            "upcoming": upcoming,
            "past": past,
        },
    )
