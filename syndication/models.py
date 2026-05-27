"""
Syndication models: PlatformConnection, Post, PlatformProjection,
AgentCredential, and IdentityToken.

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

    # Frozen content snapshot (ADR-016 D2, kb-a4u.20 hybrid content model).
    # Null while status=draft (projection tracks live canonical + override_data).
    # Materialized at draft→ready transition: stores the full effective content
    # (canonical fields + overrides at that instant) as a stable artifact.
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
