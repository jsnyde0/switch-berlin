"""Custom context processors for Switch."""

from a_core.legal import get_legal_contact
from a_core.models import get_flag, get_numeric


def legal_contact_processor(request):
    """Make legal_contact dict available in all template contexts."""
    return {"legal_contact": get_legal_contact()}


def user_primary_profile(request):
    """
    Expose the claimant's primary Profile in all template contexts.

    Returns the first active ProfileClaim's Profile for a claimant user,
    or None for non-claimants, anonymous users, and any user with no claim.

    MUST NOT call the raising _get_primary_profile_for_user — wraps the
    zero-claims case as None so it never raises during template rendering
    (parent D3, ADR-008 D3 context-processor contract).

    Used by the navbar to show/hide the Studio link (claimant-gated).
    """
    user = request.user
    # Anonymous users are never claimants
    if not user.is_authenticated:
        return {"user_primary_profile": None}

    from organizers.models import ProfileClaim

    claim = (
        ProfileClaim.objects.filter(user=user, rejected_at__isnull=True)
        .select_related("profile")
        .first()
    )
    return {"user_primary_profile": claim.profile if claim is not None else None}


def feature_flags(request):
    return {
        "MAP_ENABLED": get_flag("MAP_ENABLED", default=True),
        "INVITES_ENABLED": get_flag("INVITES_ENABLED", default=True),
        "PUBLIC_READ_ENABLED": get_flag("PUBLIC_READ_ENABLED", default=True),
        "RATINGS_ENABLED": get_flag("RATINGS_ENABLED", default=True),
        "FLAGS_ENABLED": get_flag("FLAGS_ENABLED", default=True),
        "EVENT_REVIEWS_DISPLAYED": get_flag("EVENT_REVIEWS_DISPLAYED", default=False),
        "EVENT_RATING_THRESHOLD": get_numeric(
            "threshold.event_ratings_display", default=3
        ),
    }
