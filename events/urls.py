from django.urls import path

from . import views

urlpatterns = [
    path("", views.event_list, name="event-list"),
    path("<int:event_id>/drawer/", views.event_drawer, name="event-drawer"),
    path("<int:event_id>/attend/", views.event_attend, name="event-attend"),
    path("<slug:org_slug>/<slug:event_slug>/", views.event_detail, name="event-detail"),
]
