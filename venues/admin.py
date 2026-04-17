from django.contrib import admin

from .models import Venue


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "neighborhood", "privacy_mode"]
    list_filter = ["privacy_mode"]
    search_fields = ["name", "slug", "neighborhood", "address"]
    readonly_fields = ["created_at"]
