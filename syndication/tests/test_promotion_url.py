"""
TDD tests for kb-6d7o.2: versioned canonical URL embedded in Telegram promotion body.

Contract:
1. FIRST-PUBLISH: The sent Bot API payload text contains the canonical event URL
   with ?v=<publish_rev>. Assert against the SENT payload (httpx.post mock),
   NOT the post-publish frozen snapshot.

2. REPUBLISH: After an edit-after-publish, republish_projection increments
   publish_rev AND the re-materialized frozen_content['body'] carries the new ?v=.
   (Re-dispatch to Telegram is deferred to kb-rsl4 — asserts frozen body only.)

3. A draft ContentVersion edit leaves publish_rev unchanged.

Send-sequence fact (ADR-016, kb-6d7o.2 design):
  publish_telegram_promotion calls render_projection() while status is 'ready',
  builds the payload, SENDS it, then calls transition_status('published').
  So the body Telegram receives is the draft→ready frozen body. The versioned URL
  must be embedded at draft→ready freeze, and the test asserts the SENT payload.

Mock pattern: `patch("syndication.adapters.httpx.post", ...)` — mocks only
the transport boundary; real publish_telegram_promotion runs end-to-end.
"""

from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.engine import generate_projection, transition_status
from syndication.models import PlatformConnection, Post

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**kwargs):
    from django.contrib.auth import get_user_model

    User = get_user_model()
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


def _make_telegram_connection(profile, destination_id="@testchannel", bot_token="test-bot-token"):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=["promotion"],
        credentials={"bot_token": bot_token},
    )


def _make_post(event, headline="Come join us!", body="Amazing event."):
    return Post.objects.create(event=event, headline=headline, body=body)


