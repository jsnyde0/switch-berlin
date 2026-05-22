"""
Event queryset managers — visibility-aware access control.

ADR-012 D3: viewer × event-tier access matrix. The set of User.status values
that qualify as "trusted viewer" is configurable via
``settings.EVENT_VISIBILITY_TRUSTED_STATUSES`` (FLEXIBLE per ADR-012 D3).
"""

from django.conf import settings
from django.db import models


def _is_trusted_viewer(user):
    """Return True iff the user qualifies for non-public Event tiers.

    Trusted viewers are: superuser, staff, and any user whose status is in
    ``settings.EVENT_VISIBILITY_TRUSTED_STATUSES`` (default: ``("vouched",)``).
    Suspended, banned, open-status, and anonymous users are NOT trusted by
    default. Per ADR-013 D1: suspended/banned behave like anonymous for access
    control.
    """
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.status in settings.EVENT_VISIBILITY_TRUSTED_STATUSES


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Return the subset of events the given viewer may see in *listings*.

        Access matrix per ADR-012 D3:
        - Anon / unauthenticated: public only
        - User whose status is NOT in EVENT_VISIBILITY_TRUSTED_STATUSES: public only
        - Trusted viewer (status in TRUSTED_STATUSES, staff, or superuser):
          public + semi_public

        The `unlisted` tier is URL-keyed — trusted viewers who *know the URL*
        can access via visible_to_url(), but the listing queryset never
        surfaces unlisted events.

        ADR-008 D3: invalid visibility raises at migration time; runtime never
        encounters a null/unknown value.
        """
        if _is_trusted_viewer(user):
            if user.is_superuser or user.is_staff:
                return self.all()
            return self.filter(visibility__in=["public", "semi_public"])
        return self.filter(visibility="public")

    def visible_to_url(self, user):
        """
        Return the subset of events accessible via direct URL (detail views).

        Extends visible_to() to include `unlisted` events for trusted viewers
        — ADR-012 D3: `unlisted` tier is URL-keyed, so anyone who qualifies as
        a trusted viewer AND knows the URL can access it.

        Per ADR-013 D1: suspended and banned users behave like anonymous
        regardless of URL possession.
        """
        if _is_trusted_viewer(user):
            return self.all()
        return self.filter(visibility="public")


class EventManager(models.Manager):
    def get_queryset(self):
        return EventQuerySet(self.model, using=self._db)

    def visible(self):
        """Legacy: return events with hidden=False."""
        return self.get_queryset().filter(hidden=False)

    def visible_to(self, user):
        """Return events visible to the given viewer per ADR-012 D3 (listings)."""
        return self.get_queryset().visible_to(user)

    def visible_to_url(self, user):
        """Return events accessible via direct URL per ADR-012 D3 (detail views).

        Includes `unlisted` events for trusted viewers per
        ``settings.EVENT_VISIBILITY_TRUSTED_STATUSES``.
        """
        return self.get_queryset().visible_to_url(user)
