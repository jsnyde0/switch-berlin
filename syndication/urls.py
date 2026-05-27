"""
Syndication app URL patterns (kb-a4u.3).

Routes for:
- Event CRUD web UI (create, hub, edit)
- HTMX fragment endpoints (event_facts, event_posts, event_syndication)
- Post creation scoped to Event
- PlatformConnection management

C5 (kb-a4u.5) will extend this file with projection review routes.
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
]
