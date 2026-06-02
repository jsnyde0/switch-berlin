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
import logging as _views_logger_mod

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
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
    set_event_cover,
    _get_primary_profile_for_user,
    get_publishables_for_profile,
    approve_projection,
    publish_projection,
    mark_projection_published,
    publish_all_ready_projections,
    publish_all_ready_projections_for_post,
    _resolve_projection_event,
    customize,
    copy_to,
    copy_from,
    duplicate,
    reset_to_canonical,
    edit_version,
    content_version_consumers_map,
    _resolve_publishable_for_cv,
)


# ---------------------------------------------------------------------------
# Studio front door (kb-9f1h.1)
# ---------------------------------------------------------------------------


@login_required
def studio(request):
    """
    Organizer studio front door — claimant-gated.

    A claimant sees their publishables (Events + Posts) merged and sorted by
    updated_at descending. A zero-claims user gets 403 (fail loud, ADR-008 D3 —
    never a synthesized empty workspace).

    The gating check mirrors the context processor: uses ProfileClaim directly
    (not the raising _get_primary_profile_for_user) so the error path is 403,
    not an uncaught ValueError.

    The studio shell/rail templates are kb-9f1h.3's job; this view renders a
    minimal placeholder template.
    """
    from organizers.models import ProfileClaim

    claim = (
        ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True)
        .select_related("profile")
        .first()
    )
    if claim is None:
        # Zero-claims user — fail loud, never synthesize an empty workspace
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("No organizer profile. Studio access requires an active profile claim.")

    primary_profile = claim.profile
    raw_publishables = get_publishables_for_profile(primary_profile)

    # Annotate each item with its kind so templates can distinguish Event vs Post
    # without a template filter (ADR-008 D2 — simplest thing that works).
    from events.models import Event as _Event
    publishables = []
    for item in raw_publishables:
        publishables.append({
            "kind": "event" if isinstance(item, _Event) else "post",
            "obj": item,
        })

    return render(request, "syndication/studio.html", {
        "primary_profile": primary_profile,
        "publishables": publishables,
        "current_path": request.path,
    })


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
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            cd = form.cleaned_data
            cover_file = cd.pop("cover_image", None)
            try:
                event = create_event(user=request.user, **cd)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                if cover_file:
                    try:
                        set_event_cover(request.user, event, cover_file)
                    except ValidationError as exc:
                        form.add_error("cover_image", "; ".join(exc.messages))
                        return render(request, "syndication/event_create.html", {"form": form})
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

    HX-Request branching (kb-9f1h.2): when requested via HTMX, return the
    layout-less body fragment (no {% extends %} so it can be swapped into
    #studio-main without nesting <head>/<body>). Normal GET returns the full
    page for deep-link/refresh compatibility.
    """
    event = get_object_or_404(Event, pk=pk)
    user_can_edit = can_edit(request.user, event)
    ctx = {
        "event": event,
        "can_edit": user_can_edit,
    }
    if request.headers.get("HX-Request"):
        return render(request, "syndication/event_hub_fragment.html", ctx)
    return render(request, "syndication/event_hub.html", ctx)


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
        form = EventForm(request.POST, request.FILES, initial={
            "title": event.title,
            "slug": event.slug,
            "start": event.start,
        })
        if form.is_valid():
            cd = form.cleaned_data
            cover_file = cd.pop("cover_image", None)
            update_event(user=request.user, event=event, **cd)
            if cover_file:
                try:
                    set_event_cover(request.user, event, cover_file)
                except ValidationError as exc:
                    form.add_error("cover_image", "; ".join(exc.messages))
                    return render(request, "syndication/event_edit.html", {
                        "form": form,
                        "event": event,
                    })
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
            "category": event.category,
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
    # ADR-010 D1: Switch is the canonical anchor for the event workspace — sort it first.
    # Within listing projections the Switch tab leads; all other channels follow alphabetically.
    # Promotion projections (post-owned) trail listing projections.
    def _event_proj_sort_key(p):
        # Tier 0: Switch listing → canonical anchor, always first
        if p.connection.platform == "switch" and p.kind == PlatformProjection.Kind.LISTING:
            return (0, "", "")
        # Tier 1: remaining listing channels alphabetically
        if p.kind == PlatformProjection.Kind.LISTING:
            return (1, p.connection.platform, "")
        # Tier 2: promotion channels alphabetically
        return (2, p.connection.platform, p.kind)
    projections.sort(key=_event_proj_sort_key)

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

    # Build the per-version consumers map for the "live on <channels>" cue (kb-wz8m.5).
    consumers_map = content_version_consumers_map(event)

    # has_ready_projections: true iff ≥1 projection is in 'ready' status (F3).
    # Guards the "Publish all ready" button — no-op when none are ready (ADR-008 D3).
    has_ready_projections = any(
        row["projection"].status == "ready" for row in projection_rows
    )

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
        "consumers_map": consumers_map,
        "has_ready_projections": has_ready_projections,
    })


# ---------------------------------------------------------------------------
# Post hub and fragment (kb-q4u9.3)
# ---------------------------------------------------------------------------


@login_required
def post_hub(request, pk):
    """
    Post detail hub page — the per-post Typefully workspace.

    Analogous to event_hub but scoped to a Post publishable.
    Composes the post_syndication fragment via HTMX.
    ADR-008 D2: no tab framework speculation — explicit, named fragment.

    HX-Request branching (kb-9f1h.2): when requested via HTMX, return the
    layout-less body fragment (no {% extends %} so it can be swapped into
    #studio-main without nesting <head>/<body>). Normal GET returns the full
    page for deep-link/refresh compatibility.
    """
    post = get_object_or_404(Post, pk=pk)
    event = post.event
    user_can_edit = can_edit(request.user, event)
    ctx = {
        "post": post,
        "event": event,
        "can_edit": user_can_edit,
    }
    if request.headers.get("HX-Request"):
        return render(request, "syndication/post_hub_fragment.html", ctx)
    return render(request, "syndication/post_hub.html", ctx)


@login_required
def fragment_post_syndication(request, pk, *, action_error=None):
    """
    post_syndication fragment: the per-post Typefully composer workspace.

    Shows the post's per-channel ContentVersions (promotion projections).
    Canonical is anchored at a "Source" tab (a post has no native-home channel,
    unlike events which anchor at Switch — kb-q4u9.3 D3, ADR-008 D2).

    Context mirrors fragment_event_syndication but scoped to the post's
    projections and its own canonical ContentVersion.

    Alpine 3.x: each swapped partial must carry its own x-data root.
    """
    from syndication.engine import render_projection
    import logging as _logging

    _logger = _logging.getLogger(__name__)

    post = get_object_or_404(Post, pk=pk)
    event = post.event
    user_can_edit = can_edit(request.user, event)
    user_can_publish = can_publish(request.user, event)

    projections = list(
        PlatformProjection.objects.filter(
            source_post=post
        ).select_related("connection", "source_post")
        .order_by("connection__platform")
    )

    rendered_rows = {}
    projection_rows = []
    for proj in projections:
        render_error = False
        try:
            body = render_projection(proj)
        except ValueError as exc:
            render_error = True
            body = str(exc)
            _logger.warning("render_projection failed for post projection %r: %s", proj.pk, exc)
        rendered_rows[proj.pk] = body
        projection_rows.append({"projection": proj, "body": body, "render_error": render_error})

    consumers_map = content_version_consumers_map(post=post)

    has_ready_projections = any(
        row["projection"].status == "ready" for row in projection_rows
    )

    # kb-9f1h.7: thread studio context to the template so the "Event hub"
    # cross-link uses HTMX swap attrs only when inside the studio shell.
    # The body partial passes ?studio=1 when studio_swap is True; this view
    # reads it and forwards it to post_syndication.html.
    studio_swap = bool(request.GET.get("studio"))

    return render(request, "syndication/fragments/post_syndication.html", {
        "post": post,
        "event": event,
        "projections": projections,
        "projection_rows": projection_rows,
        "rendered_rows": rendered_rows,
        "can_edit": user_can_edit,
        "can_publish": user_can_publish,
        "action_error": action_error,
        "consumers_map": consumers_map,
        "has_ready_projections": has_ready_projections,
        "studio_swap": studio_swap,
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


def _post_syndication_fragment_response(request, post):
    """
    Return the post_syndication fragment for the given post.
    Post-scoped counterpart to _syndication_fragment_response (kb-q4u9.3).
    ADR-008 D2: explicit named delegate, no generic dispatcher.
    """
    return fragment_post_syndication(request, pk=post.pk)


def _publishable_hub_redirect(proj):
    """
    Return the URL for the hub page of the projection's publishable (event or post).

    Dispatches by publishable type so version-op views don't AttributeError when
    a ContentVersion is post-owned (event is null). kb-q4u9.3 item 7.

    listing → event hub
    promotion → post hub (source_post)
    """
    if proj.kind == PlatformProjection.Kind.LISTING:
        return redirect("syndication:event-hub", pk=proj.source_event.pk)
    if proj.kind == PlatformProjection.Kind.PROMOTION:
        return redirect("syndication:post-hub", pk=proj.source_post.pk)
    raise ValueError(f"Unknown projection kind {proj.kind!r}")


def _publishable_hub_redirect_for_cv(content_version):
    """
    Return the hub redirect for the publishable owning a ContentVersion.

    For version-op views that operate on ContentVersion directly (version_edit,
    version_duplicate, version_copy_to) and need to redirect after the op.
    kb-q4u9.3 item 7: dispatch by publishable type (event-hub vs post-hub).
    """
    event, post = _resolve_publishable_for_cv(content_version)
    if event is not None:
        return redirect("syndication:event-hub", pk=event.pk)
    return redirect("syndication:post-hub", pk=post.pk)


def _publishable_fragment_response(request, proj):
    """
    Return the refreshed syndication fragment for the projection's publishable.

    Dispatches by publishable type (event → event_syndication fragment;
    post → post_syndication fragment). kb-q4u9.3 item 7.
    """
    if proj.kind == PlatformProjection.Kind.LISTING:
        return fragment_event_syndication(request, pk=proj.source_event.pk)
    if proj.kind == PlatformProjection.Kind.PROMOTION:
        return fragment_post_syndication(request, pk=proj.source_post.pk)
    raise ValueError(f"Unknown projection kind {proj.kind!r}")


def _publishable_fragment_response_for_cv(request, content_version, action_error=None):
    """
    Return the refreshed syndication fragment for a ContentVersion's publishable.

    For version-op views that operate directly on ContentVersion.
    kb-q4u9.3 item 7: dispatch by publishable type.
    """
    event, post = _resolve_publishable_for_cv(content_version)
    if event is not None:
        return fragment_event_syndication(
            request, pk=event.pk, action_error=action_error
        )
    return fragment_post_syndication(request, pk=post.pk, action_error=action_error)


_views_logger = _views_logger_mod.getLogger(__name__)


def _projection_transition_error_response(request, exc, proj):
    """
    Return an error-state fragment response for a failed lifecycle transition.
    ADR-008 D3: fail loud — surface the error to the user with a visible error state.
    ADR-008 D2: one clear path — delegate to _publishable_fragment_response pattern.

    Dispatches by publishable type (event vs post), mirroring _publishable_fragment_response,
    so that a promotion/post-owned projection error returns the POST fragment rather than
    corrupting the post workspace with an event fragment. (kb-q4u9.3 review finding 1)
    """
    _views_logger.warning("Illegal transition for projection %r: %s", proj.pk, exc)
    if proj.kind == PlatformProjection.Kind.LISTING:
        return fragment_event_syndication(
            request, pk=proj.source_event.pk, action_error=str(exc)
        )
    if proj.kind == PlatformProjection.Kind.PROMOTION:
        return fragment_post_syndication(
            request, pk=proj.source_post.pk, action_error=str(exc)
        )
    raise ValueError(f"Unknown projection kind {proj.kind!r}")


@login_required
def projection_approve(request, pk):
    """
    Approve a draft projection (draft→ready).
    POST only. Calls approve_projection service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state, never swallowed.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        approve_projection(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, proj)
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


@login_required
def projection_publish(request, pk):
    """
    Publish a ready projection (ready→published). EXPLICIT action — never auto.
    POST only. Calls publish_projection service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state, never swallowed.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        publish_projection(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, proj)
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


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
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        mark_projection_published(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # ADR-008 D3: fail loud — surface the error, never return success-shaped output
        if request.headers.get("HX-Request"):
            return _projection_transition_error_response(request, exc, proj)
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


# ---------------------------------------------------------------------------
# Version-op views (kb-wz8m.5, ADR-016 D3/D5)
#
# Each view: resolve objects, gate on login + ownership (via can_edit in
# the service layer), call the matching services.py function, return the
# refreshed syndication fragment on HX-Request.
# ---------------------------------------------------------------------------


@login_required
def projection_customize(request, pk):
    """
    Customize: duplicate the projection's current version into its own row,
    repoint the FK at it (opt-in per-channel divergence).

    POST only. Calls customize(user, projection) service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError → fail-loud error state.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        customize(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, proj)
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


@login_required
def projection_reset_to_canonical(request, pk):
    """
    Reset-to-canonical: repoint the projection's FK back at the publishable's
    canonical ContentVersion (re-enters single-row sharing).

    POST only. Calls reset_to_canonical(user, projection) service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError (missing canonical) → fail loud.
    kb-q4u9.3 item 7: dispatch by publishable type (event-hub vs post-hub).
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        reset_to_canonical(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, proj)
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


@login_required
def version_copy_to(request, pk):
    """
    Copy-to: for each target projection (from POST body), mint an independent
    new ContentVersion copied from source_version and repoint that projection's FK.

    POST only. Calls copy_to(user, source_version, target_projections) service.
    POST body: target_projection_pks — comma-separated or multi-value projection PKs.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError (cross-event, etc.) → fail loud.
    """
    from syndication.models import ContentVersion

    source_version = get_object_or_404(ContentVersion, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect_for_cv(source_version)

    # Parse target_projection_pks: supports comma-separated string or multi-value
    raw_pks = request.POST.getlist("target_projection_pks")
    if not raw_pks:
        raw_pks = request.POST.get("target_projection_pks", "").split(",")
    target_pks = [p.strip() for p in raw_pks if p.strip()]

    if not target_pks:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(request, source_version)
        return _publishable_hub_redirect_for_cv(source_version)

    target_projections = list(
        PlatformProjection.objects.filter(pk__in=target_pks)
    )

    try:
        copy_to(user=request.user, source_version=source_version, target_projections=target_projections)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(
                request, source_version, action_error=str(exc)
            )
        return _publishable_hub_redirect_for_cv(source_version)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response_for_cv(request, source_version)
    return _publishable_hub_redirect_for_cv(source_version)


@login_required
def version_edit(request, pk):
    """
    Edit-version: mutate a pre-publish version's editorial fields (body, headline, etc.)
    and flip provenance to 'manual'.

    POST only. Calls edit_version(user, version, **fields) service.
    POST body: body (and optionally headline, imagery, cta, voice).
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError (frozen consumers) → fail loud.
    """
    from syndication.models import ContentVersion

    version = get_object_or_404(ContentVersion, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect_for_cv(version)

    # Collect editorial fields from POST (only known fields; services.py filters unknowns)
    fields = {}
    for field_name in ("body", "headline", "imagery", "cta", "voice"):
        if field_name in request.POST:
            fields[field_name] = request.POST[field_name]

    try:
        edit_version(user=request.user, version=version, **fields)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(
                request, version, action_error=str(exc)
            )
        return _publishable_hub_redirect_for_cv(version)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response_for_cv(request, version)
    return _publishable_hub_redirect_for_cv(version)


@login_required
def version_duplicate(request, pk):
    """
    Duplicate: create a new independent ContentVersion copied from the given
    version (same event, copied editorial fields, fresh row).

    POST only. Calls duplicate(user, version) service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError → fail loud.
    """
    from syndication.models import ContentVersion

    version = get_object_or_404(ContentVersion, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect_for_cv(version)

    try:
        duplicate(user=request.user, version=version)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(
                request, version, action_error=str(exc)
            )
        return _publishable_hub_redirect_for_cv(version)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response_for_cv(request, version)
    return _publishable_hub_redirect_for_cv(version)


@login_required
def version_copy_from(request, pk):
    """
    Copy-from: repoint the target projection at a NEW independent copy taken
    from source_version (mint a new row from source, FK the projection to it).

    POST only. Calls copy_from(user, projection, source_version) service.
    POST body: source_version_pk — the ContentVersion to copy from.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError → fail loud.
    """
    from syndication.models import ContentVersion

    projection = get_object_or_404(PlatformProjection, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect(projection)

    source_version_pk = request.POST.get("source_version_pk", "").strip()
    if not source_version_pk:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, projection)
        return _publishable_hub_redirect(projection)

    source_version = get_object_or_404(ContentVersion, pk=source_version_pk)

    try:
        copy_from(user=request.user, projection=projection, source_version=source_version)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, projection)
        return _publishable_hub_redirect(projection)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, projection)
    return _publishable_hub_redirect(projection)


@login_required
def review_all(request, event_pk):
    """
    Review-all side-by-side surface (kb-wz8m.6).

    Read-only cross-channel review: every channel's rendered assigned-version
    preview laid out simultaneously in a responsive side-by-side grid.

    Primary use case: ToS-divergence check — confirm that divergent variants
    (e.g. censored vs uncensored body for different platforms) are EACH correct
    before publish. Also includes the per-channel publish controls (reuse from
    board — no new publish path).

    Authorization: same can_edit / can_publish gating as the board (ADR-017 D2).
    Non-claimants are shown a 403.

    Context-building mirrors fragment_event_syndication to guarantee identical
    rendering (ADR-008 D2: one clear path for projection row construction).

    ADR-004: on-stack (HTMX + Alpine + Tailwind, no React).
    ADR-008 D3: render errors surface as visible error panels, not blank cells.
    """
    from itertools import chain
    import logging as _logging
    from syndication.engine import render_projection

    _logger = _logging.getLogger(__name__)

    event = get_object_or_404(Event, pk=event_pk)

    # Authorization: must be a co-claimant (same gate as the board)
    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {"event": event}, status=403)

    user_can_edit = True  # already confirmed above
    user_can_publish = can_publish(request.user, event)

    # Collect projections — same logic as fragment_event_syndication
    listing_projections = PlatformProjection.objects.filter(
        source_event=event
    ).select_related("connection", "content_version")

    post_ids = Post.objects.filter(event=event).values_list("pk", flat=True)
    promotion_projections = PlatformProjection.objects.filter(
        source_post_id__in=post_ids
    ).select_related("connection", "source_post", "content_version")

    projections = list(chain(listing_projections, promotion_projections))
    # ADR-010 D1: Switch leads (same ordering as fragment_event_syndication)
    def _review_proj_sort_key(p):
        if p.connection.platform == "switch" and p.kind == PlatformProjection.Kind.LISTING:
            return (0, "", "")
        if p.kind == PlatformProjection.Kind.LISTING:
            return (1, p.connection.platform, "")
        return (2, p.connection.platform, p.kind)
    projections.sort(key=_review_proj_sort_key)

    # Build projection_rows — same fail-loud pattern as fragment_event_syndication
    projection_rows = []
    for proj in projections:
        render_error = False
        try:
            body = render_projection(proj)
        except ValueError as exc:
            render_error = True
            body = str(exc)
            _logger.warning("render_projection failed for projection %r: %s", proj.pk, exc)
        projection_rows.append({"projection": proj, "body": body, "render_error": render_error})

    return render(request, "syndication/review_all.html", {
        "event": event,
        "projection_rows": projection_rows,
        "can_edit": user_can_edit,
        "can_publish": user_can_publish,
    })


@login_required
def agent_pairing_page(request):
    """
    Agent pairing page (kb-a4u.6).

    Allows a logged-in facilitator to start the agent-pairing flow:
    GET: render the pairing form (instructions + "Generate pairing token" button).
    POST: call register_agent_credential to mint a one-time pairing token, then
          render the page with the pairing token shown once for the facilitator
          to hand off to their agent.

    The page shows the PAIRING TOKEN (not the Bearer key) — the Bearer key is
    only issued at redemption (agents/redeem). The long-lived secret never transits
    the facilitator's clipboard.

    ADR-004: Django + HTMX + Alpine.
    Each swapped Alpine partial needs its own x-data root (known repo gotcha).
    Page kept simple — no HTMX swaps needed here (single-action flow).
    """
    from syndication.services import register_agent_credential

    pairing_token = None

    if request.method == "POST":
        _token_record, pairing_token = register_agent_credential(request.user)

    return render(request, "syndication/agent_pairing.html", {
        "pairing_token": pairing_token,
    })


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


@login_required
def post_projection_batch_publish(request, pk):
    """
    Batch-publish all ready promotion projections for a single post.

    POST only. Calls publish_all_ready_projections_for_post service.
    HTMX-aware: returns refreshed post_syndication fragment on HX-Request.

    Post-scoped counterpart to projection_batch_publish (kb-q4u9.6 MATERIAL FIX 1).
    The event-scoped view wires the whole event; this view scopes to one post.
    On success returns the POST fragment (_post_syndication_fragment_response),
    NOT the event fragment — the post template's hx-target is #post-syndication.
    """
    post = get_object_or_404(Post, pk=pk)
    if request.method != "POST":
        return redirect("syndication:post-hub", pk=post.pk)

    try:
        _published, failures = publish_all_ready_projections_for_post(
            user=request.user, post=post
        )
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)

    if failures:
        # ADR-008 D3: fail loud — surface per-projection errors as visible error state.
        failed_descs = ", ".join(str(proj.pk) for proj, _ in failures)
        first_exc = failures[0][1]
        error_msg = (
            f"Partial publish failure (projections: {failed_descs}): {first_exc}"
        )
        return fragment_post_syndication(request, pk=post.pk, action_error=error_msg)

    if request.headers.get("HX-Request"):
        return _post_syndication_fragment_response(request, post)
    return redirect("syndication:post-hub", pk=post.pk)
