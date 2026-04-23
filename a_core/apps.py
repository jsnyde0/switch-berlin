"""AppConfig for a_core — registers system checks on startup."""

from django.apps import AppConfig


class ACoreConfig(AppConfig):
    name = "a_core"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from a_core import (
            checks,  # noqa: F401 — registers system checks via @register()
        )
