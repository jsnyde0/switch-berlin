from django.contrib import admin

from .models import EmailFailure, FeatureFlag


@admin.register(FeatureFlag)
class FeatureFlagAdmin(admin.ModelAdmin):
    list_display = ["key", "enabled", "description", "updated_at"]
    list_editable = ["enabled"]
    readonly_fields = ["updated_at"]


@admin.register(EmailFailure)
class EmailFailureAdmin(admin.ModelAdmin):
    list_display = ["recipient", "subject", "created_at", "resolved"]
    list_filter = ["resolved"]
    readonly_fields = ["created_at"]
