from django.urls import path

from . import views

urlpatterns = [
    path("submit/", views.submit_review, name="review-submit"),
    path("flag/", views.flag_target, name="flag-target"),
]
