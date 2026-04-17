from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Organizer


@admin.register(Organizer)
class OrganizerAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "verified_badge", "event_count"]
    list_filter = ["status", "verified_badge"]
    search_fields = ["name", "slug", "telegram_channel"]
    readonly_fields = ["created_at", "updated_at", "approved_at"]
    actions = ["mark_approved_record_consent"]

    def event_count(self, obj):
        return obj.events.count()

    event_count.short_description = _("Events")

    @admin.action(description=_("Mark approved + record consent"))
    def mark_approved_record_consent(self, request, queryset):
        from django.utils import timezone

        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="explicit_opt_in",
        )
