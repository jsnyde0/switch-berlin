"""
Tests for adversarial-review findings on the kb-shzi.5 sync-badge relabel.

Findings addressed:
  F2b - State-(i) Customize form must ALWAYS render even when consumers_map
        is truthy but does NOT contain the projection's canonical CV as a key.
  F4  - Inline Switch listing sync bar in event_syndication.html is 2-branch
        (missing state ii "Synced from <peer>"). Switch is always state (i)
        per ADR-010 D1, but the else-branch must never mis-render a real state.
  F3  - Count wording "edits update N channels" is ambiguous; chosen wording:
        "Shared across N channels" (N = total projections sharing the CV).
  F7  - Stale comment at ~308-309 in event_syndication.html (cosmetic, tested
        indirectly by the inline Switch bar correct rendering test).

All assertions on response.content (NOT response.context — hollow per memory).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirror existing test helpers)
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
    event = Event.objects.create(title=title, slug=slug, start=timezone.now())
    EventOrganizer.objects.create(event=event, profile=profile, is_primary=True)
    return event


def _make_canonical_cv(event=None, post=None):
    if event is not None:
        cv, _ = ContentVersion.objects.get_or_create(
            event=event,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
    else:
        cv, _ = ContentVersion.objects.get_or_create(
            post=post,
            name="canonical",
            defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
        )
    return cv


def _make_listing_projection(conn, event, cv, sync_source=None):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.LISTING,
        status=PlatformProjection.Status.DRAFT,
        source_event=event,
        content_version=cv,
        sync_source=sync_source,
    )


def _make_promotion_projection(conn, post, cv, sync_source=None):
    return PlatformProjection.objects.create(
        connection=conn,
        kind=PlatformProjection.Kind.PROMOTION,
        status=PlatformProjection.Status.DRAFT,
        source_post=post,
        content_version=cv,
        sync_source=sync_source,
    )


# ---------------------------------------------------------------------------
# F2b — State-(i) Customize form renders even when consumers_map is truthy
#        but does NOT contain the projection's canonical CV as a key.
# ---------------------------------------------------------------------------


class SyncBarStateIFormAlwaysRendersTest(TestCase):
    """
    F2b (ADR-008 D3 silent-blank): The state-(i) Customize form must ALWAYS
    render in _sync_bar.html, regardless of whether the canonical CV appears
    in consumers_map.

    The bug: the Customize form was nested inside:
      {% if consumers_map %}{% for cv, cv_consumers in consumers_map.items %}
        {% if cv.pk == cv_pk %}
          <form>...</form>
        {% endif %}
      {% endfor %}
    If consumers_map is truthy but the canonical CV key is missing, no form
    renders — the badge div becomes a blank element.

    Fix: the form must be unconditional; only the count span is conditional.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f2b_always_form", email="f2b@test.com", password="pw")
        self.profile = _make_profile("F2b Org", "f2b-org", user=self.user)
        self.event = _make_event(self.profile, "F2b Event", "f2b-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page-f2b",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-f2b",
            kinds=["listing"],
        )
        # Switch is state (i): shares canonical CV, no sync_source
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        # FetLife is ALSO state (i): shares same canonical CV (broadcast scenario)
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.canonical_cv)
        self.client.force_login(self.user)

    def test_state_i_badge_not_blank_when_cv_missing_from_consumers_map(self):
        """
        Render the _sync_bar.html partial with a consumers_map that is truthy
        but does NOT contain the projection's canonical CV as a key.
        The badge must render the Customize form (non-empty), NOT a blank div.

        This is the F2b scenario: consumers_map = {some_OTHER_cv: [...]} where
        the current projection's canonical CV is not present as a key.
        """
        # Craft a consumers_map with a different (unrelated) CV as key —
        # simulating the case where the current CV is absent from the map.
        unrelated_cv = ContentVersion.objects.create(
            event=self.event,
            name="unrelated-cv-f2b",
            body="unrelated",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        # consumers_map is truthy but lacks the switch_proj's canonical CV key
        simulated_consumers_map = {unrelated_cv: [self.fl_proj]}

        # Render the partial directly via Django's template engine.
        # We use a minimal template that includes the partial.
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        rendered = render_to_string(
            "syndication/fragments/_sync_bar.html",
            {
                "proj": self.switch_proj,
                "fragment_target": "#event-syndication",
                "oob": False,
                "consumers_map": simulated_consumers_map,
            },
            request=request,
        )

        # The rendered output must contain the Customize form action URL.
        # A blank badge would contain no form and no button.
        # The URL renders as "/syndication/projections/<pk>/customize/" not the URL name.
        self.assertIn(
            "customize",
            rendered,
            "F2b: The Customize form must render even when the canonical CV is not "
            "a key in consumers_map. The badge must never be blank for state (i). "
            f"Got rendered output: {rendered!r}",
        )
        # Also assert the "Shared" label is present
        self.assertIn(
            "Shared",
            rendered,
            "F2b: The 'Shared' badge text must render even when consumers_map lacks "
            f"the canonical CV key. Got: {rendered!r}",
        )

    def test_state_i_count_shows_when_cv_present_in_map_with_multiple_sharers(self):
        """
        F3: When consumers_map IS present and the canonical CV key IS found with
        N > 1 sharers, the count text must appear with "Shared across N channels".

        This locks the chosen F3 wording: "Shared across N channels".
        N = total projections on the CV (both switch_proj + fl_proj = 2).
        """
        # Both switch_proj and fl_proj share canonical_cv — count = 2
        consumers_map = {self.canonical_cv: [self.switch_proj, self.fl_proj]}

        from django.template.loader import render_to_string
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        rendered = render_to_string(
            "syndication/fragments/_sync_bar.html",
            {
                "proj": self.switch_proj,
                "fragment_target": "#event-syndication",
                "oob": False,
                "consumers_map": consumers_map,
            },
            request=request,
        )

        # F3: count text must use "Shared across N channels" wording
        self.assertIn(
            "Shared across",
            rendered,
            f"F3: Count text must use 'Shared across N channels' wording. Got: {rendered!r}",
        )
        self.assertIn(
            "2",
            rendered,
            f"F3: Count N=2 must appear in rendered badge. Got: {rendered!r}",
        )
        # Old ambiguous wording must NOT appear
        self.assertNotIn(
            "edits update",
            rendered,
            "F3: Old 'edits update N channels' wording must be replaced by 'Shared across N channels'. "
            f"Got: {rendered!r}",
        )

    def test_state_i_no_count_when_single_sharer(self):
        """
        F3: With only 1 sharer (single-projection scenario), no count span renders.
        """
        consumers_map = {self.canonical_cv: [self.switch_proj]}

        from django.template.loader import render_to_string
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        rendered = render_to_string(
            "syndication/fragments/_sync_bar.html",
            {
                "proj": self.switch_proj,
                "fragment_target": "#event-syndication",
                "oob": False,
                "consumers_map": consumers_map,
            },
            request=request,
        )

        # "Shared across" count text must NOT appear for a single sharer
        self.assertNotIn(
            "Shared across",
            rendered,
            f"F3: No count text should appear when only 1 projection shares the CV. Got: {rendered!r}",
        )
        # The form and badge must still render
        self.assertIn(
            "Shared",
            rendered,
            f"F3: 'Shared' badge must still render for state (i) with 1 sharer. Got: {rendered!r}",
        )


# ---------------------------------------------------------------------------
# F3 — Count text on inline Switch bar in event_syndication.html
# ---------------------------------------------------------------------------


class InlineSwitchBarCountWordingTest(TestCase):
    """
    F3: The inline Switch listing sync bar in event_syndication.html also
    shows a count. The wording must match _sync_bar.html: "Shared across N channels".

    With 2 projections sharing the canonical CV, the count span must appear with
    "Shared across 2 channels" in the rendered event_syndication fragment.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f3_switch_count", email="f3sw@test.com", password="pw")
        self.profile = _make_profile("F3 Switch Org", "f3-switch-org", user=self.user)
        self.event = _make_event(self.profile, "F3 Switch Event", "f3-switch-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page-f3",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-f3",
            kinds=["listing"],
        )
        # Both share canonical CV — N=2
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.canonical_cv)
        self.client.force_login(self.user)

    def test_inline_switch_bar_count_uses_shared_across_wording(self):
        """
        GET the event_syndication fragment — the inline Switch listing sync bar
        must show "Shared across 2 channels" count text when 2 projections share
        the canonical CV.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Shared across",
            content,
            "F3: Inline Switch bar count must use 'Shared across N channels' wording "
            f"when N=2 projections share the canonical CV. Content excerpt: {content[:2000]!r}",
        )
        # Old wording must not appear
        self.assertNotIn(
            "edits update",
            content,
            f"F3: Old 'edits update N channels' wording must be replaced. Content excerpt: {content[:2000]!r}",
        )


