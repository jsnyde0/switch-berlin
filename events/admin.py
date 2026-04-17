from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Event, EventImage, Tag


class EventImageInline(admin.TabularInline):
    model = EventImage
    extra = 0


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "organizer", "start", "status"]
    list_filter = ["status", "start", "tags", "organizer"]
    search_fields = ["title", "description"]
    inlines = [EventImageInline]
    readonly_fields = [
        "created_at", "updated_at", "published_at", "raw_message_preview"
    ]
    actions = ["publish_events", "reject_events", "archive_events"]

    def raw_message_preview(self, obj):
        if not obj.raw_message:
            return "—"
        from django.utils.html import format_html

        return format_html(
            '<pre style="max-height:200px;overflow:auto">{}</pre>',
            obj.raw_message.text or str(obj.raw_message.raw_payload),
        )

    raw_message_preview.short_description = _("Raw message")

    @admin.action(description=_("Publish selected events"))
    def publish_events(self, request, queryset):
        from django.utils import timezone

        queryset.update(status="published", published_at=timezone.now())

    @admin.action(description=_("Reject selected events"))
    def reject_events(self, request, queryset):
        queryset.update(status="rejected")

    @admin.action(description=_("Archive selected events"))
    def archive_events(self, request, queryset):
        queryset.update(status="archived")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["slug", "label", "kind"]
    list_filter = ["kind"]
    search_fields = ["slug", "label"]


@admin.register(EventImage)
class EventImageAdmin(admin.ModelAdmin):
    list_display = ["event", "is_cover", "order"]
    list_filter = ["is_cover"]
