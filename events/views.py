import time
import urllib.parse

import logfire
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import Greatest
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from a_core.models import get_flag, get_numeric
from accounts.decorators import approved_required
from organizers.models import Follow
from reviews.models import Review
from venues.serializers import venue_to_geojson

from .models import Attendance, Event, Tag

_VALID_SORT_OPTIONS = {"date", "trending", "lowest_rated", "most_reviewed"}
_RATING_SORT_OPTIONS = {"lowest_rated", "most_reviewed"}


def event_list(request):
    _t0 = time.perf_counter()
    now = timezone.now()
    qs = (
        Event.objects.visible_to(request.user)
        .filter(hidden=False, status="published", start__gte=now)
        .select_related("venue")
        .prefetch_related("tags", "event_organizer_set__profile")
    )

    # Sort: trending, lowest_rated, most_reviewed, or default chronological.
    # Rating-based sorts are gated by EVENT_REVIEWS_DISPLAYED (ADR-002/005).
    sort = request.GET.get("sort", "date")
    if sort not in _VALID_SORT_OPTIONS:
        sort = "date"
    event_reviews_displayed = get_flag("EVENT_REVIEWS_DISPLAYED", default=False)
    if sort in _RATING_SORT_OPTIONS and not event_reviews_displayed:
        sort = "date"
    trending_enabled = get_flag("TRENDING_SORT_ENABLED", default=True)

    if sort == "trending" and trending_enabled:
        from django.db.models.expressions import RawSQL

        now_ts = timezone.now()
        # RawSQL used for days_until_start: PostgreSQL does not support
        # interval / interval directly, so we convert to epoch seconds.
        qs = (
            qs.annotate(
                days_until_start=ExpressionWrapper(
                    Greatest(
                        RawSQL(
                            "EXTRACT(EPOCH FROM (start - %s)) / 86400.0",
                            [now_ts],
                        ),
                        Value(1.0),
                    ),
                    output_field=FloatField(),
                )
            )
            .annotate(
                trending_score=ExpressionWrapper(
                    F("interested_count") * (1.0 / F("days_until_start"))
                    + F("attendance_count") * 2.0,
                    output_field=FloatField(),
                )
            )
            .order_by("-trending_score", "-start", "pk")
        )
    elif sort == "lowest_rated":
        # Events with no reviews (avg_rating=None) come last.
        qs = qs.order_by(F("avg_rating").asc(nulls_last=True), "start")
    elif sort == "most_reviewed":
        qs = qs.order_by(F("rating_count").desc(), "start")
    else:
        qs = qs.order_by("start")

    # Filter: tags (OR semantics, comma-separated slugs)
    tags_param = request.GET.get("tags", "")
    tag_slugs = [s.strip() for s in tags_param.split(",") if s.strip()]
    valid_slugs: list[str] = []
    if tag_slugs:
        valid_slugs = list(
            Tag.objects.filter(slug__in=tag_slugs).values_list("slug", flat=True)
        )
        if valid_slugs:
            qs = qs.filter(tags__slug__in=valid_slugs).distinct()

    # Filter: from / to date
    from_param = request.GET.get("from", "")
    to_param = request.GET.get("to", "")
    if from_param:
        from_date = parse_date(from_param)
        if from_date:
            qs = qs.filter(start__date__gte=from_date)
    if to_param:
        to_date = parse_date(to_param)
        if to_date:
            qs = qs.filter(start__date__lte=to_date)

    # Filter: organizer slug
    organizer_param = request.GET.get("organizer", "")
    if organizer_param:
        qs = qs.filter(
            event_organizer_set__profile__slug=organizer_param,
            event_organizer_set__is_primary=True,
        ).distinct()

    # Filter: price
    price_param = request.GET.get("price", "")
    if price_param == "free":
        qs = qs.filter(is_free=True)
    elif price_param == "paid":
        qs = qs.filter(is_free=False)

    # Filter: ?filter=following — only events from organizers the user follows
    filter_param = request.GET.get("filter", "")
    if filter_param == "following" and request.user.is_authenticated:
        followed_org_ids = Follow.objects.filter(user=request.user).values_list(
            "profile_id", flat=True
        )
        qs = qs.filter(
            event_organizer_set__profile_id__in=followed_org_ids,
            event_organizer_set__is_primary=True,
        ).distinct()
    elif filter_param == "following":
        # Anonymous user with ?filter=following → return empty queryset
        qs = qs.none()

    # Pagination — invalid page falls back to page 1
    try:
        page_num = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page_num = 1

    paginator = Paginator(qs, 20)
    if sort == "trending" and trending_enabled:
        with logfire.span("events.trending_query"):
            page_obj = paginator.get_page(page_num)
    else:
        page_obj = paginator.get_page(page_num)

    all_tags = Tag.objects.all().order_by("kind", "label")

    # Build filter query string for pagination links (excludes 'page' param)
    filter_params = {}
    if valid_slugs:
        filter_params["tags"] = ",".join(valid_slugs)
    if from_param:
        filter_params["from"] = from_param
    if to_param:
        filter_params["to"] = to_param
    if organizer_param:
        filter_params["organizer"] = organizer_param
    if price_param:
        filter_params["price"] = price_param
    filter_query_string = urllib.parse.urlencode(filter_params)
    # Pagination links must preserve the active sort; chip links must not,
    # so they can switch sort without duplicating the param.
    pagination_params = dict(filter_params)
    if sort and sort != "date":
        pagination_params["sort"] = sort
    pagination_query_string = urllib.parse.urlencode(pagination_params)

    # Markers queryset — non-paginated, same filters as qs, plus optional bounds filter
    markers_qs = qs

    bounds_param = request.GET.get("bounds", "")
    if bounds_param:
        parts = bounds_param.split(",")
        if len(parts) == 4:
            try:
                lat_min, lng_min, lat_max, lng_max = [float(p) for p in parts]
                markers_qs = markers_qs.filter(
                    venue__latitude__gte=lat_min,
                    venue__latitude__lte=lat_max,
                    venue__longitude__gte=lng_min,
                    venue__longitude__lte=lng_max,
                )
            except ValueError:
                pass  # malformed bounds — ignore silently

    # Pre-compute venue PKs where requesting user has Attendance(status='going')
    if request.user.is_authenticated:
        going_venue_ids = frozenset(
            Attendance.objects.filter(
                user=request.user, status="going", event__venue__isnull=False
            ).values_list("event__venue_id", flat=True)
        )
    else:
        going_venue_ids = frozenset()

    # Serialize markers_qs into a GeoJSON FeatureCollection
    marker_features = []
    for event in markers_qs:
        if not event.venue_id:
            continue
        feature = venue_to_geojson(event.venue, going_venue_ids=going_venue_ids)
        if feature is None:
            continue
        feature["properties"].update(
            {
                "event_slug": event.slug,
                "org_slug": event.organizer.slug if event.organizer else "",
                "title": event.title,
            }
        )
        marker_features.append(feature)

    markers_geojson = {
        "type": "FeatureCollection",
        "features": marker_features,
    }

    # Convert to list for template use (Django templates can't use 'in' with frozenset)
    going_venue_id_list = list(going_venue_ids)

    # "From organizers you follow" section — authenticated users only, capped at 5
    if request.user.is_authenticated:
        followed_org_ids = Follow.objects.filter(user=request.user).values_list(
            "profile_id", flat=True
        )
        following_events = (
            Event.objects.filter(
                event_organizer_set__profile_id__in=followed_org_ids,
                event_organizer_set__is_primary=True,
                status="published",
                hidden=False,
                start__gte=now,
                event_organizer_set__profile__status="approved",
                event_organizer_set__profile__hidden=False,
            )
            .prefetch_related("event_organizer_set__profile")
            .order_by("start")
            .distinct()[:5]
        )
    else:
        following_events = []

    context = {
        "page_obj": page_obj,
        "all_tags": all_tags,
        "active_tag_slugs": valid_slugs,
        "from_param": from_param,
        "to_param": to_param,
        "organizer_param": organizer_param,
        "price_param": price_param,
        "filter_query_string": filter_query_string,
        "pagination_query_string": pagination_query_string,
        "markers_geojson": markers_geojson,
        "bounds_param": bounds_param,
        "going_venue_id_list": going_venue_id_list,
        "EVENT_REVIEWS_DISPLAYED": event_reviews_displayed,
        "EVENT_RATING_THRESHOLD": get_numeric(
            "threshold.event_ratings_display", default=3
        ),
        "following_events": following_events,
        "filter_param": filter_param,
        "sort": sort,
        "trending_enabled": trending_enabled,
    }

    if request.htmx:
        response = render(request, "events/_event_list.html", context)
        elapsed_ms = (time.perf_counter() - _t0) * 1000
        response["Server-Timing"] = f'partial;desc="event-list";dur={elapsed_ms:.1f}'
        return response
    return render(request, "events/list.html", context)


