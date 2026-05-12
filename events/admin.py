from django.contrib import admin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Event, EventFacilitator, EventImage, EventOrganizer, Tag


def _capture_organizer_consent(organizer, approved_by_user):
    """Record GDPR consent on first publish if not already recorded."""
    if organizer and not organizer.consent_recorded_at:
        now = timezone.now()
        organizer.consent_recorded_at = now
        organizer.consent_method = "telegram_forward_implied"
        organizer.consent_notes = (
            f"First event approved by {approved_by_user} on {now.date()}"
        )
        organizer.save(
            update_fields=["consent_recorded_at", "consent_method", "consent_notes"]
        )


class EventImageInline(admin.TabularInline):
    model = EventImage
    extra = 0


class EventOrganizerInline(admin.TabularInline):
    model = EventOrganizer
    extra = 1
    fields = ["profile", "is_primary", "order"]


class EventFacilitatorInline(admin.TabularInline):
    model = EventFacilitator
    extra = 1
    fields = ["profile", "role", "order"]


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "primary_organizer_display", "start", "status"]
    list_filter = ["status", "start", "tags"]
    search_fields = ["title", "description", "event_organizer_set__profile__name"]
    inlines = [EventImageInline, EventOrganizerInline, EventFacilitatorInline]
    fieldsets = [
        (
            None,
            {
                "fields": [
                    "title",
                    "slug",
                    "venue",
                    "tags",
                    "suggested_tags_display",
                    "description",
                    "status",
                    "start",
                    "end",
                ]
            },
        ),
        (
            _("Price"),
            {
                "fields": [
                    "is_free",
                    "sliding_scale",
                    "price_min_cents",
                    "price_max_cents",
                    "currency",
                    "price_description",
                ]
            },
        ),
        (
            _("Registration & Links"),
            {
                "fields": [
                    "external_url",
                    "tickets_url",
                    "registration_email",
                    "registration_required",
                    "registration_url",
                    "capacity",
                    "language",
                ]
            },
        ),
        (
            _("Visibility & Stats"),
            {
                "classes": ["collapse"],
                "fields": [
                    "hidden",
                    "published_at",
                    "attendance_count",
                    "interested_count",
                    "rating_count",
                    "avg_rating",
                ],
            },
        ),
        (
            _("Provenance"),
            {
                "classes": ["collapse"],
                "fields": [
                    "raw_message",
                    "raw_message_preview",
                    "created_at",
                    "updated_at",
                ],
            },
        ),
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "published_at",
        "raw_message_preview",
        "suggested_tags_display",
        "attendance_count",
        "interested_count",
        "rating_count",
        "avg_rating",
    ]
    actions = ["publish_events", "publish_selected", "reject_events", "archive_events"]

    class Media:
        js = ["admin/js/review_shortcuts.js"]

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
        return ", ".join(obj.suggested_tags) if obj.suggested_tags else "\u2014"

    suggested_tags_display.short_description = _("Suggested tags (unmatched)")

    def changelist_view(self, request, extra_context=None):
        # Only default-filter on GET; on POST (bulk actions) the filter would
        # exclude events whose current status doesn't match "draft", making
        # non-publish actions like reject/archive no-ops.
        if request.method == "GET" and "status__exact" not in request.GET:
            q = request.GET.copy()
            q["status__exact"] = "draft"
            request.GET = q
            request.META["QUERY_STRING"] = request.GET.urlencode()
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        from ingestion.models import ExtractionAttempt  # noqa: PLC0415

        extra_context = extra_context or {}
        attempts = ExtractionAttempt.objects.filter(event_id=object_id).order_by(
            "-attempted_at"
        )
        extra_context["extraction_attempts"] = attempts
        if attempts.exists():
            latest = attempts.first()
            extra_context["extracted_draft"] = latest.extracted_draft
            extra_context["confidence_score"] = latest.confidence_score
        return super().change_view(
            request, object_id, form_url, extra_context=extra_context
        )

    def primary_organizer_display(self, obj):
        """Show the primary organizer name in list display."""
        org = obj.organizer  # uses compat property
        return org.name if org else "—"

    primary_organizer_display.short_description = _("Organizer")

    def save_model(self, request, obj, form, change):
        old_status = (
            obj.__class__.objects.filter(pk=obj.pk)
            .values_list("status", flat=True)
            .first()
            if obj.pk
            else None
        )
        super().save_model(request, obj, form, change)
        if obj.status == "published" and old_status != "published":
            _capture_organizer_consent(obj.organizer, request.user)

    @admin.action(description=_("Publish selected events"))
    def publish_events(self, request, queryset):
        # Fetch primary organizer PKs before update via EventOrganizer through-table
        from organizers.models import Profile  # noqa: PLC0415

        organizer_pks = set(
            EventOrganizer.objects.filter(
                event__in=queryset,
                is_primary=True,
            ).values_list("profile_id", flat=True)
        )
        organizers_to_notify = list(Profile.objects.filter(pk__in=organizer_pks))

        # Only set published_at on first publish; do not overwrite if already set.
        now = timezone.now()
        queryset.filter(published_at__isnull=True).update(
            status="published", published_at=now
        )
        queryset.filter(published_at__isnull=False).update(status="published")

        # Capture GDPR consent for each organizer on their first event publish.
        for organizer in organizers_to_notify:
            _capture_organizer_consent(organizer, request.user)

    @admin.action(description=_("Publish selected (draft only)"))
    def publish_selected(self, request, queryset):
        count = queryset.filter(status="draft").update(status="published")
        self.message_user(request, _("%(count)d event(s) published.") % {"count": count})

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
