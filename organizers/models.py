from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class Organizer(models.Model):
    # Identity
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="organizers/", blank=True, null=True)
    website = models.URLField(blank=True)
    telegram_channel = models.CharField(max_length=200, blank=True)

    # Trust tier
    status = models.CharField(
        choices=[
            ("candidate", "Candidate"),
            ("approved", "Approved"),
            ("suspended", "Suspended"),
        ],
        default="candidate",
    )
    verified_badge = models.BooleanField(default=False)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_organizers",
    )

    # GDPR consent (F5 — pulled forward from 0.2; consumed from 0.5)
    consent_recorded_at = models.DateTimeField(null=True, blank=True)
    consent_method = models.CharField(
        choices=[
            ("telegram_forward_implied", "Telegram forward (implied)"),
            ("explicit_opt_in", "Explicit opt-in"),
            ("verified_public_source", "Verified public source"),
        ],
        blank=True,
    )
    consent_notes = models.TextField(blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("organizer")
        verbose_name_plural = _("organizers")

    def __str__(self):
        return self.name
