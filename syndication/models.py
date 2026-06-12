"""
Syndication models: PlatformConnection, Post, ContentVersion,
PlatformProjection, AgentCredential, and IdentityToken.

These are schema-only models. No behavioral logic beyond what Django provides
for free (enum constraints, FKs, nullability). Reservation columns
(sequence_order, lifecycle_moment, scheduled_for, generated_by,
last_generated_at) are present as data-shape only per ADR-003 cheap foresight
and ADR-016 Consequences.

ADR-016 D1: Post is a first-class entity referencing Event by FK.
ADR-016 D2: PlatformProjection carries kind ∈ {listing, promotion},
            status ∈ {draft, ready, published, failed}, a content_version FK
            to ContentVersion (editorial content + authorship signals live
            there; provenance, generated_by, last_generated_at removed from
            projection in kb-wz8m.2), and a frozen_content snapshot for
            ready/published/failed status.
            ContentVersion (added kb-wz8m.1, live-render path kb-wz8m.2):
            per-Event named editorial copy variant. NULL field = derive from
            live canonical Event/Post. Explicit value = override.
ADR-016 D3: v0 auth shape — long-lived Bearer API key → short-lived identity
            token exchange. AgentCredential mirrors MagicLinkToken envelope
            (organizers/models.py): hashed-storage + displayed-once. Single-use
            semantics were deliberately rejected — the key is long-lived and
            reusable; identity tokens are reusable within their TTL.
ADR-016 D4: PlatformConnection is a specific syndication destination owned
            by an organizer. PlatformProjection FKs to PlatformConnection,
            not to a bare platform_id string.
ADR-017 D1: Agent is the user's delegate — identical authority; actor-marker
            is audit-only provenance (no authority difference).
ADR-007 D2: PlatformConnection uses organizer/Profile FK (through-table
            pattern — direct FK here as the join is 1:N, not M2N).
ADR-008 D2: No speculative abstraction — no base classes, no adapter
            plugins; plain Django models with choices constraints.
"""

