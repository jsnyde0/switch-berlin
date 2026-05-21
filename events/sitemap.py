"""
Event sitemap — excludes non-public events per ADR-012 D3.

semi_public and unlisted events are excluded from the sitemap.
Only public-tier published events appear.
"""

from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from events.models import Event


class EventSitemap(Sitemap):
    """Sitemap for public-tier published events."""

    changefreq = "weekly"
    priority = 0.8

    def items(self):
        """Return only public-tier published events (ADR-012 D3)."""
        return (
            Event.objects.filter(
                visibility="public",
                status="published",
            )
            .select_related("venue")
            .prefetch_related("event_organizer_set__profile")
            .order_by("-start")
        )

    def location(self, obj):
        """Return the URL for the given event."""
        organizer = obj.organizer
        if organizer is None:
            # Events without an organizer are rare; fall back to a generic path.
            return f"/events/{obj.slug}/"
        return reverse(
            "event_detail",
            kwargs={"org_slug": organizer.slug, "event_slug": obj.slug},
        )
