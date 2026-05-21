"""
Event queryset managers — visibility-aware access control.

ADR-012 D3: viewer × event-tier access matrix.
"""

from django.db import models


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """
        Return the subset of events the given viewer may see.

        Access matrix per ADR-012 D3:
        - Anon / unauthenticated: public only
        - open-status user: public only
        - vouched-status user: public + semi_public
        - superuser / staff: all tiers (public + semi_public + unlisted)

        The `unlisted` tier is URL-keyed — a vouched user who *knows the URL*
        can access the event, but the queryset does NOT surface unlisted events
        in listings. That's handled at the view/middleware layer (kb-m69.6).
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


class EventManager(models.Manager):
    def get_queryset(self):
        return EventQuerySet(self.model, using=self._db)

    def visible(self):
        """Legacy: return events with hidden=False."""
        return self.get_queryset().filter(hidden=False)

    def visible_to(self, user):
        """Return events visible to the given viewer per ADR-012 D3."""
        return self.get_queryset().visible_to(user)
