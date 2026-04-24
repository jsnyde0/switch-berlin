from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import (
    ApprovedSender,
    ExtractionAttempt,
    HeartbeatLog,
    RawMessage,
    RejectedMessageAttempt,
    SourceFailure,
)


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    list_display = ["source_type", "received_at", "extraction_status", "text_preview"]
    list_filter = ["extraction_status"]
    # All read-only in 0.1 (no actions until 0.2 extraction pipeline)

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.concrete_fields]

    def text_preview(self, obj):
        return obj.text[:80] if obj.text else "(no text)"

    text_preview.short_description = _("Text preview")


@admin.register(SourceFailure)
class SourceFailureAdmin(admin.ModelAdmin):
    list_display = ["source_type", "stage", "error_class", "occurred_at", "resolved"]
    list_filter = ["resolved", "source_type"]
    search_fields = ["error_class", "error_message"]


@admin.register(HeartbeatLog)
class HeartbeatLogAdmin(admin.ModelAdmin):
    list_display = ["ran_at", "note"]
    readonly_fields = ["ran_at"]


@admin.register(ExtractionAttempt)
class ExtractionAttemptAdmin(admin.ModelAdmin):
    list_display = [
        "raw_message",
        "attempted_at",
        "model_name",
        "prompt_version",
        "confidence_score",
        "success",
    ]
    list_filter = ["success", "model_name", "prompt_version"]
    search_fields = ["raw_message__text", "error"]
    readonly_fields = ["attempted_at"]


@admin.register(RejectedMessageAttempt)
class RejectedMessageAttemptAdmin(admin.ModelAdmin):
    list_display = ["telegram_user_id", "telegram_username", "chat_id", "attempted_at"]
    readonly_fields = [
        "telegram_user_id",
        "telegram_username",
        "chat_id",
        "message_text",
        "attempted_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ApprovedSender)
class ApprovedSenderAdmin(admin.ModelAdmin):
    list_display = ["telegram_user_id", "telegram_handle", "organizer", "approved_at"]
    list_filter = ["organizer"]
    search_fields = ["telegram_user_id", "telegram_handle"]
    readonly_fields = ["approved_at"]
