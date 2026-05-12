from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class ProfileManager(models.Manager):
    def visible(self):
        return self.filter(hidden=False)


class Profile(models.Model):
    objects = ProfileManager()

    KIND_CHOICES = [
        ("person", "Person"),
        ("collective", "Collective"),
    ]

    # Discriminator
    kind = models.CharField(
        max_length=20,
        choices=KIND_CHOICES,
        default="collective",
    )

    # Identity
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    avatar = models.ImageField(upload_to="organizers/", blank=True, null=True)
    website = models.URLField(blank=True)
    telegram_link = models.CharField(max_length=200, blank=True)

    # Person-specific (optional for either kind)
    pronouns = models.CharField(max_length=100, blank=True)

    # Claim mechanism (ADR-007 D5)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="claimed_profiles",
    )
    claimed_at = models.DateTimeField(null=True, blank=True)

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
        related_name="approved_profiles",
    )

    # GDPR consent (F5 — pulled forward from 0.2; consumed from 0.5)
    consent_recorded_at = models.DateTimeField(null=True, blank=True)
    CONSENT_METHOD_CHOICES = [
        ("legitimate_interest", "Legitimate interest (Art. 6(1)(f))"),
        ("telegram_forward_implied", "Telegram forward (implied)"),
        ("explicit_opt_in", "Explicit opt-in"),
        ("verified_public_source", "Verified public source"),
    ]
    consent_method = models.CharField(
        choices=CONSENT_METHOD_CHOICES,
        blank=True,
    )
    consent_notes = models.TextField(blank=True)

    # Aggregate / visibility fields (Phase 0.5)
    hidden = models.BooleanField(default=False)
    follower_count = models.IntegerField(default=0)
    avg_rating = models.FloatField(null=True)
    rating_count = models.IntegerField(default=0)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("profile")
        verbose_name_plural = _("profiles")

    def __str__(self):
        return self.name

    @property
    def events(self):
        """
        Compat accessor: returns the queryset of Events where this Profile
        is an organizer (any is_primary value). Replaces the old FK reverse
        manager so existing call sites (`profile.events.all()`) keep working.

        New code should prefer `profile.events_organized.all()`.
        """
        return self.events_organized.all()


class OrganizerFollow(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="follows",
    )
    organizer = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "organizer")]

    def __str__(self):
        return f"{self.user} follows {self.organizer}"
