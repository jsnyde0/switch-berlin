"""Custom context processors for kinky-bubbles."""

from django.conf import settings


def feature_flags(request):
    """Expose feature-flag kill-switches to all templates.

    Adds MAP_ENABLED and INVITES_ENABLED to every template context so that
    navbar, list page, and other templates can conditionally render map/invite
    UI without importing settings directly.
    """
    return {
        "MAP_ENABLED": getattr(settings, "MAP_ENABLED", True),
        "INVITES_ENABLED": getattr(settings, "INVITES_ENABLED", True),
    }
