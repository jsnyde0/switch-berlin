"""Tests for a_core models: FeatureFlag, EmailFailure, get_flag(), get_numeric(), ModerationAction."""
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase


class FeatureFlagModelTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_featureflag_str(self):
        from a_core.models import FeatureFlag
        flag = FeatureFlag.objects.create(key="TEST_FLAG", enabled=True)
        self.assertEqual(str(flag), "TEST_FLAG=True")

    def test_featureflag_default_enabled_true(self):
        from a_core.models import FeatureFlag
        flag = FeatureFlag.objects.create(key="ANOTHER_FLAG")
        self.assertTrue(flag.enabled)

    def test_featureflag_key_is_unique(self):
        from django.db import IntegrityError
        from a_core.models import FeatureFlag
        FeatureFlag.objects.create(key="UNIQUE_FLAG", enabled=True)
        with self.assertRaises(IntegrityError):
            FeatureFlag.objects.create(key="UNIQUE_FLAG", enabled=False)

    def test_emailfailure_ordering(self):
        from a_core.models import EmailFailure
        e1 = EmailFailure.objects.create(error_message="err1")
        e2 = EmailFailure.objects.create(error_message="err2")
        qs = list(EmailFailure.objects.all())
        # Most recent first
        self.assertEqual(qs[0], e2)
        self.assertEqual(qs[1], e1)

    def test_emailfailure_resolved_default_false(self):
        from a_core.models import EmailFailure
        ef = EmailFailure.objects.create(error_message="fail")
        self.assertFalse(ef.resolved)


class GetFlagTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_get_flag_returns_db_value(self):
        from a_core.models import FeatureFlag, get_flag
        FeatureFlag.objects.create(key="MY_FLAG", enabled=False)
        result = get_flag("MY_FLAG", default=True)
        self.assertFalse(result)

    def test_get_flag_returns_default_when_missing(self):
        from a_core.models import get_flag
        result = get_flag("NONEXISTENT_FLAG", default=True)
        self.assertTrue(result)

    def test_get_flag_caches_result(self):
        from a_core.models import FeatureFlag, get_flag
        FeatureFlag.objects.create(key="CACHED_FLAG", enabled=True)
        # First call hits DB
        get_flag("CACHED_FLAG", default=False)
        # Delete the DB row — cached value should still be returned
        FeatureFlag.objects.filter(key="CACHED_FLAG").delete()
        result = get_flag("CACHED_FLAG", default=False)
        self.assertTrue(result)  # still True from cache