def event_drawer(request, org_slug, event_slug):
    event = get_object_or_404(
        Event.objects.visible_to(request.user)
        .filter(hidden=False, status="published")
        .select_related("venue")
        .prefetch_related("event_organizer_set__profile")
        .filter(
            event_organizer_set__profile__slug=org_slug,
            event_organizer_set__is_primary=True,
        )
        .distinct(),
        slug=event_slug,
    )
    if request.user.is_authenticated:
        try:
            attendance = Attendance.objects.get(user=request.user, event=event)
        except Attendance.DoesNotExist:
            attendance = None
        user_going = attendance is not None and attendance.status == "going"
        user_has_went_attendance = Attendance.objects.filter(
            user=request.user, event=event, status="went"
        ).exists()
    else:
        attendance = None
        user_going = False
        user_has_went_attendance = False
    event_past = event.start < timezone.now()
    return render(
        request,
        "events/_event_drawer.html",
        {
            "event": event,
            "attendance": attendance,
            "user_going": user_going,
            "event_past": event_past,
            "user_has_went_attendance": user_has_went_attendance,
        },
    )


def event_detail(request, org_slug, event_slug):
    qs = (
        Event.objects.visible_to_url(request.user)
        .filter(
            hidden=False,
            event_organizer_set__profile__slug=org_slug,
            event_organizer_set__is_primary=True,
            slug=event_slug,
            status="published",
        )
        .select_related("venue")
        .prefetch_related("tags", "images", "event_organizer_set__profile")
        .distinct()
    )
    event = qs.first()
    if event is None:
        raise Http404
    # Annotate resolved event on request so XRobotsTagMiddleware can set headers.
    request._resolved_event = event
    # Use generator over prefetch cache — avoids a second DB query from .filter()
    cover_image = next((img for img in event.images.all() if img.is_cover), None)
    if request.user.is_authenticated:
        try:
            attendance = Attendance.objects.get(user=request.user, event=event)
        except Attendance.DoesNotExist:
            attendance = None
        user_going = attendance is not None and attendance.status == "going"
    else:
        attendance = None
        user_going = False
    event_past = event.start < timezone.now()
    if request.user.is_authenticated:
        user_has_went_attendance = Attendance.objects.filter(
            user=request.user, event=event, status="went"
        ).exists()
    else:
        user_has_went_attendance = False
    event_reviews = (
        Review.objects.filter(event=event, hidden=False)
        .select_related("author")
        .order_by("-created_at")
    )
    context = {
        "event": event,
        "cover_image": cover_image,
        "user_going": user_going,
        "attendance": attendance,
        "event_past": event_past,
        "user_has_went_attendance": user_has_went_attendance,
        "event_reviews": event_reviews,
        "EVENT_REVIEWS_DISPLAYED": get_flag("EVENT_REVIEWS_DISPLAYED", default=False),
        "EVENT_RATING_THRESHOLD": get_numeric(
            "threshold.event_ratings_display", default=3
        ),
    }
    return render(request, "events/detail.html", context)


