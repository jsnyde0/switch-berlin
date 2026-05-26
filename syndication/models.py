"""
Syndication models: Post and PlatformProjection.

These are schema-only models per kb-a4u.1. No behavioral logic beyond what
Django provides for free (enum constraints, FKs, nullability). Reservation
columns (sequence_order, lifecycle_moment, scheduled_for) are present as
data-shape only per ADR-003 cheap foresight and ADR-016 Consequences.

ADR-016 D1: Post is a first-class entity referencing Event by FK.
ADR-016 D2: PlatformProjection carries kind ∈ {listing, promotion} and
            status ∈ {draft, ready, published, failed}, plus per-field
            override storage (override_data JSONField).
ADR-008 D2: No speculative abstraction — no base classes, no adapter
            plugins; plain Django models with choices constraints.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Post(models.Model):
    """
    A communication artifact about an Event (ADR-016 D1).

    One Event has many Posts over its lifecycle:
    save-the-date → early bird → almost-sold-out → last-call.

    Posts and Events never share fields. The Post body is post-canonical
    content, not a projection of event.description.
    """

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        related_name="posts",
    )

    # Core content fields (ADR-016 D1)
    headline = models.CharField(
        max_length=300,
        help_text="Hook / headline for this post.",
    )
    body = models.TextField(
        help_text="Post body — canonical post content, not derived from event.description.",
    )
    imagery = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text="List of image references/URLs for this post.",
    )
    cta = models.CharField(
        max_length=500,
        blank=True,
        help_text="Call-to-action text or URL (e.g., link to listing or Switch event page).",
    )
    voice = models.CharField(
        max_length=100,
        blank=True,
        help_text="Voice/tone intended for this post (e.g., 'playful', 'formal').",
    )

    # --- Campaign-sequence reservation columns (ADR-016 Consequences, ADR-003 cheap foresight) ---
    # These are data-shape reservations only. Behavioral campaign-sequencing logic
    # ships in the campaign-sequence epic, not here.

    sequence_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "RESERVED: ordinal position of this Post within a multi-Post campaign "
            "sequence. null = standalone post (no sequence). Behavior: campaign-sequence epic."
        ),
    )
    lifecycle_moment = models.CharField(
        max_length=50,
        blank=True,
        help_text=(
            "RESERVED: intended moment in the event lifecycle "
            "(e.g., 'save_the_date', 'early_bird', 'almost_sold_out', 'last_call'). "
            "Behavior: campaign-sequence epic."
        ),
    )
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "RESERVED: when this post should be published. "
            "null = publish immediately / manual. Behavior: campaign-sequence epic."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("post")
        verbose_name_plural = _("posts")

    def __str__(self):
        return f"{self.headline} (for {self.event})"


class PlatformProjection(models.Model):
    """
    A per-platform editable copy of either an Event (kind=listing) or a Post
    (kind=promotion) per ADR-016 D2.

    Carries:
    - kind ∈ {listing, promotion}
    - status ∈ {draft, ready, published, failed}
    - source_event FK (listing-kind only)
    - source_post FK (promotion-kind only)
    - override_data JSONField for per-field overrides
    - external_id, external_url, syndicated_at (populated after publication)
    - platform_id (e.g. 'fetlife', 'tickettailor', 'switch-berlin-own', 'telegram-channel:<id>')

    No behavioral logic beyond Django ORM constraints.
    """

    class Kind(models.TextChoices):
        LISTING = "listing", _("Listing")
        PROMOTION = "promotion", _("Promotion")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        READY = "ready", _("Ready")
        PUBLISHED = "published", _("Published")
        FAILED = "failed", _("Failed")

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    platform_id = models.CharField(
        max_length=200,
        help_text=(
            "Platform identifier, e.g. 'fetlife', 'tickettailor', "
            "'switch-berlin-own', 'telegram-channel:<channel_id>'."
        ),
    )

    # Source FKs — listing-kind uses source_event; promotion-kind uses source_post.
    # Both are nullable at the DB level so either can be present. Application
    # logic (or a future constraint) enforces the mutual-exclusion invariant.
    source_event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="projections",
    )
    source_post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="projections",
    )

    # Per-field overrides (ADR-016 D2): every field of the source can be
    # independently overridden on the projection; absent override = use canonical.
    override_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-field overrides for this projection. Absent key = use canonical value.",
    )

    # Populated after publication
    external_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="ID assigned by the target platform after publication.",
    )
    external_url = models.URLField(
        blank=True,
        help_text="URL of this content on the target platform after publication.",
    )
    syndicated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this projection was successfully published.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("platform projection")
        verbose_name_plural = _("platform projections")

    def __str__(self):
        return f"{self.platform_id} / {self.kind} / {self.status}"
