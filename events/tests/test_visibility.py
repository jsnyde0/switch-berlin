"""
[kb-m69.2] Event.visibility ENUM, source-derived backfill,
queryset manager, is_indexable, sitemap exclusion.

ADR-012 D1 (3-tier shape), D2 (source-derived defaults), D3 (access matrix).
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from events.models import Event

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(title="Test", slug=None, visibility="public", **kwargs):
    """Create a minimal published event with the given visibility."""
    if slug is None:
        slug = title.lower().replace(" ", "-")
    defaults = dict(
        title=title,
        slug=slug,
        start=timezone.now(),
        status="published",
        visibility=visibility,
    )
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def make_user(username, status="open"):
    """Create a user with the given status (User.status field from kb-m69.1)."""
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )
    user.status = status
    user.save(update_fields=["status"])
    return user


# ---------------------------------------------------------------------------
# D1 — field shape
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVisibilityField:
    """Event.visibility field exists with the correct choices and default."""

    def test_visibility_field_exists(self):
        f = Event._meta.get_field("visibility")
        assert f is not None

    def test_visibility_choices_are_correct(self):
        f = Event._meta.get_field("visibility")
        values = [c[0] for c in f.choices]
        assert "public" in values
        assert "semi_public" in values
        assert "unlisted" in values
        # Exactly three tiers (ADR-012 D1)
        assert len(values) == 3

    def test_visibility_default_is_public(self):
        """Field default is 'public' (overridden by source-derivation at creation)."""
        f = Event._meta.get_field("visibility")
        assert f.default == "public"

    def test_visibility_field_is_not_nullable(self):
        """ADR-008 D3 — no silent fallback; field must never be null."""
        f = Event._meta.get_field("visibility")
        assert not f.null

    def test_event_saves_with_public_visibility(self, db):
        e = make_event("Public Event", slug="public-evt")
        assert e.visibility == "public"

    def test_event_saves_with_semi_public_visibility(self, db):
        e = make_event("Semi Event", slug="semi-evt", visibility="semi_public")
        assert e.visibility == "semi_public"

    def test_event_saves_with_unlisted_visibility(self, db):
        e = make_event("Unlisted Event", slug="unlisted-evt", visibility="unlisted")
        assert e.visibility == "unlisted"


# ---------------------------------------------------------------------------
# D4 — is_indexable property (ADR-012 D4)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIsIndexable:
    """Event.is_indexable is True iff visibility == 'public'."""

    def test_public_event_is_indexable(self, db):
        e = make_event("Public", slug="pub-idx")
        assert e.is_indexable is True

    def test_semi_public_event_is_not_indexable(self, db):
        e = make_event("Semi", slug="semi-idx", visibility="semi_public")
        assert e.is_indexable is False

    def test_unlisted_event_is_not_indexable(self, db):
        e = make_event("Unlisted", slug="unl-idx", visibility="unlisted")
        assert e.is_indexable is False


# ---------------------------------------------------------------------------
# D3 — queryset manager (visible_to)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVisibleToManager:
    """Event.objects.visible_to(user) returns the correct subset per viewer tier."""

    def setup_method(self):
        """Create one event of each visibility tier."""
        # These are created inside each test via the db fixture; no setup needed.

    def test_visible_to_anon_returns_only_public(self, db):
        pub = make_event("Pub", slug="vt-pub")
        make_event("Semi", slug="vt-semi", visibility="semi_public")
        make_event("Unl", slug="vt-unl", visibility="unlisted")
        qs = Event.objects.visible_to(None)
        assert pub in qs
        assert qs.count() == 1

    def test_visible_to_open_user_returns_only_public(self, db):
        pub = make_event("Pub2", slug="vt-pub2")
        make_event("Semi2", slug="vt-semi2", visibility="semi_public")
        make_event("Unl2", slug="vt-unl2", visibility="unlisted")
        user = make_user("open_user", status="open")
        qs = Event.objects.visible_to(user)
        assert pub in qs
        assert qs.count() == 1

    def test_visible_to_vouched_user_returns_public_and_semi_public(self, db):
        pub = make_event("Pub3", slug="vt-pub3")
        semi = make_event("Semi3", slug="vt-semi3", visibility="semi_public")
        make_event("Unl3", slug="vt-unl3", visibility="unlisted")
        user = make_user("vouched_user", status="vouched")
        qs = Event.objects.visible_to(user)
        assert pub in qs
        assert semi in qs
        # unlisted is NOT returned by queryset (access by direct URL only)
        assert qs.count() == 2

    def test_visible_to_admin_returns_all_tiers(self, db):
        """Superusers / staff see everything including unlisted."""
        pub = make_event("Pub4", slug="vt-pub4")
        semi = make_event("Semi4", slug="vt-semi4", visibility="semi_public")
        unl = make_event("Unl4", slug="vt-unl4", visibility="unlisted")
        admin = make_user("admin_user", status="vouched")
        admin.is_superuser = True
        admin.save(update_fields=["is_superuser"])
        qs = Event.objects.visible_to(admin)
        assert pub in qs
        assert semi in qs
        assert unl in qs
        assert qs.count() == 3


# ---------------------------------------------------------------------------
# D2 — source-derived backfill (migration logic — tested via raw SQL helper)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSourceDerivedBackfill:
    """
    The migration backfills visibility using the source-derived mapping.

    These tests verify the *helper function* (not the migration runner) to
    confirm the mapping logic is correct before the migration is applied.
    The helper is imported from the migration module.
    """

    def test_backfill_helper_scraped_public_website_yields_public(self, db):
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(["scraped_public_website"])
        assert result == "public"

    def test_backfill_helper_telegram_public_yields_public(self, db):
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(["telegram_public_channel"])
        assert result == "public"

    def test_backfill_helper_telegram_private_yields_semi_public(self, db):
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(["telegram_private_group"])
        assert result == "semi_public"

    def test_backfill_helper_web_form_yields_semi_public(self, db):
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(["user_submitted_web_form"])
        assert result == "semi_public"

    def test_backfill_helper_manual_yields_semi_public(self, db):
        """Manual creation with no source defaults to semi_public."""
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources([])
        assert result == "semi_public"

    def test_backfill_helper_max_public_resolution_mixed_sources(self, db):
        """max(public) wins: telegram_private + scraped_public → public."""
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(
            ["telegram_private_group", "scraped_public_website"]
        )
        assert result == "public"

    def test_backfill_helper_max_public_resolution_all_semi(self, db):
        """All semi_public sources → semi_public."""
        from events.backfill_visibility import derive_visibility_from_sources

        result = derive_visibility_from_sources(
            ["telegram_private_group", "user_submitted_web_form"]
        )
        assert result == "semi_public"

    def test_backfill_helper_unknown_source_raises(self, db):
        """ADR-008 D3: unknown source must raise, not silently fallback."""
        from events.backfill_visibility import derive_visibility_from_sources

        with pytest.raises(ValueError, match="Unknown source"):
            derive_visibility_from_sources(["mystery_source"])


# ---------------------------------------------------------------------------
# Sitemap exclusion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSitemap:
    """events/sitemap.py EventSitemap excludes non-public events."""

    def test_sitemap_includes_public_events(self, db):
        from events.sitemap import EventSitemap

        pub = make_event("SitemapPub", slug="sm-pub")
        sitemap = EventSitemap()
        items = list(sitemap.items())
        assert pub in items

    def test_sitemap_excludes_semi_public_events(self, db):
        from events.sitemap import EventSitemap

        make_event("SitemapSemi", slug="sm-semi", visibility="semi_public")
        sitemap = EventSitemap()
        items = list(sitemap.items())
        slugs = [e.slug for e in items]
        assert "sm-semi" not in slugs

    def test_sitemap_excludes_unlisted_events(self, db):
        from events.sitemap import EventSitemap

        make_event("SitemapUnlisted", slug="sm-unl", visibility="unlisted")
        sitemap = EventSitemap()
        items = list(sitemap.items())
        slugs = [e.slug for e in items]
        assert "sm-unl" not in slugs
