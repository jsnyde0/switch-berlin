from django.urls import path

from .views import (
    home_view,
    impressum_view,
    privacy_view,
    terms_view,
    test_partial_view,
    test_skeleton_hx,
)

urlpatterns = [
    path("", home_view, name="home"),
    path("hx/test-partial", test_partial_view, name="test-partial"),
    path("hx/test-skeleton", test_skeleton_hx, name="test-skeleton-hx"),
    path("impressum/", impressum_view, name="impressum"),
    path("privacy/", privacy_view, name="privacy"),
    path("terms/", terms_view, name="terms"),
]