@require_POST
@login_required
@approved_required
def event_attend(request, org_slug, event_slug):
    # Art. 9(2)(a) GDPR gate — attendance on kink/queer events may reveal
    # sexual orientation. Explicit consent is required before storing any row.
    if not request.user.art9_consent_given_at:
        return render(request, "events/_consent_required.html", {}, status=200)

    event = get_object_or_404(
        Event.objects.visible_to(request.user)
        .filter(
            hidden=False,
            event_organizer_set__profile__slug=org_slug,
            event_organizer_set__is_primary=True,
        )
        .prefetch_related("event_organizer_set__profile")
        .distinct(),
        slug=event_slug,
        status="published",
    )
    status_val = request.POST.get("status", "interested")
    if status_val not in ("interested", "going", "went"):
        status_val = "interested"
    # Guard: 'went' only allowed after event.start has passed
    if status_val == "went" and event.start > timezone.now():
        status_val = "going"
    attendance, created = Attendance.objects.update_or_create(
        user=request.user,
        event=event,
        defaults={"status": status_val},
    )
    event_past = event.start < timezone.now()
    response = render(
        request,
        "events/_attend_button.html",
        {
            "event": event,
            "attendance": attendance,
            "event_past": event_past,
        },
    )
    response["HX-Trigger"] = "events:attendance-changed"
    return response
