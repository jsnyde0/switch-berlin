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
from syndication.authz import can_edit, can_publish
from syndication.forms import EventForm, PlatformConnectionForm, PostForm
from syndication.models import PlatformConnection, PlatformProjection, Post
from syndication.services import (
    create_event,
    create_post,
    update_event,
    _get_primary_profile_for_user,
    approve_projection,
    publish_projection,
    mark_projection_published,
    publish_all_ready_projections,
    save_projection_override,
    _resolve_projection_event,
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
def fragment_event_syndication(request, pk, *, action_error=None):
    """
    event_syndication fragment: projection review board (kb-a4u.5).

    Shows one row per projection for the event — both listing projections
    (source_event) and promotion projections (via Posts linked to this event).

    Context:
    - projections: all PlatformProjection rows for this event (listing + promotion)
    - rendered_rows: dict {pk: rendered_body_str} for each projection
    - has_connections: bool — whether any connections exist for this organizer
    - no_promo_posts: bool — connections support promotion but no Posts exist yet
    - can_edit: bool
    - can_publish: bool
    - event: Event
    - action_error: str or None — surfaced on illegal lifecycle transitions (ADR-008 D3)

    Empty/error states (board spec):
    1. has_connections=False → "Connect platforms" CTA
    2. no_promo_posts=True → "No promo posts yet" + Add CTA

    Alpine 3.x: each swapped partial must carry its own x-data root.
    """
    from syndication.engine import render_projection

    event = get_object_or_404(Event, pk=pk)
    user_can_edit = can_edit(request.user, event)
    user_can_publish = can_publish(request.user, event)

    # Collect all projections: listing (direct event FK) + promotion (via posts)
    listing_projections = PlatformProjection.objects.filter(
        source_event=event
    ).select_related("connection")

    post_ids = Post.objects.filter(event=event).values_list("pk", flat=True)
    promotion_projections = PlatformProjection.objects.filter(
        source_post_id__in=post_ids
    ).select_related("connection", "source_post")

    # Combine: listing first, then promotion
    from itertools import chain
    projections = list(chain(listing_projections, promotion_projections))
    projections.sort(key=lambda p: (p.connection.platform, p.kind))

    # Build rendered_rows: attempt render; on ValueError record error flag + error string.
    # rendered_rows is a dict {pk: body_str} for test assertions and template lookups.
    # projection_rows is a list of dicts for easy template iteration.
    # render_error=True is an explicit structural flag (ADR-008 D3: structural, not magic string).
    import logging as _logging
    _logger = _logging.getLogger(__name__)
    rendered_rows = {}
    projection_rows = []
    for proj in projections:
        render_error = False
        try:
            body = render_projection(proj)
        except ValueError as exc:
            # ADR-008 D3: fail loud — surface the error structurally, never zero-fill
            render_error = True
            body = str(exc)
            _logger.warning("render_projection failed for projection %r: %s", proj.pk, exc)
        rendered_rows[proj.pk] = body
        projection_rows.append({"projection": proj, "body": body, "render_error": render_error})

    # --- Empty/error state flags ---
    # has_connections: check if any enabled connections exist for this event's organizers
    from events.models import EventOrganizer
    organizer_profile_ids = EventOrganizer.objects.filter(
        event=event
    ).values_list("profile_id", flat=True)
    has_connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    ).exists()

    # has_promotion_connections: connections whose kinds list contains "promotion"
    # (must filter by kinds, not just any connection — ADR-008 D2/D3)
    all_connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    )
    has_promotion_connections = any(
        "promotion" in (conn.kinds or []) for conn in all_connections
    )
    has_posts = Post.objects.filter(event=event).exists()
    no_promo_posts = has_promotion_connections and not has_posts

    return render(request, "syndication/fragments/event_syndication.html", {
        "event": event,
        "projections": projections,
        "projection_rows": projection_rows,
        "rendered_rows": rendered_rows,
        "has_connections": has_connections,
        "no_promo_posts": no_promo_posts,
        "can_edit": user_can_edit,
        "can_publish": user_can_publish,
        "action_error": action_error,
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


# ---------------------------------------------------------------------------
# Projection lifecycle action views (kb-a4u.5, ADR-016 D5/D6)
#
# Co-equal seam: each view delegates to the matching service function.
# No lifecycle logic lives here — views are thin routing + authz dispatch.
# POST-only; HTMX-aware (return syndication fragment on HX-Request).
# Alpine 3.x: the re-rendered fragment carries its own x-data root.
# ---------------------------------------------------------------------------


def _syndication_fragment_response(request, event):
    """
    Return the event_syndication fragment for the given event.
    Used by lifecycle action views to return a refreshed board after an action.
    Delegates to fragment_event_syndication to avoid duplicating query/flag logic
    (ADR-008 D2: one clear path).
    """
    return fragment_event_syndication(request, pk=event.pk)


import logging as _views_logger_mod
_views_logger = _views_logger_mod.getLogger(__name__)


def _projection_transition_error_response(request, exc, event):
    """
    Return an error-state fragment response for a failed lifecycle transition.
    ADR-008 D3: fail loud — surface the error to the user with a visible error state.
    ADR-008 D2: one clear path — delegate to fragment_event_syndication to avoid
    duplicating query/flag logic.
    """
    _views_logger.warning("Illegal transition for event %r: %s", event.pk, exc)
    return fragment_event_syndication(request, pk=event.pk, action_error=str(exc))


@login_required
def projection_approve(request, pk):
    """
    Approve a draft projection (draft→ready).
    POST only. Calls approve_projection service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state, never swallowed.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    event = _resolve_projection_event(proj)
    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    try:
        approve_projection(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, event)
        return redirect("syndication:event-hub", pk=event.pk)

    if request.headers.get("HX-Request"):
        return _syndication_fragment_response(request, event)
    return redirect("syndication:event-hub", pk=event.pk)


@login_required
def projection_publish(request, pk):
    """
    Publish a ready projection (ready→published). EXPLICIT action — never auto.
    POST only. Calls publish_projection service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state, never swallowed.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    event = _resolve_projection_event(proj)
    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    try:
        publish_projection(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, event)
        return redirect("syndication:event-hub", pk=event.pk)

    if request.headers.get("HX-Request"):
        return _syndication_fragment_response(request, event)
    return redirect("syndication:event-hub", pk=event.pk)


@login_required
def projection_mark_published(request, pk):
    """
    Mark a projection as published (actor-attested, out-of-band posting).
    Used for no-API platforms (e.g. FetLife) where the organizer posts manually.
    POST only. Calls mark_projection_published service (co-equal with API verb).
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state, never swallowed.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    event = _resolve_projection_event(proj)
    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    try:
        mark_projection_published(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, event)
        return redirect("syndication:event-hub", pk=event.pk)

    if request.headers.get("HX-Request"):
        return _syndication_fragment_response(request, event)
    return redirect("syndication:event-hub", pk=event.pk)


@login_required
def projection_override(request, pk):
    """
    Save per-field overrides on a projection (inline edit).
    POST only. Calls save_projection_override service.
    Accepts: body (str), and any other override fields.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    event = _resolve_projection_event(proj)
    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    # Collect override fields from POST data
    override_fields = {}
    if "body" in request.POST:
        override_fields["body"] = request.POST["body"]

    try:
        save_projection_override(user=request.user, projection=proj, **override_fields)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)

    if request.headers.get("HX-Request"):
        return _syndication_fragment_response(request, event)
    return redirect("syndication:event-hub", pk=event.pk)


@login_required
def projection_batch_publish(request, event_pk):
    """
    Batch-publish all ready projections for an event.
    POST only. Calls publish_all_ready_projections service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-016 D6: co-equal seam — same service function as the API verb.
    """
    event = get_object_or_404(Event, pk=event_pk)
    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    try:
        _published, failures = publish_all_ready_projections(user=request.user, event=event)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)

    if failures:
        # ADR-008 D3: fail loud — surface per-projection errors as a visible error state.
        # Format: list all failed projection pks + first error message.
        failed_descs = ", ".join(str(proj.pk) for proj, _ in failures)
        first_exc = failures[0][1]
        error_msg = f"Partial publish failure (projections: {failed_descs}): {first_exc}"
        if request.headers.get("HX-Request"):
            return fragment_event_syndication(request, pk=event.pk, action_error=error_msg)
        # Non-HTMX: redirect with error surfaced via query param is outside scope;
        # follow the same fragment path to make the error visible (ADR-008 D3).
        return fragment_event_syndication(request, pk=event.pk, action_error=error_msg)

    if request.headers.get("HX-Request"):
        return _syndication_fragment_response(request, event)
    return redirect("syndication:event-hub", pk=event.pk)
