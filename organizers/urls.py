from django.urls import path

from . import views

urlpatterns = [
    # Claim flow (ADR-014 D2 + D3)
    path("<slug:slug>/claim/", views.claim_entry, name="organizer-claim-entry"),
    path(
        "<slug:slug>/claim/check-email/",
        views.claim_check_email,
        name="organizer-claim-check-email",
    ),
    path(
        "claim/redeem/<uuid:token>/",
        views.magic_link_redeem,
        name="organizer-claim-redeem",
    ),
    # Follow
    path("<slug:slug>/follow/", views.organizer_follow, name="organizer-follow"),
    # Legacy redirect: /o/<slug>/ → /p/<slug>/
    path("<slug:slug>/", views.profile_legacy_redirect, name="profile-legacy-redirect"),
]
