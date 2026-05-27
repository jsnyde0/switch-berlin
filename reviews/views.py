from urllib.parse import urlparse

import logfire
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import Resolver404, resolve
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django_ratelimit.core import is_ratelimited
from django_ratelimit.decorators import ratelimit

from a_core.models import get_numeric
from accounts.decorators import approved_required
from events.models import Attendance, Event
from organizers.models import Profile

from .forms import TakedownForm
from .models import Flag, Review

MIN_RATINGS_FOR_DISPLAY = 3


def _user_rate_key(group, request):
    """Rate-limit key: PK string for authenticated non-staff, REMOTE_ADDR for anon.
    Staff bypass is handled by _is_ratelimited_for_user before this is called."""
    if not request.user.is_authenticated:
        return str(request.META.get("REMOTE_ADDR", "anon"))
    return str(request.user.pk)


def _is_ratelimited_for_user(request, fn, rate, method="POST"):
    """Call is_ratelimited, bypassing for staff users."""
    if request.user.is_authenticated and request.user.is_staff:
        return False
    return is_ratelimited(
        request,
        fn=fn,
        key=_user_rate_key,
        rate=rate,
        method=method,
        increment=True,
    )


@require_POST
@login_required
@approved_required
def submit_review(request):
    """Submit or update a review. POST params: target_type, target_id, rating, body."""
    from a_core.models import get_flag

    if not get_flag("RATINGS_ENABLED", default=True):
        return render(
            request,
            "reviews/_rating_form.html",
            {"error": "Ratings are temporarily disabled."},
            status=503,
        )

    if _is_ratelimited_for_user(request, fn=submit_review, rate="10/d"):
        return render(
            request,
            "reviews/_rating_form.html",
            {"error": _("Rate limit reached, try again later.")},
            status=429,
        )

    target_type = request.POST.get("target_type")
    target_id = request.POST.get("target_id")

    try:
        rating = int(request.POST.get("rating", 0))
    except (ValueError, TypeError):
        rating = 0
    if not 1 <= rating <= 5:
        return render(
            request,
            "reviews/_rating_form.html",
            {
                "error": "Rating must be between 1 and 5.",
                "target_type": target_type,
                "target_id": target_id,
            },
        )

    body = request.POST.get("body", "").strip()

    with transaction.atomic():
        if target_type == "organizer":
            organizer = get_object_or_404(Profile, pk=target_id, status="approved")
            existing = (
                Review.objects.filter(author=request.user, organizer=organizer)
                .only("hidden", "id")
                .first()
            )
            if existing and existing.hidden:
                return render(
                    request,
                    "reviews/_rating_form.html",
                    {
                        "error": _(
                            "This review was hidden by a moderator."
                            " Contact support to appeal."
                        )
                    },
                    status=403,
                )
            review, created = Review.objects.update_or_create(
                author=request.user,
                organizer=organizer,
                defaults={"rating": rating, "body": body, "event": None},
            )
            agg = Review.objects.filter(organizer=organizer).aggregate(
                count=Count("pk"), avg=Avg("rating")
            )
            Profile.objects.filter(pk=organizer.pk).update(
                rating_count=agg["count"] or 0,
                avg_rating=agg["avg"],
            )
            organizer.refresh_from_db()
            return render(
                request,
                "reviews/_organizer_rating_display.html",
                {
                    "organizer": organizer,
                    "rating_count": organizer.rating_count,
                    "avg_rating": organizer.avg_rating,
                    "user_rating": str(rating),
                    "MIN_RATINGS_FOR_DISPLAY": MIN_RATINGS_FOR_DISPLAY,
                },
            )

        elif target_type == "event":
            event = get_object_or_404(Event, pk=target_id, status="published")
            if not Attendance.objects.filter(
                user=request.user, event=event, status="went"
            ).exists():
                return render(
                    request,
                    "reviews/_rating_form.html",
                    {"error": _("You can review this event after attending.")},
                    status=429,
                )
            existing_event = (
                Review.objects.filter(author=request.user, event=event)
                .only("hidden", "id")
                .first()
            )
            if existing_event and existing_event.hidden:
                return render(
                    request,
                    "reviews/_rating_form.html",
                    {
                        "error": _(
                            "This review was hidden by a moderator."
                            " Contact support to appeal."
                        )
                    },
                    status=403,
                )
            review, created = Review.objects.update_or_create(
                author=request.user,
                event=event,
                defaults={"rating": rating, "body": body, "organizer": None},
            )
            agg = Review.objects.filter(event=event, hidden=False).aggregate(
                count=Count("pk"), avg=Avg("rating")
            )
            Event.objects.filter(pk=event.pk).update(
                rating_count=agg["count"] or 0,
                avg_rating=agg["avg"],
            )
            return render(
                request,
                "reviews/_rating_form.html",
                {
                    "submitted": True,
                    "target_type": "event",
                    "target_id": str(event.pk),
                },
            )

        else:
            return render(
                request,
                "reviews/_rating_form.html",
                {"error": "Invalid target type."},
                status=400,
            )