# ---------------------------------------------------------------------------
# F4 — Inline Switch listing sync bar missing state (ii)
# ---------------------------------------------------------------------------


class InlineSwitchBarThreeStatesTest(TestCase):
    """
    F4 (kb-lprn bug shape): The inline Switch listing sync bar in
    event_syndication.html is a 2-branch if/else:
      canonical → "Shared"
      else      → "Custom"

    It is MISSING state (ii) "Synced from <peer>". Per ADR-010 D1, Switch is
    the canonical home for events so it cannot normally sync FROM a peer.
    However, the missing branch is still a code smell that can mis-render.

    Fix: add a {% comment %} explaining why Switch is normally state (i), AND
    add the missing elif branch for state (ii) so all three states are handled
    and a mis-configured Switch in state (ii) is never silently mis-rendered
    as "Custom".

    Test: confirm the inline bar renders "Synced from" for a Switch projection
    in state (ii). This is an unusual/unexpected config but the template must
    handle it correctly rather than falling to the "Custom" else-branch.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f4_switch_state2", email="f4sw2@test.com", password="pw")
        self.profile = _make_profile("F4 Switch Org", "f4-switch-org", user=self.user)
        self.event = _make_event(self.profile, "F4 Switch Event", "f4-switch-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.conn_switch_a = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page-f4-a",
            kinds=["listing"],
        )
        self.conn_switch_b = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page-f4-b",
            kinds=["listing"],
        )
        # Switch A: state (i) — on canonical CV
        self.switch_a_proj = _make_listing_projection(self.conn_switch_a, self.event, self.canonical_cv)
        # Switch B: state (ii) — own CV + sync_source = Switch A
        # This is unusual (Switch normally can't sync from peer per ADR-010 D1)
        # but the template must handle it correctly rather than mis-rendering.
        self.switch_b_cv = ContentVersion.objects.create(
            event=self.event,
            name="switch-b-cv-f4",
            body="synced from switch-a body",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        self.switch_b_proj = _make_listing_projection(
            self.conn_switch_b,
            self.event,
            self.switch_b_cv,
            sync_source=self.switch_a_proj,
        )
        self.client.force_login(self.user)

    def test_inline_switch_bar_state_ii_shows_copied_from_not_custom(self):
        """
        When a Switch listing projection is in state (ii) (own CV + sync_source set),
        the inline sync bar must render "Copied from" — NOT fall through to "Custom"
        via the 2-branch else-branch.

        Before F4 fix: the inline Switch bar has only:
          {% if proj.content_version.name == "canonical" %} → "Shared"
          {% else %} → "Custom"
        so Switch B in state (ii) incorrectly renders "Custom".

        After F4 fix: the elif/three-state is present, Switch B renders "Copied from"
        (snapshot label, kb-nexw.3 — was "Synced from" before the relabel).
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Copied from",
            content,
            "F4: Inline Switch listing sync bar must render 'Copied from' for a "
            "state-(ii) Switch projection (own CV + sync_source set). Before F4 fix "
            "it fell through to 'Custom'; label relabeled to 'Copied from' by kb-nexw.3 "
            "(snapshot semantics, not live-sync). "
            f"Content excerpt: {content[:3000]!r}",
        )
        # Custom amber badge must NOT appear for this Switch B (which is state ii)
        # Note: there's a Switch A in state (i) that shows "Shared" — that's fine.
        # We specifically check that the amber "Custom" badge is absent for state (ii).
        custom_badge_marker = 'text-amber-300/70">Custom'
        self.assertNotIn(
            custom_badge_marker,
            content,
            "F4: The amber 'Custom' badge must NOT appear for a state-(ii) Switch "
            "projection (snapshot from peer). Got: "
            f"{content[:3000]!r}",
        )


