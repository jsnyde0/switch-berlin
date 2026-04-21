from django.conf import settings
from django.core.cache import cache
from django.db import models


class FeatureFlag(models.Model):
    key = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )

    def __str__(self):
        return f"{self.key}={self.enabled}"

    class Meta:
        verbose_name = "feature flag"
        verbose_name_plural = "feature flags"


class EmailFailure(models.Model):
    recipient = models.EmailField(blank=True)
    subject = models.CharField(max_length=300, blank=True)
    body_preview = models.TextField(blank=True)
    error_message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        verbose_name = "email failure"
        verbose_name_plural = "email failures"
        ordering = ["-created_at"]


def get_flag(key: str, default: bool = False) -> bool:
    """Single read path for all feature flag checks. Cached 60s."""
    cache_key = f"feature_flag:{key}"
    val = cache.get(cache_key)
    if val is None:
        try:
            val = FeatureFlag.objects.get(key=key).enabled
        except FeatureFlag.DoesNotExist:
            val = default
        cache.set(cache_key, val, timeout=60)
    return val
