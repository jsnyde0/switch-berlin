"""
Tests for kb-shzi.2 — studio shell on standalone/refresh AND selected tab survives swaps.

BUG 1: Plain GET (no HX-Request) of post/event composer URL must render the
        studio two-pane shell (rail aside + #studio-main with composer inside).
        Currently, standalone hub pages extend layouts/_default.html which has
        NO rail and no #studio-main.

BUG 2: POSTing customize/reset/duplicate with selected_pk=<non-first projection pk>
        must return a fragment whose x-data selectedPk equals that pk.
        Currently, every swap re-initializes Alpine selectedPk to the first/default,
        jumping the user back to the leftmost tab.

All assertions on response.content (NOT response.context) per hollow-test memory.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_event(profile, title, slug):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_switch_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        enabled=True,
    )


def _make_promotion_connection(profile, platform, destination_id):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=["promotion"],
        enabled=True,
    )


def _make_switch_listing_projection(event, connection):
    from syndication.engine import generate_projection

    return generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )


def _assert_selected_pk_seeded(test_case, content, expected_pk, msg_prefix=""):
    """
    Assert that the x-data selectedPk is seeded to expected_pk.

    The template may emit whitespace between 'selectedPk:' and the value
    (djlint reformats inline Django template tags with newlines). We use
    a regex that tolerates optional whitespace between the colon and the value.

    Checks for: selectedPk: <optional-whitespace> <expected_pk>
    """
    pattern = rf"selectedPk:\s*{re.escape(str(expected_pk))}"
    match = re.search(pattern, content)
    test_case.assertIsNotNone(
        match,
        f"{msg_prefix}Expected selectedPk seeded to {expected_pk!r} "
        f"(pattern {pattern!r} not found). "
        f"Content excerpt: {content[:500]!r}",
    )


def _assert_selected_pk_is_source(test_case, content, msg_prefix=""):
    """Assert that x-data selectedPk is seeded to 'source'."""
    pattern = r"selectedPk:\s*'source'"
    match = re.search(pattern, content)
    test_case.assertIsNotNone(
        match,
        f"{msg_prefix}Expected selectedPk seeded to 'source' "
        f"(pattern {pattern!r} not found). "
        f"Content excerpt: {content[:500]!r}",
    )


# ---------------------------------------------------------------------------
# BUG 1: Plain GET of event hub must render studio shell (rail + #studio-main)
# ---------------------------------------------------------------------------


class EventHubFullPageRendersStudioShellTest(TestCase):
    """
    BUG 1: A plain GET (no HX-Request header) of the event hub URL must return
    HTML that contains:
    - The publishables rail aside (marked by aria-label="Publishables")
    - id="studio-main" containing the composer

    Before the fix: the standalone event_hub.html extends layouts/_default.html
    which has NO rail and no #studio-main — the rail is absent.
    After the fix: the full-page response renders the studio two-pane shell.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ehfp_user", email="ehfp@test.com", password="pw")
        self.profile = _make_profile("EHFP Org", "ehfp-org", user=self.user)
        self.event = _make_event(self.profile, "Event Hub Full Page Test", "ehfp-event")
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_event_hub_plain_get_contains_publishables_rail(self):
        """
        BUG 1: Plain GET of event hub must include the publishables rail aside.
        The rail is the core structure of the studio two-pane shell.
        Marker: aria-label="Publishables" (set on the aside in studio.html).
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url)  # No HX-Request header — plain GET

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'aria-label="Publishables"',
            content,
            "BUG 1: Plain GET of event hub must render the publishables rail aside "
            "(aria-label='Publishables'). Currently the standalone page extends "
            "layouts/_default.html which has no rail.",
        )

    def test_event_hub_plain_get_contains_studio_main(self):
        """
        BUG 1: Plain GET of event hub must include id="studio-main" — the HTMX
        swap target that contains the composer. Without this, in-studio navigation
        from the rail has no target and silently fails.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'id="studio-main"',
            content,
            "BUG 1: Plain GET of event hub must contain id='studio-main'. "
            "Currently absent from the rail-less standalone page.",
        )

    def test_event_hub_plain_get_contains_publishable_link_in_rail(self):
        """
        BUG 1: The rail must contain at least one publishable link — confirming
        the rail is populated (not just structurally present but empty).
        The event's own URL should appear in the rail as an active row.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The event's URL appears in the rail row as the active publishable
        event_url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        self.assertIn(
            event_url,
            content,
            "BUG 1: The rail must contain the event's composer URL as a publishable link. "
            "Confirms the rail is populated, not just structurally present.",
        )

    def test_event_hub_htmx_request_returns_fragment_without_rail(self):
        """
        Regression guard: HX-Request still returns the layout-less fragment
        (no rail, no full shell) so in-studio navigation continues to work.
        """
        url = reverse("syndication:event-hub", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # HX fragment must NOT nest <html or <body
        self.assertNotIn("<html", content)
        self.assertNotIn("<body", content)


# ---------------------------------------------------------------------------
# BUG 1: Plain GET of post hub must render studio shell (rail + #studio-main)
# ---------------------------------------------------------------------------


class PostHubFullPageRendersStudioShellTest(TestCase):
    """
    BUG 1: A plain GET (no HX-Request header) of the post hub URL must return
    HTML that contains the publishables rail aside AND id="studio-main".

    Before the fix: post_hub.html extends layouts/_default.html (no rail).
    After the fix: the full-page response renders the studio two-pane shell.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="phfp_user", email="phfp@test.com", password="pw")
        self.profile = _make_profile("PHFP Org", "phfp-org", user=self.user)
        self.event = _make_event(self.profile, "Post Hub Full Page Event", "phfp-event")
        self.post = Post.objects.create(event=self.event, headline="PHFP Post", body="PHFP body")
        # Create canonical CV for the post (required by fragment_post_syndication)
        ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.switch_conn = _make_switch_connection(self.profile)
        _make_switch_listing_projection(self.event, self.switch_conn)
        self.client.force_login(self.user)

    def test_post_hub_plain_get_contains_publishables_rail(self):
        """
        BUG 1: Plain GET of post hub must include the publishables rail aside.
        Marker: aria-label="Publishables".
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'aria-label="Publishables"',
            content,
            "BUG 1: Plain GET of post hub must render the publishables rail aside "
            "(aria-label='Publishables'). Currently the standalone page extends "
            "layouts/_default.html which has no rail.",
        )

    def test_post_hub_plain_get_contains_studio_main(self):
        """
        BUG 1: Plain GET of post hub must include id="studio-main".
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            'id="studio-main"',
            content,
            "BUG 1: Plain GET of post hub must contain id='studio-main'.",
        )

    def test_post_hub_plain_get_contains_publishable_link_in_rail(self):
        """
        BUG 1: The rail in the post hub full-page must list publishable links.
        The post's event URL should appear (rail shows both events and posts).
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # The post's own URL must appear in the rail
        post_url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        self.assertIn(
            post_url,
            content,
            "BUG 1: The rail in the post hub full-page must contain the post's URL. Confirms the rail is populated.",
        )

    def test_post_hub_htmx_request_returns_fragment_without_rail(self):
        """
        Regression guard: HX-Request still returns the layout-less fragment.
        """
        url = reverse("syndication:post-hub", kwargs={"pk": self.post.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertNotIn("<html", content)
        self.assertNotIn("<body", content)


# ---------------------------------------------------------------------------
# BUG 2: customize/reset/duplicate must preserve selected tab
# ---------------------------------------------------------------------------


class SelectedTabSurvivesCustomizeTest(TestCase):
    """
    BUG 2: POSTing to projection_customize with selected_pk=<non-first pk>
    must return a fragment whose x-data selectedPk equals that pk.

    Before the fix: x-data="{ selectedPk: 'source', ... }" is a constant seed
    (post) or x-data="{ selectedPk: {{ first_pk|default:'null' }}, ... }" (event),
    so every outerHTML swap re-initializes to the leftmost tab.

    After the fix: the view threads selected_pk through; the template seeds
    selectedPk from {{ selected_pk|default:first_pk }} (or 'source' for posts).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tabcust_user", email="tabcust@test.com", password="pw")
        self.profile = _make_profile("TabCust Org", "tabcust-org", user=self.user)
        self.event = _make_event(self.profile, "Tab Customize Event", "tab-customize-event")
        self.post = Post.objects.create(event=self.event, headline="Tab Post", body="Tab body")

        # Canonical CV (the Source anchor tab)
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Two promotion connections so there are at least two tabs (non-first test is meaningful)
        self.conn_telegram = _make_promotion_connection(self.profile, "telegram", "tg-tabcust")
        self.conn_fetlife = _make_promotion_connection(self.profile, "fetlife", "fl-tabcust")

        # Telegram projection (shares canonical CV — state i)
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.conn_telegram,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife projection (own CV — state iii, suitable for customize)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-tabcust-cv",
            body="fl body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_customize_with_selected_pk_seeds_that_tab_in_fragment(self):
        """
        BUG 2: POST to projection_customize with selected_pk=<fl_proj.pk>
        (the non-first / non-default tab) returns a fragment whose x-data
        selectedPk equals fl_proj.pk, NOT 'source' or the first pk.

        Assertion: response.content contains 'selectedPk: <fl_proj.pk>'.
        """
        url = reverse("syndication:projection-customize", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={"selected_pk": str(self.fl_proj.pk)},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # After customize, the fragment must seed selectedPk to the requested tab.
        # Use regex helper to tolerate djlint whitespace formatting.
        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=f"BUG 2: After customize, x-data selectedPk must be seeded to "
            f"{self.fl_proj.pk} (the selected tab), not reset to 'source' or the first tab. ",
        )


