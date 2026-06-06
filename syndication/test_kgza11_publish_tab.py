"""
Regression tests for kb-kgza.11 — publish/re-publish from a non-canonical tab
keeps the selected tab on that channel, NOT jumping to the canonical first tab.

## Background

The event syndication fragment (and post syndication fragment) is re-rendered
after a Publish or Re-publish action. The `selected_pk` context var controls
which tab Alpine initialises as active (x-data `selectedPk: <pk>`).

The publish forms thread `selected_pk` as a hidden input (`:value="selectedPk"`),
so the POST body carries the currently-selected tab pk. The view reads
`request.POST.get("selected_pk")`, validates it against the KIND-FILTERED
projection set, and seeds it into the context. The template initialises
`x-data { selectedPk: <pk> }` with this server-seeded value.

The suspect narrow-edge: `selected_pk` is validated ONLY against the
kind-filtered projection set (views.py:664-668 for event, views.py:924-931 for
post). If the published-from channel's pk were absent from that set (e.g. the
connection's kinds field was missing the expected kind), it would fall through
to `selected_pk=None` → Alpine defaults to `first_pk` (the canonical tab).

## What these tests verify

1. EVENT COMPOSER, FIRST-PUBLISH:
   Setup: event with Switch listing (canonical, first tab) + FetLife listing
   (non-canonical, second tab). FetLife projection is draft.
   Action: POST projection-direct-publish for FetLife with selected_pk=<fl pk>.
   Assert: response.content contains selectedPk seeded to fl pk (NOT sw pk).

2. EVENT COMPOSER, RE-PUBLISH (published dirty → re-publish):
   Setup: same event. FetLife projection is published+dirty.
   Action: POST projection-direct-publish for FetLife with selected_pk=<fl pk>.
   Assert: response.content contains selectedPk seeded to fl pk.

3. POST COMPOSER, FIRST-PUBLISH:
   Setup: post with Telegram promotion (first tab) + FetLife promotion
   (non-canonical, second tab). FetLife projection is draft.
   Action: POST projection-direct-publish for FetLife with selected_pk=<fl pk>.
   Assert: response.content contains selectedPk seeded to fl pk.

4. POST COMPOSER, RE-PUBLISH (published dirty → re-publish):
   Setup: same post. FetLife projection is published+dirty.
   Action: POST projection-direct-publish for FetLife with selected_pk=<fl pk>.
   Assert: response.content contains selectedPk seeded to fl pk.

All assertions are on response.content (NOT response.context) per the
hollow-test trap documented in the test suite (response.context may be None
or stale in HTMX fragment responses).

Gates: uv run pytest syndication/ (bare), ruff check, ruff format, djlint.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection, transition_status
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared helpers
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
        description="Regression test event for kb-kgza.11",
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_switch_listing_connection(profile):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="switch",
        destination_id="own-page",
        kinds=["listing"],
        enabled=True,
    )


def _make_fetlife_listing_connection(profile, destination_id="fl-listing"):
    """FetLife listing connection — non-canonical second tab in event composer."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        kinds=["listing"],
        enabled=True,
    )


