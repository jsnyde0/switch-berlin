"""
Tests for kb-shzi.6 — Thread selected_pk through ALL fragment-swapping forms.

Harness target:
  (a) Template assertions: GET fragment → assert form HTML contains
      `name="selected_pk"` (the hidden input that browsers need to send selected_pk).
  (b) Server-contract assertions: POST action with selected_pk=<non-first pk>
      → response.content contains selectedPk:<pk>.

Tests (a) are the RED gate for the TEMPLATE fix (hidden inputs missing from forms).
Tests (b) confirm the server-side plumbing reads and seeds selected_pk correctly
(views already do this; these guard against regression).

Coverage:
  - Inline Switch listing sync bar: Customize (state i), Reset-state-ii, Reset-state-iii
  - Publish/approve/mark-published/direct-publish forms (event + post composers)
  - Batch "Publish all ready" form (event composer)

All assertions on response.content (NOT response.context) per hollow-test memory.
FetLife projections used for publish paths (no real API adapter calls in tests).

Key invariant: event_syndication fragment shows LISTING projections only
(connection.kinds contains "listing"). Use second listing connection for
"non-first tab" in event-fragment tests.
"""

import re

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import transition_status
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


def _make_fetlife_listing_connection(profile, destination_id="fl-listing"):
    """FetLife connection that supports listing (for event fragment's second tab)."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        kinds=["listing"],
        enabled=True,
    )


def _make_fetlife_promotion_connection(profile, destination_id="fl-promo"):
    """FetLife connection that supports promotion (for post fragment tabs)."""
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="fetlife",
        destination_id=destination_id,
        kinds=["promotion"],
        enabled=True,
    )


def _make_telegram_connection(profile, destination_id="tg-test"):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
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


def _make_fetlife_listing_projection(event, connection):
    """Create a listing projection for a FetLife connection on an event."""
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
    Uses a regex that tolerates optional whitespace (djlint reformats inline tags).
    """
    pattern = rf"selectedPk:\s*{re.escape(str(expected_pk))}"
    match = re.search(pattern, content)
    test_case.assertIsNotNone(
        match,
        f"{msg_prefix}Expected selectedPk seeded to {expected_pk!r} "
        f"(pattern {pattern!r} not found). "
        f"Content excerpt: {content[:800]!r}",
    )


def _assert_form_has_selected_pk_input(test_case, content, action_url, msg_prefix=""):
    """
    Assert that the form with the given action URL contains name="selected_pk".

    The hidden input `<input type="hidden" name="selected_pk" :value="selectedPk">`
    must appear in the form so real browsers send selected_pk on submit.

    Strategy: locate the form block that contains action_url, then look for
    name="selected_pk" before the next </form> tag. This scopes the check to
    the specific form, not any other form in the fragment.
    """
    test_case.assertIn(
        action_url,
        content,
        f"{msg_prefix}Form action URL {action_url!r} not found in content.",
    )

    # Find the position of the form block containing this action URL.
    # Walk backward from the action_url occurrence to find the opening <form tag.
    url_pos = content.find(action_url)
    # Find the nearest <form before the URL.
    form_start = content.rfind("<form", 0, url_pos)
    test_case.assertNotEqual(
        form_start,
        -1,
        f"{msg_prefix}Could not find opening <form tag before action URL {action_url!r}.",
    )
    # Find the closing </form> after the action URL.
    form_end = content.find("</form>", url_pos)
    test_case.assertNotEqual(
        form_end,
        -1,
        f"{msg_prefix}Could not find closing </form> after action URL {action_url!r}.",
    )
    form_block = content[form_start : form_end + len("</form>")]
    test_case.assertIn(
        'name="selected_pk"',
        form_block,
        f'{msg_prefix}Hidden input name="selected_pk" not found in the form '
        f"(action={action_url!r}). "
        f'The form must include <input type="hidden" name="selected_pk" '
        f':value="selectedPk"> so browsers thread the selected tab on submit. '
        f"Form block excerpt: {form_block[:400]!r}",
    )


# ---------------------------------------------------------------------------
# STEP 2: Inline Switch listing sync bar — all three form states
# ---------------------------------------------------------------------------


