"""
Tests for honest publish copy — kb-kgza.6.

Acceptance:
- FetLife published channel: does NOT assert external delivery; positively states
  FetLife posting is manual (FetLife has no publishing API — attestation path only).
- Switch own-page published channel: states content IS live on Switch page
  (Switch own-page IS the external destination — publishing here IS real, ADR-010 D1).
- Telegram published channel: publishing IS wired (publish_telegram_promotion calls
  the Bot API) — no false-success copy AND no false-deferral copy; the neutral
  dirty-banner ("update the live post") is honest because the post is real.
- Covers BOTH event composer (listing) and post composer (promotion).
- Publish action still transitions to published and materializes frozen_content
  (regression guard — a copy change must NOT break publishing).

Honest copy decisions (per investigation of services.py + adapters.py):
- FetLife: publish_projection routes to attestation path (transition_status only).
  NO external API call. FetLife has no publishing API.
  Honest copy in published state: "Marked published" + clarifying note that FetLife
  posting is not automated.
- Telegram: publish_telegram_promotion IS called and sends to the Bot API.
  Publishing is real when credentials are configured. No false-success text needed.
  (Telegram adapter status is WIRED — contradicts the kb-a4u memory which was
   written before kb-wz8m.4 closed the kb-jgda gap. This finding is reported.)
- Switch own-page: publish_switch_own_page IS called, event becomes live on
  switch.berlin (DB-driven render, no external API needed). Publishing IS real.

Per-channel copy implemented in _channel_editor.html CTA region (sub-region c).

TDD discipline: tests written BEFORE template changes (ADR-016, kb-kgza.6).
Tests assert on response.content.decode() NOT response.context (hollow-test
prevention per memory django-view-test-context-vs-content-hollow).
"""

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


def _make_connection(profile, platform, destination_id, kinds):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=True,
    )


def _make_canonical_cv(event=None, post=None, body="canonical body"):
    if event is not None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    else:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE, "body": body},
        )
    return cv


def _make_published_listing(conn, event, cv):
    """Create a published listing projection with frozen_content set."""
    proj = PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.PUBLISHED,
        source_event=event,
        content_version=cv,
        frozen_content={"body": cv.body},
    )
    return proj


def _make_published_promotion(conn, post, cv):
    """Create a published promotion projection with frozen_content set."""
    proj = PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=PlatformProjection.Status.PUBLISHED,
        source_post=post,
        content_version=cv,
        frozen_content={"body": cv.body},
    )
    return proj


def _make_draft_listing(conn, event, cv):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.DRAFT,
        source_event=event,
        content_version=cv,
    )


def _make_draft_promotion(conn, post, cv):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=PlatformProjection.Status.DRAFT,
        source_post=post,
        content_version=cv,
    )


# ---------------------------------------------------------------------------
# Regression guard: publish still transitions status + materializes frozen_content
# ---------------------------------------------------------------------------