import hashlib
import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TelegramDialogType(models.TextChoices):
    """
    Canonical Telegram dialog-type vocabulary (kb-ru55.2 D1a — SINGLE resolution point).

    This is the ONLY definition of these values across the entire project.
    The sync agent (kb-ru55.3) emits them, this model stores them, and kb-sbhs's
    web picker categorises by them. Do NOT define a local copy in kb-sbhs or in
    any CLI child — import this class directly.

    Values match kb-sbhs D3's tree categorisation:
      channel     → Channels bucket
      group       → Groups bucket
      supergroup  → Groups bucket (Telegram supergroup is a group variant)
      forum_topic → Forums → Topics leaf (one row per topic, NOT one per forum)

    NOTE: forum_topic, not forum_group. A Telegram forum GROUP is NOT a postable
    destination — only specific forum TOPICS are. Storing 'forum_group' here would
    be an enum-vocabulary-drift from kb-sbhs's picker (adr-enum-vocabulary-drift-
    invisible-per-bead anti-pattern). Do NOT add forum_group.
    """

    CHANNEL = "channel", _("Channel")
    GROUP = "group", _("Group")
    SUPERGROUP = "supergroup", _("Supergroup")
    FORUM_TOPIC = "forum_topic", _("Forum topic")


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

    Telegram-specific fields (kb-ru55.2 — metadata-only ingest):
    - topic_id: nullable BigIntegerField for forum_topic rows (top_msg_id).
    - type: TelegramDialogType choice — the canonical vocabulary for the dialog type.
    - title: human-readable dialog name as synced from Telegram.
    - postability: capability-ladder tier (e.g. 'bot', 'agent', 'public').
    - flagged_missing: set True when a destination is absent from a later sync
      (ADR-008 D3 — fail loud: flag, never silently delete).

    No server-side session credential — ADR-018 D4: the agent holds the session;
    the server receives only metadata. No access_hash, session_string, or message
    content is stored here.
    """

    organizer = models.ForeignKey(
        "organizers.Profile",
        on_delete=models.CASCADE,
        related_name="platform_connections",
        help_text="The organizer/Profile that owns this connection.",
    )
    platform = models.CharField(
        max_length=100,
        help_text=("Platform identifier, e.g. 'fetlife', 'tickettailor', 'switch', 'telegram'."),
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

    # ---------------------------------------------------------------------------
    # Telegram-specific metadata fields (kb-ru55.2 — metadata-only ingest)
    # Added via migration 0011_platformconnection_telegram_metadata.
    # These fields are ONLY populated for platform='telegram' rows.
    # NO server-side credential (access_hash, session_string) is stored here
    # per ADR-018 D4: the agent is the sole session holder.
    # ---------------------------------------------------------------------------

    topic_id = models.BigIntegerField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Telegram forum-topic ID (top_msg_id). Set only for type=forum_topic rows. "
            "null for channels, groups, and supergroups. "
            "ADR-018 D4: no server-side session credential."
        ),
    )
    type = models.CharField(
        max_length=20,
        choices=TelegramDialogType.choices,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Telegram dialog type (kb-ru55.2 D1a canonical vocabulary). "
            "Matches TelegramDialogType: channel | group | supergroup | forum_topic. "
            "null for non-Telegram connections."
        ),
    )
    title = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Human-readable Telegram dialog name as synced from the agent. "
            "null for non-Telegram connections. "
            "Names/tags overlay (friendly display name, theme tags) is owned by kb-sbhs."
        ),
    )
    postability = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Capability-ladder tier for this Telegram destination (ADR-018 D1). "
            "Values: 'bot' (bot-accessible own/admin channels), "
            "'agent' (private groups + forum topics, requires agent session), "
            "'public' (deep-link only). "
            "null for non-Telegram connections. "
            "Read by kb-sbhs D4 picker rendering."
        ),
    )
    flagged_missing = models.BooleanField(
        default=False,
        help_text=(
            "True if this destination was absent from the most recent inventory sync. "
            "ADR-008 D3: fail loud — flag, never silently delete. "
            "kb-sbhs D3: picker renders flagged rows as vanished/unavailable."
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


class ContentVersion(models.Model):
    """
    A named editorial copy variant for a given Event or Post (ADR-016 D2,
    revised 2026-05-29, added kb-wz8m.1, generalized kb-q4u9.1).

    ContentVersion is scoped to exactly one publishable: either an Event
    (event FK non-null, post FK null) or a Post (post FK non-null, event FK
    null). A DB CheckConstraint enforces this at write-time (ADR-008 D3).

    Carries the editorial content fields (headline, body, imagery, cta, voice)
    plus the content-authorship signals (provenance, generated_by,
    last_generated_at) that ADR-016 D2 says now live on the version rather than
    on the projection.

    Many PlatformProjections may point at one ContentVersion (single-row sharing
    — editing the version propagates to all consumers). Divergence is opt-in via
    snapshot ops (customize / copy-from / copy-to), each minting a new row.

    kb-wz8m.2 cutover: override_data is dropped; content_version is the live
    render path. NULL editorial field = derive from live canonical Event/Post
    at render time (null-means-derive semantics). A1 canonical version is seeded
    EMPTY (all fields NULL = track-live). Editing a field is divergence.

    kb-q4u9.1: event FK made nullable; post FK added (nullable). Exactly one
    must be non-null — enforced by CheckConstraint (fail loud, ADR-008 D3).
    No Publishable base model (ADR-008 D2).
    ADR-003: data-shape reservation; behavioral use ships in kb-wz8m.2+.
    """

    class Provenance(models.TextChoices):
        RULE_TEMPLATE = "rule_template", _("Rule template")
        AGENT_SUPPLIED = "agent_supplied", _("Agent supplied")
        MANUAL = "manual", _("Manual")

    event = models.ForeignKey(
        "events.Event",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="content_versions",
        help_text=("The Event this version belongs to. Exactly one of event/post must be non-null (CheckConstraint)."),
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="content_versions",
        help_text=("The Post this version belongs to. Exactly one of event/post must be non-null (CheckConstraint)."),
    )
    name = models.CharField(
        max_length=200,
        help_text=(
            "Human-readable name for this editorial variant, e.g. 'canonical', 'hipsy-censored', 'campaign-v1'."
        ),
    )

    # Editorial content fields (ADR-016 D2, kb-wz8m.2).
    # NULL means "derive from the live canonical Event/Post at render time"
    # (mirrors the role key-absence played in the old override_data dict).
    # An explicit non-null value is an override that shadows the canonical field.
    # Seeded as NULL/None for the A1 canonical version (track-live semantics).
    headline = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        default=None,
        help_text=("Headline / hook for this version. NULL = derive from canonical Event/Post at render time."),
    )
    body = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Body text for this version. NULL = compose body from live canonical Event/Post fields at render time."
        ),
    )
    imagery = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=("List of image references/URLs for this version. NULL = derive from canonical."),
    )
    cta = models.CharField(
        max_length=500,
        null=True,
        blank=True,
        default=None,
        help_text=("Call-to-action text or URL. NULL = derive from canonical."),
    )
    voice = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        default=None,
        help_text=("Voice/tone for this version (e.g. 'playful', 'formal'). NULL = derive from canonical."),
    )

    # Content-authorship signals (ADR-016 D2, revised 2026-05-29).
    # These describe the content and travel with it; formerly on the projection.
    provenance = models.CharField(
        max_length=20,
        choices=Provenance.choices,
        default=Provenance.RULE_TEMPLATE,
        help_text=("How the content in this version was last produced. Flips to 'manual' on human edit."),
    )
    # RESERVED: agent identity that produced this version (ADR-003 cheap foresight).
    generated_by = models.CharField(
        max_length=300,
        null=True,
        blank=True,
        default=None,
        help_text=(
            "RESERVED: agent identity ref that last generated content for this "
            "version. null = human-driven. Behavior: future projection-revision epic."
        ),
    )
    # RESERVED: timestamp of last agent generation (ADR-003 cheap foresight).
    last_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "RESERVED: when this version was last generated by an agent. "
            "null = never generated. Behavior: future projection-revision epic."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("content version")
        verbose_name_plural = _("content versions")
        constraints = [
            # Exactly one of event/post must be non-null (ADR-008 D3 — fail loud).
            models.CheckConstraint(
                condition=(
                    models.Q(event__isnull=False, post__isnull=True) | models.Q(event__isnull=True, post__isnull=False)
                ),
                name="syndication_contentversion_exactly_one_of_event_post",
                violation_error_message=(
                    "ContentVersion must be scoped to exactly one publishable: "
                    "set exactly one of event or post, not both and not neither."
                ),
            ),
            # Partial unique: (event, name) where event is set.
            # Mirrors PlatformProjection.source_event/source_post pattern.
            models.UniqueConstraint(
                fields=["event", "name"],
                condition=models.Q(event__isnull=False),
                name="syndication_contentversion_event_name_uniq",
            ),
            # Partial unique: (post, name) where post is set.
            models.UniqueConstraint(
                fields=["post", "name"],
                condition=models.Q(post__isnull=False),
                name="syndication_contentversion_post_name_uniq",
            ),
        ]

    def __str__(self):
        if self.event_id is not None:
            return f"{self.name} (event={self.event_id})"
        return f"{self.name} (post={self.post_id})"


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
    - content_version FK (non-null after kb-wz8m.2 migration backfill) —
      editorial content + authorship signals live here (ADR-016 D2 revised
      2026-05-29). override_data and projection-level provenance/generated_by/
      last_generated_at removed in kb-wz8m.2 (ADR-008 D1, no back-compat shim).
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

    # ContentVersion FK (ADR-016 D2, revised 2026-05-29, kb-wz8m.2 cutover).
    # Non-null — every projection always has a content version (A1 invariant).
    # on_delete=PROTECT: deleting a ContentVersion that still has consumer
    # projections is blocked rather than silently nulling/cascading (ADR-008 D3).
    # Many projections may point at one ContentVersion (single-row sharing).
    # Editorial content + authorship signals live on ContentVersion, not here.
    content_version = models.ForeignKey(
        ContentVersion,
        on_delete=models.PROTECT,
        related_name="projections",
        help_text=(
            "ContentVersion this projection draws editorial content from. "
            "Non-null (A1 invariant): every projection always has a version. "
            "NULL field on ContentVersion = derive from live canonical at render time."
        ),
    )

    # Sync-source self-FK (kb-s41r live-share mechanism — ADR-016 D2 re-resolved 2026-06-09).
    # A nullable FK to the source PlatformProjection within the same publishable's
    # projection set. Records which channel this one syncs FROM (live-share: shares
    # the source's content_version row; source edits propagate automatically).
    #
    # Three render states:
    #   (i) content_version IS the shared canonical row AND sync_source IS NULL
    #       → "Shared" (synced live from canonical — default)
    #  (ii) sync_source IS NOT NULL (shares source's content_version row)
    #       → "Synced from <that peer channel> · follows source edits live"
    # (iii) own content_version AND sync_source IS NULL
    #       → "Custom / detached"
    #
    # LIVE propagation: a source edit writes to the shared CV row and reaches all
    # followers automatically (single-row write-once-broadcast + kb-ciqf OOB sibling
    # re-render). No snapshot copy needed.
    # Detach-on-edit: when a FOLLOWER edits its per-channel body, it forks to its own
    # new CV (customize) and sync_source is cleared → state (iii). This is the only
    # path that diverges a channel; editing the SOURCE does NOT detach followers.
    # Re-sync: discard-confirm → re-share the source's current row + re-set sync_source.
    # Cycle guard (backend): a projection is a legal source iff its own
    # sync_source IS NULL. Service raises if asked to sync from a non-null-source
    # projection (ADR-008 D3 fail-loud).
    #
    # on_delete=SET_NULL: deleting the source projection nulls this pointer
    # (the synced channel keeps its own forked content_version if detached, or falls
    # back to the canonical if still sharing — graceful degradation).
    sync_source = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_dependents",
        help_text=(
            "The source PlatformProjection this one syncs FROM (live-share: shares source's "
            "content_version row; source edits propagate live). "
            "NULL = not synced (canonical or custom). Non-null = live-following that peer. "
            "A projection is a legal sync source iff its OWN sync_source IS NULL (cycle guard)."
        ),
    )

    # Publish revision counter (kb-6d7o.2 cache-bust mechanism).
    # Incremented by 1 at each body-freeze that feeds a send:
    #   - draft→ready transition (transition_status in engine.py)
    #   - republish_projection re-materialize (services.py)
    # NOT incremented on draft ContentVersion edits (ADR-016 D2 freeze rule).
    # Embedded as ?v=<publish_rev> in the promotion body at each freeze so
    # the URL the Telegram adapter sends carries the current rev.
    publish_rev = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Publish revision counter. Incremented at each body-freeze that feeds a send "
            "(draft→ready and republish_projection). Embedded as ?v=<rev> in the "
            "promotion body so cached Telegram link previews can be busted."
        ),
    )

    # Frozen content snapshot (ADR-016 D2, kb-a4u.20 hybrid content model).
    # Null while status=draft (projection tracks live canonical via content_version).
    # Materialized at draft→ready transition: stores the full effective content
    # (version explicit fields + live canonical fallbacks at that instant).
    # From ready onward (ready, published, failed), render_projection returns
    # this snapshot — NOT the live canonical. ADR-008 D3: fail loud if a
    # non-draft projection has no frozen_content (missing = bug, not fallback).
    frozen_content = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "Effective content frozen at draft→ready transition. "
            "Null while status=draft. "
            "From ready onward, render_projection returns this snapshot."
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

    @property
    def is_dirty(self):
        """
        True iff this published projection's effective content differs from
        what was frozen at publish time (edit-after-publish, ADR-016 D5).

        Gate order (critical — ADR-016 D5, ADR-008 D3):
          1. status != 'published' → return False immediately.
             A DRAFT projection legitimately has null frozen_content and
             is NEVER dirty — do NOT check frozen_content for drafts.
          2. status == 'published' AND frozen_content is None →
             invariant violation → raise ValueError (ADR-008 D3: fail loud).
          3. status == 'published' AND frozen_content set →
             compute current effective content and compare to frozen.

        Deferred import: engine imports models at module level, so we
        import engine here inside the property body to avoid a circular
        import at load time.
        """
        if self.status != self.Status.PUBLISHED:
            return False

        # status == 'published': frozen_content MUST be set (ADR-008 D3).
        if self.frozen_content is None:
            raise ValueError(
                f"PlatformProjection {self.pk!r} is status='published' but has "
                "frozen_content=None — invariant violation. frozen_content must be "
                "materialized at draft→ready and must not be cleared for published rows. "
                "(ADR-008 D3: fail loud — not a silent dirty=False)"
            )

        # Compare the current effective content dict to the frozen snapshot.
        # Deferred import to avoid circular import (engine imports models at load time).
        from syndication.engine import _materialize_effective_fields  # noqa: PLC0415

        current = _materialize_effective_fields(self)
        return current != self.frozen_content


# ---------------------------------------------------------------------------
# Agent credential auth models (ADR-016 D3, kb-a4u.2)
# ---------------------------------------------------------------------------
# Bearer key (AgentCredential) is LONG-LIVED + reusable for many exchanges.
# "Displayed once" at registration (raw key shown once, stored hashed).
# Revoke via `enabled=False` — no consume-on-exchange semantics.
#
# IdentityToken is ~1h TTL and REUSABLE within that window.
# Enforce expiry; do NOT consume-per-request.
# ---------------------------------------------------------------------------


def _generate_raw_key():
    """Generate a URL-safe 40-byte random token (320-bit entropy)."""
    return secrets.token_urlsafe(40)


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw key for storage. Raw key never stored."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class AgentCredential(models.Model):
    """
    Long-lived Bearer API key for agent → Switch auth (ADR-016 D3).

    The raw key is returned ONCE on agents/register and never stored.
    key_hash stores SHA-256(raw_key) for subsequent lookup.

    The key is LONG-LIVED and REUSABLE for many identity-token exchanges.
    "Displayed once" means the raw key is shown at registration and never
    recoverable — not that the key is single-use for exchanges.

    Revoke a credential by setting enabled=False (soft revoke) or deleting it.
    revoked_at is set when enabled flips False for audit purposes.

    Credential→User binding: the full pairing flow (browser OAuth hand-off
    with ProfileClaim verification) lives in C6/kb-a4u.6. Here we bind
    directly to the authenticated User who hits agents/register.

    ADR-017 D1: Agent is the user's delegate — same authority; actor_marker
    is audit-only (no authority difference between session and bearer).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_credentials",
        help_text="The user whose agent holds this credential.",
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 of the raw Bearer API key. Raw key never stored.",
    )
    enabled = models.BooleanField(
        default=True,
        help_text=(
            "Whether this credential is still valid. Set False to revoke. "
            "Long-lived — reusable for many token exchanges until revoked."
        ),
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Optional hard expiry on the long-lived key. null = no expiry at v0.",
    )
    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when this credential was revoked (enabled set False). Audit only.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("agent credential")
        verbose_name_plural = _("agent credentials")

    def __str__(self):
        return f"AgentCredential({self.user}, enabled={self.enabled})"

    @classmethod
    def issue(cls, user):
        """
        Generate a raw key, store its hash, return (credential, raw_key).
        Caller is responsible for returning raw_key to the user exactly once.
        The key is long-lived and reusable — do NOT consume it on first exchange.
        """
        raw_key = _generate_raw_key()
        credential = cls.objects.create(
            user=user,
            key_hash=_hash_key(raw_key),
        )
        return credential, raw_key

    @classmethod
    def validate(cls, raw_key):
        """
        Look up the credential by raw_key hash, validate it is enabled and
        unexpired, and return (credential, user).

        Does NOT consume the key — it is long-lived and reusable.
        To revoke a credential: set enabled=False (and optionally stamp
        revoked_at for audit). There is no revoke() method — callers set
        the field directly (ADR-008 D2: no speculative abstraction).

        Raises AgentCredential.DoesNotExist or ValueError on failure (fail loud
        per ADR-008 D3).
        """
        key_hash = _hash_key(raw_key)
        try:
            cred = cls.objects.select_related("user").get(key_hash=key_hash)
        except cls.DoesNotExist as exc:
            raise cls.DoesNotExist("Invalid API key.") from exc

        if not cred.enabled:
            raise ValueError("API key has been revoked.")

        if cred.expires_at is not None and cred.expires_at < timezone.now():
            raise ValueError("API key expired.")

        return cred, cred.user