class InlineSwitchBarCustomizeTabPersistenceTest(TestCase):
    """
    kb-shzi.6 STEP 2: Inline Switch listing sync bar — state (i) Customize form.

    The inline bar in event_syndication.html (NOT _sync_bar.html) has its OWN
    Customize form for the Switch listing projection. The form must contain
    name="selected_pk" so real browsers send the tab on submit.

    RED (template test): GET the event_syndication fragment → form for
    projection-customize on the Switch listing must contain name="selected_pk".
    RED (server-contract): POST with selected_pk → x-data selectedPk seeded correctly.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="sw_cust_user", email="sw_cust@test.com", password="pw")
        self.profile = _make_profile("SW Cust Org", "sw-cust-org", user=self.user)
        self.event = _make_event(self.profile, "Switch Cust Event", "sw-cust-event")

        # Switch listing (canonical home per ADR-010 D1 — first tab)
        self.sw_conn = _make_switch_connection(self.profile)
        self.sw_proj = _make_switch_listing_projection(self.event, self.sw_conn)

        # Second LISTING connection (FetLife listing — second tab in event fragment).
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-sw-cust")
        self.fl_proj = _make_fetlife_listing_projection(self.event, self.fl_conn)

        self.client.force_login(self.user)

    def test_inline_switch_customize_form_has_selected_pk_input(self):
        """
        RED gate: GET event_syndication fragment → the inline Switch bar Customize
        form (projection-customize) must contain name="selected_pk".

        Before the fix: the form lacks this hidden input → browsers never send
        selected_pk → selectedPk always resets to the first tab on swap.
        After the fix: hidden input present → browsers send selected_pk on submit.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        customize_url = reverse("syndication:projection-customize", kwargs={"pk": self.sw_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            customize_url,
            msg_prefix="kb-shzi.6 inline Switch bar Customize form: ",
        )

    def test_inline_switch_customize_with_selected_pk_seeds_that_tab(self):
        """
        Server-contract: POST to projection-customize with selected_pk=<fl_proj.pk>
        → fragment seeds selectedPk to fl_proj.pk.
        """
        url = reverse("syndication:projection-customize", kwargs={"pk": self.sw_proj.pk})
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
                f"kb-shzi.6 inline Switch bar Customize: x-data selectedPk must be "
                f"seeded to {self.fl_proj.pk} (the selected tab), not reset to first. "
            ),
        )


class InlineSwitchBarResetStateIITabPersistenceTest(TestCase):
    """
    kb-shzi.6 STEP 2: Inline Switch listing sync bar — state (ii) Reset form.

    State (ii): own CV + sync_source SET → Reset button calls projection-reset-to-canonical.
    Form must have name="selected_pk" so browsers thread the selected tab.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="sw_rstii_user", email="sw_rstii@test.com", password="pw")
        self.profile = _make_profile("SW RstII Org", "sw-rstii-org", user=self.user)
        self.event = _make_event(self.profile, "Switch RstII Event", "sw-rstii-event")

        # Switch listing — in state (ii): own CV + sync_source set
        self.sw_conn = _make_switch_connection(self.profile)
        # Canonical CV on the event (required by reset-to-canonical service)
        self.canonical_cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        # Own CV for the Switch projection (not canonical) — makes it state (ii)
        self.sw_cv = ContentVersion.objects.create(
            event=self.event,
            name="switch-own-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Second LISTING projection — also acts as sync_source AND as selected tab
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-rstii")
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-rstii-cv",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.fl_proj = PlatformProjection.objects.create(
            connection=self.fl_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.fl_cv,
        )

        # Switch listing projection with own CV + sync_source set → state (ii)
        self.sw_proj = PlatformProjection.objects.create(
            connection=self.sw_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.sw_cv,
            sync_source=self.fl_proj,
        )

        self.client.force_login(self.user)

    def test_inline_switch_reset_stateii_form_has_selected_pk_input(self):
        """
        RED gate: GET event_syndication fragment → the inline Switch bar state (ii)
        Reset form (projection-reset-to-canonical) must contain name="selected_pk".
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        reset_url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.sw_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            reset_url,
            msg_prefix="kb-shzi.6 inline Switch bar Reset state(ii) form: ",
        )

    def test_inline_switch_reset_stateii_with_selected_pk_seeds_that_tab(self):
        """
        Server-contract: POST to projection-reset-to-canonical (state ii) with
        selected_pk=<fl_proj.pk> → fragment seeds selectedPk to fl_proj.pk.
        """
        url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.sw_proj.pk})
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
                f"kb-shzi.6 inline Switch bar Reset state(ii): x-data selectedPk must be "
                f"seeded to {self.fl_proj.pk} (the selected tab). "
            ),
        )


