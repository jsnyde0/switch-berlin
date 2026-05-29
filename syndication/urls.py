"""
Syndication app URL patterns (kb-a4u.3 + kb-a4u.5).

Routes for:
- Event CRUD web UI (create, hub, edit)
- HTMX fragment endpoints (event_facts, event_posts, event_syndication)
- Post creation scoped to Event
- PlatformConnection management
- Projection lifecycle action endpoints (approve, publish, mark-published, override)
"""

from django.urls import path

from syndication import views

app_name = "syndication"

urlpatterns = [
    # --- Agent pairing flow (kb-a4u.6) ---
    path("agents/pair/", views.agent_pairing_page, name="agent-pairing"),

    # --- Events ---
    path("events/new/", views.event_create, name="event-create"),
    path("events/<int:pk>/", views.event_hub, name="event-hub"),
    path("events/<int:pk>/edit/", views.event_hub_edit, name="event-edit"),

    # --- HTMX fragments (independently addressable per bead design) ---
    path(
        "events/<int:pk>/fragments/event_facts/",
        views.fragment_event_facts,
        name="fragment-event-facts",
    ),
    path(
        "events/<int:pk>/fragments/event_posts/",
        views.fragment_event_posts,
        name="fragment-event-posts",
    ),
    path(
        "events/<int:pk>/fragments/event_syndication/",
        views.fragment_event_syndication,
        name="fragment-event-syndication",
    ),

    # --- Posts (scoped to Event) ---
    path(
        "events/<int:event_pk>/posts/new/",
        views.post_create,
        name="post-create",
    ),

    # --- PlatformConnections ---
    path("connections/", views.connections_list, name="connections-list"),
    path("connections/new/", views.connection_create, name="connection-create"),
    path("connections/<int:pk>/toggle/", views.connection_toggle, name="connection-toggle"),

    # --- Projection lifecycle actions (kb-a4u.5) ---
    # POST only; HTMX-aware (returns refreshed syndication fragment on HX-Request).
    # Co-equal seam: each view delegates to the matching service function in services.py.
    path(
        "projections/<int:pk>/approve/",
        views.projection_approve,
        name="projection-approve",
    ),
    path(
        "projections/<int:pk>/publish/",
        views.projection_publish,
        name="projection-publish",
    ),
    path(
        "projections/<int:pk>/mark-published/",
        views.projection_mark_published,
        name="projection-mark-published",
    ),
    path(
        "events/<int:event_pk>/projections/publish-all-ready/",
        views.projection_batch_publish,
        name="projection-batch-publish",
    ),

    # --- Version-op endpoints (kb-wz8m.5) ---
    # POST only; HTMX-aware (returns refreshed syndication fragment on HX-Request).
    path(
        "projections/<int:pk>/customize/",
        views.projection_customize,
        name="projection-customize",
    ),
    path(
        "projections/<int:pk>/reset-to-canonical/",
        views.projection_reset_to_canonical,
        name="projection-reset-to-canonical",
    ),
    path(
        "versions/<int:pk>/copy-to/",
        views.version_copy_to,
        name="version-copy-to",
    ),
    path(
        "versions/<int:pk>/edit/",
        views.version_edit,
        name="version-edit",
    ),
    path(
        "versions/<int:pk>/duplicate/",
        views.version_duplicate,
        name="version-duplicate",
    ),
    path(
        "projections/<int:pk>/copy-from/",
        views.version_copy_from,
        name="version-copy-from",
    ),

    # --- Review-all surface (kb-wz8m.6) ---
    # Side-by-side cross-channel review. Route name + event_pk signature
    # referenced from the board template (event_syndication.html).
    path(
        "events/<int:event_pk>/review-all/",
        views.review_all,
        name="review-all",
    ),
]
