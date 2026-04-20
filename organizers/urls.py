from django.urls import path

from . import views

urlpatterns = [
    path("<slug:slug>/follow/", views.organizer_follow, name="organizer-follow"),
    path("<slug:slug>/", views.organizer_profile, name="organizer-profile"),
]