class InlineSwitchBarResetStateIIITabPersistenceTest(TestCase):
    """
    kb-shzi.6 STEP 2: Inline Switch listing sync bar — state (iii) Reset form.

    State (iii): own CV + sync_source NULL → Reset to synced button.
    Form must have name="selected_pk".
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="sw_rstiii_user", email="sw_rstiii@test.com", password="pw")
        self.profile = _make_profile("SW RstIII Org", "sw-rstiii-org", user=self.user)
        self.event = _make_event(self.profile, "Switch RstIII Event", "sw-rstiii-event")

        self.sw_conn = _make_switch_connection(self.profile)
        # Canonical CV (required by reset-to-canonical service)
        self.canonical_cv = ContentVersion.objects.create(
            event=self.event,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        # Own CV for Switch (not canonical, no sync_source → state iii)
        self.sw_cv = ContentVersion.objects.create(
            event=self.event,
            name="switch-own-cv-iii",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.sw_proj = PlatformProjection.objects.create(
            connection=self.sw_conn,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
            source_event=self.event,
            content_version=self.sw_cv,
        )

        # Second LISTING projection (FetLife listing — second tab in event fragment)
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-rstiii")
        self.fl_cv = ContentVersion.objects.create(
            event=self.event,
            name="fl-rstiii-cv",
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

    def test_inline_switch_reset_stateiii_form_has_selected_pk_input(self):
        """
        RED gate: GET event_syndication fragment → the inline Switch bar state (iii)
        Reset form (projection-reset-to-canonical) must contain name="selected_pk".
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        reset_url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.sw_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            reset_url,
            msg_prefix="kb-shzi.6 inline Switch bar Reset state(iii) form: ",
        )

    def test_inline_switch_reset_stateiii_with_selected_pk_seeds_that_tab(self):
        """
        Server-contract: POST to projection-reset-to-canonical (state iii) with
        selected_pk=<fl_proj.pk> → fragment seeds selectedPk to fl_proj.pk.
        """
        url = reverse("syndication:projection-reset-to-canonical", kwargs={"pk": self.sw_proj.pk})
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
                f"kb-shzi.6 inline Switch bar Reset state(iii): x-data selectedPk must be "
                f"seeded to {self.fl_proj.pk} (the selected tab). "
            ),
        )


# ---------------------------------------------------------------------------
# Event composer: publish / approve / mark-published / direct-publish / batch-publish
# ---------------------------------------------------------------------------