@require_POST
@login_required
@approved_required
def flag_target(request):
    """Create a Flag. Authenticated users only. Rate limit: 10/day per user."""
    from a_core.models import get_flag

    if not get_flag("FLAGS_ENABLED", default=True):
        return HttpResponse("Flagging is temporarily disabled.", status=503)

    limited_hourly = _is_ratelimited_for_user(request, fn=flag_target, rate="5/h")
    limited_daily = _is_ratelimited_for_user(request, fn=flag_target, rate="20/d")
    if limited_hourly or limited_daily:
        return render(
            request,
            "reviews/_flag_button.html",
            {"error": _("Rate limit reached, try again later.")},
            status=429,
        )

    target_type = request.POST.get("target_type")
    target_id = request.POST.get("target_id")
    reason = request.POST.get("reason", "other")

    with transaction.atomic():
        if target_type == "event":
            event = get_object_or_404(Event, pk=target_id)
            flag, created = Flag.objects.get_or_create(
                reporter=request.user,
                event=event,
                defaults={"reason": reason},
            )
            if not created:
                return render(request, "reviews/_flag_button.html", {"flagged": True})
            auth_flag_count = Flag.objects.filter(
                event=event, reporter__isnull=False, resolved=False
            ).count()
            if auth_flag_count >= get_numeric("threshold.auto_hide_flag", default=3):
                Event.objects.filter(pk=event.pk).update(hidden=True)

        elif target_type == "organizer":
            organizer = get_object_or_404(Profile, pk=target_id)
            flag, created = Flag.objects.get_or_create(
                reporter=request.user,
                organizer=organizer,
                defaults={"reason": reason},
            )
            if not created:
                return render(request, "reviews/_flag_button.html", {"flagged": True})
            auth_flag_count = Flag.objects.filter(
                organizer=organizer, reporter__isnull=False, resolved=False
            ).count()
            if auth_flag_count >= get_numeric("threshold.auto_hide_flag", default=3):
                Profile.objects.filter(pk=organizer.pk).update(hidden=True)
        else:
            return HttpResponse("Invalid target.", status=400)

    return render(request, "reviews/_flag_button.html", {"flagged": True})


