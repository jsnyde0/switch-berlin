from django.contrib import admin

from .models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "neighborhood", "privacy_mode", "run_by"]
    list_filter = ["privacy_mode"]
    search_fields = ["name", "slug", "neighborhood", "address"]
    readonly_fields = ["created_at"]
    autocomplete_fields = ["run_by"]
