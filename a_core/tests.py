"""Tests for a_core models: FeatureFlag, EmailFailure, get_flag()."""
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
        # LOGIN_WALL_ENABLED is not in context
        self.assertNotIn("LOGIN_WALL_ENABLED", ctx)
