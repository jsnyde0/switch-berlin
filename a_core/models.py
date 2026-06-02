from django.conf import settings
from django.core.cache import cache
from django.db import models


class _NotCached:
    """Local sentinel meaning 'key was not in the cache at all'.

    Never stored in the cache — only used as the default for cache.get().
    A regular object() works here because we only compare it with 'is',
    and it is never pickled.
    """


_NOT_CACHED = _NotCached()


class _NoFlag:
    """Picklable singleton stored in the cache when a FeatureFlag key does not exist
    in DB.

    By caching this sentinel we avoid repeated DB hits for unknown flag keys.
    __reduce__ restores the module-level singleton on unpickle so 'is' comparisons
    survive serializing cache backends (Redis, Memcached).
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __reduce__(self):
        return (_NoFlag, ())

    def __repr__(self):
        return "<NO_FLAG>"


_NO_FLAG = _NoFlag()


class FeatureFlag(models.Model):
    key = models.CharField(max_length=100, unique=True)
    enabled = models.BooleanField(default=True)
    numeric_value = models.IntegerField(
        null=True,
        blank=True,
        help_text="For threshold-style flags; None means boolean-only",
    )
    description = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f"{self.key}={self.enabled}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache.delete(f"feature_flag_row:{self.key}")

    def delete(self, *args, **kwargs):
        key = self.key
        super().delete(*args, **kwargs)
        cache.delete(f"feature_flag_row:{key}")

    class Meta:
        verbose_name = "feature flag"
        verbose_name_plural = "feature flags"


class ModerationAction(models.Model):
    moderator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    flag = models.ForeignKey("reviews.Flag", null=True, blank=True, on_delete=models.SET_NULL)
    target_type = models.CharField(
        max_length=20,
        choices=[
            ("event", "Event"),
            ("organizer", "Organizer"),
            ("review", "Review"),
        ],
    )
    target_id = models.IntegerField()
    target_repr = models.CharField(
        max_length=200,
        help_text=(
            "Snapshot of target's human-readable label at action time. "
            "Preserved so audit rows remain interpretable after target deletion."
        ),
    )
    action = models.CharField(
        max_length=20,
        choices=[
            ("no_action", "No action"),
            ("hide", "Hide target"),
            ("delete", "Delete review (soft)"),
            ("suspend", "Suspend organizer"),
            ("resolved", "Mark resolved"),
        ],
    )
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["target_type", "target_id"])]


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


def _load_flag_row(key: str):
    """Fetch the FeatureFlag row for *key*, caching under 'feature_flag_row:{key}'.

    Returns the FeatureFlag instance, or _NO_FLAG if the key does not exist in the DB.
    Caches _NO_FLAG for 60s to prevent repeated DB hits for unknown keys.

    Uses _NOT_CACHED as the cache.get() default to distinguish:
      - 'key not in cache at all' → _NOT_CACHED (never stored)
      - 'key in cache, flag missing in DB' → _NO_FLAG (stored by this function)
    """
    cache_key = f"feature_flag_row:{key}"
    cached = cache.get(cache_key, _NOT_CACHED)
    if cached is not _NOT_CACHED:
        # Return whatever is in cache: either a FeatureFlag row or _NO_FLAG
        return cached
    try:
        row = FeatureFlag.objects.get(key=key)
    except FeatureFlag.DoesNotExist:
        row = _NO_FLAG
    cache.set(cache_key, row, timeout=60)
    return row


def get_flag(key: str, default: bool = False) -> bool:
    """Single read path for all feature flag checks. Cached 60s.

    Stores the full FeatureFlag row under 'feature_flag_row:{key}'.
    Old 'feature_flag:{key}' entries expire naturally within their 60s TTL
    after deploy — no manual cache-bust required.
    """
    row = _load_flag_row(key)
    if row is _NO_FLAG:
        return default
    return row.enabled


def get_numeric(key: str, default: int) -> int:
    """Cached numeric-flag lookup; falls back to default if flag or value missing.

    Projects numeric_value from the unified 'feature_flag_row:{key}' cache entry.
    Both get_flag() and get_numeric() share the same cached FeatureFlag instance.
    """
    row = _load_flag_row(key)
    if row is _NO_FLAG:
        return default
    if row.numeric_value is None:
        return default
    return row.numeric_value