def takedown_view(request):
    """Anonymous DSA takedown form. No authentication required.
    Resolves submitted URL to a DB entity for the Flag target FK."""
    # Apply rate limiting on POST only
    if request.method == "POST":
        is_limited = is_ratelimited(
            request,
            fn=takedown_view,
            key="ip",
            rate="10/h",
            method="POST",
            increment=True,
        )
        if is_limited:
            return HttpResponse(
                "Rate limit exceeded. Please try again later.", status=429
            )

        event_url = request.POST.get("event_url", "").strip()
        form = TakedownForm(data=request.POST)

        if not form.is_valid():
            return render(
                request,
                "reviews/takedown.html",
                {"form": form, "values": request.POST},
            )

        reason = form.cleaned_data["reason"]
        body = form.cleaned_data.get("body", "")
        contact_email = form.cleaned_data.get("contact_email", "")
        law_reference = form.cleaned_data.get("law_reference", "")
        good_faith_confirmed = form.cleaned_data.get("good_faith_confirmed", False)

        if not event_url and not body:
            return render(
                request,
                "reviews/takedown.html",
                {"form": form, "error": "Please describe what you are reporting."},
            )

        # Resolve URL to DB entity
        target_event = None
        target_organizer = None
        if event_url:
            try:
                path = urlparse(event_url).path
                match = resolve(path)
                if match.url_name == "event-detail":
                    target_event = Event.objects.filter(
                        event_organizer_set__profile__slug=match.kwargs["org_slug"],
                        event_organizer_set__is_primary=True,
                        slug=match.kwargs["event_slug"],
                    ).first()
                elif match.url_name == "organizer-profile":
                    target_organizer = Profile.objects.filter(
                        slug=match.kwargs["slug"],
                    ).first()
            except (Resolver404, KeyError):
                logfire.warning(
                    "takedown.invalid_url",
                    event_url=event_url,
                )
                return render(
                    request,
                    "reviews/takedown.html",
                    {
                        "form": form,
                        "error": (
                            "The URL you provided is not a valid site URL. "
                            "Please check the URL and try again."
                        ),
                        "values": request.POST,
                    },
                )

        if not target_event and not target_organizer:
            if event_url:
                return render(
                    request,
                    "reviews/takedown.html",
                    {
                        "form": form,
                        "error": (
                            "We could not identify the content at that URL. "
                            "Please check the URL or contact us directly "
                            "at the email below."
                        ),
                        "values": request.POST,
                    },
                )
            return render(
                request,
                "reviews/takedown.html",
                {
                    "form": form,
                    "error": "Please provide the URL of the content you are reporting.",
                },
            )

        Flag.objects.create(
            reporter=None,
            event=target_event,
            organizer=target_organizer,
            reason=reason,
            body=f"URL: {event_url}\n\n{body}" if body else f"URL: {event_url}",
            contact_email=contact_email,
            law_reference=law_reference,
            good_faith_confirmed=good_faith_confirmed,
        )
        from django_q.tasks import async_task

        async_task(
            "reviews.tasks.send_takedown_notification",
            event_url=event_url,
            reason=reason,
            body=body,
            contact_email=contact_email,
        )
        return render(request, "reviews/takedown.html", {"submitted": True})

    form = TakedownForm()
    return render(request, "reviews/takedown.html", {"form": form})


@ratelimit(key="ip", rate="3/h", method="POST", block=False)
def organizer_opt_out_view(request):
    """GDPR opt-out form. Verified via telegram_user_id + organizer FK linkage."""
    from ingestion.models import ApprovedSender

    if request.method == "POST":
        if getattr(request, "limited", False):
            return HttpResponse(
                "Rate limit exceeded. Please try again later.", status=429
            )

        telegram_user_id = request.POST.get("telegram_user_id", "").strip()
        organizer_slug = request.POST.get("organizer_slug", "").strip()

        try:
            # Require the ApprovedSender to be linked to the submitted organizer slug.
            # This prevents any approved sender from suspending an unrelated organizer
            # (IDOR fix: the sender must own the organizer they are opting out).
            organizer = Profile.objects.get(slug=organizer_slug)
            ApprovedSender.objects.get(
                telegram_user_id=telegram_user_id,
                organizer=organizer,
            )
            organizer.status = "suspended"
            organizer.save(update_fields=["status"])
            return render(
                request, "reviews/organizer_opt_out.html", {"submitted": True}
            )
        except (ApprovedSender.DoesNotExist, Profile.DoesNotExist):
            return render(
                request,
                "reviews/organizer_opt_out.html",
                {
                    "error": (
                        "Verification failed. Please contact us via the takedown form."
                    )
                },
            )

    return render(request, "reviews/organizer_opt_out.html", {})
