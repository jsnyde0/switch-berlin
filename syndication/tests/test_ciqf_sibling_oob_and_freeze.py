"""
TDD tests for kb-ciqf: sibling channel OOB re-render + event canonical freeze fix.

BUG A (POST) — version_edit autosave on a shared canonical CV must emit
  hx-swap-oob body fragments for SIBLING channels (not the edited projection).
  The sibling's `#channel-body-wrapper-<pk>` must appear in the response.
  The edited projection's body wrapper must NOT appear (cursor protection).

BUG B (EVENT) — event_hub_edit autosave must emit OOB body fragments for
  all listing projections that share the canonical CV (track-live channels).
  AND: after an event-master edit (event_hub_edit POST), the canonical CV
  body must remain NULL (track-live preserved, not frozen).

Regression lock: a detached/customized channel must NOT be overwritten by
  a master edit (canonical body stays NULL → detached channel renders its
  own body).

Assertions on response.content (NOT response.context — hollow per memory
django-view-test-context-vs-content-hollow).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import render_projection
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


def _make_event(profile, title, slug, description="Test event description"):
    event = Event.objects.create(
        title=title,
        slug=slug,
        start=timezone.now() + timezone.timedelta(days=7),
        description=description,
    )
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_connection(profile, platform, destination_id="own-page", kinds=None):
    if kinds is None:
        kinds = ["listing"]
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds,
        enabled=True,
    )


def _make_canonical_cv_for_post(post, body=None):
    cv, _ = ContentVersion.objects.get_or_create(
        post=post,
        name="canonical",
        defaults={
            "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
            "body": body,
        },
    )
    return cv


def _make_canonical_cv_for_event(event):
    """Event canonical starts with body=NULL (track-live semantics)."""
    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={
            "provenance": ContentVersion.Provenance.RULE_TEMPLATE,
        },
    )
    return cv


def _make_projection(conn, event, cv, kind="listing", source_event=None, source_post=None):
    if kind == "listing":
        return PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=source_event or event,
            content_version=cv,
        )
    else:
        return PlatformProjection.objects.create(
            connection=conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=source_post,
            content_version=cv,
        )


# ---------------------------------------------------------------------------
# BUG A (POST) — version_edit OOB: sibling body wrappers emitted, edited one skipped
# ---------------------------------------------------------------------------


class VersionEditSiblingBodyOOBTest(TestCase):
    """
    When the POST master copy tab fires version_edit (version-edit endpoint),
    the response must include hx-swap-oob body wrapper fragments for EVERY
    sibling projection sharing the canonical CV.

    The master copy form itself has no associated projection, so all sharing
    projections should get OOB body updates.

    Assertions on response.content (hx-swap-oob="true" + channel-body-wrapper-<pk>).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="sibling_oob_user", email="sibling_oob@test.com", password="pw")
        self.profile = _make_profile("Sibling OOB Org", "sibling-oob-org", user=self.user)
        self.event = _make_event(self.profile, "Sibling OOB Event", "sibling-oob-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Sibling OOB Post",
            body="original body for sibling test",
        )
        # Two promotion channels both sharing the canonical CV
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-sibling-oob", kinds=["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-sibling-oob", kinds=["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical post body")
        self.tg_proj = _make_projection(
            self.conn_telegram,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.fl_proj = _make_projection(
            self.conn_fetlife,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.client.force_login(self.user)

    def test_version_edit_emits_sibling_body_wrapper_oob_for_telegram(self):
        """
        After POST to version-edit (canonical CV), the response must contain
        a channel-body-wrapper OOB fragment for the Telegram projection.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "updated master body"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.tg_proj.pk}"',
            content,
            f"version_edit OOB response must contain channel-body-wrapper-{self.tg_proj.pk} "
            "so the Telegram sibling body updates without a reload.",
        )

    def test_version_edit_emits_sibling_body_wrapper_oob_for_fetlife(self):
        """
        After POST to version-edit (canonical CV), the response must contain
        a channel-body-wrapper OOB fragment for the FetLife projection.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "updated master body"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.fl_proj.pk}"',
            content,
            f"version_edit OOB response must contain channel-body-wrapper-{self.fl_proj.pk} "
            "so the FetLife sibling body updates without a reload.",
        )

    def test_version_edit_sibling_oob_carries_hx_swap_oob_attribute(self):
        """
        The channel-body-wrapper fragments must carry hx-swap-oob="true" so HTMX
        processes them even under hx-swap="none" autosave.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "updated master body"}, HTTP_HX_REQUEST="true")
        content = response.content.decode()

        # Find the channel-body-wrapper element and verify hx-swap-oob is present on it
        wrapper_id_tg = f'id="channel-body-wrapper-{self.tg_proj.pk}"'
        self.assertIn(wrapper_id_tg, content)
        wrapper_idx = content.index(wrapper_id_tg)
        # Look backward for the opening tag
        tag_start = content.rindex("<", 0, wrapper_idx)
        tag_end = content.index(">", wrapper_idx)
        tag_text = content[tag_start : tag_end + 1]
        self.assertIn(
            'hx-swap-oob="true"',
            tag_text,
            f"channel-body-wrapper-{self.tg_proj.pk} must carry hx-swap-oob='true' "
            "so HTMX processes the OOB swap under hx-swap=none autosave.",
        )

    def test_version_edit_sibling_oob_contains_updated_body_text(self):
        """
        The OOB body wrapper for each sibling must contain the updated body text
        so the textarea content reflects the new canonical body.
        """
        url = reverse("syndication:version-edit", kwargs={"pk": self.canonical_cv.pk})
        response = self.client.post(url, {"body": "UPDATED MASTER BODY TEXT"}, HTTP_HX_REQUEST="true")
        content = response.content.decode()

        self.assertIn(
            "UPDATED MASTER BODY TEXT",
            content,
            "OOB sibling body wrapper must contain the updated body text so the textarea renders the new content.",
        )


# ---------------------------------------------------------------------------
# BUG A (POST) — projection_detach_and_edit: sibling body wrappers emitted,
#               edited projection NOT emitted (cursor protection)
# ---------------------------------------------------------------------------


class DetachAndEditSiblingBodyOOBTest(TestCase):
    """
    After projection_detach_and_edit, the STILL-CANONICAL siblings must get
    OOB body wrapper fragments (their canonical body is unchanged — still renders
    from the canonical), and the edited projection must NOT get an OOB body
    wrapper (cursor protection: don't clobber the active textarea).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="detach_sibling_oob_user",
            email="detach_sibling_oob@test.com",
            password="pw",
        )
        self.profile = _make_profile("Detach Sibling OOB Org", "detach-sibling-oob-org", user=self.user)
        self.event = _make_event(self.profile, "Detach Sibling OOB Event", "detach-sibling-oob-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Detach Sibling OOB Post",
            body="original body for detach sibling test",
        )
        # Three promotion channels all sharing the canonical CV
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-detach-sibling-oob", kinds=["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-detach-sibling-oob", kinds=["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical for detach test")
        self.tg_proj = _make_projection(
            self.conn_telegram,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.fl_proj = _make_projection(
            self.conn_fetlife,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.client.force_login(self.user)

    def test_detach_edit_sibling_gets_body_oob_fragment(self):
        """
        When FetLife is the edited projection (detach-and-edit), Telegram (sibling still
        on canonical) must receive an OOB body wrapper fragment.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, {"body": "FL custom body"}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.tg_proj.pk}"',
            content,
            f"After FetLife detach-and-edit, the Telegram sibling (still on canonical) "
            f"must get OOB body wrapper channel-body-wrapper-{self.tg_proj.pk}.",
        )

    def test_detach_edit_edited_projection_NOT_in_sibling_oob(self):
        """
        The edited projection (FetLife) must NOT receive an OOB body wrapper —
        that would clobber the active textarea the user is typing in.

        The FetLife channel-body-wrapper must NOT appear as an OOB element
        in the response from FetLife's own form submit.
        """
        url = reverse("syndication:projection-detach-and-edit", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, {"body": "FL custom body"}, HTTP_HX_REQUEST="true")
        content = response.content.decode()

        # Sentinel against a tautological pass (kb-ciqf adversarial-review Finding 6):
        # the negative assertion below is meaningless if the response emitted no OOB at
        # all. Require the Telegram sibling OOB to be present AND an hx-swap-oob marker,
        # so "the edited projection is absent" can only pass because it was SKIPPED, not
        # because the whole response was empty.
        self.assertIn(
            f'id="channel-body-wrapper-{self.tg_proj.pk}"',
            content,
            "Sentinel: Telegram sibling OOB must be present so the skip assertion is meaningful.",
        )
        self.assertIn(
            'hx-swap-oob="true"',
            content,
            "Sentinel: response must carry at least one OOB fragment, else the skip check is vacuous.",
        )

        # The edited projection's wrapper must NOT appear with hx-swap-oob
        fl_wrapper_id = f'id="channel-body-wrapper-{self.fl_proj.pk}"'
        if fl_wrapper_id in content:
            # If it appears, it must NOT have hx-swap-oob
            wrapper_idx = content.index(fl_wrapper_id)
            tag_start = content.rindex("<", 0, wrapper_idx)
            tag_end = content.index(">", wrapper_idx)
            tag_text = content[tag_start : tag_end + 1]
            self.assertNotIn(
                'hx-swap-oob="true"',
                tag_text,
                f"The edited projection (fl_proj pk={self.fl_proj.pk}) must NOT have "
                "channel-body-wrapper with hx-swap-oob='true' — that would clobber the "
                "active textarea the user is typing in.",
            )


# ---------------------------------------------------------------------------
# BUG B (EVENT) — event_hub_edit OOB: listing projections get body wrappers
# ---------------------------------------------------------------------------


class EventHubEditSiblingBodyOOBTest(TestCase):
    """
    After event_hub_edit POST (editing the event master via Switch listing form),
    all listing projections that share the canonical CV must receive OOB body
    wrapper fragments so their displayed content updates without a reload.

    This covers FetLife/Telegram listing channels that are track-live
    (canonical body = NULL, recomposed from event fields).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="event_hub_oob_user",
            email="event_hub_oob@test.com",
            password="pw",
        )
        self.profile = _make_profile("Event Hub OOB Org", "event-hub-oob-org", user=self.user)
        self.event = _make_event(
            self.profile,
            "Event Hub OOB Event",
            "event-hub-oob-event",
            description="Initial description",
        )
        # Two listing channels sharing the canonical CV (track-live)
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-event-hub-oob", kinds=["listing"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-event-hub-oob", kinds=["listing"])
        self.canonical_cv = _make_canonical_cv_for_event(self.event)
        self.tg_proj = _make_projection(
            self.conn_telegram,
            self.event,
            self.canonical_cv,
            kind="listing",
            source_event=self.event,
        )
        self.fl_proj = _make_projection(
            self.conn_fetlife,
            self.event,
            self.canonical_cv,
            kind="listing",
            source_event=self.event,
        )
        self.client.force_login(self.user)

    def _post_event_edit(self, **extra_fields):
        """POST to event-edit (HTMX) with minimal required fields."""
        url = reverse("syndication:event-edit", kwargs={"pk": self.event.pk})
        data = {
            "title": self.event.title,
            "slug": self.event.slug,
            "start": self.event.start.strftime("%Y-%m-%d %H:%M:%S"),
            "description": "Updated description via master edit",
        }
        data.update(extra_fields)
        return self.client.post(url, data, HTTP_HX_REQUEST="true")

    def test_event_hub_edit_emits_telegram_body_wrapper_oob(self):
        """
        After event_hub_edit POST, the Telegram listing projection must get
        an OOB body wrapper fragment so its displayed content updates live.
        """
        response = self._post_event_edit()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.tg_proj.pk}"',
            content,
            f"event_hub_edit OOB response must contain channel-body-wrapper-{self.tg_proj.pk} "
            "so the Telegram listing body updates after an event-master edit.",
        )

    def test_event_hub_edit_emits_fetlife_body_wrapper_oob(self):
        """
        After event_hub_edit POST, the FetLife listing projection must get
        an OOB body wrapper fragment.
        """
        response = self._post_event_edit()
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.fl_proj.pk}"',
            content,
            f"event_hub_edit OOB response must contain channel-body-wrapper-{self.fl_proj.pk} "
            "so the FetLife listing body updates after an event-master edit.",
        )

    def test_event_hub_edit_body_oob_carries_hx_swap_oob(self):
        """
        The body wrapper OOB fragments must carry hx-swap-oob="true" so HTMX
        processes them under the hx-swap="none" autosave form.
        """
        response = self._post_event_edit()
        content = response.content.decode()

        wrapper_id = f'id="channel-body-wrapper-{self.tg_proj.pk}"'
        self.assertIn(wrapper_id, content)
        wrapper_idx = content.index(wrapper_id)
        tag_start = content.rindex("<", 0, wrapper_idx)
        tag_end = content.index(">", wrapper_idx)
        tag_text = content[tag_start : tag_end + 1]
        self.assertIn(
            'hx-swap-oob="true"',
            tag_text,
            f"channel-body-wrapper-{self.tg_proj.pk} must carry hx-swap-oob='true'.",
        )


