from django.urls import path

from . import views

urlpatterns = [
    path("", views.event_list, name="event-list"),
    path(
        "<slug:org_slug>/<slug:event_slug>/drawer/",
        views.event_drawer,
        name="event-drawer",
    ),
    path(
        "<slug:org_slug>/<slug:event_slug>/attend/",
        views.event_attend,
        name="event-attend",
    ),
    path("<slug:org_slug>/<slug:event_slug>/", views.event_detail, name="event-detail"),
]
