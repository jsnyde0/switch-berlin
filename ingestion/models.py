from django.db import models


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
        ],
        default="pending",
    )
    extraction_error = models.TextField(blank=True)

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

    def __str__(self):
        return f"{self.error_class} at {self.stage}"


class HeartbeatLog(models.Model):
    ran_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Heartbeat @ {self.ran_at}"
