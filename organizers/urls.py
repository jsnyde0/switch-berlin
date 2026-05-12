from django.urls import path

from . import views

urlpatterns = [
    path("<slug:slug>/follow/", views.organizer_follow, name="organizer-follow"),
    path("<slug:slug>/", views.profile_legacy_redirect, name="profile-legacy-redirect"),
]
