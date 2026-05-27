"""
Syndication web UI views (kb-a4u.3).

Co-equal seam (ADR-016 D3/D6): views call the same syndication.services
functions as the Ninja API handlers. No parallel persistence implementations.

Authorization: edit/publish gated through syndication.authz.can_edit /
can_publish seam (ADR-017 D2). No inline is_primary / claimant checks.

HTMX + Alpine per ADR-004.
Fragment-seam composition: the Event hub page composes independently-addressable
HTMX-swappable django_cotton fragments named by domain concept (event_facts,
event_posts, event_syndication). Fragments have their own endpoints.
Each swapped partial has its own x-data root (Alpine 3.x known bug —
directives go inert without their own x-data root).

ADR-008 D2: no speculative abstraction (no tab framework, no generic fragment
dispatcher — each fragment is a named, explicit URL).
"""

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from events.models import Event
from syndication.authz import can_edit
from syndication.forms import EventForm, PlatformConnectionForm, PostForm
from syndication.models import PlatformConnection, PlatformProjection, Post
from syndication.services import (
    create_event,
    create_post,
    update_event,
    _get_primary_profile_for_user,
)


# ---------------------------------------------------------------------------
# Event hub: create, detail/edit
# ---------------------------------------------------------------------------


@login_required
def event_create(request):
    """
    Create a new Event via the web form.
    GET: render the form.
    POST: call create_event service (co-equal with API), redirect to hub on success.
    """
    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            try:
                event = create_event(user=request.user, **cd)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                return redirect("syndication:event-hub", pk=event.pk)
    else:
        form = EventForm()

    return render(request, "syndication/event_create.html", {"form": form})


@login_required
def event_hub(request, pk):
    """
    Event detail/edit hub page.

    Composes three independently-addressable HTMX-swappable fragments:
    - event_facts: title, dates, location, capacity, etc.
    - event_posts: promotional posts
    - event_syndication: projection review board (expanded in C5)

    The hub page does NOT inline fragment query logic — it just includes
    the fragments by reference. ADR-008 D2: no tab framework speculation.
    """
    event = get_object_or_404(Event, pk=pk)
    user_can_edit = can_edit(request.user, event)
    return render(request, "syndication/event_hub.html", {
        "event": event,
        "can_edit": user_can_edit,
    })


@login_required
def event_hub_edit(request, pk):
    """
    Edit an Event via the web form.
    GET: render form pre-populated with current values.
    POST: call update_event service (co-equal with API), redirect to hub on success.
    """
    event = get_object_or_404(Event, pk=pk)
    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {"event": event}, status=403)

    if request.method == "POST":
        form = EventForm(request.POST, initial={
            "title": event.title,
            "slug": event.slug,
            "start": event.start,
        })
        if form.is_valid():
            cd = form.cleaned_data
            update_event(user=request.user, event=event, **cd)
            return redirect("syndication:event-hub", pk=event.pk)
    else:
        # Include ALL editable fields so edit-load round-trips stored values.
        # ADR-008 D3: missing fields here = silent data loss on save (wipe on re-save).
        form = EventForm(initial={
            "title": event.title,
            "slug": event.slug,
            "start": event.start,
            "end": event.end,
            "description": event.description,
            "venue": event.venue_id,
            "tags": ", ".join(
                event.tags.values_list("slug", flat=True)
            ) if event.pk else "",
            "dress_code": event.dress_code,
            "content_warnings": (
                json.dumps(event.content_warnings)
                if isinstance(event.content_warnings, list)
                else event.content_warnings or ""
            ),
            "age_restriction": event.age_restriction,
            "capacity": event.capacity,
            "visibility": event.visibility,
            "language": event.language,
            "is_free": event.is_free,
            "price_min_cents": event.price_min_cents,
            "price_max_cents": event.price_max_cents,
            "currency": event.currency,
            "sliding_scale": event.sliding_scale,
            "price_description": event.price_description,
            "external_url": event.external_url,
            "tickets_url": event.tickets_url,
            "registration_required": event.registration_required,
            "registration_url": event.registration_url,
            "registration_email": event.registration_email,
        })

    return render(request, "syndication/event_edit.html", {
        "form": form,
        "event": event,
    })


# ---------------------------------------------------------------------------
# HTMX fragments (event_facts, event_posts, event_syndication)
# Each fragment has its own URL, own query logic, and own x-data root.
# ---------------------------------------------------------------------------


@login_required
def fragment_event_facts(request, pk):
    """
    event_facts fragment: title, dates, location, capacity, pricing fields.
    HTMX target for partial refresh of the event facts panel.
    """
    event = get_object_or_404(Event, pk=pk)
    user_can_edit = can_edit(request.user, event)
    return render(request, "syndication/fragments/event_facts.html", {
        "event": event,
        "can_edit": user_can_edit,
    })


