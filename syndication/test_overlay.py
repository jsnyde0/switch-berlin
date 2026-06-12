"""
TDD tests for the names/tags overlay on PlatformConnection (kb-sbhs.1).

These two additive fields decorate a PlatformConnection for display and
theme-tag filtering — never message content, never replacing connection identity.

ADR-008 D3 (additive-only): defaults must NOT regress prior visibility.
ADR-003 (audience-ready): shape allows a future Audiences feature to read
  the overlay without reshaping — no Audiences abstraction built here.
ADR-016 D4: overlay decorates PlatformConnection — no lighter-record bypass.
"""

from django.test import TestCase

from organizers.models import Profile
from syndication.models import PlatformConnection


def _make_profile(name="Test Organizer", slug="test-overlay-organizer"):
    return Profile.objects.create(name=name, slug=slug)


def _make_connection(profile, **kwargs):
    """Create a minimal PlatformConnection with sensible defaults."""
    kwargs.setdefault("platform", "telegram")
    kwargs.setdefault("destination_id", "-1001234567890")
    kwargs.setdefault("kinds", ["promotion"])
    return PlatformConnection.objects.create(organizer=profile, **kwargs)


class OverlayDefaultsTest(TestCase):
    """
    friendly_name defaults to None; theme_tags defaults to an empty list.
    Neither default changes prior visibility/behavior.
    """

    def setUp(self):
        self.profile = _make_profile()

    def test_friendly_name_defaults_to_none(self):
        conn = _make_connection(self.profile)
        self.assertIsNone(conn.friendly_name)

    def test_theme_tags_defaults_to_empty_list(self):
        conn = _make_connection(self.profile)
        self.assertEqual(conn.theme_tags, [])

    def test_defaults_are_preserved_on_reload(self):
        """A connection created without touching the overlay returns the same defaults on DB reload."""
        conn = _make_connection(self.profile)
        pk = conn.pk
        reloaded = PlatformConnection.objects.get(pk=pk)
        self.assertIsNone(reloaded.friendly_name)
        self.assertEqual(reloaded.theme_tags, [])


class OverlayRoundTripTest(TestCase):
    """
    theme_tags round-trips as a Python list — stored as JSON, loaded as list
    (never as a raw JSON string).
    """

    def setUp(self):
        self.profile = _make_profile()

    def test_theme_tags_round_trip_as_list(self):
        conn = _make_connection(self.profile, theme_tags=["munich", "queer"])
        pk = conn.pk
        reloaded = PlatformConnection.objects.get(pk=pk)
        self.assertIsInstance(reloaded.theme_tags, list)
        self.assertEqual(reloaded.theme_tags, ["munich", "queer"])

    def test_theme_tags_is_not_a_json_string(self):
        """Confirm the loaded value is a list, not a serialised JSON string."""
        conn = _make_connection(self.profile, theme_tags=["berlin", "fetish"])
        pk = conn.pk
        reloaded = PlatformConnection.objects.get(pk=pk)
        self.assertNotIsInstance(reloaded.theme_tags, str)

    def test_friendly_name_round_trip(self):
        conn = _make_connection(self.profile, friendly_name="Munich Kink Scene")
        pk = conn.pk
        reloaded = PlatformConnection.objects.get(pk=pk)
        self.assertEqual(reloaded.friendly_name, "Munich Kink Scene")


class OverlayVisibilityRegressionTest(TestCase):
    """
    ADR-008 D3: a connection without overlay fields must surface and behave
    exactly as before — no visibility regression.
    """

    def setUp(self):
        self.profile = _make_profile()

    def test_connection_without_overlay_is_still_enabled(self):
        """A connection without overlay fields is still enabled by default."""
        conn = _make_connection(self.profile)
        reloaded = PlatformConnection.objects.get(pk=conn.pk)
        self.assertTrue(reloaded.enabled)
        self.assertIsNone(reloaded.friendly_name)
        self.assertEqual(reloaded.theme_tags, [])

    def test_connection_without_overlay_preserves_kinds(self):
        """kinds is unaffected by empty overlay."""
        conn = _make_connection(self.profile, kinds=["promotion"])
        reloaded = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(reloaded.kinds, ["promotion"])
        self.assertIsNone(reloaded.friendly_name)
        self.assertEqual(reloaded.theme_tags, [])

    def test_connection_without_overlay_flagged_missing_default_false(self):
        """flagged_missing default is not changed by the overlay fields."""
        conn = _make_connection(self.profile)
        reloaded = PlatformConnection.objects.get(pk=conn.pk)
        self.assertFalse(reloaded.flagged_missing)
        self.assertIsNone(reloaded.friendly_name)
        self.assertEqual(reloaded.theme_tags, [])

    def test_connection_without_overlay_platform_fields_intact(self):
        """Core identity fields (platform, destination_id) are intact."""
        conn = _make_connection(self.profile, platform="telegram", destination_id="-999")
        reloaded = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(reloaded.platform, "telegram")
        self.assertEqual(reloaded.destination_id, "-999")
        self.assertIsNone(reloaded.friendly_name)
        self.assertEqual(reloaded.theme_tags, [])


class OverlayIndependenceTest(TestCase):
    """
    Overlay fields are independent of kinds and enabled — setting one must
    not affect the others.
    """

    def setUp(self):
        self.profile = _make_profile()

    def test_setting_friendly_name_does_not_affect_kinds(self):
        conn = _make_connection(self.profile, kinds=["promotion"], friendly_name="Test Channel")
        self.assertEqual(conn.kinds, ["promotion"])

    def test_setting_theme_tags_does_not_affect_enabled(self):
        conn = _make_connection(self.profile, theme_tags=["queer"], enabled=True)
        self.assertTrue(conn.enabled)

    def test_setting_theme_tags_does_not_affect_kinds(self):
        conn = _make_connection(self.profile, kinds=["listing", "promotion"], theme_tags=["kink"])
        self.assertEqual(conn.kinds, ["listing", "promotion"])

    def test_overlay_fields_are_independent_of_each_other(self):
        """Setting friendly_name does not affect theme_tags and vice versa."""
        conn = _make_connection(self.profile, friendly_name="Named Channel")
        self.assertEqual(conn.theme_tags, [])

        conn2 = _make_connection(
            self.profile,
            destination_id="-2222",
            theme_tags=["tag1"],
        )
        self.assertIsNone(conn2.friendly_name)

    def test_enabled_false_coexists_with_overlay(self):
        """Disabling a connection does not interact with overlay fields."""
        conn = _make_connection(
            self.profile,
            enabled=False,
            friendly_name="Disabled Channel",
            theme_tags=["archive"],
        )
        pk = conn.pk
        reloaded = PlatformConnection.objects.get(pk=pk)
        self.assertFalse(reloaded.enabled)
        self.assertEqual(reloaded.friendly_name, "Disabled Channel")
        self.assertEqual(reloaded.theme_tags, ["archive"])

    def test_overlay_does_not_replace_title(self):
        """
        friendly_name is DISPLAY ONLY; title is the synced source-of-truth.
        Setting friendly_name must not change title.
        """
        conn = _make_connection(
            self.profile,
            title="@munich_kink_real",
            friendly_name="Munich Kink Scene",
        )
        reloaded = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(reloaded.title, "@munich_kink_real")
        self.assertEqual(reloaded.friendly_name, "Munich Kink Scene")