def _fake_ok_response(message_id=42):
    """Return a fake httpx.Response-like mock for Telegram Bot API success."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True, "result": {"message_id": message_id}}
    return resp


def _expected_event_url(event):
    """Return the absolute canonical Switch event URL (no version parameter)."""
    path = reverse(
        "event-detail",
        kwargs={
            "org_slug": event.organizer.slug,
            "event_slug": event.slug,
        },
    )
    return settings.SITE_URL + path


# ---------------------------------------------------------------------------
# 1. FIRST-PUBLISH: sent payload contains versioned URL
# ---------------------------------------------------------------------------


class FirstPublishSentPayloadContainsVersionedUrlTest(TestCase):
    """
    FIRST-PUBLISH: the body the Telegram adapter SENDS (Bot API payload text)
    contains the canonical event URL with ?v=<publish_rev>.

    Assert against the SENT httpx.post payload — NOT the post-publish frozen
    snapshot. (Invalidation guard: if we checked frozen_content after publishing,
    the test would pass even if Telegram never received the URL.)

    publish_rev must be 1 after the first publish (incremented from 0 at draft→ready).
    """

    def setUp(self):
        self.user = _make_user(username="fp_url_user", email="fp_url@test.com", password="pw")
        self.profile = _make_profile("FP URL Org", "fp-url-org", user=self.user)
        self.event = _make_event(self.profile, "FP URL Event", "fp-url-event")
        self.conn = _make_telegram_connection(self.profile)
        self.post = _make_post(self.event)
        self.proj = generate_projection(
            kind="promotion",
            connection=self.conn,
            source_post=self.post,
            mode="rule_based",
        )

    @override_settings(SITE_URL="https://switch.berlin")
    def test_first_publish_sent_payload_contains_versioned_url(self):
        """
        The text sent to the Telegram Bot API must contain the canonical event URL
        with ?v=<publish_rev> (not just ?v=0 — the rev must be bumped before freeze).
        """
        from syndication.services import publish_projection_direct

        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()) as mock_post:
            publish_projection_direct(user=self.user, projection=self.proj)

        # httpx.post must have been called (the send happened)
        self.assertEqual(mock_post.call_count, 1, "httpx.post must be called exactly once for the send.")

        # Extract the sent payload text
        call_kwargs = mock_post.call_args[1]  # keyword args: httpx.post(url, json=payload)
        sent_text = call_kwargs["json"]["text"]

        # Build expected versioned URL
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.publish_rev, 1, "publish_rev must be 1 after first publish.")

        event_url = _expected_event_url(self.event)
        expected_url_fragment = f"{event_url}?v=1"

        self.assertIn(
            expected_url_fragment,
            sent_text,
            f"Sent payload text must contain versioned URL {expected_url_fragment!r}. "
            f"Got sent_text={sent_text!r}",
        )

    @override_settings(SITE_URL="https://switch.berlin")
    def test_publish_rev_increments_at_draft_ready_not_before(self):
        """
        publish_rev must be 0 in draft state and increment to 1 at draft→ready.
        """
        # Before freeze: publish_rev is 0
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.publish_rev, 0, "publish_rev must be 0 before any freeze.")

        # Transition to ready (freeze)
        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.publish_rev, 1, "publish_rev must be 1 after draft→ready freeze.")


# ---------------------------------------------------------------------------
# 2. REPUBLISH: publish_rev increments and frozen body carries new ?v=
# ---------------------------------------------------------------------------


class RepublishBumpsRevAndFreezeBodyTest(TestCase):
    """
    REPUBLISH: after an edit-after-publish, republish_projection increments
    publish_rev AND (for telegram) the re-materialized frozen_content['body']
    carries the new ?v=.

    Re-dispatch to Telegram is deferred (kb-rsl4 — out of scope here).
    Assert frozen body (the correct observable for re-freeze-only v0).

    Both tests use a Telegram connection (URL embed is telegram-only per Fix 1
    of kb-6d7o.2 review correction). republish_projection is re-freeze-only —
    no httpx.post call is made.
    """

    def setUp(self):
        self.user = _make_user(username="repu_url_user", email="repu_url@test.com", password="pw")
        self.profile = _make_profile("Repu URL Org", "repu-url-org", user=self.user)
        self.event = _make_event(self.profile, "Repu URL Event", "repu-url-event")
        # Use telegram connection — URL embed is telegram-only; republish is
        # re-freeze-only in v0 (no httpx.post call needed here).
        self.tg_conn = _make_telegram_connection(self.profile, destination_id="@repu-url-channel")
        self.post = _make_post(self.event)
        self.proj = generate_projection(
            kind="promotion",
            connection=self.tg_conn,
            source_post=self.post,
            mode="rule_based",
        )

    @override_settings(SITE_URL="https://switch.berlin")
    def test_republish_increments_publish_rev(self):
        """
        republish_projection must increment publish_rev.

        First publish via publish_projection_direct (mocking httpx.post for the
        Telegram send). Then republish_projection (re-freeze-only — no second send).
        """
        from syndication.services import customize, publish_projection_direct, republish_projection

        # First publish: mock httpx.post for the Telegram send
        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()):
            publish_projection_direct(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, "published")
        first_rev = self.proj.publish_rev
        self.assertEqual(first_rev, 1, "publish_rev must be 1 after first publish.")

        # Edit-after-publish: customize then edit
        own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        own_cv.body = "Updated body text for republish test"
        own_cv.save(update_fields=["body", "updated_at"])

        # Republish: re-freeze only (no send) — must bump publish_rev
        republish_projection(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()

        self.assertEqual(
            self.proj.publish_rev,
            first_rev + 1,
            f"republish_projection must increment publish_rev from {first_rev} to {first_rev + 1}. "
            f"Got publish_rev={self.proj.publish_rev}.",
        )

    @override_settings(SITE_URL="https://switch.berlin")
    def test_republish_frozen_body_carries_new_versioned_url(self):
        """
        After republish of a telegram projection, frozen_content['body'] must
        carry the new ?v=<publish_rev>.
        """
        from syndication.services import customize, publish_projection_direct, republish_projection

        # First publish: mock httpx.post for the Telegram send
        with patch("syndication.adapters.httpx.post", return_value=_fake_ok_response()):
            publish_projection_direct(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()

        # Edit-after-publish
        own_cv = customize(self.user, self.proj)
        self.proj.refresh_from_db()
        own_cv.body = "New body for republish URL test"
        own_cv.save(update_fields=["body", "updated_at"])

        # Republish (re-freeze-only — no second Telegram send in v0)
        republish_projection(user=self.user, projection=self.proj)
        self.proj.refresh_from_db()

        new_rev = self.proj.publish_rev
        event_url = _expected_event_url(self.event)
        expected_url_fragment = f"{event_url}?v={new_rev}"

        frozen_body = self.proj.frozen_content["body"]
        self.assertIn(
            expected_url_fragment,
            frozen_body,
            f"After republish, frozen_content['body'] must contain {expected_url_fragment!r}. "
            f"Got frozen_body={frozen_body!r}",
        )


# ---------------------------------------------------------------------------
# 3. Draft ContentVersion edit leaves publish_rev unchanged
# ---------------------------------------------------------------------------


class DraftEditLeavesPublishRevUnchangedTest(TestCase):
    """
    A draft ContentVersion edit must NOT change publish_rev.
    publish_rev increments only at body-freeze sites (draft→ready, republish).
    """

    def setUp(self):
        self.user = _make_user(username="draft_rev_user", email="draft_rev@test.com", password="pw")
        self.profile = _make_profile("Draft Rev Org", "draft-rev-org", user=self.user)
        self.event = _make_event(self.profile, "Draft Rev Event", "draft-rev-event")
        self.conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-draft-rev",
            kinds=["promotion"],
        )
        self.post = _make_post(self.event)
        self.proj = generate_projection(
            kind="promotion",
            connection=self.conn,
            source_post=self.post,
            mode="rule_based",
        )

    def test_draft_content_version_edit_leaves_publish_rev_unchanged(self):
        """
        Editing the draft ContentVersion body must NOT increment publish_rev.
        publish_rev must remain 0 throughout draft edits.
        """
        from syndication.services import edit_version

        # Confirm initial state
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.publish_rev, 0, "publish_rev must be 0 before any action.")

        # Edit the draft ContentVersion body
        cv = self.proj.content_version
        edit_version(user=self.user, version=cv, body="Draft edit body — should not bump rev")

        # publish_rev must still be 0
        self.proj.refresh_from_db()
        self.assertEqual(
            self.proj.publish_rev,
            0,
            "Draft ContentVersion edit must NOT increment publish_rev. "
            f"Got publish_rev={self.proj.publish_rev}.",
        )


# ---------------------------------------------------------------------------
# 4. Fix 1 (review correction): Non-telegram promotion bodies do NOT get ?v=
# ---------------------------------------------------------------------------


class NonTelegramPromotionBodyHasNoVersionedUrlTest(TestCase):
    """
    Fix 1 (kb-6d7o.2 review correction): the ?v= versioned URL is a Telegram
    link-preview cache-bust artifact. Non-telegram promotion projections (FetLife,
    Switch, etc.) must NOT have the URL appended to their body.

    Frozen body must be EXACTLY the composed/explicit body — no URL suffix.
    """

    def setUp(self):
        self.user = _make_user(username="nourl_user", email="nourl@test.com", password="pw")
        self.profile = _make_profile("NoURL Org", "nourl-org", user=self.user)
        self.event = _make_event(self.profile, "NoURL Event", "nourl-event")
        self.fl_conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-nourl-test",
            kinds=["promotion"],
        )
        self.post = _make_post(self.event, headline="NoURL Headline", body="NoURL body text.")
        self.proj = generate_projection(
            kind="promotion",
            connection=self.fl_conn,
            source_post=self.post,
            mode="rule_based",
        )

    def test_fetlife_promotion_frozen_body_has_no_versioned_url(self):
        """
        At draft->ready freeze, a FetLife promotion body must NOT contain ?v=.
        The body must be exactly the composed body (headline + body) — no URL suffix.
        """
        from syndication.engine import transition_status

        transition_status(self.proj, "ready")
        self.proj.refresh_from_db()

        frozen_body = self.proj.frozen_content["body"]
        self.assertNotIn(
            "?v=",
            frozen_body,
            "Non-telegram (FetLife) promotion body must NOT contain ?v= (Fix 1: "
            "URL embed is telegram-only). "
            f"Got frozen_body={frozen_body!r}",
        )
        # The body must be exactly the composed promotion body (no URL suffix).
        expected_body = "NoURL Headline\n\nNoURL body text."
        self.assertEqual(
            frozen_body,
            expected_body,
            "FetLife promotion frozen body must be EXACTLY the composed body — no URL appended. "
            f"Got frozen_body={frozen_body!r}",
        )


# ---------------------------------------------------------------------------
# 5. Fix 2 (review correction): Telegram promotion for organizer-less event raises
# ---------------------------------------------------------------------------


class TelegramPromotionOrganizerlesEventRaisesTest(TestCase):
    """
    Fix 2 (kb-6d7o.2 review correction, ADR-008 D3): when a telegram promotion
    projection's event lacks the organizer (or slug) needed to build the event-detail
    URL, _materialize_promotion_fields must RAISE ValueError at the freeze site with
    a clear message naming the projection and the missing data.

    Silent omission is wrong: the cache-bust silently fails with no error signal.
    """

    def setUp(self):
        self.user = _make_user(username="noorg_user", email="noorg@test.com", password="pw")
        self.profile = _make_profile("NoOrg TG Org", "noorg-tg-org", user=self.user)
        # Event with NO organizer (no EventOrganizer row)
        self.event_no_org = Event.objects.create(
            title="Organizer-less Event",
            slug="organizer-less-event",
            start=timezone.now() + timezone.timedelta(days=7),
        )
        self.tg_conn = _make_telegram_connection(self.profile, destination_id="@noorg-channel")
        self.post = _make_post(self.event_no_org, headline="NoOrg Headline", body="NoOrg body.")
        self.proj = generate_projection(
            kind="promotion",
            connection=self.tg_conn,
            source_post=self.post,
            mode="rule_based",
        )

    def test_telegram_promotion_for_organizer_less_event_raises_at_freeze(self):
        """
        Freezing a telegram promotion projection whose event has no organizer
        must raise ValueError with a descriptive message.

        ADR-008 D3: fail loud — do not silently omit the URL (that would let
        publish succeed with a URL-less body, so the cache-bust silently fails).
        """
        from syndication.engine import transition_status

        with self.assertRaises(ValueError) as ctx:
            transition_status(self.proj, "ready")

        error_msg = str(ctx.exception)
        self.assertIn(
            "telegram",
            error_msg.lower(),
            "The error message must mention 'telegram' so the caller knows which "
            f"platform triggered the constraint. Got: {error_msg!r}",
        )
        self.assertIn(
            "organizer",
            error_msg.lower(),
            "The error message must mention 'organizer' to identify the missing data. "
            f"Got: {error_msg!r}",
        )
