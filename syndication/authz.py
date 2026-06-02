"""
Authorization seam for syndication (ADR-017 D2).

Single chokepoint for edit/publish authorization.
Policy per ADR-017 D1: a principal may edit/publish an Event iff they are a
claimant (via ProfileClaim) of a Profile that is an EventOrganizer of that Event.
EventFacilitators are credited-only and cannot edit or publish.

v0: trivially satisfied for single-facilitator case.
Future: enrich this seam for team-management (ADR-017 D3 — ProfileClaim.role).
Do NOT inline is_primary / claimant checks at call sites.
"""

from events.models import EventOrganizer
from organizers.models import ProfileClaim


def can_edit(user, event) -> bool:
    """
    Return True iff user is a claimant of an EventOrganizer Profile for this event.

    A claimant is a user with an active (non-revoked) ProfileClaim on a Profile
    that is in the event's EventOrganizer through-table.

    EventFacilitators are credited-only — they do NOT get edit rights.
    v0: ProfileClaim.role is trivially 'admin' for all claimants.
    ADR-017 D2: single seam, no scattered is_primary checks.
    """
    # Get all organizer Profile IDs for this event.
    organizer_profile_ids = EventOrganizer.objects.filter(event=event).values_list("profile_id", flat=True)

    if not organizer_profile_ids:
        return False

    # Check if user holds an active ProfileClaim on any of those profiles.
    # Active = rejected_at IS NULL (ADR-014 D1 soft-delete convention).
    return ProfileClaim.objects.filter(
        profile_id__in=organizer_profile_ids,
        user=user,
        rejected_at__isnull=True,
    ).exists()


def can_publish(user, event) -> bool:
    """
    Return True iff user may publish projections for this event.

    At v0, publish authority is identical to edit authority (ADR-017 D2 — same
    derivation; edit and publish are sibling predicates that share v0 logic).
    When edit and publish authority legitimately diverge, enrich this seam here
    without touching call sites.
    """
    return can_edit(user, event)