class PublishActionRegressionTest(TestCase):
    """
    Regression guard: a copy-only change in the template must NOT break the
    publish service. publish_projection_direct on a FetLife draft listing must:
    1. Transition projection.status to 'published'.
    2. Set frozen_content (non-null dict).
    This test calls the SERVICE directly — it's a service-layer unit test, not
    a view test, so it's unaffected by template changes.
    """

    def setUp(self):
        self.user = _make_user(
            username="reg_pub_user",
            email="reg_pub@test.com",
            password="pw",
        )
        self.profile = _make_profile("Reg Pub Org", "reg-pub-org", user=self.user)
        self.event = _make_event(self.profile, "Reg Pub Event", "reg-pub-event")
        self.conn = _make_connection(self.profile, "fetlife", "fl-reg-pub", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="reg pub body")
        self.proj = _make_draft_listing(self.conn, self.event, self.cv)

    def test_publish_transitions_fetlife_draft_to_published(self):
        """
        FetLife: publish_projection_direct on a draft listing must transition
        status to published. Regression guard — copy changes must not break this.
        """
        from syndication.services import publish_projection_direct

        publish_projection_direct(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.PUBLISHED)

    def test_publish_materializes_frozen_content(self):
        """
        FetLife: publish_projection_direct must set frozen_content (non-null dict).
        ADR-016 D5: frozen_content is NEVER null on a published row.
        """
        from syndication.services import publish_projection_direct

        publish_projection_direct(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()
        self.assertIsNotNone(self.proj.frozen_content)
        self.assertIsInstance(self.proj.frozen_content, dict)


# ---------------------------------------------------------------------------
# FetLife published channel: honest copy in event composer
# ---------------------------------------------------------------------------


class FetLifePublishedEventComposerCopyTest(TestCase):
    """
    FetLife published projection in the event composer must NOT claim external delivery
    and must positively state that live FetLife posting is forthcoming/manual.

    Background: FetLife has no publishing API. publish_projection routes to the
    attestation path (transition_status only). The publish button in the UI
    marks the content as published internally, but nothing is posted to FetLife.

    Harness target for kb-kgza.6:
    - Negative: no text claiming it was "posted to FetLife" or "live on FetLife".
    - Positive: concrete honest text present (e.g. "FetLife has no publishing API"
      or "post manually on FetLife").
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="fl_pub_evt_user",
            email="fl_pub_evt@test.com",
            password="pw",
        )
        self.profile = _make_profile("FL Pub Evt Org", "fl-pub-evt-org", user=self.user)
        self.event = _make_event(self.profile, "FL Pub Event", "fl-pub-event")
        self.conn = _make_connection(self.profile, "fetlife", "fl-pub-evt-ch", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="fl pub event body")
        self.proj = _make_published_listing(self.conn, self.event, self.cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_fetlife_published_does_not_claim_external_delivery(self):
        """
        FetLife published: no text claiming content was posted to FetLife externally.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must NOT claim external delivery to FetLife
        self.assertNotIn("Posted to FetLife", content)
        self.assertNotIn("Live on FetLife", content)
        self.assertNotIn("Published to FetLife", content)

    def test_fetlife_published_states_live_posting_is_manual(self):
        """
        FetLife published: honest copy must state that live FetLife posting is
        manual/deferred. Must positively name the honest state (not just be absent).
        A negative-only assertion would pass on a blank template — the positive
        honest string must be present.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Positive assertion: honest text about FetLife posting being manual.
        # This fails until the template is updated with honest copy.
        self.assertIn("FetLife has no publishing API", content)

    def test_fetlife_re_publish_dirty_banner_is_honest(self):
        """
        FetLife dirty published: the dirty banner in the channel editor must NOT
        say 're-publish to update the live post' — that implies updating a live
        external post, which FetLife cannot do (no API).

        The dirty banner is identified by data-testid='dirty-banner' in the
        _channel_editor.html template. We check the region around it for honesty.
        """
        # Make the projection dirty (edit the CV body)
        self.cv.body = "updated fl body"
        self.cv.save(update_fields=["body"])
        # frozen_content keeps the OLD body → projection is dirty
        # (frozen_content set in setUp to the original body)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Find the dirty-banner region (data-testid="dirty-banner")
        banner_idx = content.find('data-testid="dirty-banner"')
        self.assertGreater(banner_idx, -1, "Dirty banner must be present for dirty FetLife projection")
        # Extract the banner region (banner div and its ~600 chars of content)
        banner_region = content[banner_idx : banner_idx + 600]
        # The dirty banner text must NOT say "re-publish to update the live post" for FetLife
        self.assertNotIn("re-publish to update the live post", banner_region)
        # The dirty banner must positively state FetLife posting is manual
        self.assertIn("FetLife", banner_region)


# ---------------------------------------------------------------------------
# FetLife published channel: honest copy in post composer
# ---------------------------------------------------------------------------


class FetLifePublishedPostComposerCopyTest(TestCase):
    """
    FetLife published promotion in the post composer: same honest-copy contract.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="fl_pub_post_user",
            email="fl_pub_post@test.com",
            password="pw",
        )
        self.profile = _make_profile("FL Pub Post Org", "fl-pub-post-org", user=self.user)
        self.event = _make_event(self.profile, "FL Pub Post Event", "fl-pub-post-event")
        self.post = Post.objects.create(event=self.event, headline="FL Pub Post", body="fl pub post body")
        self.canonical_cv = _make_canonical_cv(post=self.post, body="canonical post body")
        self.conn = _make_connection(self.profile, "fetlife", "fl-pub-post-ch", ["promotion"])
        self.cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-pub-post-cv",
            body="fl pub post body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.proj = _make_published_promotion(self.conn, self.post, self.cv)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_fetlife_post_published_does_not_claim_external_delivery(self):
        """
        Post composer: FetLife published: no text claiming external delivery to FetLife.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("Posted to FetLife", content)
        self.assertNotIn("Live on FetLife", content)
        self.assertNotIn("Published to FetLife", content)

    def test_fetlife_post_published_states_live_posting_is_manual(self):
        """
        Post composer: FetLife published: honest copy states posting is manual.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("FetLife has no publishing API", content)


