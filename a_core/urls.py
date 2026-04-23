"""URL configuration for kinky-bubbles."""

from debug_toolbar.toolbar import debug_toolbar_urls
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import (
    RateLimitedSignupView,
    art9_consent_view,
    art9_consent_withdraw_view,
    me_view,
)
from pages.views import age_check_view, robots_txt_view
from reviews.views import organizer_opt_out_view, takedown_view

urlpatterns = [
    path("", include("pages.urls")),
    path("admin/", admin.site.urls),
    path("accounts/signup/", RateLimitedSignupView.as_view(), name="account_signup"),
    path("accounts/", include("allauth.urls")),
    path("events/", include("events.urls")),
    path("o/", include("organizers.urls")),
    path("reviews/", include("reviews.urls")),
    path("me/", me_view, name="me"),
    path("accounts/art9-consent/", art9_consent_view, name="art9-consent"),
    path(
        "accounts/art9-consent/withdraw/",
        art9_consent_withdraw_view,
        name="art9-consent-withdraw",
    ),
    path("robots.txt", robots_txt_view, name="robots-txt"),
    path("age-check/", age_check_view, name="age-check"),
    path("takedown/", takedown_view, name="takedown"),
    path("organizer-opt-out/", organizer_opt_out_view, name="organizer-opt-out"),
]

if settings.DEBUG:
    urlpatterns += debug_toolbar_urls()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
