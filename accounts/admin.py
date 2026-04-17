from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (_("Approval"), {"fields": ("is_approved", "approved_at", "approved_by")}),
    )
    list_display = ["username", "email", "is_approved", "is_staff"]