@login_required
def fragment_event_posts(request, pk):
    """
    event_posts fragment: list of promotional Posts + inline add form.
    HTMX target for partial refresh after a Post is added.
    """
    event = get_object_or_404(Event, pk=pk)
    posts = Post.objects.filter(event=event).order_by("-created_at")
    user_can_edit = can_edit(request.user, event)
    return render(request, "syndication/fragments/event_posts.html", {
        "event": event,
        "posts": posts,
        "can_edit": user_can_edit,
        "post_form": PostForm(),
    })


@login_required
def fragment_event_syndication(request, pk):
    """
    event_syndication fragment: projection review board (stub; expanded in C5).
    Shows existing draft projections per connection.
    """
    event = get_object_or_404(Event, pk=pk)
    projections = PlatformProjection.objects.filter(
        source_event=event
    ).select_related("connection").order_by("connection__platform")
    user_can_edit = can_edit(request.user, event)
    return render(request, "syndication/fragments/event_syndication.html", {
        "event": event,
        "projections": projections,
        "can_edit": user_can_edit,
    })


# ---------------------------------------------------------------------------
# Post creation (scoped to Event)
# ---------------------------------------------------------------------------


@login_required
def post_create(request, event_pk):
    """
    Create a Post scoped to an Event.
    GET: render the Post form.
    POST: call create_post service (co-equal with API), redirect to event hub.

    ADR-016 D4: creation triggers eager promotion projection fan-out.
    Authorization via can_edit seam (ADR-017 D2).
    """
    event = get_object_or_404(Event, pk=event_pk)

    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {"event": event}, status=403)

    if request.method == "POST":
        form = PostForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            post = create_post(user=request.user, event=event, **cd)
            # HTMX-aware: if request is HTMX, return event_posts fragment
            if request.headers.get("HX-Request"):
                posts = Post.objects.filter(event=event).order_by("-created_at")
                return render(request, "syndication/fragments/event_posts.html", {
                    "event": event,
                    "posts": posts,
                    "can_edit": can_edit(request.user, event),
                    "post_form": PostForm(),
                })
            return redirect("syndication:event-hub", pk=event.pk)
    else:
        form = PostForm()

    return render(request, "syndication/post_create.html", {
        "form": form,
        "event": event,
    })


# ---------------------------------------------------------------------------
# PlatformConnection management UI
# ---------------------------------------------------------------------------


@login_required
def connections_list(request):
    """
    List PlatformConnections for the authenticated user's profiles.
    """
    from organizers.models import ProfileClaim
    profile_ids = ProfileClaim.objects.filter(
        user=request.user, rejected_at__isnull=True
    ).values_list("profile_id", flat=True)
    connections = PlatformConnection.objects.filter(
        organizer_id__in=profile_ids
    ).select_related("organizer").order_by("platform", "destination_id")
    return render(request, "syndication/connections_list.html", {
        "connections": connections,
    })


@login_required
def connection_create(request):
    """
    Create a new PlatformConnection.
    GET: render the form.
    POST: create connection, redirect to connections list.
    """
    try:
        profile = _get_primary_profile_for_user(request.user)
    except ValueError:
        return render(request, "syndication/403.html", {
            "detail": "No organizer profile found for your account."
        }, status=403)

    if request.method == "POST":
        form = PlatformConnectionForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            PlatformConnection.objects.create(
                organizer=profile,
                platform=cd["platform"],
                destination_id=cd["destination_id"],
                kinds=cd["kinds"],
                enabled=cd.get("enabled", True),
            )
            return redirect("syndication:connections-list")
    else:
        form = PlatformConnectionForm()

    return render(request, "syndication/connection_create.html", {"form": form})


@login_required
def connection_toggle(request, pk):
    """
    Toggle the enabled flag on a PlatformConnection.
    POST only. Returns redirect or 200 for HTMX.
    """
    from organizers.models import ProfileClaim

    profile_ids = ProfileClaim.objects.filter(
        user=request.user, rejected_at__isnull=True
    ).values_list("profile_id", flat=True)

    conn = get_object_or_404(PlatformConnection, pk=pk, organizer_id__in=profile_ids)

    if request.method == "POST":
        conn.enabled = not conn.enabled
        conn.save(update_fields=["enabled"])
        if request.headers.get("HX-Request"):
            connections = PlatformConnection.objects.filter(
                organizer_id__in=profile_ids
            ).select_related("organizer").order_by("platform", "destination_id")
            return render(request, "syndication/connections_list.html", {
                "connections": connections,
            })
        return redirect("syndication:connections-list")

    return redirect("syndication:connections-list")