class SelectedTabSurvivesResetTest(TestCase):
    """
    BUG 2: POSTing to projection_reset_to_canonical with selected_pk=<non-first pk>
    must return a fragment whose x-data selectedPk equals that pk.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tabreset_user", email="tabreset@test.com", password="pw")
        self.profile = _make_profile("TabReset Org", "tabreset-org", user=self.user)
        self.event = _make_event(self.profile, "Tab Reset Event", "tab-reset-event")
        self.post = Post.objects.create(event=self.event, headline="Tab Reset Post", body="Reset body")
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        self.conn_telegram = _make_promotion_connection(self.profile, "telegram", "tg-tabreset")
        self.conn_fetlife = _make_promotion_connection(self.profile, "fetlife", "fl-tabreset")

        # Telegram on canonical (state i)
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.conn_telegram,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife with own CV and sync_source set (state ii — reset-to-canonical applies)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-tabreset-cv",
            body="fl reset body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
            sync_source=self.tg_proj,
        )

        self.client.force_login(self.user)

    def test_reset_with_selected_pk_seeds_that_tab_in_fragment(self):
        """
        BUG 2: POST to projection_reset_to_canonical with selected_pk=<fl_proj.pk>
        returns a fragment seeded to that pk, not 'source'.

        After reset, fl_proj is repointed to canonical CV. The tab still exists
        (the projection remains; only its content_version pointer changes).
        """
        url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={"selected_pk": str(self.fl_proj.pk)},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=f"BUG 2: After reset, x-data selectedPk must be seeded to {self.fl_proj.pk}. ",
        )


class SelectedTabSurvivesDuplicateTest(TestCase):
    """
    BUG 2: POSTing to version_duplicate with selected_pk=<non-first pk>
    must return a fragment whose x-data selectedPk equals a tab that STILL EXISTS.

    Duplicate creates a NEW ContentVersion but the projection count stays the same
    (duplicate clones the CV, not the projection). After duplicate the selected
    projection still exists, so selectedPk can be preserved as-is.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tabdup_user", email="tabdup@test.com", password="pw")
        self.profile = _make_profile("TabDup Org", "tabdup-org", user=self.user)
        self.event = _make_event(self.profile, "Tab Duplicate Event", "tab-duplicate-event")
        self.post = Post.objects.create(event=self.event, headline="Tab Dup Post", body="Dup body")
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        self.conn_telegram = _make_promotion_connection(self.profile, "telegram", "tg-tabdup")
        self.conn_fetlife = _make_promotion_connection(self.profile, "fetlife", "fl-tabdup")

        # Telegram on canonical (state i)
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.conn_telegram,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife with own CV (state iii — can duplicate from)
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-tabdup-cv",
            body="fl dup body",
            provenance=ContentVersion.Provenance.MANUAL,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_duplicate_with_selected_pk_seeds_that_tab_in_fragment(self):
        """
        BUG 2: POST to version_duplicate with selected_pk=<fl_proj.pk> returns
        a fragment seeded to fl_proj.pk (projection still exists after duplicate).
        """
        url = reverse("syndication:version-duplicate", kwargs={"pk": self.fl_cv.pk})
        response = self.client.post(
            url,
            data={"selected_pk": str(self.fl_proj.pk)},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=f"BUG 2: After duplicate, x-data selectedPk must be seeded to {self.fl_proj.pk}. ",
        )


