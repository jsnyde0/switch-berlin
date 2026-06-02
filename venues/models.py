from django.db import models
from django.utils.translation import gettext_lazy as _


class Venue(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    address = models.CharField(max_length=300, blank=True)
    neighborhood = models.CharField(max_length=100, blank=True)

    # F4 — Decimal, migrate to PointField later if needed
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Privacy mode (matches ADR-001 D5; feeds map blur at 0.4)
    privacy_mode = models.CharField(
        choices=[
            ("public", "Public"),
            ("neighborhood_blur", "Neighborhood blur"),
            ("private", "Private address on request"),
        ],
        default="public",
    )
    blur_radius_m = models.IntegerField(default=250)

    url = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("venue")
        verbose_name_plural = _("venues")

    def __str__(self):
        return self.name
