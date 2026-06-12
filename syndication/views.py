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
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string

from events.models import Event
from events.og import card_image_url
from syndication.authz import can_edit, can_publish
from syndication.forms import EventForm, PlatformConnectionForm, PostForm
from syndication.models import PlatformConnection, PlatformProjection, Post
from syndication.services import (
    _get_primary_profile_for_user,
    _resolve_projection_event,
    _resolve_publishable_for_cv,
    _supports_post_promotion,
    add_projection,
    approve_projection,
    content_version_consumers_map,
    copy_to,
    create_event,
    create_post,
    customize,
    detach_and_edit,
    duplicate,
    edit_after_publish_policy,
    edit_version,
    get_publishables_for_profile,
    mark_projection_published,
    publish_all_ready_projections,
    publish_all_ready_projections_for_post,
    publish_projection,
    publish_projection_direct,
    reset_to_canonical,
    set_event_cover,
    sync_projection_from,
    update_event,
)

_views_logger = _views_logger_mod.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rail OOB helper (kb-96tn.6 gap closure)
# ---------------------------------------------------------------------------


def _render_rail_oob(request):
    """
    Render the studio rail partial with hx-swap-oob="true" so HTMX replaces
    the <aside id="studio-rail"> element after an inline-create success response.

    Returns the rendered OOB HTML string (to be appended to the main response body).
    Returns empty string when the user has no profile claim (fail-soft — inline
    create already succeeded; don't corrupt the response for a missing rail claim).

    Mirrors the profile/publishables context-building in studio() and event_hub().
    ADR-008 D2: one clear path — no separate context-builder abstraction; the
    pattern is simple enough to inline (three-line clone, not third diverging caller).
    """
    from events.models import Event as _Event
    from organizers.models import ProfileClaim

    claim = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        return ""

    primary_profile = claim.profile
    raw_publishables = get_publishables_for_profile(primary_profile)
    publishables = [{"kind": "event" if isinstance(item, _Event) else "post", "obj": item} for item in raw_publishables]

    return render_to_string(
        "syndication/fragments/_studio_rail_oob.html",
        {
            "primary_profile": primary_profile,
            "publishables": publishables,
            "current_path": request.path,
            "oob": True,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Sibling body OOB helper (kb-ciqf)
# ---------------------------------------------------------------------------


def _render_sibling_body_oob_fragments(request, projections, *, skip_pk=None, is_post_composer=False):
    """
    Render OOB body-wrapper fragments for a list of projections, skipping the one
    with pk == skip_pk (cursor protection: do NOT clobber the textarea the user
    is actively typing in).

    Each fragment targets `#channel-body-wrapper-<pk>` with hx-swap-oob="true"
    so HTMX replaces the body form content in non-active tabs without a reload.

    Per-row try/except ValueError containment mirrors version_edit lines ~1807-1829
    (ADR-008 D3: a corrupt sibling must not abort the active edit).

    Returns a list of rendered OOB HTML strings (to be joined into the response).
    """
    from syndication.engine import render_projection

    fragments = []
    for proj in projections:
        if skip_pk is not None and proj.pk == skip_pk:
            continue
        try:
            body = render_projection(proj)
        except ValueError as _exc:
            _views_logger.warning(
                "_render_sibling_body_oob_fragments: skipping body OOB for projection %r "
                "(render_projection failed — sibling must not break active edit): %s",
                proj.pk,
                _exc,
            )
            continue
        fragments.append(
            render_to_string(
                "syndication/fragments/_channel_body_oob.html",
                {
                    "proj": proj,
                    "body": body,
                    "is_post_composer": is_post_composer,
                    "oob": True,
                },
                request=request,
            )
        )
    return fragments


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

    claim = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        # Zero-claims user — fail loud, never synthesize an empty workspace.
        # Render the styled 403 template (status=403) rather than a bare string,
        # mirroring the other syndication 403 gates (e.g. connections views).
        return render(
            request,
            "syndication/403.html",
            {"detail": "No organizer profile. Studio access requires an active profile claim."},
            status=403,
        )

    primary_profile = claim.profile
    raw_publishables = get_publishables_for_profile(primary_profile)

    # Annotate each item with its kind so templates can distinguish Event vs Post
    # without a template filter (ADR-008 D2 — simplest thing that works).
    from events.models import Event as _Event

    publishables = []
    for item in raw_publishables:
        publishables.append(
            {
                "kind": "event" if isinstance(item, _Event) else "post",
                "obj": item,
            }
        )

    return render(
        request,
        "syndication/studio.html",
        {
            "primary_profile": primary_profile,
            "publishables": publishables,
            "current_path": request.path,
        },
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

    HX-Request branching (kb-96tn.6): when requested via HTMX, return the
    layout-less form fragment (no {% extends %}) for swapping into #studio-main.
    On POST success with HX-Request, return the event hub fragment instead of
    a full-page redirect (keeps rail visible, no full reload).
    """
    is_htmx = bool(request.headers.get("HX-Request"))

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
                        template = (
                            "syndication/event_create_fragment.html" if is_htmx else "syndication/event_create.html"
                        )
                        return render(request, template, {"form": form})
                if is_htmx:
                    # HTMX success: return the event hub fragment + an OOB rail
                    # update so the left rail reflects the new event without a
                    # full-page reload (kb-96tn.6 gap closure).
                    from django.urls import reverse

                    hub_url = reverse("syndication:event-hub", kwargs={"pk": event.pk})
                    hub_html = render_to_string(
                        "syndication/event_hub_fragment.html",
                        {"event": event, "can_edit": can_edit(request.user, event)},
                        request=request,
                    )
                    rail_oob = _render_rail_oob(request)
                    response = HttpResponse(hub_html + rail_oob, content_type="text/html")
                    response["HX-Push-Url"] = hub_url
                    return response
                return redirect("syndication:event-hub", pk=event.pk)
    else:
        form = EventForm()

    if is_htmx:
        return render(request, "syndication/event_create_fragment.html", {"form": form})
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

    kb-shzi.2 (BUG 1 fix): the full-page response now renders the studio
    two-pane shell (rail + #studio-main) so that direct GET / refresh /
    deep-link all show the rail — not just in-studio HTMX navigation.
    Rail context (primary_profile, publishables, current_path) is populated
    via the same pattern as the studio front-door view.
    """
    event = get_object_or_404(Event, pk=pk)
    user_can_edit = can_edit(request.user, event)
    ctx = {
        "event": event,
        "can_edit": user_can_edit,
    }
    if request.headers.get("HX-Request"):
        return render(request, "syndication/event_hub_fragment.html", ctx)

    # Full-page render: populate the studio shell rail context (kb-shzi.2).
    # Fail loud when there is no claim — mirror the studio view's no-claim
    # handling (ADR-008 D3: never synthesize a broken rail on missing data).
    from events.models import Event as _Event
    from organizers.models import ProfileClaim

    claim = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        # Zero-claims user — fail loud, never render a broken rail (ADR-008 D3).
        return render(
            request,
            "syndication/403.html",
            {"detail": "No organizer profile. Studio access requires an active profile claim."},
            status=403,
        )

    primary_profile = claim.profile
    raw_publishables = get_publishables_for_profile(primary_profile)
    publishables = [{"kind": "event" if isinstance(item, _Event) else "post", "obj": item} for item in raw_publishables]
    ctx.update(
        {
            "primary_profile": primary_profile,
            "publishables": publishables,
            "current_path": request.path,
        }
    )

    return render(request, "syndication/event_hub.html", ctx)


@login_required
def event_hub_edit(request, pk):
    """
    Edit an Event via the web form.
    GET: render form pre-populated with current values.
    POST: call update_event service (co-equal with API), redirect to hub on success.
    HTMX-aware (kb-ide0.1): on HX-Request, return the event_syndication fragment
    so the edit-in-place card re-renders without a full page reload.
    """
    event = get_object_or_404(Event, pk=pk)
    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {"event": event}, status=403)

    if request.method == "POST":
        form = EventForm(
            request.POST,
            request.FILES,
            initial={
                "title": event.title,
                "slug": event.slug,
                "start": event.start,
            },
        )
        if form.is_valid():
            cd = form.cleaned_data
            cover_file = cd.pop("cover_image", None)
            # FIX 2 (ADR-008 D3): For HTMX/partial-form POSTs (card edit-in-place), only
            # update fields that were explicitly present in the submitted POST data.
            # Boolean checkbox fields are absent from POST when unchecked — on a partial
            # form, "absent" means "user didn't touch it", not "user set it to False".
            # The full-page edit (non-HTMX) submits all fields, so no filtering needed.
            if request.headers.get("HX-Request"):
                submitted_keys = set(request.POST.keys())
                cd = {k: v for k, v in cd.items() if k in submitted_keys}
            update_event(user=request.user, event=event, **cd)
            if cover_file:
                try:
                    set_event_cover(request.user, event, cover_file)
                except ValidationError as exc:
                    form.add_error("cover_image", "; ".join(exc.messages))
                    return render(
                        request,
                        "syndication/event_edit.html",
                        {
                            "form": form,
                            "event": event,
                        },
                    )
            if request.headers.get("HX-Request"):
                # kb-nexw.2: emit OOB dirty-banner + Re-publish CTA for each
                # published LISTING projection of this event so the dirty state
                # reaches the DOM even though hx-swap="none" discards the
                # main response body (EventForm autosave autosave pattern).
                #
                # The full fragment_event_syndication() returned previously was
                # silently discarded by HTMX — the OOB swap is the only path
                # that survives hx-swap="none" (mirrors projection_detach_and_edit
                # ~1498-1546 and version_edit ~1684-1773).
                #
                # Per-row try/except ValueError containment (mirrors version_edit
                # ~1737-1759): a corrupt sibling must not abort the active edit.
                # kb-ciqf Fix 1: query ALL listing projections for this event so we
                # can emit body OOBs for track-live channels (not just published ones).
                _all_listing_projs = list(
                    PlatformProjection.objects.filter(
                        source_event=event,
                        kind=PlatformProjection.Kind.LISTING,
                    ).select_related(
                        "connection",
                        "content_version",
                        "source_event",
                        "source_event__venue",
                        "sync_source",
                        "sync_source__connection",
                    )
                )
                _published_listing_projs = [
                    _p
                    for _p in _all_listing_projs
                    if _p.status == PlatformProjection.Status.PUBLISHED and _p.frozen_content is not None
                ]
                _oob_fragments = []
                for _proj in _published_listing_projs:
                    _target = "#event-syndication"
                    _oob_fragments.append(
                        render_to_string(
                            "syndication/fragments/_sync_bar.html",
                            {"proj": _proj, "fragment_target": _target, "oob": True},
                            request=request,
                        )
                    )
                    try:
                        _content_is_dirty = _proj.is_dirty
                        if _content_is_dirty:
                            _policy = edit_after_publish_policy(_proj.connection.platform)
                            _is_dirty = _policy == "dirty_then_republish"
                        else:
                            _is_dirty = False
                        _publishable = _resolve_projection_event(_proj)
                        _user_can_publish = can_publish(request.user, _publishable)
                    except ValueError as _dirty_exc:
                        _views_logger.warning(
                            "event_hub_edit: skipping dirty-state OOB for projection %r "
                            "(corrupt data — sibling must not break active edit): %s",
                            _proj.pk,
                            _dirty_exc,
                        )
                        continue
                    _oob_fragments.append(
                        render_to_string(
                            "syndication/fragments/_channel_dirty_oob.html",
                            {
                                "proj": _proj,
                                "is_dirty": _is_dirty,
                                "oob": True,
                                "can_publish": _user_can_publish,
                                "fragment_target": _target,
                            },
                            request=request,
                        )
                    )
                # kb-ciqf Fix 1: emit body OOBs for all non-switch listing projections
                # (Switch listing uses the EventForm card, not a textarea). The event
                # master edit updates Event fields, so track-live channels recompose from
                # the updated event. OOB body updates surface the new content live without
                # a reload. The Switch EventForm is the edited entity — no skip_pk needed.
                _body_oob_projs = [_p for _p in _all_listing_projs if _p.connection.platform != "switch"]
                _oob_fragments.extend(
                    _render_sibling_body_oob_fragments(
                        request,
                        _body_oob_projs,
                        is_post_composer=False,
                    )
                )
                return HttpResponse("\n".join(_oob_fragments), content_type="text/html")
            return redirect("syndication:event-hub", pk=event.pk)
    else:
        # Include ALL editable fields so edit-load round-trips stored values.
        # ADR-008 D3: missing fields here = silent data loss on save (wipe on re-save).
        form = EventForm(
            initial={
                "title": event.title,
                "slug": event.slug,
                "start": event.start,
                "end": event.end,
                "description": event.description,
                "venue": event.venue_id,
                "tags": ", ".join(event.tags.values_list("slug", flat=True)) if event.pk else "",
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
            }
        )

    return render(
        request,
        "syndication/event_edit.html",
        {
            "form": form,
            "event": event,
        },
    )


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
    return render(
        request,
        "syndication/fragments/event_facts.html",
        {
            "event": event,
            "can_edit": user_can_edit,
        },
    )


@login_required
def fragment_event_posts(request, pk):
    """
    event_posts fragment: list of promotional Posts + inline add form.
    HTMX target for partial refresh after a Post is added.
    """
    event = get_object_or_404(Event, pk=pk)
    posts = Post.objects.filter(event=event).order_by("-created_at")
    user_can_edit = can_edit(request.user, event)
    return render(
        request,
        "syndication/fragments/event_posts.html",
        {
            "event": event,
            "posts": posts,
            "can_edit": user_can_edit,
            "post_form": PostForm(),
        },
    )


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

    # kb-ide0.3 D3: Event composer shows ONLY listing projections (connections
    # whose kinds contains "listing"). Promotion projections (post-owned, via
    # PlatformConnection.kinds contains "promotion" only) belong to the post
    # composer, not the event composer. This matches the eager-creation filter
    # in _eager_create_listing_projections (same field, no new abstraction —
    # ADR-008 D2). No hard-coded platform names: kinds drives the filter.
    listing_projections = PlatformProjection.objects.filter(source_event=event).select_related("connection")

    # Filter: only connections whose kinds includes "listing" (drop promotion-only tabs)
    projections = [p for p in listing_projections if "listing" in (p.connection.kinds or [])]

    # ADR-010 D1: Switch is the canonical anchor for the event workspace — sort it first.
    # Within listing projections the Switch tab leads; all other channels follow alphabetically.
    def _event_proj_sort_key(p):
        # Tier 0: Switch listing → canonical anchor, always first
        if p.connection.platform == "switch" and p.kind == PlatformProjection.Kind.LISTING:
            return (0, "", "")
        # Tier 1: remaining listing channels alphabetically
        return (1, p.connection.platform, "")

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
        # Compute is_dirty for this projection (ADR-016 D5 edit-after-publish).
        # For published projections: compares current effective content to frozen_content.
        # For non-published projections: always False (no raise).
        # For published+null frozen_content (invariant violation): surface as error.
        #
        # ADR-016 D5 / ADR-003 cheap foresight: gate the dirty AFFORDANCE through
        # edit_after_publish_policy so the seam is live — if a platform resolves a
        # non-dirty_then_republish policy, the affordance is suppressed without
        # touching the template.  is_dirty (the content-diff fact) is unchanged;
        # only the rendered affordance is gated.  ADR-008 D2: only dirty_then_republish
        # is implemented; alternate branches (lock/auto) are not built here.
        is_dirty = False
        try:
            content_is_dirty = proj.is_dirty
        except ValueError as exc:
            # Invariant violation (published+null frozen_content): surface as render_error.
            render_error = True
            if not body:
                body = str(exc)
            _logger.warning("is_dirty check failed for projection %r: %s", proj.pk, exc)
            content_is_dirty = False
        if content_is_dirty:
            policy = edit_after_publish_policy(proj.connection.platform)
            is_dirty = policy == "dirty_then_republish"
        # Compute editable flag for this projection (kb-kgza.3 ADR-016 D5).
        # A published projection is editable when the platform's policy allows
        # edit-after-publish (dirty_then_republish). Draft projections are always
        # editable (the existing status-gate already covers that). The flag is
        # threaded from here so the template does NOT inline policy logic.
        if proj.status == PlatformProjection.Status.PUBLISHED:
            _edit_policy = edit_after_publish_policy(proj.connection.platform)
            editable = _edit_policy == "dirty_then_republish"
        else:
            editable = False  # draft: handled by the existing `can_edit and proj.status == 'draft'` gate
        rendered_rows[proj.pk] = body
        # kb-6d7o.3: For Telegram projections, compute the card image URL so the
        # Telegram branch of _channel_preview.html can render the link-preview card.
        # Uses events.og.card_image_url — the same resolver the live event-page
        # og:image tag calls (ADR-003 single resolution point). preview == reality
        # is structurally guaranteed: both paths call the same function, not a
        # coincidence of parallel implementations.
        row_card_image_url = None
        if proj.connection.platform == "telegram":
            row_card_image_url = card_image_url(event, request)
        projection_rows.append(
            {
                "projection": proj,
                "body": body,
                "render_error": render_error,
                "is_dirty": is_dirty,
                "editable": editable,
                "card_image_url": row_card_image_url,
            }
        )

    # --- Empty/error state flags ---
    # has_connections: check if any enabled connections exist for this event's organizers
    from events.models import EventOrganizer

    organizer_profile_ids = EventOrganizer.objects.filter(event=event).values_list("profile_id", flat=True)
    has_connections = PlatformConnection.objects.filter(
        organizer_id__in=organizer_profile_ids,
        enabled=True,
    ).exists()

    # has_promotion_connections: connections whose kinds list contains "promotion"
    # (must filter by kinds, not just any connection — ADR-008 D2/D3)
    # Materialise to a list so we can reuse across multiple passes without extra DB queries.
    all_connections = list(
        PlatformConnection.objects.filter(
            organizer_id__in=organizer_profile_ids,
            enabled=True,
        )
    )
    has_promotion_connections = any(
        "promotion" in (conn.kinds or []) and _supports_post_promotion(conn.platform) for conn in all_connections
    )
    has_posts = Post.objects.filter(event=event).exists()
    no_promo_posts = has_promotion_connections and not has_posts

    # Build the per-version consumers map for the "live on <channels>" cue (kb-wz8m.5).
    consumers_map = content_version_consumers_map(event)

    # has_ready_projections: true iff ≥1 projection is in 'ready' status (F3).
    # Guards the "Publish all ready" button — no-op when none are ready (ADR-008 D3).
    has_ready_projections = any(row["projection"].status == "ready" for row in projection_rows)

    # kb-ide0.1: thread studio context to the template (same pattern as
    # fragment_post_syndication). The event_syndication template gates
    # studio-specific HTMX attrs on this flag. Without ?studio=1 the fragment
    # serves the standalone context (no hx-target="#studio-main" emitted).
    studio_swap = bool(request.GET.get("studio"))

    # kb-ide0.1 D2: pre-populate the EventForm with the event's current field
    # values for the Switch listing edit-in-place card. The form renders structured
    # inputs (title, description, start, etc.) inside the styled listing card.
    # ADR-008 D2: simplest path — same form used by event_hub_edit, same initial dict.
    import json as _json

    event_form = EventForm(
        initial={
            "title": event.title,
            "slug": event.slug,
            "start": event.start,
            "end": event.end,
            "description": event.description,
            "venue": event.venue_id,
            "tags": ", ".join(event.tags.values_list("slug", flat=True)) if event.pk else "",
            "dress_code": event.dress_code,
            "content_warnings": (
                _json.dumps(event.content_warnings)
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
        }
    )
    # kb-y209.1: all 16 previously-hidden fields are now rendered as editable widgets
    # in progressive-disclosure sections in the Switch listing card. The HiddenInput
    # override loop is removed — every field keeps its native widget.

    # kb-shzi.2 (BUG 2 fix): resolve selected_pk so the re-rendered fragment
    # re-opens the same channel tab. The action POSTs (customize/reset/duplicate)
    # submit selected_pk as a hidden input; we read it from POST (or GET fallback),
    # validate it against the current projection set, and fall back to first_pk
    # if the pk is absent or no longer exists.
    # The autosave path (hx-swap="none") does NOT use this — no change there.
    raw_selected = request.POST.get("selected_pk") or request.GET.get("selected_pk") or ""
    projection_pks = {str(proj.pk) for proj in projections}
    if raw_selected and raw_selected in projection_pks:
        selected_pk = int(raw_selected)
    else:
        selected_pk = None  # None → template falls back to first_pk

    # kb-96tn.4: available_connections — enabled connections that support 'listing'
    # but have no projection yet for this event. Powers the "…" toggle dropdown.
    # Excludes connections already projected (any status — including published).
    already_projected_conn_ids = set(p.connection_id for p in projections)
    available_connections = [
        conn
        for conn in all_connections
        if "listing" in (conn.kinds or []) and conn.pk not in already_projected_conn_ids
    ]

    return render(
        request,
        "syndication/fragments/event_syndication.html",
        {
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
            "studio_swap": studio_swap,
            "event_form": event_form,
            "selected_pk": selected_pk,
            "available_connections": available_connections,
        },
    )


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

    kb-shzi.2 (BUG 1 fix): the full-page response now renders the studio
    two-pane shell (rail + #studio-main) so that direct GET / refresh /
    deep-link all show the rail. Same pattern as event_hub.
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

    # Full-page render: populate the studio shell rail context (kb-shzi.2).
    # Fail loud when there is no claim — mirror the studio view's no-claim
    # handling (ADR-008 D3: never synthesize a broken rail on missing data).
    from events.models import Event as _Event
    from organizers.models import ProfileClaim

    claim = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        # Zero-claims user — fail loud, never render a broken rail (ADR-008 D3).
        return render(
            request,
            "syndication/403.html",
            {"detail": "No organizer profile. Studio access requires an active profile claim."},
            status=403,
        )

    primary_profile = claim.profile
    raw_publishables = get_publishables_for_profile(primary_profile)
    publishables = [{"kind": "event" if isinstance(item, _Event) else "post", "obj": item} for item in raw_publishables]
    ctx.update(
        {
            "primary_profile": primary_profile,
            "publishables": publishables,
            "current_path": request.path,
        }
    )

    return render(request, "syndication/post_hub.html", ctx)


@login_required
def fragment_post_syndication(request, pk, *, action_error=None):
    """
    post_syndication fragment: the per-post Typefully composer workspace.

    Shows the post's per-channel ContentVersions (promotion projections only —
    connections whose kinds contains "promotion"; listing-only connections are
    excluded, symmetric with the event composer's listing filter).

    ADR-010 D1 (kb-ide0.4): A Post has no native-home channel, so its canonical
    is an abstract "Source" anchor. The Source tab is rendered FIRST in the tab row
    — it is the default sync source for all secondary channels. source_row carries
    the canonical ContentVersion body for this tab.

    Context mirrors fragment_event_syndication but scoped to the post's
    projections and its own canonical ContentVersion.

    Alpine 3.x: each swapped partial must carry its own x-data root.
    """
    import logging as _logging

    from syndication.engine import render_projection
    from syndication.models import ContentVersion as _ContentVersion

    _logger = _logging.getLogger(__name__)

    post = get_object_or_404(Post, pk=pk)
    event = post.event
    user_can_edit = can_edit(request.user, event)
    user_can_publish = can_publish(request.user, event)

    # kb-ide0.3 D3: Post composer shows ONLY promotion projections (connections
    # whose kinds contains "promotion"). Listing-only connections belong to the
    # event composer, not the post composer. No hard-coded platform names:
    # kinds drives the filter — symmetric with the event-side "listing" guard
    # in fragment_event_syndication (ADR-008 D2/D3 — defend the invariant).
    all_post_projections = list(
        PlatformProjection.objects.filter(source_post=post)
        .select_related("connection", "source_post")
        .order_by("connection__platform")
    )
    projections = [
        p
        for p in all_post_projections
        if "promotion" in (p.connection.kinds or []) and _supports_post_promotion(p.connection.platform)
    ]

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
        # Compute is_dirty for this projection (ADR-016 D5 edit-after-publish).
        # Gate the dirty affordance through edit_after_publish_policy (ADR-003 seam).
        is_dirty = False
        try:
            content_is_dirty = proj.is_dirty
        except ValueError as exc:
            render_error = True
            if not body:
                body = str(exc)
            _logger.warning("is_dirty check failed for post projection %r: %s", proj.pk, exc)
            content_is_dirty = False
        if content_is_dirty:
            policy = edit_after_publish_policy(proj.connection.platform)
            is_dirty = policy == "dirty_then_republish"
        # Compute editable flag for this projection (kb-kgza.3 ADR-016 D5).
        # Symmetric with fragment_event_syndication: published → policy-gated,
        # draft → handled by the existing status-gate in _channel_editor.html.
        if proj.status == PlatformProjection.Status.PUBLISHED:
            _edit_policy = edit_after_publish_policy(proj.connection.platform)
            editable = _edit_policy == "dirty_then_republish"
        else:
            editable = False  # draft: handled by the existing `can_edit and proj.status == 'draft'` gate
        rendered_rows[proj.pk] = body
        projection_rows.append(
            {
                "projection": proj,
                "body": body,
                "render_error": render_error,
                "is_dirty": is_dirty,
                "editable": editable,
            }
        )

    consumers_map = content_version_consumers_map(post=post)

    has_ready_projections = any(row["projection"].status == "ready" for row in projection_rows)

    # kb-9f1h.7: thread studio context to the template so the "Event hub"
    # cross-link uses HTMX swap attrs only when inside the studio shell.
    # The body partial passes ?studio=1 when studio_swap is True; this view
    # reads it and forwards it to post_syndication.html.
    studio_swap = bool(request.GET.get("studio"))

    # ADR-010 D1 (kb-ide0.4): Resolve the post's canonical ContentVersion for
    # the "Source" anchor tab (the abstract master a post anchors at, since
    # posts have no native-home channel). Fail loud if absent (A1 invariant) —
    # a missing canonical is a data bug (ADR-008 D3), not a silent gap.
    try:
        source_cv = _ContentVersion.objects.get(post=post, name="canonical")
        source_body = source_cv.body if source_cv.body is not None else post.body
    except _ContentVersion.DoesNotExist:
        # A1 invariant violated — surface the error rather than hiding it.
        source_cv = None
        source_body = post.body  # Fallback to Post.body for display; log the violation.
        _logger.warning(
            "fragment_post_syndication: post %r has no canonical ContentVersion. "
            "A1 invariant violated — every post must be seeded with a canonical CV. "
            "(ADR-008 D3: fail loud). Falling back to post.body for Source tab display.",
            post.pk,
        )

    source_row = {
        "content_version": source_cv,
        "body": source_body,
    }

    # kb-kgza.3 FIX 1: Compute source_editable — gates the master/source panel
    # editor in post_syndication.html so it is INTENTIONALLY editable rather than
    # always-on-but-broken.
    #
    # The master/source tab editor is editable when:
    #   (a) No projections yet — no consumers, the canonical CV can always be edited.
    #   (b) At least one draft consumer — the regular pre-publish editing path.
    #   (c) All consumers are non-draft AND the edit_after_publish policy for all
    #       channels is dirty_then_republish — the edit-after-publish broadcast path
    #       (ADR-016 D5). The view fix passes _allow_edit_after_publish=True in this
    #       case; the template gate ensures the textarea is shown intentionally.
    #
    # source_editable = False only when all consumers are non-draft AND at least one
    # channel's policy disallows post-publish editing (no such platform at V0, but
    # the seam is explicit per ADR-003 cheap foresight).
    if not projections:
        # No projection consumers yet — canonical CV can be freely edited.
        source_editable = True
    elif any(p.status == PlatformProjection.Status.DRAFT for p in projections):
        # At least one draft consumer — standard editing path, always allowed.
        source_editable = True
    else:
        # All consumers are non-draft (published/ready/failed).
        # Editable only when all projections' platforms support dirty_then_republish.
        source_editable = all(
            edit_after_publish_policy(proj.connection.platform) == "dirty_then_republish" for proj in projections
        )

    # kb-shzi.2 (BUG 2 fix): resolve selected_pk so the re-rendered fragment
    # re-opens the same channel tab. The action POSTs (customize/reset/duplicate)
    # submit selected_pk as a hidden input; we read it from POST (or GET fallback),
    # validate it against the current projection set, and fall back to 'source'
    # if the pk is absent or no longer exists (fail-loud-friendly: never crash).
    # The autosave path (hx-swap="none") does NOT use this — no change there.
    raw_selected = request.POST.get("selected_pk") or request.GET.get("selected_pk") or ""
    projection_pks = {str(proj.pk) for proj in projections}
    if raw_selected and raw_selected in projection_pks:
        # Valid non-first tab — preserve it
        selected_pk = int(raw_selected)
    else:
        # No selection or invalid pk — default to 'source' (the Source anchor tab)
        selected_pk = None  # None → template renders 'source' default

    # kb-96tn.4: available_connections — enabled connections that support 'promotion'
    # but have no projection yet for this post. Powers the "…" toggle dropdown.
    # Excludes connections already projected (any status — including published).
    # Symmetric with fragment_event_syndication's available_connections (listing kind there).
    from events.models import EventOrganizer as _EventOrganizer

    organizer_profile_ids = _EventOrganizer.objects.filter(event=event).values_list("profile_id", flat=True)
    all_post_connections = list(
        PlatformConnection.objects.filter(
            organizer_id__in=organizer_profile_ids,
            enabled=True,
        )
    )
    already_projected_conn_ids = set(p.connection_id for p in projections)
    available_connections = [
        conn
        for conn in all_post_connections
        if "promotion" in (conn.kinds or [])
        and _supports_post_promotion(conn.platform)
        and conn.pk not in already_projected_conn_ids
    ]

    return render(
        request,
        "syndication/fragments/post_syndication.html",
        {
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
            "source_row": source_row,
            "selected_pk": selected_pk,
            "available_connections": available_connections,
            "source_editable": source_editable,
        },
    )


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
            _post = create_post(user=request.user, event=event, **cd)
            # HTMX-aware: if request is HTMX, return event_posts fragment + OOB rail
            if request.headers.get("HX-Request"):
                posts = Post.objects.filter(event=event).order_by("-created_at")
                posts_html = render_to_string(
                    "syndication/fragments/event_posts.html",
                    {
                        "event": event,
                        "posts": posts,
                        "can_edit": can_edit(request.user, event),
                        "post_form": PostForm(),
                    },
                    request=request,
                )
                rail_oob = _render_rail_oob(request)
                return HttpResponse(posts_html + rail_oob, content_type="text/html")
            return redirect("syndication:event-hub", pk=event.pk)
    else:
        form = PostForm()

    return render(
        request,
        "syndication/post_create.html",
        {
            "form": form,
            "event": event,
        },
    )


# ---------------------------------------------------------------------------
# Standalone post creation (kb-96tn.6 — no parent event selected yet)
# ---------------------------------------------------------------------------


@login_required
def post_create_standalone(request):
    """
    Create a Post, choosing the parent Event from the user's own events.

    This is the entry point for '+ New → New promo post' in the studio rail,
    where no specific event is pre-selected. The user picks an event, fills
    the headline/body, and submits.

    HX-Request branching (kb-96tn.6): HTMX GET returns a layout-less fragment
    (for swapping into #studio-main). HTMX POST success returns the post hub
    fragment; plain POST redirects to the event hub.
    """
    from organizers.models import ProfileClaim

    is_htmx = bool(request.headers.get("HX-Request"))

    # Gather the user's events (same approach as studio view).
    claim = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).select_related("profile").first()
    if claim is None:
        return render(
            request,
            "syndication/403.html",
            {"detail": "No organizer profile. Studio access requires an active profile claim."},
            status=403,
        )

    primary_profile = claim.profile
    events = list(Event.objects.filter(organizers=primary_profile).distinct().order_by("-updated_at"))

    if request.method == "POST":
        form = PostForm(request.POST)
        event_pk = request.POST.get("event_id")
        event = None
        if event_pk:
            try:
                event = Event.objects.get(pk=event_pk)
                if not can_edit(request.user, event):
                    event = None
            except Event.DoesNotExist:
                event = None

        if event is None:
            form.add_error(None, "Please select a valid event.")

        if form.is_valid() and event is not None:
            cd = form.cleaned_data
            post = create_post(user=request.user, event=event, **cd)
            if is_htmx:
                from django.urls import reverse

                hub_url = reverse("syndication:post-hub", kwargs={"pk": post.pk})
                user_can_edit = can_edit(request.user, post.event)
                hub_html = render_to_string(
                    "syndication/post_hub_fragment.html",
                    {"post": post, "event": post.event, "can_edit": user_can_edit},
                    request=request,
                )
                rail_oob = _render_rail_oob(request)
                response = HttpResponse(hub_html + rail_oob, content_type="text/html")
                response["HX-Push-Url"] = hub_url
                return response
            return redirect("syndication:post-hub", pk=post.pk)
    else:
        form = PostForm()

    ctx = {"form": form, "events": events}
    if is_htmx:
        return render(request, "syndication/post_create_standalone_fragment.html", ctx)
    return render(request, "syndication/post_create_standalone.html", ctx)


# ---------------------------------------------------------------------------
# PlatformConnection management UI
# ---------------------------------------------------------------------------


@login_required
def connections_list(request):
    """
    List PlatformConnections for the authenticated user's profiles.
    """
    from organizers.models import ProfileClaim

    profile_ids = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )
    connections = (
        PlatformConnection.objects.filter(organizer_id__in=profile_ids)
        .select_related("organizer")
        .order_by("platform", "destination_id")
    )
    return render(
        request,
        "syndication/connections_list.html",
        {
            "connections": connections,
        },
    )


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
        return render(
            request, "syndication/403.html", {"detail": "No organizer profile found for your account."}, status=403
        )

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

    profile_ids = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    conn = get_object_or_404(PlatformConnection, pk=pk, organizer_id__in=profile_ids)

    if request.method == "POST":
        conn.enabled = not conn.enabled
        conn.save(update_fields=["enabled"])
        if request.headers.get("HX-Request"):
            connections = (
                PlatformConnection.objects.filter(organizer_id__in=profile_ids)
                .select_related("organizer")
                .order_by("platform", "destination_id")
            )
            return render(
                request,
                "syndication/connections_list.html",
                {
                    "connections": connections,
                },
            )
        return redirect("syndication:connections-list")

    return redirect("syndication:connections-list")


# ---------------------------------------------------------------------------
# Destination picker (kb-sbhs.2 — RENDER ONLY)
#
# Renders the synced Telegram inventory as a categorised tree:
#   Channels / Groups / Forums → Topics
# with theme-tag filter (chips + text search, Alpine-driven) and
# capability-ladder indicators (bot / agent / public tiers).
#
# Agent detection: AgentCredential.objects.filter(user=..., enabled=True).exists()
# — if the user has any active AgentCredential, agent-tier destinations are
# unlocked; otherwise they render visible-but-locked with "agent required".
#
# Forum-topic trap (canonical footgun):
#   A forum/group cluster label has NO checkbox — it is a NON-interactive label.
#   Only forum_topic leaves (type=forum_topic, topic_id IS NOT NULL) are
#   selectable post targets. A forum group cannot receive a post without topic_id.
# ---------------------------------------------------------------------------


@login_required
def destination_picker(request):
    """
    Render-only destination picker (kb-sbhs.2).

    Builds a structured context object grouping PlatformConnections by type:
    - channels: all type=channel rows
    - groups: all type=group / supergroup rows (excluding forum clusters)
    - forums: clusters of type=group/supergroup rows that have associated
              forum_topic children, each cluster listing its topic leaves

    No mutation endpoints — checkboxes are display affordances; POST wiring
    is Child kb-sbhs.3.
    """
    from collections import defaultdict

    from organizers.models import ProfileClaim
    from syndication.models import AgentCredential, TelegramDialogType, TelegramPostability

    profile_ids = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    # All Telegram connections for the user's profiles (Telegram only)
    telegram_types = [
        TelegramDialogType.CHANNEL,
        TelegramDialogType.GROUP,
        TelegramDialogType.SUPERGROUP,
        TelegramDialogType.FORUM_TOPIC,
    ]
    connections = (
        PlatformConnection.objects.filter(
            organizer_id__in=profile_ids,
            platform="telegram",
            type__in=telegram_types,
        )
        .select_related("organizer")
        .order_by("type", "destination_id", "topic_id")
    )

    # --- Detect agent connection ---
    agent_connected = AgentCredential.objects.filter(user=request.user, enabled=True).exists()

    # --- Build tree structure in the view (ADR-008 D2: no template logic) ---
    channels = []
    groups = []  # non-forum groups/supergroups
    # forum_map: destination_id → {cluster: PlatformConnection, topics: []}
    forum_map = defaultdict(lambda: {"cluster": None, "topics": []})

    # Find destination_ids that have forum_topic children
    forum_topic_dest_ids = set(c.destination_id for c in connections if c.type == TelegramDialogType.FORUM_TOPIC)

    for conn in connections:
        # Display name: friendly_name overrides title
        conn.display_name = conn.friendly_name or conn.title or conn.destination_id

        # Capability-ladder tier flags (server-side booleans — no string literals in template)
        conn.is_agent_tier = conn.postability == TelegramPostability.AGENT
        conn.is_bot_tier = conn.postability == TelegramPostability.BOT
        conn.is_public_tier = conn.postability == TelegramPostability.PUBLIC

        # Capability-ladder lock state
        conn.is_locked = (conn.is_agent_tier and not agent_connected) or conn.flagged_missing

        # Selection state: is this connection currently selected for promotion?
        conn.is_selected = "promotion" in (conn.kinds or [])

        if conn.type == TelegramDialogType.CHANNEL:
            channels.append(conn)
        elif conn.type == TelegramDialogType.FORUM_TOPIC:
            forum_map[conn.destination_id]["topics"].append(conn)
        elif conn.type in (TelegramDialogType.GROUP, TelegramDialogType.SUPERGROUP):
            if conn.destination_id in forum_topic_dest_ids:
                # This group/supergroup row is the forum cluster label
                existing = forum_map[conn.destination_id]["cluster"]
                if existing is None:
                    forum_map[conn.destination_id]["cluster"] = conn
            else:
                # Plain group with no forum topics
                groups.append(conn)

    # Build the forums list for the template
    forums = []
    for dest_id, data in forum_map.items():
        cluster = data["cluster"]
        topics = data["topics"]
        if cluster is None and topics:
            # Forum topics without an explicit cluster row — synthesise a label
            # from the first topic's title (fail-loud: don't silently drop them)
            first = topics[0]
            cluster = type(
                "ForumCluster",
                (),
                {
                    "display_name": first.title or dest_id,
                    "destination_id": dest_id,
                    "pk": None,
                    "flagged_missing": False,
                    "postability": first.postability,
                    "is_locked": False,
                },
            )()
        if cluster is not None:
            cluster.display_name = (
                cluster.friendly_name
                if hasattr(cluster, "friendly_name") and cluster.friendly_name
                else (cluster.title if hasattr(cluster, "title") and cluster.title else dest_id)
            )
        forums.append({"cluster": cluster, "topics": topics})

    # --- Collect all theme tags (union across all connections) ---
    all_tags = sorted(set(tag for conn in connections for tag in (conn.theme_tags or [])))

    return render(
        request,
        "syndication/destination_picker.html",
        {
            "channels": channels,
            "groups": groups,
            "forums": forums,
            "all_tags": all_tags,
            "agent_connected": agent_connected,
        },
    )


# ---------------------------------------------------------------------------
# Destination picker mutation endpoints (kb-sbhs.3)
#
# SELECT / DESELECT: sets kinds+enabled (additive — never clobbers existing kinds)
# OVERLAY writer:    persists friendly_name + theme_tags
#
# Server-side selectability guard (ADR-008 D3 FIRM):
#   A connection is NOT selectable if:
#   1. flagged_missing=True (vanished)
#   2. is_locked: agent-tier postability AND no active AgentCredential for user
#   3. is_forum_parent: type is group/supergroup AND it has forum_topic children
#      sharing the same destination_id (it is a forum cluster label, not a leaf)
#
# The guard is re-derived server-side from DB state — never trusted from client.
# ---------------------------------------------------------------------------


def _derive_selectability(conn, agent_connected):
    """
    Re-derive server-side whether a connection is selectable for promotion.

    Returns (is_selectable: bool, rejection_reason: str | None).

    Reasons (ADR-008 D3 fail-loud):
    - "flagged_missing": the row is no longer visible in the last sync.
    - "agent_required": agent-tier postability but no agent connected.
    - "forum_parent": the row is a forum cluster label (not a postable leaf).
    """
    from syndication.models import TelegramDialogType, TelegramPostability

    if conn.flagged_missing:
        return False, "flagged_missing"

    # Locked: agent-tier with no active agent
    if conn.postability == TelegramPostability.AGENT and not agent_connected:
        return False, "agent_required"

    # Forum parent: a group/supergroup row that has forum_topic children
    # sharing the same destination_id AND organizer. Such rows are cluster
    # labels, NOT selectable post targets (a forum group cannot receive a post
    # without topic_id).
    # SECURITY: scope to the same organizer — two organizers can share a
    # destination_id (same Telegram chat_id). Without scope, Org B's forum
    # leaks presence info and wrongly blocks Org A's plain group at the same
    # chat_id. The unique key is (organizer, platform, destination_id, topic_id).
    if conn.type in (TelegramDialogType.GROUP, TelegramDialogType.SUPERGROUP):
        # Check if any forum_topic child shares this destination_id AND organizer
        has_topics = PlatformConnection.objects.filter(
            organizer_id=conn.organizer_id,
            destination_id=conn.destination_id,
            type=TelegramDialogType.FORUM_TOPIC,
        ).exists()
        if has_topics:
            return False, "forum_parent"

    return True, None


@login_required
def destination_select(request, pk):
    """
    Toggle promotion selection for a destination (kb-sbhs.3).

    POST selected=true  → add 'promotion' to kinds (additive) + enabled=True
    POST selected=false → remove 'promotion' from kinds

    Server-side selectability guard (ADR-008 D3 FIRM): re-derives lock/forum-parent
    state from DB — never trusts client-side disabled attributes.

    Returns 200 (HTMX-aware: renders the updated picker row) or 400 on guard failure.
    """
    from organizers.models import ProfileClaim
    from syndication.models import AgentCredential, TelegramDialogType, TelegramPostability

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    profile_ids = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    conn = get_object_or_404(PlatformConnection, pk=pk, organizer_id__in=profile_ids)

    # --- Server-side selectability guard (ADR-008 D3 FIRM) ---
    agent_connected = AgentCredential.objects.filter(user=request.user, enabled=True).exists()

    is_selectable, rejection_reason = _derive_selectability(conn, agent_connected)

    selected_str = request.POST.get("selected", "")
    selecting = selected_str.lower() in ("true", "1", "on", "yes")

    if selecting and not is_selectable:
        # Fail loud: 4xx with reason; NO kinds mutation (ADR-008 D3)
        return HttpResponseBadRequest(f"Cannot select destination: {rejection_reason or 'not selectable'}")

    # --- Mutate kinds (additive) ---
    kinds = list(conn.kinds or [])

    if selecting:
        if "promotion" not in kinds:
            kinds.append("promotion")
        conn.kinds = kinds
        conn.enabled = True
        conn.save(update_fields=["kinds", "enabled"])
    else:
        # Deselect: remove only "promotion", leave other kinds intact
        kinds = [k for k in kinds if k != "promotion"]
        conn.kinds = kinds
        conn.save(update_fields=["kinds"])

    if request.headers.get("HX-Request"):
        # Re-derive display flags for the partial
        conn.display_name = conn.friendly_name or conn.title or conn.destination_id
        conn.is_agent_tier = conn.postability == TelegramPostability.AGENT
        conn.is_bot_tier = conn.postability == TelegramPostability.BOT
        conn.is_public_tier = conn.postability == TelegramPostability.PUBLIC
        conn.is_locked = (conn.is_agent_tier and not agent_connected) or conn.flagged_missing
        conn.is_selected = "promotion" in conn.kinds

        # Determine if this is a forum topic for the partial context
        picker_row_is_topic = conn.type == TelegramDialogType.FORUM_TOPIC

        return render(
            request,
            "syndication/fragments/_picker_row.html",
            {"conn": conn, "picker_row_is_topic": picker_row_is_topic},
        )

    return HttpResponse(status=200)


@login_required
def destination_overlay(request, pk):
    """
    Persist the names/tags overlay for a connection (kb-sbhs.3).

    POST friendly_name + theme_tags (comma-separated string) → save to DB.

    Returns 200 (or HTMX partial for autosave).
    """
    from organizers.models import ProfileClaim

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    profile_ids = ProfileClaim.objects.filter(user=request.user, rejected_at__isnull=True).values_list(
        "profile_id", flat=True
    )

    conn = get_object_or_404(PlatformConnection, pk=pk, organizer_id__in=profile_ids)

    friendly_name_raw = request.POST.get("friendly_name", "").strip()
    theme_tags_raw = request.POST.get("theme_tags", "").strip()

    # --- Fail-loud validation (ADR-008 D3) ---
    # friendly_name: max 300 chars (DB field constraint). Do NOT silently truncate.
    FRIENDLY_NAME_MAX = 300
    if len(friendly_name_raw) > FRIENDLY_NAME_MAX:
        return HttpResponseBadRequest(f"friendly_name exceeds maximum length of {FRIENDLY_NAME_MAX} characters.")

    # theme_tags: each individual tag must be reasonable length.
    TAG_MAX_LENGTH = 100
    if theme_tags_raw:
        raw_tags = [tag.strip() for tag in theme_tags_raw.split(",") if tag.strip()]
        for tag in raw_tags:
            if len(tag) > TAG_MAX_LENGTH:
                return HttpResponseBadRequest(f"A theme_tag exceeds maximum length of {TAG_MAX_LENGTH} characters.")

    # Normalize friendly_name: empty string → None (no override)
    conn.friendly_name = friendly_name_raw if friendly_name_raw else None

    # Normalize theme_tags: comma-separated → deduplicated list of stripped strings
    if theme_tags_raw:
        conn.theme_tags = sorted({tag.strip() for tag in theme_tags_raw.split(",") if tag.strip()})
    else:
        conn.theme_tags = []

    conn.save(update_fields=["friendly_name", "theme_tags"])

    if request.headers.get("HX-Request"):
        # Return the updated picker row partial for inline swap
        from syndication.models import AgentCredential, TelegramDialogType, TelegramPostability

        agent_connected = AgentCredential.objects.filter(user=request.user, enabled=True).exists()

        conn.display_name = conn.friendly_name or conn.title or conn.destination_id
        conn.is_agent_tier = conn.postability == TelegramPostability.AGENT
        conn.is_bot_tier = conn.postability == TelegramPostability.BOT
        conn.is_public_tier = conn.postability == TelegramPostability.PUBLIC
        conn.is_locked = (conn.is_agent_tier and not agent_connected) or conn.flagged_missing
        conn.is_selected = "promotion" in (conn.kinds or [])
        picker_row_is_topic = conn.type == TelegramDialogType.FORUM_TOPIC

        return render(
            request,
            "syndication/fragments/_picker_row.html",
            {"conn": conn, "picker_row_is_topic": picker_row_is_topic},
        )

    return HttpResponse(status=200)


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


def _publishable_fragment_response(request, proj, action_error=None):
    """
    Return the refreshed syndication fragment for the projection's publishable.

    Dispatches by publishable type (event → event_syndication fragment;
    post → post_syndication fragment). kb-q4u9.3 item 7.
    """
    if proj.kind == PlatformProjection.Kind.LISTING:
        return fragment_event_syndication(request, pk=proj.source_event.pk, action_error=action_error)
    if proj.kind == PlatformProjection.Kind.PROMOTION:
        return fragment_post_syndication(request, pk=proj.source_post.pk, action_error=action_error)
    raise ValueError(f"Unknown projection kind {proj.kind!r}")


def _publishable_fragment_response_for_cv(request, content_version, action_error=None):
    """
    Return the refreshed syndication fragment for a ContentVersion's publishable.

    For version-op views that operate directly on ContentVersion.
    kb-q4u9.3 item 7: dispatch by publishable type.
    """
    event, post = _resolve_publishable_for_cv(content_version)
    if event is not None:
        return fragment_event_syndication(request, pk=event.pk, action_error=action_error)
    return fragment_post_syndication(request, pk=post.pk, action_error=action_error)


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
        return fragment_event_syndication(request, pk=proj.source_event.pk, action_error=str(exc))
    if proj.kind == PlatformProjection.Kind.PROMOTION:
        return fragment_post_syndication(request, pk=proj.source_post.pk, action_error=str(exc))
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
def projection_direct_publish(request, pk):
    """
    Direct-publish: solo-flow Publish CTA (kb-ide0.2 D6).

    Drives the internal draft→ready→published two-step transparently.
    If the projection is 'draft': approve (freeze frozen_content) then publish.
    If the projection is 'ready': publish directly.

    POST only. Calls publish_projection_direct service.
    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: ValueError (illegal transition) surfaces as error state.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    try:
        publish_projection_direct(user=request.user, projection=proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
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
def projection_detach_and_edit(request, pk):
    """
    Detach-and-edit: customize (mint own CV) then apply editorial field edits —
    for per-channel body autosave on a projection sharing the canonical CV (state i).

    POST only. Calls detach_and_edit(user, projection, **fields) service.
    HTMX-aware: returns OOB sync-bar fragments (hx-swap="none" autosave path)
    so the badge updates from the server's truth after the round-trip.

    ADR-016 D2: editing a per-channel tab auto-detaches to its own independent CV.
    ADR-016 D5: editing a published projection is allowed (dirties, does not corrupt).
    ADR-008 D3: PermissionError → 403; ValueError → fail loud.

    The master/source tab body form stays on version-edit (cv-keyed) and keeps
    broadcasting. This view is ONLY for per-channel tabs.
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    fields = {}
    for field_name in ("body", "headline", "imagery", "cta", "voice"):
        if field_name in request.POST:
            fields[field_name] = request.POST[field_name]

    try:
        new_cv, proj = detach_and_edit(user=request.user, projection=proj, **fields)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, proj, action_error=str(exc))
        return _publishable_hub_redirect(proj)

    if request.headers.get("HX-Request"):
        # Server-driven OOB badge update — same pattern as version_edit.
        # After detach the projection is on its own new CV (state iii: "Custom").
        # Re-render the sync-bar for ONLY this projection (no siblings share new_cv).
        # The autosave form uses hx-swap="none" so HTMX ignores the main body but
        # still processes hx-swap-oob="true" elements.
        proj.refresh_from_db()
        if proj.kind == PlatformProjection.Kind.LISTING:
            _target = "#event-syndication"
        else:
            _target = "#post-syndication"
        _oob_fragments = [
            render_to_string(
                "syndication/fragments/_sync_bar.html",
                {"proj": proj, "fragment_target": _target, "oob": True},
                request=request,
            )
        ]
        # Also emit OOB dirty-state for published projections (ADR-016 D5).
        # ADR-008 D3: do NOT catch ValueError from is_dirty — let it propagate.
        # Any ValueError here is a data-integrity violation, not a recoverable condition.
        if proj.status == PlatformProjection.Status.PUBLISHED and proj.frozen_content is not None:
            _content_is_dirty = proj.is_dirty
            if _content_is_dirty:
                _policy = edit_after_publish_policy(proj.connection.platform)
                _is_dirty = _policy == "dirty_then_republish"
            else:
                _is_dirty = False
            # kb-kgza.10 B: compute can_publish so the OOB partial can render the
            # Re-publish CTA region (#channel-cta-<pk>) without a full page reload.
            _publishable = _resolve_projection_event(proj)
            _user_can_publish = can_publish(request.user, _publishable)
            _oob_fragments.append(
                render_to_string(
                    "syndication/fragments/_channel_dirty_oob.html",
                    {
                        "proj": proj,
                        "is_dirty": _is_dirty,
                        "oob": True,  # FIX C (kb-kgza.2): emit hx-swap-oob="true" so HTMX
                        # processes the dirty pill/banner OOB swap client-side.
                        # version_edit passes oob=True (views.py ~1651-1655); detach-and-edit
                        # was missing it, leaving the dirty indicator un-updated after detach.
                        "can_publish": _user_can_publish,
                        "fragment_target": _target,
                    },
                    request=request,
                )
            )
        # kb-ciqf Fix 1: emit body OOBs for sibling projections still on the canonical
        # CV (the projections that share the same publishable but were NOT the edited one).
        # After detach, proj is on its own new CV; siblings still share the original CV.
        # MUST skip proj itself (cursor protection: don't clobber the active textarea).
        # Look up the CANONICAL CV for this publishable — siblings still pointing to it
        # need body OOBs so their displayed content stays in sync (track-live or not).
        from syndication.models import ContentVersion as _ContentVersion

        _publishable_for_cv = _resolve_publishable_for_cv(proj.content_version)
        if _publishable_for_cv is not None:
            _event_for_sibling, _post_for_sibling = _publishable_for_cv
            try:
                if _post_for_sibling is not None:
                    _canonical_cv = _ContentVersion.objects.get(post=_post_for_sibling, name="canonical")
                    _sibling_projs = list(
                        _canonical_cv.projections.select_related(
                            "connection", "content_version", "source_post", "source_event"
                        ).all()
                    )
                    _is_post_sibling = True
                elif _event_for_sibling is not None:
                    _canonical_cv = _ContentVersion.objects.get(event=_event_for_sibling, name="canonical")
                    _sibling_projs = list(
                        _canonical_cv.projections.select_related(
                            "connection", "content_version", "source_event", "source_post"
                        ).all()
                    )
                    _is_post_sibling = False
                else:
                    _sibling_projs = []
                    _is_post_sibling = False
                # Filter out switch-listing (EventForm, no textarea OOB needed)
                _sibling_body_projs = [
                    _p
                    for _p in _sibling_projs
                    if not (_p.kind == PlatformProjection.Kind.LISTING and _p.connection.platform == "switch")
                ]
                _oob_fragments.extend(
                    _render_sibling_body_oob_fragments(
                        request,
                        _sibling_body_projs,
                        skip_pk=proj.pk,  # Do NOT clobber the just-edited textarea
                        is_post_composer=_is_post_sibling,
                    )
                )
            except _ContentVersion.DoesNotExist:
                pass  # No canonical CV — no siblings to notify (degenerate state)
        return HttpResponse("\n".join(_oob_fragments), content_type="text/html")
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

    target_projections = list(PlatformProjection.objects.filter(pk__in=target_pks))

    try:
        copy_to(user=request.user, source_version=source_version, target_projections=target_projections)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(request, source_version, action_error=str(exc))
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

    Edit-after-publish (ADR-016 D5 / kb-kgza.3): when ALL consumers of the CV are
    non-draft (published/ready/failed), this is the legitimate master/source-tab
    edit-after-publish flow. The edit broadcasts to all sharers → they become dirty
    (frozen_content snapshot unchanged = no corruption). Pass _allow_edit_after_publish=True
    to bypass the all-consumers-non-draft guard in edit_version. The service-level
    corruption guard (published + null frozen_content) remains active even with the
    bypass — genuine invariant violations still fail loud.
    """
    from syndication.models import ContentVersion, PlatformProjection

    version = get_object_or_404(ContentVersion, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect_for_cv(version)

    # Collect editorial fields from POST (only known fields; services.py filters unknowns)
    fields = {}
    for field_name in ("body", "headline", "imagery", "cta", "voice"):
        if field_name in request.POST:
            fields[field_name] = request.POST[field_name]

    # kb-ciqf Fix 2: guard against writing body to an event canonical CV via this
    # view. ADR-016 D2: the intended model is that editing an event's MASTER updates
    # Event MODEL FIELDS (via update_event / event_hub_edit), leaving the canonical
    # CV body NULL so it stays track-live. Any body write on the event canonical
    # freezes recomposition — dependents never follow further master edits.
    # The version_edit view is for POST master-copy tabs (not event canons).
    # Strip "body" at the view level so even direct URL access cannot freeze it.
    # (Service-level edit_version remains general — test helpers call it directly.)
    if version.name == "canonical" and version.event_id is not None:
        fields.pop("body", None)

    # Determine whether to bypass the all-consumers-non-draft guard.
    # When all consumers are non-draft, this is the master/source-tab edit-after-publish
    # flow (ADR-016 D5): editing the canonical CV dirties all sharers, frozen_content
    # stays unchanged. Pass _allow_edit_after_publish=True so the guard does not block
    # the legitimate broadcast-and-dirty operation.
    _consumers = list(version.projections.all())
    _allow_edit_after_publish = bool(_consumers) and all(
        p.status != PlatformProjection.Status.DRAFT for p in _consumers
    )

    try:
        edit_version(user=request.user, version=version, _allow_edit_after_publish=_allow_edit_after_publish, **fields)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response_for_cv(request, version, action_error=str(exc))
        return _publishable_hub_redirect_for_cv(version)

    # kb-s41r FIX 1: under live-share, version_edit is the MASTER/SOURCE edit path.
    # Followers share this CV row — editing it broadcasts to them automatically.
    # Do NOT detach followers here: their sync_source must stay intact so they
    # continue rendering "Synced from <source>" (live-follow state).
    # Detach-on-edit only applies when a FOLLOWER edits its own per-channel tab
    # via projection_detach_and_edit — that path is handled in detach_and_edit().
    # (Removed the old snapshot-era detach block that called detach_sync_source on
    # every synced consumer after a master edit — wrong under live-share.)

    if request.headers.get("HX-Request"):
        # kb-lprn: server-driven OOB badge update.
        # Return OOB sync-bar fragments for every projection sharing this CV so
        # the badge updates from the server's truth after the autosave round-trip.
        # The autosave form uses hx-swap="none" — HTMX ignores the main body but
        # still processes hx-swap-oob="true" elements. This is the only source of
        # truth that's correct for BOTH detach (own CV → "Custom") and broadcast
        # (shared canonical → still "Synced") — the naive optimistic flip lies
        # for broadcast channels (ADR-016 D2 single-row sharing).
        #
        # kb-96tn.5: also emit dirty-state OOB (channel-dot + channel-dirty)
        # for published projections so the pill dot and banner update WITHOUT a
        # full page reload. Published projections that share this CV may become
        # dirty immediately after the autosave — surface it in the same round-trip.
        _cv_projections = list(
            version.projections.select_related(
                "sync_source",
                "sync_source__connection",
                "content_version",
                "connection",
                "source_event",
                "source_event__venue",
                "source_post",
            ).all()
        )
        _oob_fragments = []
        for _proj in _cv_projections:
            # Determine the full-fragment target for the Customize/Reset forms in
            # the OOB partial (these forms refresh the whole fragment if clicked).
            if _proj.kind == PlatformProjection.Kind.LISTING:
                _target = "#event-syndication"
            else:
                _target = "#post-syndication"
            _oob_fragments.append(
                render_to_string(
                    "syndication/fragments/_sync_bar.html",
                    {"proj": _proj, "fragment_target": _target, "oob": True},
                    request=request,
                )
            )
            # kb-96tn.5: OOB dirty-state update for published projections.
            # Compute is_dirty for this projection and emit the channel-dot +
            # channel-dirty OOB fragments so the pill dot updates live.
            # Only published projections can be dirty (is_dirty gates on status).
            # ADR-016 D5 / ADR-003: gate the affordance through edit_after_publish_policy.
            #
            # FOLD 1 (kb-kgza.10, review Finding 2): per-row containment for the
            # broadcast loop.  This loop iterates EVERY projection sharing the edited
            # ContentVersion — a corrupt sibling (e.g. source_event=None) must not
            # abort the autosave of the channel the user is actually editing.
            # Mirror the board-render loop pattern (fragment_event_syndication ~517):
            # catch ValueError per row, log, skip the CTA OOB for that row only.
            # (ADR-008 D3 "render visible error state" for a loop, not a single subject.)
            if _proj.status == PlatformProjection.Status.PUBLISHED and _proj.frozen_content is not None:
                try:
                    _content_is_dirty = _proj.is_dirty
                    if _content_is_dirty:
                        _policy = edit_after_publish_policy(_proj.connection.platform)
                        _is_dirty = _policy == "dirty_then_republish"
                    else:
                        _is_dirty = False
                    # kb-kgza.10 B: compute can_publish so the OOB partial can render the
                    # Re-publish CTA region (#channel-cta-<pk>) without a full page reload.
                    # Only computed for projections whose CTA OOB fragment is being emitted.
                    _publishable = _resolve_projection_event(_proj)
                    _user_can_publish = can_publish(request.user, _publishable)
                except ValueError as _dirty_exc:
                    # Per-row containment: corrupt sibling degrades only its own CTA row.
                    # Log and skip the dirty-state OOB for this projection.
                    _views_logger.warning(
                        "version_edit: skipping dirty-state OOB for projection %r "
                        "(corrupt data — sibling must not break active edit): %s",
                        _proj.pk,
                        _dirty_exc,
                    )
                    continue
                _oob_fragments.append(
                    render_to_string(
                        "syndication/fragments/_channel_dirty_oob.html",
                        {
                            "proj": _proj,
                            "is_dirty": _is_dirty,
                            "oob": True,
                            "can_publish": _user_can_publish,
                            "fragment_target": _target,
                        },
                        request=request,
                    )
                )
        # kb-ciqf Fix 1: emit OOB body-wrapper fragments for all sibling projections
        # that have a body textarea (non-switch-listing only — Switch listing uses
        # the EventForm card, not a textarea). This updates sibling channel textareas
        # live so the user sees the new master content without a full reload.
        # The master copy form (version-edit) has no associated projection, so no
        # skip_pk is needed — all body-form siblings should update.
        _body_oob_projections = [
            _p
            for _p in _cv_projections
            if not (_p.kind == PlatformProjection.Kind.LISTING and _p.connection.platform == "switch")
        ]
        _is_post_composer = any(_p.kind == PlatformProjection.Kind.PROMOTION for _p in _body_oob_projections)
        _oob_fragments.extend(
            _render_sibling_body_oob_fragments(
                request,
                _body_oob_projections,
                is_post_composer=_is_post_composer,
            )
        )
        return HttpResponse("".join(_oob_fragments), content_type="text/html")
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
            return _publishable_fragment_response_for_cv(request, version, action_error=str(exc))
        return _publishable_hub_redirect_for_cv(version)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response_for_cv(request, version)
    return _publishable_hub_redirect_for_cv(version)


@login_required
def version_copy_from(request, pk):
    """
    Copy-from: repoint the target projection at a NEW independent copy taken
    from a source (mint a new row from source, FK the projection to it).

    POST only. Takes source_projection_pk (kb-ide0.4): copies from a peer
    PlatformProjection and sets projection.sync_source = that peer
    (snapshot + persisted pointer). Enforces cycle guard: raises ValueError if
    source projection has non-null sync_source (ADR-008 D3 fail-loud —
    backend-enforced, not UI-only).

    ADR-008 D1: the legacy source_version_pk (bare ContentVersion copy) path
    was deleted — it was unreachable from all templates (all forms use
    source_projection_pk). No backward-compat shim at V0.

    HTMX-aware: returns refreshed syndication fragment on HX-Request.
    ADR-008 D3: PermissionError → 403; ValueError → surfaced as action_error.
    """
    projection = get_object_or_404(PlatformProjection, pk=pk)

    if request.method != "POST":
        return _publishable_hub_redirect(projection)

    source_projection_pk = request.POST.get("source_projection_pk", "").strip()
    if not source_projection_pk:
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, projection)
        return _publishable_hub_redirect(projection)

    source_proj = get_object_or_404(PlatformProjection, pk=source_projection_pk)
    try:
        sync_projection_from(user=request.user, target=projection, source=source_proj)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)
    except ValueError as exc:
        # Cycle guard violation or cross-event error — fail loud (ADR-008 D3).
        if request.headers.get("HX-Request"):
            return _publishable_fragment_response(request, projection, action_error=str(exc))
        return _publishable_hub_redirect(projection)

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, projection)
    return _publishable_hub_redirect(projection)


# ---------------------------------------------------------------------------
# Add-channel / remove-channel endpoints (kb-96tn.4, ADR-016 D4)
#
# add_channel_event: POST /syndication/events/<pk>/add-channel/
#   Mints a draft projection for an enabled connection not yet projected.
#   can_edit gated (ADR-017). Returns HTMX swap of the syndication fragment.
#
# remove_channel: POST /syndication/projections/<pk>/remove-channel/
#   Removes/deletes an UNPUBLISHED projection.
#   CRITICAL (ADR-008 D3): if called on a PUBLISHED projection, return HTTP 400
#   with a VISIBLE reason in the response body — never a silent 200 or empty 400.
# ---------------------------------------------------------------------------


@login_required
def add_channel_event(request, pk):
    """
    Add a channel to an event by minting a draft PlatformProjection for an
    enabled connection that has no projection yet for this event.

    POST only. Takes `connection_pk` from the POST body.
    can_edit gated (ADR-017 D1).
    Calls add_projection service (co-equal API verb, ADR-016 D3).
    Returns HTMX swap of the event_syndication fragment on HX-Request.

    Idempotent: re-POSTing for an already-projected connection returns 200 (via
    add_projection's idempotency — no duplicate minted).
    """
    event = get_object_or_404(Event, pk=pk)
    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {}, status=403)

    if request.method != "POST":
        return redirect("syndication:event-hub", pk=event.pk)

    connection_pk = request.POST.get("connection_pk")
    if not connection_pk:
        return HttpResponse("connection_pk is required", status=400)

    conn = get_object_or_404(PlatformConnection, pk=connection_pk)

    try:
        add_projection(event, conn)
    except ValueError as exc:
        _views_logger.warning("add_channel_event: ValueError for event %r, conn %r: %s", pk, connection_pk, exc)
        if request.headers.get("HX-Request"):
            return fragment_event_syndication(request, pk=event.pk, action_error=str(exc))
        return redirect("syndication:event-hub", pk=event.pk)

    if request.headers.get("HX-Request"):
        return fragment_event_syndication(request, pk=event.pk)
    return redirect("syndication:event-hub", pk=event.pk)


@login_required
def add_channel_post(request, pk):
    """
    Add a channel to a post by minting a draft PlatformProjection for an
    enabled promotion connection that has no projection yet for this post.

    POST only. Takes `connection_pk` from the POST body.
    can_edit gated (ADR-017 D1) — checked against the parent event.
    Calls add_projection service (co-equal API verb, ADR-016 D3).
    Returns HTMX swap of the post_syndication fragment on HX-Request.

    Idempotent: re-POSTing for an already-projected connection returns 200 (via
    add_projection's idempotency — no duplicate minted).

    Mirror of add_channel_event but scoped to Post (kb-96tn.4 parity).
    """
    post = get_object_or_404(Post, pk=pk)
    event = post.event
    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {}, status=403)

    if request.method != "POST":
        return redirect("syndication:post-hub", pk=post.pk)

    connection_pk = request.POST.get("connection_pk")
    if not connection_pk:
        return HttpResponse("connection_pk is required", status=400)

    conn = get_object_or_404(PlatformConnection, pk=connection_pk)

    try:
        add_projection(post, conn)
    except ValueError as exc:
        _views_logger.warning("add_channel_post: ValueError for post %r, conn %r: %s", pk, connection_pk, exc)
        if request.headers.get("HX-Request"):
            return fragment_post_syndication(request, pk=post.pk, action_error=str(exc))
        return redirect("syndication:post-hub", pk=post.pk)

    if request.headers.get("HX-Request"):
        return fragment_post_syndication(request, pk=post.pk)
    return redirect("syndication:post-hub", pk=post.pk)


@login_required
def remove_channel(request, pk):
    """
    Remove/delete an UNPUBLISHED PlatformProjection.

    POST only. can_edit gated (ADR-017 D1).

    CRITICAL (ADR-008 D3 fail-loud): if called on a PUBLISHED projection,
    return HTTP 400 with a VISIBLE reason in the response body — NOT an empty
    400, NOT a silent 200. The reason must explain why the remove is refused.

    For draft/ready projections: delete the projection and return the refreshed
    syndication fragment (HTMX swap).
    """
    proj = get_object_or_404(PlatformProjection, pk=pk)
    event = _resolve_projection_event(proj)

    if not can_edit(request.user, event):
        return render(request, "syndication/403.html", {}, status=403)

    if request.method != "POST":
        return _publishable_hub_redirect(proj)

    # CRITICAL (ADR-008 D3): fail loud if the projection is published.
    # A published projection is already on an external platform — it cannot be
    # silently deleted. Surface a visible reason in the response body.
    if proj.status == PlatformProjection.Status.PUBLISHED:
        reason = (
            f"Cannot remove a published projection (pk={proj.pk!r}, "
            f"platform={proj.connection.platform!r}). "
            "The content has already been published to the external platform. "
            "To remove it, un-publish or archive it on the platform directly. "
            "(ADR-008 D3: fail loud — published projections are immutable from Switch's side)"
        )
        _views_logger.warning("remove_channel: refused to delete published projection %r", proj.pk)
        return HttpResponse(reason, status=400, content_type="text/plain")

    # Unpublished (draft or ready): safe to delete.
    proj.delete()

    if request.headers.get("HX-Request"):
        return _publishable_fragment_response(request, proj)
    return _publishable_hub_redirect(proj)


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

    return render(
        request,
        "syndication/agent_pairing.html",
        {
            "pairing_token": pairing_token,
        },
    )


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
        _published, failures = publish_all_ready_projections_for_post(user=request.user, post=post)
    except PermissionError:
        return render(request, "syndication/403.html", {}, status=403)

    if failures:
        # ADR-008 D3: fail loud — surface per-projection errors as visible error state.
        failed_descs = ", ".join(str(proj.pk) for proj, _ in failures)
        first_exc = failures[0][1]
        error_msg = f"Partial publish failure (projections: {failed_descs}): {first_exc}"
        return fragment_post_syndication(request, pk=post.pk, action_error=error_msg)

    if request.headers.get("HX-Request"):
        return _post_syndication_fragment_response(request, post)
    return redirect("syndication:post-hub", pk=post.pk)