class FeatureFlagNumericValueTest(TestCase):
    """Tests for FeatureFlag.numeric_value field and get_numeric() helper."""

    def setUp(self):
        cache.clear()

    def test_featureflag_numeric_value_field_exists(self):
        """FeatureFlag.numeric_value field exists and accepts integers."""
        from a_core.models import FeatureFlag

        flag = FeatureFlag.objects.create(
            key="THRESHOLD_TEST", enabled=True, numeric_value=5
        )
        flag.refresh_from_db()
        self.assertEqual(flag.numeric_value, 5)

    def test_featureflag_numeric_value_nullable(self):
        """FeatureFlag.numeric_value can be None (boolean-only flags)."""
        from a_core.models import FeatureFlag

        flag = FeatureFlag.objects.create(key="BOOL_ONLY_FLAG", enabled=True)
        flag.refresh_from_db()
        self.assertIsNone(flag.numeric_value)

    def test_get_numeric_returns_db_value(self):
        """get_numeric returns numeric_value from DB row."""
        from a_core.models import FeatureFlag, get_numeric

        FeatureFlag.objects.create(
            key="threshold.test_threshold", enabled=True, numeric_value=7
        )
        result = get_numeric("threshold.test_threshold", default=3)
        self.assertEqual(result, 7)

    def test_get_numeric_returns_default_when_flag_missing(self):
        """get_numeric returns default when flag does not exist."""
        from a_core.models import get_numeric

        result = get_numeric("threshold.nonexistent", default=5)
        self.assertEqual(result, 5)

    def test_missing_flag_is_cached_to_prevent_repeated_db_hits(self):
        """A flag key that doesn't exist in DB is cached so repeated calls don't hit DB."""
        from a_core.models import _NO_FLAG, get_flag

        # First call — DB hit (nothing found)
        result1 = get_flag("NONEXISTENT_CACHED_FLAG", default=True)
        self.assertTrue(result1)

        # The _NO_FLAG sentinel must be in cache after first call
        from django.core.cache import cache as dj_cache

        cached = dj_cache.get("feature_flag_row:NONEXISTENT_CACHED_FLAG")
        self.assertIs(cached, _NO_FLAG)

        # Second call — must NOT hit DB (sentinel in cache)
        result2 = get_flag("NONEXISTENT_CACHED_FLAG", default=True)
        self.assertTrue(result2)

    def test_get_numeric_returns_default_when_numeric_value_is_none(self):
        """get_numeric returns default when numeric_value is None."""
        from a_core.models import FeatureFlag, get_numeric

        FeatureFlag.objects.create(
            key="BOOL_ONLY_NO_NUMERIC", enabled=True, numeric_value=None
        )
        result = get_numeric("BOOL_ONLY_NO_NUMERIC", default=10)
        self.assertEqual(result, 10)

    def test_get_flag_and_get_numeric_use_unified_cache_key(self):
        """get_flag and get_numeric both read from feature_flag_row:{key} cache."""
        from a_core.models import FeatureFlag, get_flag, get_numeric

        FeatureFlag.objects.update_or_create(
            key="threshold.auto_hide_flag",
            defaults={"enabled": True, "numeric_value": 3},
        )
        # Warm cache via get_flag
        flag_result = get_flag("threshold.auto_hide_flag", default=False)
        self.assertTrue(flag_result)

        # Now delete DB row — get_numeric must still return from cache
        FeatureFlag.objects.filter(key="threshold.auto_hide_flag").delete()
        numeric_result = get_numeric("threshold.auto_hide_flag", default=99)
        self.assertEqual(numeric_result, 3)  # from cache, not default

    def test_get_numeric_caches_row(self):
        """get_numeric caches the FeatureFlag row so subsequent DB deletes don't affect it."""
        from a_core.models import FeatureFlag, get_numeric

        FeatureFlag.objects.create(
            key="threshold.cached_test", enabled=True, numeric_value=8
        )
        # Warm cache
        get_numeric("threshold.cached_test", default=0)
        # Delete DB row
        FeatureFlag.objects.filter(key="threshold.cached_test").delete()
        # Cache should still return 8
        result = get_numeric("threshold.cached_test", default=0)
        self.assertEqual(result, 8)

    def test_featureflag_save_invalidates_unified_cache(self):
        """FeatureFlag.save() invalidates the feature_flag_row: cache key."""
        from a_core.models import FeatureFlag, get_numeric

        flag = FeatureFlag.objects.create(
            key="threshold.save_test", enabled=True, numeric_value=3
        )
        # Warm cache
        get_numeric("threshold.save_test", default=0)
        # Update via save() — must bust cache
        flag.numeric_value = 10
        flag.save()
        # Must reflect new value
        result = get_numeric("threshold.save_test", default=0)
        self.assertEqual(result, 10)

    def test_featureflag_delete_invalidates_unified_cache(self):
        """FeatureFlag.delete() invalidates the feature_flag_row: cache key."""
        from a_core.models import FeatureFlag, get_numeric

        flag = FeatureFlag.objects.create(
            key="threshold.delete_test", enabled=True, numeric_value=5
        )
        # Warm cache
        get_numeric("threshold.delete_test", default=0)
        # Delete — must bust cache
        flag.delete()
        # Must return default now
        result = get_numeric("threshold.delete_test", default=99)
        self.assertEqual(result, 99)

    def test_get_flag_uses_unified_cache_key(self):
        """get_flag stores and reads from feature_flag_row:{key} cache."""
        from django.core.cache import cache

        from a_core.models import FeatureFlag, get_flag

        flag = FeatureFlag.objects.create(key="UNIFIED_KEY_TEST", enabled=True)
        get_flag("UNIFIED_KEY_TEST", default=False)
        # Unified key must be set
        cached = cache.get("feature_flag_row:UNIFIED_KEY_TEST")
        self.assertIsNotNone(cached)
        self.assertIsInstance(cached, FeatureFlag)
        # Old key must NOT be set
        old_cached = cache.get("feature_flag:UNIFIED_KEY_TEST")
        self.assertIsNone(old_cached)