# ---------------------------------------------------------------------------
# F3 — Count text in event_syndication.html post/event composer fragment
#        (full integration test via HTTP)
# ---------------------------------------------------------------------------


class ConsumerCountWordingIntegrationTest(TestCase):
    """
    F3 integration: A canonical CV with N=2 projections (sharers) → the event
    composer fragment renders the count text with "Shared across 2 channels".

    This covers the _sync_bar.html partial count (used by non-Switch projections)
    AND the inline Switch bar count in event_syndication.html.
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(username="f3_count_integ", email="f3ci@test.com", password="pw")
        self.profile = _make_profile("F3 Count Org", "f3-count-org", user=self.user)
        self.event = _make_event(self.profile, "F3 Count Event", "f3-count-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="own-page-f3ci",
            kinds=["listing"],
        )
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-f3ci",
            kinds=["listing"],
        )
        # Both projections share canonical_cv — N=2 sharers
        self.switch_proj = _make_listing_projection(self.conn_switch, self.event, self.canonical_cv)
        self.fl_proj = _make_listing_projection(self.conn_fetlife, self.event, self.canonical_cv)
        self.client.force_login(self.user)

    def test_count_text_uses_shared_across_n_channels(self):
        """
        GET the event_syndication fragment with 2 projections sharing the canonical CV.
        The count text must be "Shared across 2 channels" (exact string fragment).
        Assert the exact string + the right N.
        """
        url = reverse("syndication:fragment-event-syndication", kwargs={"pk": self.event.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        # Exact string check: "Shared across 2 channels"
        self.assertIn(
            "Shared across 2 channels",
            content,
            "F3: The count text must be exactly 'Shared across 2 channels' when N=2. "
            f"Content excerpt: {content[:3000]!r}",
        )


# ---------------------------------------------------------------------------
# kb-nexw.3 — State-(ii) label must say "Copied from" + "won't follow later edits"
#              (snapshot semantics, not live-sync semantics)
# ---------------------------------------------------------------------------


class StateTwoSnapshotLabelTest(TestCase):
    """
    kb-nexw.3: State-(ii) — own CV + sync_source set — is a ONE-TIME SNAPSHOT.
    The source channel's later edits do NOT propagate (ADR-016 D2 mechanism c).

    The old label "Synced from <platform>" + "· editing detaches" overstated the
    mechanism (implying ongoing live sync). The correct labels are:
      main:  "Copied from <platform>"
      sub:   "· snapshot, won't follow later edits"

    Tested in BOTH:
      (a) _sync_bar.html (canonical single-source partial) — rendered via
          render_to_string
      (b) _channel_editor.html inline Switch badge (twin) — rendered via
          the event-syndication fragment HTTP response
    """

    def setUp(self):
        self.client = Client()
        self.user = _make_user(
            username="nexw3_state2", email="nexw3@test.com", password="pw"
        )
        self.profile = _make_profile("Nexw3 Org", "nexw3-org", user=self.user)
        self.event = _make_event(self.profile, "Nexw3 Event", "nexw3-event")
        self.canonical_cv = _make_canonical_cv(event=self.event)

        # Connection A (FetLife): canonical source
        self.conn_fetlife = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-nexw3",
            kinds=["listing"],
        )
        # Connection B (Switch): will be state (ii) — peer-synced from FetLife
        self.conn_switch = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="switch",
            destination_id="sw-nexw3",
            kinds=["listing"],
        )

        # FetLife projection: state (i) — canonical CV, no sync_source
        self.fl_proj = _make_listing_projection(
            self.conn_fetlife, self.event, self.canonical_cv
        )

        # Switch own CV (peer-synced snapshot from FetLife)
        self.switch_cv = ContentVersion.objects.create(
            event=self.event,
            name="switch-nexw3-cv",
            body="snapshot from fetlife",
            provenance=ContentVersion.Provenance.RULE_TEMPLATE,
        )
        # Switch projection: state (ii) — own CV + sync_source set
        self.switch_proj = _make_listing_projection(
            self.conn_switch,
            self.event,
            self.switch_cv,
            sync_source=self.fl_proj,
        )
        self.client.force_login(self.user)

    def test_sync_bar_state_ii_shows_copied_from_not_synced_from(self):
        """
        (a) _sync_bar.html partial: state-(ii) must render "Copied from" for the
        main label, NOT "Synced from".
        """
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        rendered = render_to_string(
            "syndication/fragments/_sync_bar.html",
            {
                "proj": self.switch_proj,
                "fragment_target": "#event-syndication",
                "oob": False,
                "consumers_map": None,
            },
            request=request,
        )

        self.assertIn(
            "Copied from",
            rendered,
            "kb-nexw.3: _sync_bar.html state (ii) must render 'Copied from' "
            f"(snapshot label). Got: {rendered!r}",
        )
        self.assertNotIn(
            "Synced from",
            rendered,
            "kb-nexw.3: _sync_bar.html state (ii) must NOT render 'Synced from' "
            f"(overstated live-sync label). Got: {rendered!r}",
        )

    def test_sync_bar_state_ii_shows_snapshot_sub_label(self):
        """
        (a) _sync_bar.html partial: state-(ii) sub-label must read
        "won't follow later edits", NOT "· editing detaches".
        """
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get("/")
        request.user = self.user

        rendered = render_to_string(
            "syndication/fragments/_sync_bar.html",
            {
                "proj": self.switch_proj,
                "fragment_target": "#event-syndication",
                "oob": False,
                "consumers_map": None,
            },
            request=request,
        )

        self.assertIn(
            "won't follow later edits",
            rendered,
            "kb-nexw.3: _sync_bar.html state (ii) sub-label must read "
            f"'won't follow later edits'. Got: {rendered!r}",
        )
        self.assertNotIn(
            "editing detaches",
            rendered,
            "kb-nexw.3: _sync_bar.html state (ii) must NOT say 'editing detaches'. "
            f"Got: {rendered!r}",
        )

    def test_channel_editor_inline_twin_state_ii_shows_copied_from(self):
        """
        (b) _channel_editor.html inline Switch badge (twin): state-(ii) must render
        "Copied from" in the event-syndication fragment response.

        The switch_proj is already in state (ii) (own CV + sync_source set).
        The event-syndication fragment renders the Switch listing inline badge.
        """
        url = reverse(
            "syndication:fragment-event-syndication", kwargs={"pk": self.event.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "Copied from",
            content,
            "kb-nexw.3: _channel_editor.html inline twin state (ii) must render "
            f"'Copied from'. Content excerpt: {content[:3000]!r}",
        )
        self.assertNotIn(
            "Synced from",
            content,
            "kb-nexw.3: _channel_editor.html inline twin state (ii) must NOT render "
            f"'Synced from'. Content excerpt: {content[:3000]!r}",
        )

    def test_channel_editor_inline_twin_state_ii_shows_snapshot_sub_label(self):
        """
        (b) _channel_editor.html inline Switch badge (twin): state-(ii) sub-label
        must read "won't follow later edits" in the event-syndication response.
        """
        url = reverse(
            "syndication:fragment-event-syndication", kwargs={"pk": self.event.pk}
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()

        self.assertIn(
            "won't follow later edits",
            content,
            "kb-nexw.3: _channel_editor.html inline twin state (ii) sub-label must "
            f"read 'won't follow later edits'. Content excerpt: {content[:3000]!r}",
        )
        self.assertNotIn(
            "editing detaches",
            content,
            "kb-nexw.3: _channel_editor.html inline twin state (ii) must NOT say "
            f"'editing detaches'. Content excerpt: {content[:3000]!r}",
        )


class StateTwoSnapshotLabelTwinParityGuardTest(TestCase):
    """
    kb-nexw.3 twin-parity structural guard: both _sync_bar.html AND the inline
    twin in _channel_editor.html must use the snapshot label, not the old
    live-sync label.

    This is a file-content scan (not a rendered test) that asserts:
      - "Copied from" appears in both files in functional markup (not just comments)
      - "Synced from" does NOT appear in state-(ii) functional markup in either file

    Derived paths use settings.BASE_DIR (never hardcoded absolute paths).
    """

    def _get_template_content(self, rel_path: str) -> str:
        from pathlib import Path

        from django.conf import settings

        return (Path(settings.BASE_DIR) / "templates" / rel_path).read_text(
            encoding="utf-8"
        )

    def test_sync_bar_contains_copied_from_not_synced_from_in_markup(self):
        """
        _sync_bar.html must contain "Copied from" in functional markup
        and must NOT contain "Synced from" outside of comment blocks.
        """
        content = self._get_template_content(
            "syndication/fragments/_sync_bar.html"
        )

        self.assertIn(
            "Copied from",
            content,
            "kb-nexw.3: _sync_bar.html must contain 'Copied from' (snapshot label) "
            "in state (ii) markup.",
        )
        # Check "Synced from" does not appear outside of {% comment %} blocks.
        # We check for the trans tag form used in functional markup.
        self.assertNotIn(
            'trans "Synced from"',
            content,
            "kb-nexw.3: _sync_bar.html must NOT contain '{% trans \"Synced from\" %}' "
            "in state (ii) markup — use 'Copied from' instead.",
        )

    def test_channel_editor_contains_copied_from_not_synced_from_in_markup(self):
        """
        _channel_editor.html inline twin must contain "Copied from" and must NOT
        contain the old "Synced from" trans tag in functional markup.
        """
        content = self._get_template_content(
            "syndication/fragments/_channel_editor.html"
        )

        self.assertIn(
            "Copied from",
            content,
            "kb-nexw.3: _channel_editor.html inline twin must contain 'Copied from' "
            "(snapshot label) in state (ii) markup.",
        )
        self.assertNotIn(
            'trans "Synced from"',
            content,
            "kb-nexw.3: _channel_editor.html inline twin must NOT contain "
            "'{% trans \"Synced from\" %}' — use 'Copied from' instead.",
        )
