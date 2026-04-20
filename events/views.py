import time
import urllib.parse

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from venues.serializers import venue_to_geojson

from .models import Attendance, Event, Tag


def event_list(request):
    _t0 = time.perf_counter()
    now = timezone.now()
    qs = (
        Event.objects.filter(status="published", start__gte=now)
        .select_related("organizer", "venue")
        .prefetch_related("tags")
        .order_by("start")
    )

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
        qs = qs.filter(organizer__slug=organizer_param)

    # Filter: price
    price_param = request.GET.get("price", "")
    if price_param == "free":
        qs = qs.filter(is_free=True)
    elif price_param == "paid":
        qs = qs.filter(is_free=False)

    # Pagination — invalid page falls back to page 1
    try:
        page_num = int(request.GET.get("page", 1))
    except (ValueError, TypeError):
        page_num = 1

    paginator = Paginator(qs, 20)
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
                "event_id": event.pk,
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

    context = {
        "page_obj": page_obj,
        "all_tags": all_tags,
        "active_tag_slugs": valid_slugs,
        "from_param": from_param,
        "to_param": to_param,
        "organizer_param": organizer_param,
        "price_param": price_param,
        "filter_query_string": filter_query_string,
        "markers_geojson": markers_geojson,
        "bounds_param": bounds_param,
        "going_venue_id_list": going_venue_id_list,
    }

    if request.htmx:
        response = render(request, "events/_event_list.html", context)
        elapsed_ms = (time.perf_counter() - _t0) * 1000
        response["Server-Timing"] = f'partial;desc="event-list";dur={elapsed_ms:.1f}'
        return response
    return render(request, "events/list.html", context)


def event_drawer(request, event_id):
    event = get_object_or_404(
        Event.objects.filter(status="published").select_related("organizer", "venue"),
        pk=event_id,
    )
    if request.user.is_authenticated:
        user_going = Attendance.objects.filter(
            user=request.user, event=event, status="going"
        ).exists()
    else:
        user_going = False
    return render(
        request,
        "events/_event_drawer.html",
        {"event": event, "user_going": user_going},
    )


def event_detail(request, org_slug, event_slug):
    qs = (
        Event.objects.filter(
            organizer__slug=org_slug, slug=event_slug, status="published"
        )
        .select_related("organizer", "venue")
        .prefetch_related("tags", "images")
    )
    event = qs.first()
    if event is None:
        raise Http404
    # Use generator over prefetch cache — avoids a second DB query from .filter()
    cover_image = next((img for img in event.images.all() if img.is_cover), None)
    if request.user.is_authenticated:
        user_going = Attendance.objects.filter(
            user=request.user, event=event, status="going"
        ).exists()
        try:
            attendance = Attendance.objects.get(user=request.user, event=event)
        except Attendance.DoesNotExist:
            attendance = None
    else:
        user_going = False
        attendance = None
    event_past = event.start < timezone.now()
    context = {
        "event": event,
        "cover_image": cover_image,
        "user_going": user_going,
        "attendance": attendance,
        "event_past": event_past,
    }
    return render(request, "events/detail.html", context)


@require_POST
@login_required
def event_attend(request, event_id):
    event = get_object_or_404(Event, pk=event_id, status="published")
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