def _make_fetlife_promotion_connection(profile, destination_id="fl-promo"):
    """FetLife promotion connection — non-canonical tab in post composer."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        kinds=["promotion"],
        enabled=True,
    )


def _make_telegram_promotion_connection(profile, destination_id="tg-promo"):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=["promotion"],
        enabled=True,
    )


def _make_listing_projection(event, connection):
    return generate_projection(
        kind="listing",
        connection=connection,
        source_event=event,
        mode="rule_based",
    )


def _make_published_dirty_projection(event, connection, kind="listing", source_post=None):
    """
    Create a projection, publish it (draft→ready→published), then edit
    its body so is_dirty returns True. This is the Re-publish scenario.
    """
    if kind == "listing":
        proj = generate_projection(
            kind="listing",
            connection=connection,
            source_event=event,
            mode="rule_based",
        )
    else:
        # promotion kind: create directly
        cv = ContentVersion.objects.create(
            post=source_post,
            name=f"cv-{connection.platform}-{connection.destination_id}",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        proj = PlatformProjection.objects.create(
            connection=connection,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=source_post,
            content_version=cv,
        )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    transition_status(proj, "published")
    proj.refresh_from_db()
    # Make the content dirty: edit body after publish (frozen_content diverges)
    cv = proj.content_version
    cv.body = "EDITED AFTER PUBLISH — body now differs from frozen_content snapshot"
    cv.save(update_fields=["body"])
    proj.refresh_from_db()
    return proj


def _assert_selected_pk_seeded(test_case, content, expected_pk, msg_prefix=""):
    """
    Assert that the x-data selectedPk is seeded to expected_pk.
    Uses a regex that tolerates optional whitespace around the value
    (djlint may reformat inline Alpine expressions).

    This checks response.content directly — NOT response.context —
    which is the user-observable output of the server (hollow-test safe).
    """
    pattern = rf"selectedPk:\s*{re.escape(str(expected_pk))}"
    match = re.search(pattern, content)
    test_case.assertIsNotNone(
        match,
        f"{msg_prefix}Expected selectedPk seeded to {expected_pk!r} "
        f"in x-data (pattern {pattern!r} not found). "
        f"The publish-view response must seed selectedPk to the published-from "
        f"channel, NOT jump to the canonical first_pk. "
        f"Content excerpt (first 600 chars): {content[:600]!r}",
    )


# ---------------------------------------------------------------------------
# Event composer — first-publish from non-canonical tab
# ---------------------------------------------------------------------------


class EventFirstPublishFromNonCanonicalTabTest(TestCase):
    """
    After Publish (draft→published) from a NON-canonical FetLife listing tab,
    the re-rendered event_syndication fragment must seed selectedPk to the
    FetLife projection's pk, NOT to the canonical Switch tab's pk.

    Regression guard: if views.py:665-666 validation drops the published-from
    pk (e.g. kind mismatch or whitelist narrowing), it falls to first_pk
    (Switch = canonical). This test is the canary.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="kgza11_ev_fp_user", email="kgza11_ev_fp@test.com", password="pw")
        self.profile = _make_profile("Kgza11 Ev FP Org", "kgza11-ev-fp-org", user=self.user)
        self.event = _make_event(self.profile, "Kgza11 Ev FP Event", "kgza11-ev-fp-event")

        # Switch listing — canonical (first tab per ADR-010 D1, sort key tier 0)
        self.sw_conn = _make_switch_listing_connection(self.profile)
        self.sw_proj = _make_listing_projection(self.event, self.sw_conn)

        # FetLife listing — non-canonical (second tab)
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-kgza11-ev-fp")
        self.fl_proj = _make_listing_projection(self.event, self.fl_conn)

        self.client.force_login(self.user)

    def test_first_publish_from_noncanoical_tab_keeps_that_tab_selected(self):
        """
        POST projection-direct-publish for FetLife (draft) with
        selected_pk=<fl_proj.pk> → response seeds selectedPk to fl_proj.pk.

        This is the kb-kgza.11 regression: before the fix (which landed 2026-06-04
        as kb-shzi.2), the view did NOT read selected_pk from POST, so the
        fragment always opened the canonical first tab (Switch pk).

        If this test PASSES: the mechanism is confirmed correct for first-publish.
        If this test FAILS: the kind-filtered validation set drops the FetLife pk
        and the view falls back to first_pk = canonical Switch tab.
        """
        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={"selected_pk": str(self.fl_proj.pk)},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Primary assertion: selectedPk in x-data must be the FetLife tab
        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=(
                "kb-kgza.11 event first-publish from non-canonical tab: "
                "selectedPk must be seeded to the FetLife (published-from) tab, "
                "not jump to canonical Switch tab. "
            ),
        )

        # Corroborating assertion: Alpine binding for FetLife tab is present
        # (ensures the FetLife tab button is rendered, not stripped from output)
        self.assertIn(
            f':aria-selected="selectedPk === {self.fl_proj.pk}"',
            content,
            f"kb-kgza.11: FetLife tab button with aria-selected binding for pk "
            f"{self.fl_proj.pk} must be present in the response fragment.",
        )

        # Falsifying assertion: selectedPk must NOT be seeded to the canonical Switch pk
        # (if the view fell back to first_pk, this would match Switch's selectedPk)
        sw_pattern = rf"selectedPk:\s*{re.escape(str(self.sw_proj.pk))}"
        sw_match = re.search(sw_pattern, content)
        self.assertIsNone(
            sw_match,
            f"kb-kgza.11 event first-publish: selectedPk must NOT be seeded to the "
            f"canonical Switch tab pk ({self.sw_proj.pk}). "
            f"A match means the view ignored selected_pk and defaulted to first_pk.",
        )


# ---------------------------------------------------------------------------
# Event composer — re-publish from non-canonical tab (published dirty)
# ---------------------------------------------------------------------------


