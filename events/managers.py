"""
Event queryset managers — visibility-aware access control.

ADR-012 D3: viewer × event-tier access matrix.
"""

from django.db import models


def _is_trusted_viewer(user):
    """Return True iff the user has full trusted-viewer access.

    Trusted viewers are: superuser, staff, and vouched-status users.
    Suspended, banned, open-status, and anonymous users are NOT trusted.
    Per ADR-013 D1: suspended/banned behave like anonymous for access control.
    """
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return getattr(user, "status", None) == "vouched"


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Return the subset of events the given viewer may see in *listings*.

        Access matrix per ADR-012 D3:
        - Anon / unauthenticated: public only
        - open-status user: public only
        - vouched-status user: public + semi_public
        - superuser / staff: all tiers (public + semi_public + unlisted)

        The `unlisted` tier is URL-keyed — a vouched user who *knows the URL*
        can access the event, but the queryset does NOT surface unlisted events
        in listings. That's handled by visible_to_url() at the view layer
        (kb-m69.6).
        ADR-008 D3: invalid visibility raises at migration time; runtime never
        encounters a null/unknown value.
        """
        if user is None or not user.is_authenticated:
            return self.filter(visibility="public")

        # Superuser / staff see everything (admin tooling, moderation)
        if user.is_superuser or user.is_staff:
            return self.all()

        # Determine tier from User.status (ADR-008 D1: no compat shim)
        is_vouched = user.status == "vouched"

        if is_vouched:
            return self.filter(visibility__in=["public", "semi_public"])

        # open status (or any unrecognised status) → public only
        return self.filter(visibility="public")

    def visible_to_url(self, user):
        """
        Return the subset of events accessible via direct URL (detail views).

        Extends visible_to() to include `unlisted` events for trusted viewers
        (vouched / staff / superuser) — ADR-012 D3: `unlisted` tier is
        URL-keyed, so anyone with the URL can access it, but only trusted
        viewers (not suspended / banned / open / anonymous).

        Per ADR-013 D1: suspended and banned users behave like anonymous
        regardless of URL possession.
        """
        if user is None or not user.is_authenticated:
            return self.filter(visibility="public")

        # Superuser / staff see everything
        if user.is_superuser or user.is_staff:
            return self.all()

        status = getattr(user, "status", "open")

        if status == "vouched":
            # Vouched users can access public + semi_public + unlisted by URL
            return self.filter(visibility__in=["public", "semi_public", "unlisted"])

        # open / suspended / banned → public only
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

        Includes `unlisted` events for trusted viewers (vouched/staff/superuser).
        """
        return self.get_queryset().visible_to_url(user)
