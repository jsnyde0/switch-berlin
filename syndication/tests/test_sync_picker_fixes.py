"""
TDD tests for kb-kgza.4 — Two fixes in _sync_picker.html:

Bug 1: POST copy-from with selected_pk=<non-canonical pk> → rendered fragment
       initializes Alpine selectedPk to THAT pk (stays on the current tab).
       Root cause: the copy-from form lacked <input name="selected_pk" :value="selectedPk">.

Bug 2 (presence): The sync-source picker renders "Master copy" as the FIRST option.

Bug 2 (behavior): POST the Master-copy selection → reset-to-canonical executed →
       DB state: projection.content_version == canonical CV AND sync_source is NULL.

Coverage: both event and post composers (shared _sync_picker.html include).

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
# Shared test helpers
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


def _assert_selected_pk_seeded(test_case, content, expected_pk, msg_prefix=""):
    """Assert that the Alpine x-data selectedPk is seeded to expected_pk."""
    pattern = rf"selectedPk:\s*{re.escape(str(expected_pk))}"
    match = re.search(pattern, content)
    test_case.assertIsNotNone(
        match,
        f"{msg_prefix}Expected selectedPk seeded to {expected_pk!r} "
        f"(pattern {pattern!r} not found). "
        f"Content excerpt: {content[:800]!r}",
    )


# ---------------------------------------------------------------------------
# Bug 1: copy-from Apply stays on current tab
# ---------------------------------------------------------------------------


class CopyFromSelectedPkEventComposerTest(TestCase):
    """
    kb-kgza.4 Bug 1: POST to version-copy-from with selected_pk=<non-canonical pk>
    must render a fragment that seeds Alpine selectedPk to THAT pk.

    Before the fix: copy-from forms lack the hidden selected_pk input,
    so version_copy_from returns a fragment with selected_pk=None and Alpine
    falls back to the first/source tab.

    After the fix: the hidden input is present, version_copy_from reads it,
    and the fragment inits selectedPk to the posted pk.

    Event composer path: LISTING projections.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cfrm_ev_user", email="cfrm_ev@test.com", password="pw")
        self.profile = _make_profile("CopyFrom Event Org", "copyfrom-ev-org", user=self.user)
        self.event = _make_event(self.profile, "CopyFrom Event Test", "copyfrom-ev-test")

        # Canonical CV for the event
        self.canonical_cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Switch listing (source/first tab)
        self.sw_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
            enabled=True,
        )
        self.sw_proj = PlatformProjection.objects.create(
            connection=self.sw_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.canonical_cv,
        )

        # FetLife listing (second tab — the "current tab" we want to stay on)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-copyfrom-ev",
            kinds=["listing"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-copyfrom-ev-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_copy_from_form_has_selected_pk_input_event(self):
        """
        RED gate (template assertion): GET event_syndication fragment →
        the version-copy-from form for the FetLife projection must contain
        name="selected_pk" so browsers send it on submit.

        Before the fix: the copy-from forms lack the hidden input.
        After the fix: the hidden input is present.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        copy_from_url = reverse("syndication:version-copy-from", kwargs={"pk": self.fl_proj.pk})
        self.assertIn(
            copy_from_url,
            content,
            f"Expected copy-from action URL {copy_from_url!r} in fragment content.",
        )

        # Find the form block containing this action URL
        url_pos = content.find(copy_from_url)
        form_start = content.rfind("<form", 0, url_pos)
        self.assertNotEqual(form_start, -1, "Could not find <form before copy-from action URL.")
        form_end = content.find("</form>", url_pos)
        self.assertNotEqual(form_end, -1, "Could not find </form> after copy-from action URL.")
        form_block = content[form_start : form_end + len("</form>")]

        self.assertIn(
            'name="selected_pk"',
            form_block,
            f"Hidden input name='selected_pk' not found in the copy-from form "
            f"(action={copy_from_url!r}). The form must include "
            f'<input type="hidden" name="selected_pk" :value="selectedPk"> '
            f"so browsers thread the selected tab on submit. "
            f"Form block: {form_block[:400]!r}",
        )

    def test_copy_from_with_selected_pk_seeds_that_tab_event(self):
        """
        Server-contract (content assertion): POST to version-copy-from with
        selected_pk=<fl_proj.pk> → event_syndication fragment seeds
        Alpine selectedPk to fl_proj.pk (stays on the FetLife tab).

        Before the fix: selected_pk not sent (missing hidden input) →
        fragment seeds selectedPk to None → Alpine falls back to first tab.
        After the fix: fragment seeds selectedPk to fl_proj.pk.
        """
        url = reverse("syndication:version-copy-from", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={
                "source_projection_pk": str(self.sw_proj.pk),
                "selected_pk": str(self.fl_proj.pk),
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=(
                f"kb-kgza.4 Bug 1 (event): after copy-from Apply, selectedPk must be "
                f"seeded to {self.fl_proj.pk} (the FetLife tab), not reset to first. "
                f"The copy-from form was missing the hidden selected_pk input. "
            ),
        )


class CopyFromSelectedPkPostComposerTest(TestCase):
    """
    kb-kgza.4 Bug 1: Same test for the POST composer (promotion projections).

    POST to version-copy-from with selected_pk=<non-first pk> → fragment seeds
    Alpine selectedPk to THAT pk.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="cfrm_ps_user", email="cfrm_ps@test.com", password="pw")
        self.profile = _make_profile("CopyFrom Post Org", "copyfrom-ps-org", user=self.user)
        self.event = _make_event(self.profile, "CopyFrom Post Event", "copyfrom-ps-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="CopyFrom Post",
            body="Source body",
        )

        # Canonical CV for the post
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Telegram promotion (source/first projection)
        self.tg_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-copyfrom-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife promotion (second projection — the "current tab" we want to stay on)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-copyfrom-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-copyfrom-ps-cv",
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

    def test_copy_from_form_has_selected_pk_input_post(self):
        """
        RED gate (template assertion): GET post_syndication fragment →
        the version-copy-from form for the FetLife projection must contain
        name="selected_pk".
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        copy_from_url = reverse("syndication:version-copy-from", kwargs={"pk": self.fl_proj.pk})
        self.assertIn(
            copy_from_url,
            content,
            f"Expected copy-from action URL {copy_from_url!r} in post fragment content.",
        )

        url_pos = content.find(copy_from_url)
        form_start = content.rfind("<form", 0, url_pos)
        self.assertNotEqual(form_start, -1, "Could not find <form before copy-from action URL.")
        form_end = content.find("</form>", url_pos)
        self.assertNotEqual(form_end, -1, "Could not find </form> after copy-from action URL.")
        form_block = content[form_start : form_end + len("</form>")]

        self.assertIn(
            'name="selected_pk"',
            form_block,
            f"Hidden input name='selected_pk' not found in the copy-from form "
            f"(action={copy_from_url!r}). "
            f"Form block: {form_block[:400]!r}",
        )

    def test_copy_from_with_selected_pk_seeds_that_tab_post(self):
        """
        Server-contract: POST to version-copy-from with selected_pk=<fl_proj.pk>
        → post_syndication fragment seeds Alpine selectedPk to fl_proj.pk.
        """
        url = reverse("syndication:version-copy-from", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(
            url,
            data={
                "source_projection_pk": str(self.tg_proj.pk),
                "selected_pk": str(self.fl_proj.pk),
            },
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        _assert_selected_pk_seeded(
            self,
            content,
            self.fl_proj.pk,
            msg_prefix=(
                f"kb-kgza.4 Bug 1 (post): after copy-from Apply, selectedPk must be "
                f"seeded to {self.fl_proj.pk} (the FetLife tab). "
            ),
        )


# ---------------------------------------------------------------------------
# Bug 2 (presence): "Master copy" appears as first option in sync picker
# ---------------------------------------------------------------------------


class MasterCopyOptionPresenceEventTest(TestCase):
    """
    kb-kgza.4 Bug 2 (presence): The sync-source picker for a non-canonical channel
    in event_syndication must render "Master copy" as the FIRST option.

    Before the fix: the picker iterates projection_rows only (promotion projections),
    never offering the canonical ContentVersion.

    After the fix: "Master copy" appears first in the picker for non-master channels.
    The picker must NOT show "Master copy" on the master/source channel itself
    (a channel cannot sync from itself).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="mc_ev_user", email="mc_ev@test.com", password="pw")
        self.profile = _make_profile("Master Copy Event Org", "mc-ev-org", user=self.user)
        self.event = _make_event(self.profile, "Master Copy Event", "mc-ev-test")

        # Canonical CV for the event
        self.canonical_cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Switch listing (master/source — owns canonical CV)
        self.sw_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
            enabled=True,
        )
        self.sw_proj = PlatformProjection.objects.create(
            connection=self.sw_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.canonical_cv,
        )

        # FetLife listing (secondary channel — has its own CV)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-mc-ev",
            kinds=["listing"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-mc-ev-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_master_copy_option_appears_in_event_picker(self):
        """
        GET event_syndication fragment → the sync-source picker for the FetLife
        (non-canonical) channel must contain a "Master copy" option.

        Before the fix: picker only lists projection_rows (other projections),
        never the canonical ContentVersion. "Master copy" absent.
        After the fix: "Master copy" appears as the first option.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Master copy",
            content,
            "The sync-source picker must offer 'Master copy' as a source option "
            "for a non-canonical channel. Before the fix, only projection rows "
            "were listed, and the canonical CV was never offered. "
            f"Content excerpt: {content[:2000]!r}",
        )


class MasterCopyOptionPresencePostTest(TestCase):
    """
    kb-kgza.4 Bug 2 (presence): Same check for the POST composer (promotion projections).

    The sync-source picker in post_syndication must also offer "Master copy" for
    non-master channels.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="mc_ps_user", email="mc_ps@test.com", password="pw")
        self.profile = _make_profile("Master Copy Post Org", "mc-ps-org", user=self.user)
        self.event = _make_event(self.profile, "Master Copy Post Event", "mc-ps-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="Master Copy Post",
            body="Source body",
        )

        # Canonical CV for the post
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Telegram (shares canonical — master)
        self.tg_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-mc-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife (has own CV — secondary channel)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-mc-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-mc-ps-cv",
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

    def test_master_copy_option_appears_in_post_picker(self):
        """
        GET post_syndication fragment → the sync-source picker for the FetLife
        (non-canonical) channel must contain a "Master copy" option.
        """
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Master copy",
            content,
            "The sync-source picker in post_syndication must offer 'Master copy' "
            "as a source option for a non-canonical channel. "
            f"Content excerpt: {content[:2000]!r}",
        )