class EventRepublishFromNonCanonicalTabTest(TestCase):
    """
    After Re-publish (published+dirty → republish) from a NON-canonical FetLife
    listing tab, the re-rendered event_syndication fragment must seed selectedPk
    to the FetLife projection's pk, NOT to the canonical Switch tab's pk.

    Re-publish goes through publish_projection_direct → republish_projection
    (same URL: projection-direct-publish, status=published).

    Regression guard: the Invalidation clause in kb-kgza.11 — if kind-filtered
    validation is ever narrowed, this test fires.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="kgza11_ev_rp_user", email="kgza11_ev_rp@test.com", password="pw")
        self.profile = _make_profile("Kgza11 Ev RP Org", "kgza11-ev-rp-org", user=self.user)
        self.event = _make_event(self.profile, "Kgza11 Ev RP Event", "kgza11-ev-rp-event")

        # Switch listing — canonical (first tab, tier 0 sort)
        self.sw_conn = _make_switch_listing_connection(self.profile)
        self.sw_proj = _make_listing_projection(self.event, self.sw_conn)

        # FetLife listing — non-canonical (second tab), published+dirty
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-kgza11-ev-rp")
        self.fl_proj = _make_published_dirty_projection(self.event, self.fl_conn, kind="listing")

        self.client.force_login(self.user)

    def test_republish_from_noncanoical_tab_keeps_that_tab_selected(self):
        """
        POST projection-direct-publish for FetLife (published+dirty) with
        selected_pk=<fl_proj.pk> → response seeds selectedPk to fl_proj.pk.

        This is the re-publish variant: publish_projection_direct routes to
        republish_projection when projection.status == PUBLISHED (dirty).
        Both first-publish and re-publish go through the same view
        (projection_direct_publish) and the same _publishable_fragment_response
        dispatch, so the selected_pk round-trip is symmetric.
        """
        self.fl_proj.refresh_from_db()
        self.assertEqual(
            self.fl_proj.status,
            PlatformProjection.Status.PUBLISHED,
            "Pre-condition: FetLife projection must be in PUBLISHED state for re-publish path.",
        )
        self.assertTrue(
            self.fl_proj.is_dirty,
            "Pre-condition: FetLife projection must be dirty (body differs from frozen_content).",
        )

        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
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
            msg_prefix=(
                "kb-kgza.11 event re-publish from non-canonical tab: "
                "selectedPk must be seeded to the FetLife (re-published-from) tab, "
                "not jump to canonical Switch tab. "
            ),
        )

        # Corroborating: the FetLife tab button must be rendered in the fragment
        self.assertIn(
            f':aria-selected="selectedPk === {self.fl_proj.pk}"',
            content,
            f"kb-kgza.11: FetLife tab button with aria-selected binding for pk "
            f"{self.fl_proj.pk} must be present after re-publish.",
        )

        # Falsifying: must NOT have seeded to canonical Switch tab
        sw_pattern = rf"selectedPk:\s*{re.escape(str(self.sw_proj.pk))}"
        self.assertIsNone(
            re.search(sw_pattern, content),
            f"kb-kgza.11 event re-publish: selectedPk must NOT be seeded to "
            f"canonical Switch tab pk ({self.sw_proj.pk}). "
            f"A match means the view ignored selected_pk and defaulted to first_pk.",
        )


# ---------------------------------------------------------------------------
# Post composer — first-publish from non-canonical tab
# ---------------------------------------------------------------------------


class PostFirstPublishFromNonCanonicalTabTest(TestCase):
    """
    After Publish (draft→published) from a NON-canonical FetLife promotion tab
    in the post composer, the re-rendered post_syndication fragment must seed
    selectedPk to the FetLife projection's pk, NOT to the Telegram (first) tab.

    Post fragment shows PROMOTION projections only (kinds contains "promotion").
    Telegram is first alphabetically; FetLife is second.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="kgza11_ps_fp_user", email="kgza11_ps_fp@test.com", password="pw")
        self.profile = _make_profile("Kgza11 PS FP Org", "kgza11-ps-fp-org", user=self.user)
        self.event = _make_event(self.profile, "Kgza11 PS FP Event", "kgza11-ps-fp-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Kgza11 PS FP Post",
            body="Test body for kb-kgza.11 post first-publish",
        )
        # Canonical ContentVersion required for the post composer Source tab
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Telegram — promotion (first tab, alphabetically first in post fragment)
        self.tg_conn = _make_telegram_promotion_connection(self.profile, destination_id="tg-kgza11-ps-fp")
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-kgza11-ps-fp-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.tg_cv,
        )

        # FetLife — promotion (second tab, non-canonical)
        self.fl_conn = _make_fetlife_promotion_connection(self.profile, destination_id="fl-kgza11-ps-fp")
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-kgza11-ps-fp-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_post_first_publish_from_noncanoical_tab_keeps_that_tab_selected(self):
        """
        POST projection-direct-publish for FetLife post promotion (draft) with
        selected_pk=<fl_proj.pk> → response seeds selectedPk to fl_proj.pk.

        Mirrors the event first-publish test but for the post composer (promotion
        projections, different kind filter).
        """
        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
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
            msg_prefix=(
                "kb-kgza.11 post first-publish from non-canonical tab: "
                "selectedPk must be seeded to the FetLife (published-from) tab. "
            ),
        )

        # Corroborating: the FetLife tab button is in the fragment
        self.assertIn(
            f':aria-selected="selectedPk === {self.fl_proj.pk}"',
            content,
            f"kb-kgza.11 post first-publish: FetLife tab aria-selected binding "
            f"for pk {self.fl_proj.pk} must be present.",
        )

        # Falsifying: must NOT have seeded to the Telegram (first) tab
        tg_pattern = rf"selectedPk:\s*{re.escape(str(self.tg_proj.pk))}"
        self.assertIsNone(
            re.search(tg_pattern, content),
            f"kb-kgza.11 post first-publish: selectedPk must NOT be seeded to "
            f"Telegram tab pk ({self.tg_proj.pk}). "
            f"A match means the view ignored selected_pk and defaulted to first_pk.",
        )


