from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from .models import Organizer


@admin.register(Organizer)
class OrganizerAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "verified_badge", "event_count"]
    list_filter = ["status", "verified_badge"]
    search_fields = ["name", "slug", "telegram_channel"]
    readonly_fields = ["created_at", "updated_at", "approved_at"]
    actions = [
        "mark_approved_explicit_opt_in",
        "mark_approved_telegram_forward_implied",
        "mark_approved_verified_public_source",
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(event_count=Count("events"))

    def event_count(self, obj):
        return obj.event_count

    event_count.short_description = _("Events")
    event_count.admin_order_field = "event_count"

    @admin.action(description=_("Mark approved — explicit opt-in consent"))
    def mark_approved_explicit_opt_in(self, request, queryset):
        from django.utils import timezone

        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="explicit_opt_in",
        )

    @admin.action(description=_("Mark approved — Telegram forward (implied consent)"))
    def mark_approved_telegram_forward_implied(self, request, queryset):
        from django.utils import timezone

        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="telegram_forward_implied",
        )

    @admin.action(description=_("Mark approved — verified public source"))
    def mark_approved_verified_public_source(self, request, queryset):
        from django.utils import timezone

        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="verified_public_source",
        )
