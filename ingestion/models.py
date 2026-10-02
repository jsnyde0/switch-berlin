from django.db import models
from django.utils.translation import gettext_lazy as _


class RawMessage(models.Model):
    source_type = models.CharField(
        choices=[
            ("telegram_bot_forward", "Telegram bot forward"),
            # Collected feeds (sb-7wzb.2): the value names the source shape, which
            # derives the tier (events/backfill_visibility.py, ADR-012 D2).
            ("telegram_telethon", "Telegram public channel, group or forum topic (user session)"),
            ("telegram_private_channel", "Telegram private channel (user session)"),
            ("telegram_private_group", "Telegram private group or forum topic (user session)"),
            ("website", "Organizer website"),
            ("email_submission", "Email submission"),  # future
            ("web_form", "Web form"),  # future
        ],
    )
    sender_id = models.CharField(max_length=100, blank=True)
    channel_id = models.CharField(max_length=100, blank=True)
    message_id = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    raw_payload = models.JSONField()
    text = models.TextField(blank=True)
    enriched_payload = models.JSONField(default=dict, blank=True)  # populated in 0.2
    extraction_status = models.CharField(
        choices=[
            ("pending", "Pending"),
            ("extracted", "Extracted"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
            ("needs_review", "Needs review"),  # NEW in 0.2
            ("duplicate", "Duplicate of an existing event"),
        ],
        default="pending",
    )
    extraction_error = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    # Per-source collector switch (sb-7wzb.2 D4): rows from a collect-only source
    # land as drafts and never publish, whatever the organizer's claim state.
    collect_only = models.BooleanField(default=False)

    class Meta:
        ordering = ["-received_at"]
        verbose_name = _("raw message")
        verbose_name_plural = _("raw messages")
        constraints = [
            models.UniqueConstraint(
                fields=["source_type", "channel_id", "message_id"],
                condition=models.Q(message_id__gt=""),
                name="rawmessage_dedup_source_channel_message",
            ),
        ]

    def __str__(self):
        return f"{self.source_type} @ {self.received_at}"


class SourceFailure(models.Model):
    source_type = models.CharField(max_length=50)
    raw_message = models.ForeignKey(
        RawMessage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    stage = models.CharField(max_length=50)  # "enrichment", "extraction", "publish"
    error_class = models.CharField(max_length=200)
    error_message = models.TextField()
    occurred_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name = _("source failure")
        verbose_name_plural = _("source failures")

    def __str__(self):
        return f"{self.error_class} at {self.stage}"


class HeartbeatLog(models.Model):
    ran_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-ran_at"]
        verbose_name = _("heartbeat log")
        verbose_name_plural = _("heartbeat logs")

    def __str__(self):
        return f"Heartbeat @ {self.ran_at}"


class ExtractionAttempt(models.Model):
    raw_message = models.ForeignKey(RawMessage, on_delete=models.CASCADE, related_name="attempts")
    event = models.ForeignKey(
        "events.Event",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="extraction_attempts",
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    model_name = models.CharField(max_length=100)  # e.g. 'claude-opus-4-7'
    prompt_version = models.CharField(max_length=50)  # monotonic: 'v1', 'v2', ...
    raw_response = models.JSONField()
    # serialized EventDraft
    extracted_draft = models.JSONField(default=dict, blank=True)
    confidence_score = models.FloatField(null=True, blank=True)
    success = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = _("extraction attempt")
        verbose_name_plural = _("extraction attempts")

    def __str__(self):
        return f"ExtractionAttempt({self.raw_message_id}) @ {self.attempted_at}"


class RejectedMessageAttempt(models.Model):
    telegram_user_id = models.BigIntegerField()
    telegram_username = models.CharField(max_length=100, blank=True)
    chat_id = models.BigIntegerField(null=True, blank=True)
    message_text = models.TextField(blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = _("rejected message attempt")
        verbose_name_plural = _("rejected message attempts")

    def __str__(self):
        return f"Rejected({self.telegram_user_id}) @ {self.attempted_at}"

    def save(self, *args, **kwargs):
        self.message_text = self.message_text[:500]
        super().save(*args, **kwargs)


class ApprovedSender(models.Model):
    telegram_user_id = models.CharField(max_length=100, unique=True)
    telegram_handle = models.CharField(max_length=100, blank=True)
    organizer = models.ForeignKey(
        "organizers.Profile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    approved_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = _("approved sender")
        verbose_name_plural = _("approved senders")

    def __str__(self):
        return f"{self.telegram_user_id} ({self.telegram_handle})"


class ArtistCreditSuppression(models.Model):
    """A credited artist's removed name, per source (sb-7wzb.23, LIA §3a objection).

    Written by the staff action "remove credit and suppress"; the collector skips an artist
    name whose `name_key` (organizers.names.name_key) is listed for the row's `channel_id`.
    Another source may still credit the name.
    """

    name_key = models.CharField(max_length=200)
    channel_id = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name_key", "channel_id"], name="artist_suppression_one_per_name_source"),
        ]
        verbose_name = _("artist credit suppression")
        verbose_name_plural = _("artist credit suppressions")

    def __str__(self):
        return f"{self.name_key} @ {self.channel_id}"
