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
        "projections/<int:pk>/override/",
        views.projection_override,
        name="projection-override",
    ),
    path(
        "events/<int:event_pk>/projections/publish-all-ready/",
        views.projection_batch_publish,
        name="projection-batch-publish",
    ),
]