# ---------------------------------------------------------------------------
# Post composer — re-publish from non-canonical tab (published dirty)
# ---------------------------------------------------------------------------


class PostRepublishFromNonCanonicalTabTest(TestCase):
    """
    After Re-publish (published+dirty → republish) from a NON-canonical FetLife
    promotion tab in the post composer, the re-rendered post_syndication fragment
    must seed selectedPk to the FetLife projection's pk.

    Symmetric with EventRepublishFromNonCanonicalTabTest but scoped to
    post promotion projections.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="kgza11_ps_rp_user", email="kgza11_ps_rp@test.com", password="pw")
        self.profile = _make_profile("Kgza11 PS RP Org", "kgza11-ps-rp-org", user=self.user)
        self.event = _make_event(self.profile, "Kgza11 PS RP Event", "kgza11-ps-rp-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Kgza11 PS RP Post",
            body="Test body for kb-kgza.11 post re-publish",
        )
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Telegram — first tab (draft, stays draft; not the published-from channel)
        self.tg_conn = _make_telegram_promotion_connection(self.profile, destination_id="tg-kgza11-ps-rp")
        self.tg_cv = ContentVersion.objects.create(
            post=self.post,
            name="tg-kgza11-ps-rp-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.tg_cv,
        )

        # FetLife — second tab, published+dirty (the re-publish scenario)
        self.fl_conn = _make_fetlife_promotion_connection(self.profile, destination_id="fl-kgza11-ps-rp")
        self.fl_proj = _make_published_dirty_projection(
            self.event,
            self.fl_conn,
            kind="promotion",
            source_post=self.post,
        )

        self.client.force_login(self.user)

    def test_post_republish_from_noncanoical_tab_keeps_that_tab_selected(self):
        """
        POST projection-direct-publish for FetLife post promotion (published+dirty)
        with selected_pk=<fl_proj.pk> → response seeds selectedPk to fl_proj.pk.
        """
        self.fl_proj.refresh_from_db()
        self.assertEqual(
            self.fl_proj.status,
            PlatformProjection.Status.PUBLISHED,
            "Pre-condition: FetLife post projection must be PUBLISHED for re-publish path.",
        )
        self.assertTrue(
            self.fl_proj.is_dirty,
            "Pre-condition: FetLife post projection must be dirty for re-publish.",
        )

        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
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
            msg_prefix=(
                "kb-kgza.11 post re-publish from non-canonical tab: "
                "selectedPk must be seeded to the FetLife (re-published-from) tab. "
            ),
        )

        # Corroborating: FetLife tab button present
        self.assertIn(
            f':aria-selected="selectedPk === {self.fl_proj.pk}"',
            content,
            f"kb-kgza.11 post re-publish: FetLife tab aria-selected binding for pk {self.fl_proj.pk} must be present.",
        )

        # Falsifying: must NOT have seeded to the Telegram (first) tab
        tg_pattern = rf"selectedPk:\s*{re.escape(str(self.tg_proj.pk))}"
        self.assertIsNone(
            re.search(tg_pattern, content),
            f"kb-kgza.11 post re-publish: selectedPk must NOT be seeded to Telegram tab pk ({self.tg_proj.pk}).",
        )
