from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .models import InviteCode, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (_("Approval"), {"fields": ("is_approved", "approved_at", "approved_by")}),
    )
    list_display = ["username", "email", "is_approved", "is_staff"]
    list_filter = UserAdmin.list_filter + ("is_approved",)


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "created_by",
        "created_at",
        "redeemed_by",
        "redeemed_at",
        "expires_at",
    ]
    list_filter = ["redeemed_by"]
    readonly_fields = ["code", "redeemed_by", "redeemed_at", "created_at"]
