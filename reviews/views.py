from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from accounts.decorators import approved_required
from events.models import Event
from organizers.models import Organizer

from .models import Review

MIN_RATINGS_FOR_DISPLAY = 3


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
            {"error": "Rating must be between 1 and 5."},
            status=400,
        )

    body = request.POST.get("body", "").strip()

    with transaction.atomic():
        if target_type == "organizer":
            organizer = get_object_or_404(Organizer, pk=target_id, status="approved")
            review, created = Review.objects.update_or_create(
                author=request.user,
                organizer=organizer,
                defaults={"rating": rating, "body": body, "event": None},
            )
            agg = Review.objects.filter(organizer=organizer).aggregate(
                count=Count("pk"), avg=Avg("rating")
            )
            Organizer.objects.filter(pk=organizer.pk).update(
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
            review, created = Review.objects.update_or_create(
                author=request.user,
                event=event,
                defaults={"rating": rating, "body": body, "organizer": None},
            )
            count = Review.objects.filter(event=event).count()
            Event.objects.filter(pk=event.pk).update(rating_count=count)
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