# ---------------------------------------------------------------------------
# Bug 2 (behavior): Selecting Master copy invokes reset-to-canonical
# ---------------------------------------------------------------------------


class MasterCopySelectionBehaviorEventTest(TestCase):
    """
    kb-kgza.4 Bug 2 (behavior): Selecting "Master copy" in the picker for an
    event channel must POST to reset-to-canonical, resulting in:
    - projection.content_version == canonical CV
    - projection.sync_source is NULL

    This confirms the routing uses the existing reset-to-canonical endpoint,
    NOT version_copy_from with a non-projection pk (which would crash).

    Cycle-safety confirmed: canonical CV has sync_source=NULL, so reset-to-canonical
    passes ADR-016 D2 (sync only from independent sources).
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="mc_bh_ev_user", email="mc_bh_ev@test.com", password="pw")
        self.profile = _make_profile("MC Behavior Event Org", "mc-bh-ev-org", user=self.user)
        self.event = _make_event(self.profile, "MC Behavior Event", "mc-bh-ev-test")

        # Canonical CV for the event
        self.canonical_cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
            body="canonical event body",
        )

        # Switch listing (master — on canonical CV)
        self.sw_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page",
            kinds=["listing"],
            enabled=True,
        )
        self.sw_proj = PlatformProjection.objects.create(
            connection=self.sw_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.canonical_cv,
        )

        # FetLife listing (secondary channel — has its own CV, not canonical)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-mc-bh-ev",
            kinds=["listing"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-mc-bh-ev-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
            body="fetlife custom body",
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_master_copy_selection_resets_to_canonical_event(self):
        """
        POST to the reset-to-canonical endpoint for the FetLife projection
        (as would happen when the user selects "Master copy") → DB state:
        - fl_proj.content_version == canonical_cv (repointed back)
        - fl_proj.sync_source is NULL (state i: sharing canonical)

        This is a behavioral test (DB state), not just a presence test.
        It verifies that the "Master copy" option routes to reset-to-canonical,
        not to version_copy_from (which would crash with a non-projection pk).
        """
        reset_url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(reset_url, data={}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)

        self.fl_proj.refresh_from_db()

        self.assertEqual(
            self.fl_proj.content_version_id,
            self.canonical_cv.pk,
            "After selecting 'Master copy', the projection must point at the canonical CV. "
            f"Expected content_version_id={self.canonical_cv.pk}, "
            f"got {self.fl_proj.content_version_id}.",
        )
        self.assertIsNone(
            self.fl_proj.sync_source,
            "After selecting 'Master copy', sync_source must be NULL (state i: "
            "sharing canonical CV, no sync chain). "
            f"Got sync_source={self.fl_proj.sync_source!r}.",
        )


class MasterCopySelectionBehaviorPostTest(TestCase):
    """
    kb-kgza.4 Bug 2 (behavior): Same behavioral test for the POST composer.

    Selecting "Master copy" in the post_syndication picker → reset-to-canonical →
    DB: projection.content_version == canonical CV AND sync_source is NULL.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="mc_bh_ps_user", email="mc_bh_ps@test.com", password="pw")
        self.profile = _make_profile("MC Behavior Post Org", "mc-bh-ps-org", user=self.user)
        self.event = _make_event(self.profile, "MC Behavior Post Event", "mc-bh-ps-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="MC Behavior Post",
            body="Source body",
        )

        # Canonical CV for the post
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
            body="canonical post body",
        )

        # Telegram (shares canonical — master)
        self.tg_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="tg-mc-bh-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife (has own CV — secondary channel)
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-mc-bh-ps",
            kinds=["promotion"],
            enabled=True,
        )
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-mc-bh-ps-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
            body="fetlife custom body",
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.fl_cv,
        )

        self.client.force_login(self.user)

    def test_master_copy_selection_resets_to_canonical_post(self):
        """
        POST to reset-to-canonical for the FetLife promotion projection
        → DB: fl_proj.content_version == canonical_cv AND sync_source is NULL.

        This is the behavioral test confirming the "Master copy" option routes
        to reset-to-canonical, not version_copy_from.
        """
        reset_url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(reset_url, data={}, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)

        self.fl_proj.refresh_from_db()

        self.assertEqual(
            self.fl_proj.content_version_id,
            self.canonical_cv.pk,
            "After selecting 'Master copy', the post projection must point at the canonical CV. "
            f"Expected content_version_id={self.canonical_cv.pk}, "
            f"got {self.fl_proj.content_version_id}.",
        )
        self.assertIsNone(
            self.fl_proj.sync_source,
            "After selecting 'Master copy', sync_source must be NULL (state i). "
            f"Got sync_source={self.fl_proj.sync_source!r}.",
        )
