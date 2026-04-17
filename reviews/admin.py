from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from .models import Review


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