class ModerationActionModelTest(TestCase):
    """Tests for the ModerationAction model."""

    def test_moderation_action_can_be_created(self):
        """ModerationAction can be created with required fields."""
        from django.contrib.auth import get_user_model

        from a_core.models import ModerationAction

        User = get_user_model()
        moderator = User.objects.create_user(
            username="mod", email="mod@example.com", password="pass"
        )
        action = ModerationAction.objects.create(
            moderator=moderator,
            target_type="event",
            target_id=42,
            target_repr="Test Event (2026-04-21)",
            action="hide",
            reason="spam",
        )
        action.refresh_from_db()
        self.assertEqual(action.target_type, "event")
        self.assertEqual(action.target_id, 42)
        self.assertEqual(action.target_repr, "Test Event (2026-04-21)")
        self.assertEqual(action.action, "hide")

    def test_moderation_action_target_repr_max_length_200(self):
        """target_repr field has max_length of 200."""
        from a_core.models import ModerationAction

        field = ModerationAction._meta.get_field("target_repr")
        self.assertEqual(field.max_length, 200)

    def test_moderation_action_flag_fk_nullable(self):
        """ModerationAction.flag FK is null/blank=True (optional)."""
        from django.contrib.auth import get_user_model

        from a_core.models import ModerationAction

        User = get_user_model()
        moderator = User.objects.create_user(
            username="mod2", email="mod2@example.com", password="pass"
        )
        action = ModerationAction.objects.create(
            moderator=moderator,
            target_type="organizer",
            target_id=1,
            target_repr="Test Organizer",
            action="no_action",
        )
        self.assertIsNone(action.flag)

    def test_moderation_action_has_compound_index(self):
        """ModerationAction has an index on (target_type, target_id)."""
        from a_core.models import ModerationAction

        index_fields = [
            tuple(idx.fields) for idx in ModerationAction._meta.indexes
        ]
        self.assertIn(("target_type", "target_id"), index_fields)

    def test_moderation_action_created_at_auto(self):
        """ModerationAction.created_at is set automatically."""
        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from a_core.models import ModerationAction

        User = get_user_model()
        moderator = User.objects.create_user(
            username="mod3", email="mod3@example.com", password="pass"
        )
        before = timezone.now()
        action = ModerationAction.objects.create(
            moderator=moderator,
            target_type="review",
            target_id=5,
            target_repr="Review by user",
            action="resolved",
        )
        after = timezone.now()
        self.assertGreaterEqual(action.created_at, before)
        self.assertLessEqual(action.created_at, after)


class ContextProcessorTest(TestCase):
    def setUp(self):
        cache.clear()

    def test_feature_flags_context_keys(self):
        from a_core.models import FeatureFlag
        from a_core.context_processors import feature_flags
        # Seed flags
        for key in ["MAP_ENABLED", "INVITES_ENABLED", "PUBLIC_READ_ENABLED",
                    "RATINGS_ENABLED", "FLAGS_ENABLED"]:
            FeatureFlag.objects.get_or_create(key=key, defaults={"enabled": True})
        ctx = feature_flags(None)
        self.assertIn("MAP_ENABLED", ctx)
        self.assertIn("INVITES_ENABLED", ctx)
        self.assertIn("PUBLIC_READ_ENABLED", ctx)
        self.assertIn("RATINGS_ENABLED", ctx)
        self.assertIn("FLAGS_ENABLED", ctx)
        # New flags added for event reviews display
        self.assertIn("EVENT_REVIEWS_DISPLAYED", ctx)
        self.assertIn("EVENT_RATING_THRESHOLD", ctx)
        # LOGIN_WALL_ENABLED is not in context
        self.assertNotIn("LOGIN_WALL_ENABLED", ctx)
