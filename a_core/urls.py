"""URL configuration for kinky-bubbles."""

from debug_toolbar.toolbar import debug_toolbar_urls
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from pages.views import age_check_view, robots_txt_view

urlpatterns = [
    path("", include("pages.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("events/", include("events.urls")),
    path("o/", include("organizers.urls")),
    path("reviews/", include("reviews.urls")),
    path("robots.txt", robots_txt_view, name="robots-txt"),
    path("age-check/", age_check_view, name="age-check"),
]

if settings.DEBUG:
    urlpatterns += debug_toolbar_urls()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