# ---------------------------------------------------------------------------
# BUG B (EVENT) — event canonical stays NULL (track-live) after master edit
# ---------------------------------------------------------------------------


class EventCanonicalFreezePreventionTest(TestCase):
    """
    After event_hub_edit POST (event-master edit), the canonical CV body
    must remain NULL so track-live channels keep recomposing from event fields.

    BUG: some path writes a non-null body onto the canonical CV (provenance=manual),
    permanently freezing recomposition.

    FIX: the event-master edit path must never write body to the canonical CV.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="event_freeze_user",
            email="event_freeze@test.com",
            password="pw",
        )
        self.profile = _make_profile("Event Freeze Org", "event-freeze-org", user=self.user)
        self.event = _make_event(
            self.profile,
            "Event Freeze Test",
            "event-freeze-test",
            description="Initial description",
        )
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-event-freeze", kinds=["listing"])
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-event-freeze", kinds=["listing"])
        self.canonical_cv = _make_canonical_cv_for_event(self.event)
        self.fl_proj = _make_projection(
            self.conn_fetlife,
            self.event,
            self.canonical_cv,
            kind="listing",
            source_event=self.event,
        )
        self.tg_proj = _make_projection(
            self.conn_telegram,
            self.event,
            self.canonical_cv,
            kind="listing",
            source_event=self.event,
        )
        self.client.force_login(self.user)

    def _post_event_edit(self, description="Updated description"):
        url = reverse("syndication:event-edit", kwargs={"pk": self.event.pk})
        data = {
            "title": self.event.title,
            "slug": self.event.slug,
            "start": self.event.start.strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
        }
        return self.client.post(url, data, HTTP_HX_REQUEST="true")

    def test_event_hub_edit_canonical_body_stays_null(self):
        """
        After event_hub_edit, the canonical CV body must remain NULL.
        Any non-null value would freeze recomposition (BUG B).
        """
        self._post_event_edit()
        self.canonical_cv.refresh_from_db()
        self.assertIsNone(
            self.canonical_cv.body,
            "After event_hub_edit, canonical CV body must remain NULL "
            "(track-live: recompose from event fields on render). "
            "A non-null body freezes recomposition — this is the event canonical freeze bug.",
        )

    def test_event_hub_edit_second_master_edit_propagates_to_track_live_channel(self):
        """
        After TWO event-master edits, a track-live channel must render
        the SECOND edit's content (not frozen at the first edit).

        This verifies that track-live channels keep following further master edits
        (the freeze would lock them at snapshot 1, ignoring snapshot 2).
        """
        # First master edit
        self._post_event_edit(description="First master edit description")
        self.event.refresh_from_db()

        # Second master edit
        self._post_event_edit(description="Second master edit description UNIQUE_MARKER")
        self.event.refresh_from_db()

        # Render the canonical track-live channel — must show the SECOND edit content
        self.tg_proj.refresh_from_db()
        rendered_body = render_projection(self.tg_proj)
        self.assertIn(
            "UNIQUE_MARKER",
            rendered_body,
            "After two event-master edits, a track-live channel must render "
            "the second edit's content (UNIQUE_MARKER). "
            "The freeze bug would lock the render at the first-edit snapshot.",
        )

    def test_detached_channel_not_overwritten_by_event_master_edit(self):
        """
        A deliberately detached/customized channel must NOT be overwritten
        by an event-master edit (regression lock for ADR-016 D2).

        The FetLife channel is customized first (mints own CV, own body).
        Then the event master is edited. The FetLife channel must still
        render its own custom body, not the new event description.
        """
        from syndication.services import detach_and_edit

        # Customize FetLife channel: detach to own CV with custom body
        _custom_cv, _updated_proj = detach_and_edit(
            user=self.user,
            projection=self.fl_proj,
            body="CUSTOM_FETLIFE_BODY_NOT_TO_BE_OVERWRITTEN",
        )
        self.fl_proj.refresh_from_db()

        # Now edit the event master
        self._post_event_edit(description="Master edit that must not overwrite custom channel")

        # The FetLife channel must still render its custom body
        self.fl_proj.refresh_from_db()
        rendered_body = render_projection(self.fl_proj)
        self.assertIn(
            "CUSTOM_FETLIFE_BODY_NOT_TO_BE_OVERWRITTEN",
            rendered_body,
            "After event-master edit, the customized FetLife channel must still "
            "render its own custom body — NOT the event's new description. "
            "ADR-016 D2: deliberate customization must survive master edits.",
        )
        self.assertNotIn(
            "Master edit that must not overwrite custom channel",
            rendered_body,
            "The customized FetLife channel must NOT contain the event's updated "
            "description — it was deliberately detached from track-live.",
        )


# ---------------------------------------------------------------------------
# Stable wrapper ID presence in rendered fragment
# ---------------------------------------------------------------------------


class ChannelBodyWrapperIDPresenceTest(TestCase):
    """
    The event_syndication and post_syndication fragments must render
    channel-body-wrapper-<pk> stable wrapper IDs for each channel editor,
    so OOB swaps can target them.

    These IDs must be present even for channels in the non-active Alpine tab
    (x-cloak hides them visually but they're in the DOM).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="wrapper_id_user",
            email="wrapper_id@test.com",
            password="pw",
        )
        self.profile = _make_profile("Wrapper ID Org", "wrapper-id-org", user=self.user)
        self.event = _make_event(self.profile, "Wrapper ID Event", "wrapper-id-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Wrapper ID Post",
            body="Wrapper body",
        )
        self.conn_telegram = _make_connection(self.profile, "telegram", "tg-wrapper-id", kinds=["promotion"])
        self.conn_fetlife = _make_connection(self.profile, "fetlife", "fl-wrapper-id", kinds=["promotion"])
        self.canonical_cv = _make_canonical_cv_for_post(self.post, body="canonical wrapper body")
        self.tg_proj = _make_projection(
            self.conn_telegram,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.fl_proj = _make_projection(
            self.conn_fetlife,
            self.event,
            self.canonical_cv,
            kind="promotion",
            source_post=self.post,
        )
        self.client.force_login(self.user)

    def test_post_syndication_fragment_has_channel_body_wrapper_ids(self):
        """
        The rendered post_syndication fragment must contain channel-body-wrapper-<pk>
        for each projection (both Telegram and FetLife).
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            f'id="channel-body-wrapper-{self.tg_proj.pk}"',
            content,
            f"post_syndication fragment must contain channel-body-wrapper-{self.tg_proj.pk} "
            "for the Telegram projection.",
        )
        self.assertIn(
            f'id="channel-body-wrapper-{self.fl_proj.pk}"',
            content,
            f"post_syndication fragment must contain channel-body-wrapper-{self.fl_proj.pk} "
            "for the FetLife projection.",
        )
