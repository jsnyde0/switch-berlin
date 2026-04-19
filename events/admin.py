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
        "created_at",
        "updated_at",
        "published_at",
        "raw_message_preview",
        "suggested_tags_display",
    ]
    actions = ["publish_events", "reject_events", "archive_events"]

    def raw_message_preview(self, obj):
        if not obj.raw_message:
            return "—"
        import json

        from django.utils.html import format_html

        enriched = obj.raw_message.enriched_payload
        enriched_str = (
            json.dumps(enriched, indent=2, ensure_ascii=False)
            if enriched
            else _("(not yet enriched)")
        )
        return format_html(
            "<strong>{}</strong>"
            '<pre style="max-height:200px;overflow:auto">{}</pre>'
            "<strong>{}</strong>"
            '<pre style="max-height:200px;overflow:auto">{}</pre>',
            _("Raw text:"),
            obj.raw_message.text or str(obj.raw_message.raw_payload),
            _("Enriched payload:"),
            enriched_str,
        )

    raw_message_preview.short_description = _("Raw message")

    def suggested_tags_display(self, obj):
        return ', '.join(obj.suggested_tags) if obj.suggested_tags else '\u2014'
    suggested_tags_display.short_description = _('Suggested tags (unmatched)')

    def changelist_view(self, request, extra_context=None):
        if 'status__exact' not in request.GET:
            q = request.GET.copy()
            q['status__exact'] = 'draft'
            request.GET = q
            request.META['QUERY_STRING'] = request.GET.urlencode()
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url='', extra_context=None):
        import json  # noqa: PLC0415

        from ingestion.models import ExtractionAttempt  # noqa: PLC0415

        extra_context = extra_context or {}
        attempts = ExtractionAttempt.objects.filter(
            event_id=object_id
        ).order_by('-attempted_at')
        extra_context['extraction_attempts'] = attempts
        if attempts.exists():
            latest = attempts.first()
            extra_context['extracted_draft_json'] = json.dumps(latest.extracted_draft)
            extra_context['confidence_score'] = latest.confidence_score
        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )

    def save_model(self, request, obj, form, change):
        from django.utils import timezone  # noqa: PLC0415

        old_status = (
            obj.__class__.objects.filter(pk=obj.pk)
            .values_list('status', flat=True)
            .first()
            if obj.pk else None
        )
        super().save_model(request, obj, form, change)
        if (obj.status == 'published'
                and old_status != 'published'
                and obj.organizer
                and not obj.organizer.consent_recorded_at):
            obj.organizer.consent_recorded_at = timezone.now()
            obj.organizer.consent_method = 'telegram_forward_implied'
            obj.organizer.consent_notes = (
                f'First event approved by {request.user} on {timezone.now().date()}'
            )
            obj.organizer.save(
                update_fields=['consent_recorded_at', 'consent_method', 'consent_notes']
            )

    @admin.action(description=_("Publish selected events"))
    def publish_events(self, request, queryset):
        from django.utils import timezone

        # Only set published_at on first publish; do not overwrite if already set.
        now = timezone.now()
        queryset.filter(published_at__isnull=True).update(
            status="published", published_at=now
        )
        queryset.filter(published_at__isnull=False).update(status="published")

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
