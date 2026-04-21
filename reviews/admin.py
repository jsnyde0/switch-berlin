from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Flag, Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["author", "target_display", "rating", "created_at"]

    def target_display(self, obj):
        if obj.organizer:
            return f"Organizer: {obj.organizer}"
        if obj.event:
            return f"Event: {obj.event}"
        return "(none)"

    target_display.short_description = _("Target")


@admin.register(Flag)
class FlagAdmin(admin.ModelAdmin):
    list_display = ["reporter", "organizer", "event", "reason", "resolved", "created_at"]
    list_filter = ["resolved", "reason"]
    readonly_fields = ["created_at"]
