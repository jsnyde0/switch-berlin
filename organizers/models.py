from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from a_core.validators import validate_image_size


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
    avatar = models.ImageField(
        upload_to="organizers/",
        blank=True,
        null=True,
        validators=[
            validate_image_size,
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]),
        ],
    )
    website = models.URLField(blank=True)
    telegram_link = models.CharField(max_length=200, blank=True)

    # Person-specific (optional for either kind)
    pronouns = models.CharField(max_length=100, blank=True)

    # Claim mechanism — ProfileClaim through-model (ADR-014 D1, ADR-007 D5 revised 2026-05-21)
    # Profile.claimed_by FK removed; use Profile.claimants M2M and Profile.is_claimed property.
    claimants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="ProfileClaim",
        related_name="claimed_profiles",
        blank=True,
    )

    # Claim fast-path (ADR-014 D2 — email-domain fast-path, admin-set opt-in)
    verified_domain = models.CharField(
        max_length=253,
        blank=True,
        null=True,
        db_index=True,
        help_text=(
            "Admin-set domain for email-domain fast-path claim verification "
            "(ADR-014 D2). If set, users whose email matches this domain can "
            "claim this profile via magic-link without admin review."
        ),
    )

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
    def active_claimants(self):
        """
        Returns the User queryset for active (non-revoked) ProfileClaim rows.
        Active = rejected_at IS NULL per ADR-014 D1 (revised 2026-05-21).
        """
        return self.claimants.filter(profileclaim__rejected_at__isnull=True)

    @property
    def is_claimed(self):
        """
        True if there is at least one active (non-revoked) ProfileClaim.
        Uses active_claimants per ADR-014 D1 (revised 2026-05-21) — excludes
        claims with rejected_at set (soft-deleted via admin revoke, ADR-003).
        """
        return self.profileclaim_set.filter(rejected_at__isnull=True).exists()

    @property
    def events(self):
        """
        Compat accessor: returns the queryset of Events where this Profile
        is an organizer (any is_primary value). Replaces the old FK reverse
        manager so existing call sites (`profile.events.all()`) keep working.

        New code should prefer `profile.events_organized.all()`.
        """
        return self.events_organized.all()


class ProfileClaim(models.Model):
    """
    Through-model for Profile ↔ User M2M claim relationship.

    Replaces Profile.claimed_by FK per ADR-014 D1 + ADR-007 D5 (revised 2026-05-21).
    Cardinality: 0..N — a Profile may have multiple active claimants (e.g. IKSK co-organizers).

    verified_method enum vocabulary (ADR-014 D1):
    - "email_domain" — email-domain fast-path (S8 fast-path)
    - "admin_review"  — admin-review fallback track (S9 approval)
    - "admin_legacy"  — data-migration backfill for pre-through-model rows
    - "auto_self"     — signup-time auto-claim of user's own kind=person Profile (S4)

    rejected_at + rejected_by_admin are cheap-foresight soft-delete cols (ADR-003);
    S9 (admin claim-queue) populates them on revoke. Active claims have rejected_at=NULL.
    """

    VERIFIED_METHOD_CHOICES = [
        ("email_domain", "Email domain fast-path"),
        ("admin_review", "Admin review"),
        ("admin_legacy", "Admin legacy (migration backfill)"),
        ("auto_self", "Auto self-claim on signup"),
    ]

    ROLE_CHOICES = [
        ("admin", "Admin"),  # V0 default; cheap foresight for future roles
    ]

    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
    )
    verified_at = models.DateTimeField(default=timezone.now)
    verified_method = models.CharField(
        max_length=30,
        choices=VERIFIED_METHOD_CHOICES,
    )
    # NULL for email_domain / auto_self tracks; set to admin username string for
    # admin_review / admin_legacy tracks (canonical string per ADR-014 D1 line 137).
    verified_by_admin = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        default="admin",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # Cheap-foresight soft-delete cols (ADR-003); populated by S9 admin revoke.
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by_admin = models.CharField(
        max_length=150,
        blank=True,
        null=True,
    )

    class Meta:
        unique_together = [("profile", "user")]

    def __str__(self):
        return f"{self.user} → {self.profile} ({self.verified_method})"


class Follow(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="follows",
    )
    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="followers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("user", "profile")]

    def __str__(self):
        return f"{self.user} follows {self.profile}"