# ---------------------------------------------------------------------------
# Agent pairing token (kb-a4u.6 — one-time pairing-token redemption mechanic)
# ---------------------------------------------------------------------------
# AgentPairingToken is the SHORT-LIVED, SINGLE-USE envelope that a facilitator
# shows to their agent. The agent redeems it once to receive the LONG-LIVED
# Bearer key (AgentCredential). The long-lived secret never transits the
# facilitator's clipboard — only the agent ever holds it.
#
# Mirrors MagicLinkToken envelope (organizers/models.py) in structure:
#   - Single-use (used_at stamped on first valid redemption — NULL = unused)
#   - Short-lived (expires_at, ~15 min TTL default)
#   - URL-safe random raw token for display
#
# DIVERGENCE from MagicLinkToken — storage security:
#   AgentPairingToken stores SHA-256(raw_token) — the raw value is NEVER stored.
#   MagicLinkToken stores a plaintext UUID.  Do NOT "align" these to match each
#   other; the hashing here is intentional and more secure.  Any future
#   maintainer who removes the hash to match MagicLinkToken would be a regression.
#
# kb-eya divergence from MagicLinkToken:
#   MagicLinkToken binds (email, profile_id, user_target) triple because the
#   magic-link flow involves an out-of-band email delivery to prove address
#   control. AgentPairingToken binds ONLY to the registering User — the
#   facilitator is already authenticated (session), so email verification is
#   not needed; the pairing token is purely a short-lived handoff envelope.
#   No email, profile, or intended_method fields here.
# ---------------------------------------------------------------------------


