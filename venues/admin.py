from django.contrib import admin
from django.utils.translation import gettext_lazy as _

from organizers.merge import merge_action, merge_venues

from .models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "neighborhood", "privacy_mode", "run_by"]
    list_filter = ["privacy_mode"]
    search_fields = ["name", "slug", "neighborhood", "address"]
    readonly_fields = ["created_at"]
    autocomplete_fields = ["run_by"]
    actions = ["merge_into"]

    @admin.action(description=_("Merge into…"), permissions=["delete"])
    def merge_into(self, request, queryset):
        return merge_action(self, request, queryset, merge_venues)
