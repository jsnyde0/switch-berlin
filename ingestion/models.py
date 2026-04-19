from django.db import models
from django.utils.translation import gettext_lazy as _


class RawMessage(models.Model):
    source_type = models.CharField(
        choices=[
            ("telegram_bot_forward", "Telegram bot forward"),
            ("telegram_telethon", "Telegram Telethon"),  # future
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
        ],
        default="pending",
    )
    extraction_error = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)

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
    raw_message = models.ForeignKey(
        RawMessage, on_delete=models.CASCADE, related_name="attempts"
    )
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


class ApprovedSender(models.Model):
    telegram_user_id = models.CharField(max_length=100, unique=True)
    telegram_handle = models.CharField(max_length=100, blank=True)
    organizer = models.ForeignKey(
        "organizers.Organizer",
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