def _generate_pairing_token():
    """Generate a URL-safe 32-byte random token for display to the facilitator."""
    return secrets.token_urlsafe(32)


class AgentPairingToken(models.Model):
    """
    Short-lived, single-use pairing token for the agent-credential issuance flow
    (kb-a4u.6 — pairing-token redemption mechanic, ADR-016 D3).

    Step 1: facilitator hits agents/register → receives raw pairing token (once).
    Step 2: agent redeems raw token at agents/redeem → receives long-lived Bearer key.

    The raw token is shown ONCE at registration and never stored (SHA-256 hash only).
    On redemption: token is marked used (single-use), AgentCredential is issued.

    Short TTL (default 15 min) prevents stale tokens from being redeemed.
    Fail loud on invalid/expired/used token (ADR-008 D3).

    Structure mirrors MagicLinkToken envelope (organizers/models.py): single-use,
    short-lived, URL-safe random raw token.  Storage diverges intentionally:
    AgentPairingToken hashes the raw value (SHA-256); MagicLinkToken stores
    plaintext UUID.  The hash here is MORE secure — do NOT remove it to align
    with MagicLinkToken (that would be a security regression, not an alignment).
    kb-eya divergence: binds to User only — no email/profile triple needed
    because the facilitator is already authenticated when issuing the token.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="agent_pairing_tokens",
        help_text="The facilitator User who initiated agent registration.",
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 of the raw pairing token. Raw token never stored.",
    )
    expires_at = models.DateTimeField(
        help_text="Expiry timestamp — ~15 min from creation. Token invalid after this.",
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Stamped on first valid redemption — NULL means unused.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("agent pairing token")
        verbose_name_plural = _("agent pairing tokens")

    def __str__(self):
        return f"AgentPairingToken({self.user}, expires={self.expires_at})"

    @property
    def is_expired(self):
        """True if the token has passed its expiry time."""
        return timezone.now() >= self.expires_at

    @property
    def is_used(self):
        """True if the token has already been redeemed."""
        return self.used_at is not None

    @property
    def is_valid(self):
        """True if the token is neither expired nor used."""
        return not self.is_expired and not self.is_used

    def mark_used(self):
        """Stamp used_at to invalidate the token for future redemptions."""
        self.used_at = timezone.now()
        self.save(update_fields=["used_at"])

    @classmethod
    def issue(cls, user, ttl_seconds=900):
        """
        Issue a fresh short-lived pairing token for user.

        Default TTL: 900 seconds (15 minutes).
        Returns (token_record, raw_token). The caller MUST return raw_token
        to the facilitator exactly once — it is never stored and cannot be recovered.
        """
        raw_token = _generate_pairing_token()
        token_hash = _hash_key(raw_token)
        expires_at = timezone.now() + timezone.timedelta(seconds=ttl_seconds)
        record = cls.objects.create(
            user=user,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        return record, raw_token

    @classmethod
    def validate(cls, raw_token: str):
        """
        Validate a raw pairing token: must exist, not be expired, not be used.

        Returns (token_record, user) on success.
        Does NOT consume the token — call mark_used() after issuing the credential.

        Raises AgentPairingToken.DoesNotExist or ValueError on failure
        (ADR-008 D3: fail loud, no silent fallback).
        """
        token_hash = _hash_key(raw_token)
        try:
            record = cls.objects.select_related("user").get(token_hash=token_hash)
        except cls.DoesNotExist as exc:
            raise cls.DoesNotExist("Invalid pairing token.") from exc

        if record.is_used:
            raise ValueError("Pairing token has already been redeemed.")

        if record.is_expired:
            raise ValueError("Pairing token has expired.")

        return record, record.user


class IdentityToken(models.Model):
    """
    Short-lived (~1h) identity token issued after API key exchange
    (ADR-016 D3, leg 2).

    After AgentCredential.validate() succeeds, an IdentityToken is issued.
    The token is a UUID stored plaintext (low blast-radius: 1h TTL).
    The token is REUSABLE within its TTL — a 1h TTL is meaningless if the
    token dies after one request. Expiry is enforced; single-use is NOT.

    The protected endpoints validate this token via IdentityTokenAuth.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="identity_tokens",
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
    )
    expires_at = models.DateTimeField(
        help_text="~1h from issuance. Token is valid (reusable) until this timestamp.",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("identity token")
        verbose_name_plural = _("identity tokens")

    def __str__(self):
        return f"IdentityToken({self.user}, expires={self.expires_at})"

    @classmethod
    def issue(cls, user, ttl_seconds=3600):
        """Issue a fresh identity token with TTL (default 1h)."""
        expires_at = timezone.now() + timezone.timedelta(seconds=ttl_seconds)
        return cls.objects.create(user=user, expires_at=expires_at)

    @classmethod
    def validate(cls, raw_token: str):
        """
        Validate a UUID identity token: must exist and not be expired.
        Returns (identity_token, user) on success.

        Does NOT consume the token — it is reusable within its TTL.
        Raises IdentityToken.DoesNotExist or ValueError on failure (fail loud
        per ADR-008 D3).
        """
        try:
            token_uuid = uuid.UUID(raw_token)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Malformed identity token.") from exc

        try:
            it = cls.objects.select_related("user").get(token=token_uuid)
        except cls.DoesNotExist as exc:
            raise cls.DoesNotExist("Identity token not found.") from exc

        if it.expires_at < timezone.now():
            raise ValueError("Identity token expired.")

        return it, it.user
