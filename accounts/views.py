from allauth.account.views import SignupView
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_ratelimit.core import is_ratelimited

from events.models import Attendance
from organizers.models import Follow


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
        Follow.objects.filter(
            user=request.user,
            profile__hidden=False,
            profile__status="approved",
        )
        .select_related("profile")
        .order_by("profile__name")
    )
    upcoming = (
        Attendance.objects.filter(
            user=request.user,
            status__in=("going", "interested"),
            event__start__gte=now,
            event__status="published",
            event__hidden=False,
        )
        .select_related("event", "event__venue")
        .prefetch_related("event__event_organizer_set__profile")
        .order_by("event__start")
    )
    past = (
        Attendance.objects.filter(
            user=request.user,
            status="went",
            event__start__lt=now,
            event__status="published",
            event__hidden=False,
        )
        .select_related("event", "event__venue")
        .prefetch_related("event__event_organizer_set__profile")
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


@login_required
@require_POST
def art9_consent_view(request):
    """Set Art. 9(2)(a) consent timestamp. Idempotent — safe to POST twice.

    Returns an HTMX-compatible 200 response with HX-Redirect header so the
    client reloads to the original URL after consent is given.
    """
    if not request.user.art9_consent_given_at:
        request.user.art9_consent_given_at = timezone.now()
        request.user.save(update_fields=["art9_consent_given_at"])
    next_url = request.POST.get("next", "/")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        next_url = "/"
    response = HttpResponse()
    response["HX-Redirect"] = next_url
    return response


@login_required
@require_POST
def art9_consent_withdraw_view(request):
    """Withdraw Art. 9 consent: clears timestamp AND deletes all Attendance rows."""
    from accounts.consent import revoke_art9_consent

    revoke_art9_consent(request.user)
    messages.success(
        request,
        _("Attendance consent withdrawn. All attendance records deleted."),
    )
    return redirect("me")