class EventComposerPublishFormsHaveSelectedPkTest(TestCase):
    """
    kb-shzi.6: Event composer publish forms must contain name="selected_pk".

    Covers projection-direct-publish (draft), projection-publish (ready),
    projection-mark-published (ready), projection-approve (draft "retry"),
    and batch-publish.

    Event fragment shows LISTING projections only; use FetLife listing for second tab.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ev_forms_user", email="ev_forms@test.com", password="pw")
        self.profile = _make_profile("Ev Forms Org", "ev-forms-org", user=self.user)
        self.event = _make_event(self.profile, "Event Forms Test", "ev-forms-test")

        # Switch listing (first tab)
        self.sw_conn = _make_switch_connection(self.profile)
        self.sw_proj = _make_switch_listing_projection(self.event, self.sw_conn)

        # FetLife listing (second tab — covers the forms for draft/ready states)
        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-ev-forms")
        self.fl_proj = _make_fetlife_listing_projection(self.event, self.fl_conn)

        self.client.force_login(self.user)

    def _get_fragment(self):
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_event_direct_publish_form_has_selected_pk_input(self):
        """
        RED gate: The projection-direct-publish form (shown on draft status) must
        contain name="selected_pk" so browsers send it on submit.
        """
        content = self._get_fragment()
        dp_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            dp_url,
            msg_prefix="kb-shzi.6 event composer direct-publish form: ",
        )

    def test_event_batch_publish_form_has_selected_pk_input(self):
        """
        RED gate: The projection-batch-publish form (Publish all ready) must
        contain name="selected_pk" so browsers send it on submit.

        The batch publish button only appears when has_ready_projections=True.
        Approve the Switch projection to ready so the button renders.
        """
        transition_status(self.sw_proj, "ready")
        self.sw_proj.refresh_from_db()

        content = self._get_fragment()
        batch_url = reverse(
            "syndication:projection-batch-publish",
            kwargs={"event_pk": self.event.pk},
        )
        _assert_form_has_selected_pk_input(
            self,
            content,
            batch_url,
            msg_prefix="kb-shzi.6 event composer batch-publish form: ",
        )

    def test_event_projection_publish_form_has_selected_pk_input(self):
        """
        RED gate: The projection-publish form (shown on ready status) must
        contain name="selected_pk".
        """
        # Move fl_proj to ready so the publish form appears
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        pub_url = reverse("syndication:projection-publish", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            pub_url,
            msg_prefix="kb-shzi.6 event composer projection-publish form: ",
        )

    def test_event_mark_published_form_has_selected_pk_input(self):
        """
        RED gate: The projection-mark-published form (shown on ready status) must
        contain name="selected_pk".
        """
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        mkp_url = reverse("syndication:projection-mark-published", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            mkp_url,
            msg_prefix="kb-shzi.6 event composer mark-published form: ",
        )

    def test_event_approve_retry_form_has_selected_pk_input(self):
        """
        RED gate: The projection-approve (Retry) form (shown on failed status) must
        contain name="selected_pk".
        """
        # Move fl_proj to failed status (ready→failed is legal per _LEGAL_TRANSITIONS)
        transition_status(self.fl_proj, "ready")
        transition_status(self.fl_proj, "failed")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        approve_url = reverse("syndication:projection-approve", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            approve_url,
            msg_prefix="kb-shzi.6 event composer approve/retry form: ",
        )


# ---------------------------------------------------------------------------
# Post composer: publish / approve / mark-published / direct-publish
# ---------------------------------------------------------------------------


class PostComposerPublishFormsHaveSelectedPkTest(TestCase):
    """
    kb-shzi.6: Post composer publish forms must contain name="selected_pk".

    Covers projection-direct-publish (draft), projection-publish (ready),
    projection-mark-published (ready), projection-approve (draft "retry").

    Post fragment shows PROMOTION projections linked via source_post.
    Use Telegram (first tab) + FetLife (second tab) for two tabs.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ps_forms_user", email="ps_forms@test.com", password="pw")
        self.profile = _make_profile("PS Forms Org", "ps-forms-org", user=self.user)
        self.event = _make_event(self.profile, "PS Forms Event", "ps-forms-event")
        self.post = Post.objects.create(
            event=self.event,
            headline="PS Forms Post",
            body="PS forms body",
        )

        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )

        # Telegram (first tab — draft)
        self.tg_conn = _make_telegram_connection(self.profile, destination_id="tg-ps-forms")
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )

        # FetLife (second tab — draft; moved to different states per test)
        self.fl_conn = _make_fetlife_promotion_connection(self.profile, destination_id="fl-ps-forms")
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-ps-forms-cv",
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

    def _get_fragment(self):
        url = reverse("syndication:fragment-post-syndication", kwargs={"pk": self.post.pk})
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_post_direct_publish_form_has_selected_pk_input(self):
        """
        RED gate: The projection-direct-publish form (draft status) in post_syndication
        must contain name="selected_pk".
        """
        content = self._get_fragment()
        dp_url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            dp_url,
            msg_prefix="kb-shzi.6 post composer direct-publish form: ",
        )

    def test_post_projection_publish_form_has_selected_pk_input(self):
        """
        RED gate: The projection-publish form (ready status) in post_syndication
        must contain name="selected_pk".
        """
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        pub_url = reverse("syndication:projection-publish", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            pub_url,
            msg_prefix="kb-shzi.6 post composer projection-publish form: ",
        )

    def test_post_mark_published_form_has_selected_pk_input(self):
        """
        RED gate: The projection-mark-published form (ready status) in post_syndication
        must contain name="selected_pk".
        """
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        mkp_url = reverse("syndication:projection-mark-published", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            mkp_url,
            msg_prefix="kb-shzi.6 post composer mark-published form: ",
        )

    def test_post_approve_retry_form_has_selected_pk_input(self):
        """
        RED gate: The projection-approve (Retry) form (failed status) in post_syndication
        must contain name="selected_pk".
        """
        transition_status(self.fl_proj, "ready")
        transition_status(self.fl_proj, "failed")
        self.fl_proj.refresh_from_db()

        content = self._get_fragment()
        approve_url = reverse("syndication:projection-approve", kwargs={"pk": self.fl_proj.pk})
        _assert_form_has_selected_pk_input(
            self,
            content,
            approve_url,
            msg_prefix="kb-shzi.6 post composer approve/retry form: ",
        )


