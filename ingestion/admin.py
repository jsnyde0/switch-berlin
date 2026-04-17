from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import HeartbeatLog, RawMessage, SourceFailure


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
