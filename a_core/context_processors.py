"""Custom context processors for Switch."""

from a_core.legal import get_legal_contact
from a_core.models import get_flag, get_numeric


def legal_contact_processor(request):
    """Make legal_contact dict available in all template contexts."""
    return {"legal_contact": get_legal_contact()}


def feature_flags(request):
    return {
        "MAP_ENABLED": get_flag("MAP_ENABLED", default=True),
        "INVITES_ENABLED": get_flag("INVITES_ENABLED", default=True),
        "PUBLIC_READ_ENABLED": get_flag("PUBLIC_READ_ENABLED", default=True),
        "RATINGS_ENABLED": get_flag("RATINGS_ENABLED", default=True),
        "FLAGS_ENABLED": get_flag("FLAGS_ENABLED", default=True),
        "EVENT_REVIEWS_DISPLAYED": get_flag("EVENT_REVIEWS_DISPLAYED", default=False),
        "EVENT_RATING_THRESHOLD": get_numeric("threshold.event_ratings_display", default=3),
    }
