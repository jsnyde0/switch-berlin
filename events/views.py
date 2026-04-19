import time
import urllib.parse

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from .models import Event, Tag


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
    if tag_slugs:
        filter_params["tags"] = ",".join(tag_slugs)
    if from_param:
        filter_params["from"] = from_param
    if to_param:
        filter_params["to"] = to_param
    if organizer_param:
        filter_params["organizer"] = organizer_param
    if price_param:
        filter_params["price"] = price_param
    filter_query_string = urllib.parse.urlencode(filter_params)

    context = {
        "page_obj": page_obj,
        "all_tags": all_tags,
        "active_tag_slugs": tag_slugs,
        "from_param": from_param,
        "to_param": to_param,
        "organizer_param": organizer_param,
        "price_param": price_param,
        "filter_query_string": filter_query_string,
    }

    if request.htmx:
        response = render(request, "events/list.html#event_list", context)
        elapsed_ms = (time.perf_counter() - _t0) * 1000
        response["Server-Timing"] = f'partial;desc="event-list";dur={elapsed_ms:.1f}'
        return response
    return render(request, "events/list.html", context)


def event_detail(request, slug):
    event = get_object_or_404(
        Event.objects.select_related("organizer", "venue")
        .prefetch_related("tags", "images"),
        slug=slug,
        status="published",
    )
    cover_image = event.images.filter(is_cover=True).first()
    context = {
        "event": event,
        "cover_image": cover_image,
    }
    return render(request, "events/detail.html", context)