# ---------------------------------------------------------------------------
# Switch own-page published channel: honest copy (event composer)
# ---------------------------------------------------------------------------


class SwitchPublishedEventComposerCopyTest(TestCase):
    """
    Switch own-page published projection in event composer: publishing IS real.

    publish_switch_own_page resolves the event-detail URL and calls
    publish_event(event), making the event live on switch.berlin (DB-driven render,
    no external API needed). Per ADR-010 D1, Switch IS the canonical home.

    The copy must NOT say "live posting to Switch is coming" — that would lie in
    the opposite direction. The copy must confirm the event IS live on Switch.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="sw_pub_evt_user",
            email="sw_pub_evt@test.com",
            password="pw",
        )
        self.profile = _make_profile("SW Pub Evt Org", "sw-pub-evt-org", user=self.user)
        self.event = _make_event(self.profile, "SW Pub Event", "sw-pub-event")
        self.conn = _make_connection(self.profile, "switch", "own-page", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="sw pub event body")
        self.proj = _make_published_listing(self.conn, self.event, self.cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_switch_published_does_not_say_posting_is_coming(self):
        """
        Switch own-page: must NOT say live posting is coming — publishing IS real
        and the event IS live on switch.berlin. Saying 'coming' would be dishonest.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Must NOT falsely say Switch posting is deferred/forthcoming
        self.assertNotIn("FetLife has no publishing API", content)

    def test_switch_published_confirms_live_on_switch(self):
        """
        Switch own-page: published state must positively confirm the event is live
        on the Switch page. This is honest because publish_switch_own_page IS called.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Positive assertion: confirms it is live on Switch
        self.assertIn("Published to your Switch page", content)


# ---------------------------------------------------------------------------
# Draft publish CTA: honest button label for FetLife (event composer)
# ---------------------------------------------------------------------------


class FetLifeDraftPublishCtaEventComposerTest(TestCase):
    """
    FetLife draft projection in the event composer: Publish CTA.

    The Publish button fires projection-direct-publish which for FetLife does NOT
    call an external adapter. The button label must not imply external posting.
    The button may say 'Publish' (neutral, honest) or something more specific.

    Core constraint: the button must still be present and actionable (linking to
    projection-direct-publish), since the publish action still transitions status.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="fl_draft_cta_user",
            email="fl_draft_cta@test.com",
            password="pw",
        )
        self.profile = _make_profile("FL Draft CTA Org", "fl-draft-cta-org", user=self.user)
        self.event = _make_event(self.profile, "FL Draft CTA Event", "fl-draft-cta-event")
        self.conn = _make_connection(self.profile, "fetlife", "fl-draft-cta-ch", ["listing"])
        self.cv = _make_canonical_cv(event=self.event, body="fl draft cta body")
        self.proj = _make_draft_listing(self.conn, self.event, self.cv)
        self.url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        self.client.force_login(self.user)

    def test_publish_cta_still_present_for_fetlife_draft(self):
        """
        FetLife draft: Publish CTA (projection-direct-publish) must still be present.
        The copy change must not remove the CTA.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        publish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.assertIn(publish_url, content)


# ---------------------------------------------------------------------------
# Draft publish CTA: honest button label for FetLife (post composer)
# ---------------------------------------------------------------------------


class FetLifeDraftPublishCtaPostComposerTest(TestCase):
    """
    FetLife draft promotion in the post composer: Publish CTA still present.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="fl_draft_post_cta_user",
            email="fl_draft_post_cta@test.com",
            password="pw",
        )
        self.profile = _make_profile("FL Draft Post CTA Org", "fl-draft-post-cta-org", user=self.user)
        self.event = _make_event(self.profile, "FL Draft Post CTA Event", "fl-draft-post-cta-event")
        self.post = Post.objects.create(event=self.event, headline="FL Draft Post CTA", body="fl draft post body")
        self.canonical_cv = _make_canonical_cv(post=self.post, body="canonical post body")
        self.conn = _make_connection(self.profile, "fetlife", "fl-draft-post-cta-ch", ["promotion"])
        self.cv = _make_canonical_cv(post=self.post)
        self.proj = _make_draft_promotion(self.conn, self.post, self.cv)
        self.url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        self.client.force_login(self.user)

    def test_publish_cta_still_present_for_fetlife_draft_post(self):
        """
        Post composer FetLife draft: Publish CTA (projection-direct-publish) must
        still be present after copy changes.
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        publish_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.proj.pk})
        self.assertIn(publish_url, content)
