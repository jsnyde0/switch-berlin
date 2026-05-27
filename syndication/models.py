"""
Syndication models: PlatformConnection, Post, and PlatformProjection.

These are schema-only models. No behavioral logic beyond what Django provides
for free (enum constraints, FKs, nullability). Reservation columns
(sequence_order, lifecycle_moment, scheduled_for, generated_by,
last_generated_at) are present as data-shape only per ADR-003 cheap foresight
and ADR-016 Consequences.

ADR-016 D1: Post is a first-class entity referencing Event by FK.
ADR-016 D2: PlatformProjection carries kind ∈ {listing, promotion},
            status ∈ {draft, ready, published, failed}, provenance
            ∈ {rule_template, agent_supplied, manual}, plus per-field
            override storage (override_data JSONField), plus ADR-003
            reservation fields generated_by and last_generated_at.
ADR-016 D4: PlatformConnection is a specific syndication destination owned
            by an organizer. PlatformProjection FKs to PlatformConnection,
            not to a bare platform_id string.
ADR-007 D2: PlatformConnection uses organizer/Profile FK (through-table
            pattern — direct FK here as the join is 1:N, not M2N).
ADR-008 D2: No speculative abstraction — no base classes, no adapter
            plugins; plain Django models with choices constraints.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PlatformConnection(models.Model):
    """
    A specific syndication destination owned by an organizer (ADR-016 D4).

    This model unifies two surfaces that would otherwise drift:
    - The organizer's "which platforms am I syndicating to" setting (enabled flag).
    - The per-organizer adapter credential store the adapter beads consume
      (credentials JSONField).

    An organizer may hold multiple connections per platform (e.g., three
    Telegram channels = three PlatformConnection rows). Multiple rows per
    platform is additive — zero schema reshape.

    Supported kinds for known platforms (ADR-016 D4):
    - Switch own-event-page → listing
    - Ticket Tailor → listing
    - Telegram channel → promotion
    - FetLife → both (listing + promotion)
    """

    organizer = models.ForeignKey(
        "organizers.Profile",
        on_delete=models.CASCADE,
        related_name="platform_connections",
        help_text="The organizer/Profile that owns this connection.",
    )
    platform = models.CharField(
        max_length=100,
        help_text=(
            "Platform identifier, e.g. 'fetlife', 'tickettailor', "
            "'switch', 'telegram'."
        ),
    )
    destination_id = models.CharField(
        max_length=300,
        help_text=(
            "Platform-specific destination identifier, e.g. a Telegram channel ID, "
            "a FetLife username, a Ticket Tailor account ID, or 'own-page' for Switch."
        ),
    )
    credentials = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Per-destination credentials for adapter access. "
            "Structure is platform-specific. Empty = no stored creds (e.g. Switch own page)."
        ),
    )
    enabled = models.BooleanField(
        default=True,
        help_text=(
            "Whether projections should be eagerly created for this connection. "
            "Disable to pause syndication to this destination without deleting it."
        ),
    )
    kinds = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Projection kinds this connection supports: 'listing', 'promotion', or both. "
            "e.g. ['listing'] for Switch/TT, ['promotion'] for Telegram, "
            "['listing', 'promotion'] for FetLife."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["platform", "destination_id"]
        verbose_name = _("platform connection")
        verbose_name_plural = _("platform connections")

    def __str__(self):
        return f"{self.organizer} → {self.platform} / {self.destination_id}"


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
    - connection FK to PlatformConnection (ADR-016 D4 — replaces the former
      platform_id string; deleted per ADR-008 D1, no backward-compat shim)
    - kind ∈ {listing, promotion}
    - status ∈ {draft, ready, published, failed}
    - source_event FK (listing-kind only)
    - source_post FK (promotion-kind only)
    - override_data JSONField for per-field overrides
    - provenance ∈ {rule_template, agent_supplied, manual} (ADR-016 D2 refinement)
    - generated_by (nullable agent identity) — ADR-003 reservation field
    - last_generated_at (nullable datetime) — ADR-003 reservation field
    - external_id, external_url, syndicated_at (populated after publication)

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

    class Provenance(models.TextChoices):
        RULE_TEMPLATE = "rule_template", _("Rule template")
        AGENT_SUPPLIED = "agent_supplied", _("Agent supplied")
        MANUAL = "manual", _("Manual")

    # Connection FK (ADR-016 D4) — the specific PlatformConnection destination.
    # platform_id CharField removed per ADR-008 D1 (pre-launch, no shim).
    connection = models.ForeignKey(
        PlatformConnection,
        on_delete=models.CASCADE,
        related_name="projections",
        help_text="The specific PlatformConnection (destination) this projection targets.",
    )

    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
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

    # Provenance and attribution reservation fields (ADR-016 D2, ADR-003).
    # provenance tracks how the current effective content was last produced.
    # Flips to 'manual' the moment a human edits an override.
    provenance = models.CharField(
        max_length=20,
        choices=Provenance.choices,
        default=Provenance.RULE_TEMPLATE,
        help_text=(
            "How the current effective content was last produced. "
            "Flips to 'manual' on human edit of an override."
        ),
    )
    # RESERVED: agent identity that generated this projection (ADR-003 cheap foresight).
    # Null for human-driven flows; the column a future ProjectionRevision table keys on.
    generated_by = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "RESERVED: agent identity ref that last generated content for this "
            "projection. null = human-driven. Behavior: future projection-revision epic."
        ),
    )
    # RESERVED: timestamp of last agent generation (ADR-003 cheap foresight).
    last_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "RESERVED: when this projection was last generated by an agent. "
            "null = never generated. Behavior: future projection-revision epic."
        ),
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
        return f"{self.connection} / {self.kind} / {self.status}"
