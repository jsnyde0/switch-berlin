from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .models import InviteCode, InviteGrant, User, Vouch


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (
            _("Trust"),
            {
                "fields": (
                    "status",
                    "vouch_score",
                    "personal_rating",
                    "invite_codes_remaining",
                    "approved_at",
                    "approved_by",
                )
            },
        ),
    )
    list_display = ["username", "email", "status", "is_staff"]
    list_filter = UserAdmin.list_filter + ("status",)


@admin.register(InviteCode)
class InviteCodeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "created_by",
        "created_at",
        "used_by",
        "used_at",
        "expires_at",
    ]
    list_filter = ["used_by"]
    search_fields = ["code", "created_by__email", "created_by__username"]
    readonly_fields = ["code", "used_by", "used_at", "created_at"]


@admin.register(InviteGrant)
class InviteGrantAdmin(admin.ModelAdmin):
    """Read-only audit log for invite redemptions."""

    list_display = [
        "invite_code",
        "grantor",
        "recipient",
        "granted_at",
        "reason",
    ]
    list_filter = ["granted_at"]
    search_fields = [
        "recipient__email",
        "recipient__username",
        "grantor__email",
        "grantor__username",
        "invite_code__code",
    ]
    readonly_fields = ["invite_code", "grantor", "recipient", "granted_at"]


@admin.register(Vouch)
class VouchAdmin(admin.ModelAdmin):
    list_display = ["voucher", "vouchee", "created_at", "cancelled_at"]
    list_filter = ["cancelled_at"]
    search_fields = [
        "voucher__email",
        "voucher__username",
        "vouchee__email",
        "vouchee__username",
    ]
    readonly_fields = ["voucher", "vouchee", "created_at"]
