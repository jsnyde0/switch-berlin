from django.contrib import admin
from django.db.models import Count
from django.utils.translation import gettext_lazy as _

from .models import Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "status", "verified_badge", "event_count"]
    list_filter = ["kind", "status", "verified_badge"]
    search_fields = ["name", "slug", "telegram_link"]
    readonly_fields = ["created_at", "updated_at", "approved_at"]
    actions = [
        "mark_approved_explicit_opt_in",
        "mark_approved_telegram_forward_implied",
        "mark_approved_verified_public_source",
    ]

    def get_queryset(self, request):
        # events_organized is the M2M reverse from Event.organizers (kb-n0y)
        return super().get_queryset(request).annotate(
            event_count=Count("events_organized", distinct=True)
        )

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
