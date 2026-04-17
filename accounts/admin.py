from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Approval", {"fields": ("is_approved", "approved_at", "approved_by")}),
    )
    list_display = ["username", "email", "is_approved", "is_staff"]