class SelectedTabFallsBackWhenTabGoneTest(TestCase):
    """
    BUG 2: Edge case — if selected_pk refers to a tab that no longer exists after
    the action (shouldn't happen for projection-level actions, but guard it),
    the fragment must fall back to a valid tab (first or 'source').

    This is primarily a spec-clarification test: since customize/reset/duplicate
    don't remove projections, the selected tab always persists. This test confirms
    the fallback behavior when an invalid/nonexistent pk is passed.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="tabfb_user", email="tabfb@test.com", password="pw")
        self.profile = _make_profile("TabFB Org", "tabfb-org", user=self.user)
        self.event = _make_event(self.profile, "Tab Fallback Event", "tab-fallback-event")
        self.post = Post.objects.create(event=self.event, headline="Tab FB Post", body="FB body")
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        self.conn_telegram = _make_promotion_connection(self.profile, "telegram", "tg-tabfb")
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.conn_telegram,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-tabfb-cv",
            body="fl fb body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.conn_fetlife = _make_promotion_connection(self.profile, "fetlife", "fl-tabfb")
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.conn_fetlife,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_invalid_selected_pk_falls_back_to_source(self):
        """
        If selected_pk=99999 (nonexistent), the fragment must fall back gracefully
        to 'source' or the first available projection tab — NOT raise a 500.
        The response must be 200 and contain a valid x-data selectedPk value.
        """
        url = reverse("syndication:projection-customize", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={"selected_pk": "99999"},  # nonexistent pk
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Must not crash; must contain a valid selectedPk seed.
        # Use regex to tolerate djlint whitespace formatting.
        has_valid_seed = bool(re.search(r"selectedPk:\s*'source'", content)) or bool(
            re.search(r"selectedPk:\s*\d+", content)
        )
        self.assertTrue(
            has_valid_seed,
            f"BUG 2 fallback: invalid selected_pk must not crash and must produce a "
            f"valid selectedPk seed. Content excerpt: {content[:500]!r}",
        )
