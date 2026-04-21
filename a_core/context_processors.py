"""Custom context processors for kinky-bubbles."""

from a_core.models import get_flag


def feature_flags(request):
    return {
        "MAP_ENABLED": get_flag("MAP_ENABLED", default=True),
        "INVITES_ENABLED": get_flag("INVITES_ENABLED", default=True),
        "PUBLIC_READ_ENABLED": get_flag("PUBLIC_READ_ENABLED", default=True),
        "RATINGS_ENABLED": get_flag("RATINGS_ENABLED", default=True),
        "FLAGS_ENABLED": get_flag("FLAGS_ENABLED", default=True),
    }
