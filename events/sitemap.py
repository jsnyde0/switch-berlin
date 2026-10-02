"""
Event sitemap — excludes non-public events per ADR-012 D3.

semi_public and unlisted events are excluded from the sitemap.
Only public-tier, published, non-hidden events appear.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from events.models import Event


class EventSitemap(Sitemap):
    """Sitemap for public-tier published events."""

    changefreq = "weekly"
    priority = 0.8

    def items(self):
        """Return only public-tier, published, non-hidden events (ADR-012 D3)."""
        return (
            Event.objects.filter(
                visibility="public",
                status="published",
                hidden=False,
                # location() needs a primary organizer; no route exists without one.
                event_organizer_set__is_primary=True,
            )
            .select_related("venue")
            .prefetch_related("event_organizer_set__profile")
            .order_by("-start")
        )

    def location(self, obj):
        """Return the URL for the given event."""
        organizer = obj.organizer
        if organizer is None:
            # ADR-008 D3: no route matches an organizer-less event; never emit a broken URL.
            raise ValueError(f"Event {obj.pk} has no primary organizer; it has no detail URL")
        return reverse(
            "event-detail",
            kwargs={"org_slug": organizer.slug, "event_slug": obj.slug},
        )