# ---------------------------------------------------------------------------
# Server-contract tests: POST with selected_pk → selectedPk seeded correctly
# These confirm the server-side plumbing works and guard against regression.
# ---------------------------------------------------------------------------


class EventComposerServerContractTest(TestCase):
    """
    Server-contract: POST event-composer actions with selected_pk=<non-first pk>
    → fragment seeds selectedPk to that pk. Guards the view-side plumbing.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ev_sc_user", email="ev_sc@test.com", password="pw")
        self.profile = _make_profile("Ev SC Org", "ev-sc-org", user=self.user)
        self.event = _make_event(self.profile, "Event SC Test", "ev-sc-test")

        self.sw_conn = _make_switch_connection(self.profile)
        self.sw_proj = _make_switch_listing_projection(self.event, self.sw_conn)

        self.fl_conn = _make_fetlife_listing_connection(self.profile, destination_id="fl-ev-sc")
        self.fl_proj = _make_fetlife_listing_projection(self.event, self.fl_conn)

        self.client.force_login(self.user)

    def test_projection_approve_seeds_selected_pk(self):
        url = reverse("syndication:projection-approve", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="projection-approve server-contract: ",
        )

    def test_direct_publish_seeds_selected_pk(self):
        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="projection-direct-publish server-contract: ",
        )

    def test_projection_publish_seeds_selected_pk(self):
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()
        url = reverse("syndication:projection-publish", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="projection-publish server-contract: ",
        )

    def test_mark_published_seeds_selected_pk(self):
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()
        url = reverse("syndication:projection-mark-published", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="projection-mark-published server-contract: ",
        )

    def test_batch_publish_seeds_selected_pk(self):
        transition_status(self.sw_proj, "ready")
        self.sw_proj.refresh_from_db()
        url = reverse("syndication:projection-batch-publish", kwargs={"event_pk": self.event.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="projection-batch-publish server-contract: ",
        )


class PostComposerServerContractTest(TestCase):
    """
    Server-contract: POST post-composer actions with selected_pk=<non-first pk>
    → fragment seeds selectedPk to that pk.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="ps_sc_user", email="ps_sc@test.com", password="pw")
        self.profile = _make_profile("PS SC Org", "ps-sc-org", user=self.user)
        self.event = _make_event(self.profile, "PS SC Event", "ps-sc-event")
        self.post = Post.objects.create(event=self.event, headline="PS SC Post", body="SC body")
        self.canonical_cv = ContentVersion.objects.create(
            post=self.post,
            name="canonical",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.tg_conn = _make_telegram_connection(self.profile, destination_id="tg-ps-sc")
        self.tg_proj = PlatformProjection.objects.create(
            connection=self.tg_conn,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
            source_post=self.post,
            content_version=self.canonical_cv,
        )
        self.fl_conn = _make_fetlife_promotion_connection(self.profile, destination_id="fl-ps-sc")
        self.fl_cv = ContentVersion.objects.create(
            post=self.post,
            name="fl-ps-sc-cv",
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

    def test_post_approve_seeds_selected_pk(self):
        url = reverse("syndication:projection-approve", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="post projection-approve server-contract: ",
        )

    def test_post_direct_publish_seeds_selected_pk(self):
        url = reverse("syndication:projection-direct-publish", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="post projection-direct-publish server-contract: ",
        )

    def test_post_projection_publish_seeds_selected_pk(self):
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()
        url = reverse("syndication:projection-publish", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="post projection-publish server-contract: ",
        )

    def test_post_mark_published_seeds_selected_pk(self):
        transition_status(self.fl_proj, "ready")
        self.fl_proj.refresh_from_db()
        url = reverse("syndication:projection-mark-published", kwargs={"pk": self.fl_proj.pk})
        response = self.client.post(url, data={"selected_pk": str(self.fl_proj.pk)}, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        _assert_selected_pk_seeded(
            self,
            response.content.decode(),
            self.fl_proj.pk,
            msg_prefix="post projection-mark-published server-contract: ",
        )
