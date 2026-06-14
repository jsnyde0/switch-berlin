"""
TDD tests for the TelegramPlacement model + placement-report API verb +
bot-tier inline write + reconciliation service (kb-56c2.1).

Harness target (from bead --design):
(a) model persists a record per (projection,connection) with the THREE stored
    states {placed, failed, skipped-pre-existing-draft} + unique constraint;
    "sent" absent from the enum;
(b) report verb writes/updates a record under identity auth and returns 422
    on session/content fields;
(c) bot-tier publish path writes placed on Bot-API ok / failed on error inline,
    and fails loud if the placement write diverges from the status transition;
(d) reconciliation returns placed/failed/skipped from records, `pending` for a
    selected bot/agent connection with no record, a `deep-link` affordance for a
    selected public-tier connection (not placed, not pending), and surfaces
    flagged_missing;
(e) no "sent" string in enum/model/serializer.

ADR-018 D2: no "sent" state ever.
ADR-018 D4: report verb rejects session/content fields with 422.
ADR-008 D3: fail loud on bot-tier write divergence; no phantom pending.
ADR-008 D2: no DistributionRun envelope.
"""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile
from syndication.models import (
    IdentityToken,
    PlatformConnection,
    PlatformProjection,
    Post,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _issue_identity_token(user):
    """Helper: issue a fresh identity token for a user."""
    return IdentityToken.issue(user)


def _auth_headers(token: IdentityToken) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}


def _make_profile(slug="placement-test-org"):
    return Profile.objects.create(name="Placement Test Organizer", slug=slug)


def _make_event(slug="placement-test-event", **kwargs):
    defaults = {
        "title": "Placement Test Party",
        "slug": slug,
        "start": timezone.now(),
        "status": "published",
        "visibility": "public",
    }
    defaults.update(kwargs)
    return Event.objects.create(**defaults)


def _make_post(event, headline="Placement Test Post", body="Come join us."):
    return Post.objects.create(event=event, headline=headline, body=body)


def _make_connection(profile, destination_id="-1001234567890", postability="bot", kinds=None, **kwargs):
    """Create a Telegram PlatformConnection with given postability."""
    if kinds is None:
        kinds = ["promotion"]
    return PlatformConnection.objects.create(
        organizer=profile,
        platform="telegram",
        destination_id=destination_id,
        kinds=kinds,
        postability=postability,
        **kwargs,
    )


def _seed_canonical_cv(event):
    """Get-or-create the canonical ContentVersion for an event."""
    from syndication.models import ContentVersion

    cv, _ = ContentVersion.objects.get_or_create(
        event=event,
        name="canonical",
        defaults={"provenance": ContentVersion.Provenance.RULE_TEMPLATE},
    )
    return cv


def _make_ready_promotion_projection(connection, post):
    """Generate a promotion projection and advance it to ready status."""
    from syndication.engine import generate_projection, transition_status

    proj = generate_projection(
        kind="promotion",
        connection=connection,
        source_post=post,
        mode="rule_based",
    )
    transition_status(proj, "ready")
    proj.refresh_from_db()
    return proj


def _make_bot_api_success_response(message_id=42):
    """Return a MagicMock that looks like a successful Telegram Bot API response."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "ok": True,
        "result": {"message_id": message_id},
    }
    return mock_response


def _make_bot_api_error_response():
    """Return a MagicMock that looks like a failed Telegram Bot API response."""
    mock_response = MagicMock()
    mock_response.status_code = 400
    mock_response.json.return_value = {"ok": False, "description": "Bad Request"}
    return mock_response


def _make_vouched_user(username="placement-agent", email="placement@example.com"):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username=username,
        email=email,
        password="testpass",
        status="vouched",
    )


# ---------------------------------------------------------------------------
# (a) + (e): TelegramPlacement model — three stored states, unique constraint,
# no "sent" in enum
# ---------------------------------------------------------------------------


class TelegramPlacementEnumTest(TestCase):
    """
    (a) TelegramPlacementStatus enum has EXACTLY three values:
    {placed, failed, skipped-pre-existing-draft}.
    (e) "sent" is NOT present in the enum.
    """

    def test_stored_status_enum_has_exactly_three_values(self):
        """The placement status enum must define exactly three values."""
        from syndication.models import TelegramPlacementStatus

        values = {v for v, _label in TelegramPlacementStatus.choices}
        self.assertEqual(
            values,
            {"placed", "failed", "skipped-pre-existing-draft"},
            "TelegramPlacementStatus must have exactly three values: "
            "placed, failed, skipped-pre-existing-draft",
        )

    def test_sent_is_not_in_enum(self):
        """'sent' must NOT exist in the placement status enum (ADR-018 D2)."""
        from syndication.models import TelegramPlacementStatus

        values = {v for v, _label in TelegramPlacementStatus.choices}
        self.assertNotIn(
            "sent",
            values,
            "'sent' must NOT be in TelegramPlacementStatus — the machine cannot "
            "observe the human's native send (ADR-018 D2 FIRM draft-only firewall).",
        )

    def test_pending_is_not_in_enum(self):
        """'pending' must NOT be a stored value — it is computed at reconciliation."""
        from syndication.models import TelegramPlacementStatus

        values = {v for v, _label in TelegramPlacementStatus.choices}
        self.assertNotIn(
            "pending",
            values,
            "'pending' must NOT be stored — it is computed at reconciliation "
            "(absence of a record means pending for bot/agent-tier destinations).",
        )


class TelegramPlacementModelTest(TestCase):
    """
    (a) TelegramPlacement model: persists records per (projection, connection),
    unique constraint enforced, all three stored states reachable, nullable
    error_detail, timestamp.
    """

    def setUp(self):
        self.profile = _make_profile(slug="model-test-org")
        self.event = _make_event(slug="model-test-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)
        self.conn = _make_connection(self.profile, destination_id="-1001111111111", postability="bot")
        self.proj = _make_ready_promotion_projection(self.conn, self.post)

    def test_model_can_create_placed_record(self):
        """TelegramPlacement can store a 'placed' status record."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        placement = TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.PLACED,
        )
        fetched = TelegramPlacement.objects.get(pk=placement.pk)
        self.assertEqual(fetched.status, "placed")

    def test_model_can_create_failed_record(self):
        """TelegramPlacement can store a 'failed' status record."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        placement = TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.FAILED,
            error_detail="Bot API returned 400",
        )
        fetched = TelegramPlacement.objects.get(pk=placement.pk)
        self.assertEqual(fetched.status, "failed")
        self.assertEqual(fetched.error_detail, "Bot API returned 400")

    def test_model_can_create_skipped_record(self):
        """TelegramPlacement can store a 'skipped-pre-existing-draft' status record."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        placement = TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.SKIPPED_PRE_EXISTING_DRAFT,
        )
        fetched = TelegramPlacement.objects.get(pk=placement.pk)
        self.assertEqual(fetched.status, "skipped-pre-existing-draft")

    def test_error_detail_is_nullable(self):
        """error_detail is nullable — absent for placed/skipped records."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        placement = TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.PLACED,
        )
        fetched = TelegramPlacement.objects.get(pk=placement.pk)
        self.assertIsNone(fetched.error_detail)

    def test_timestamp_is_set_on_create(self):
        """placed_at timestamp is set on record creation."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        before = timezone.now()
        placement = TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.PLACED,
        )
        self.assertIsNotNone(placement.placed_at)
        self.assertGreaterEqual(placement.placed_at, before)

    def test_unique_constraint_projection_connection(self):
        """Only one TelegramPlacement per (projection, connection) pair."""
        from django.db import IntegrityError

        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        TelegramPlacement.objects.create(
            projection=self.proj,
            connection=self.conn,
            status=TelegramPlacementStatus.PLACED,
        )
        with self.assertRaises(IntegrityError):
            TelegramPlacement.objects.create(
                projection=self.proj,
                connection=self.conn,
                status=TelegramPlacementStatus.FAILED,
                error_detail="duplicate attempt",
            )

    def test_update_or_create_overwrites_existing_record(self):
        """update_or_create can update an existing placement record in place."""
        from syndication.models import TelegramPlacement, TelegramPlacementStatus

        TelegramPlacement.objects.update_or_create(
            projection=self.proj,
            connection=self.conn,
            defaults={"status": TelegramPlacementStatus.FAILED, "error_detail": "first attempt"},
        )
        TelegramPlacement.objects.update_or_create(
            projection=self.proj,
            connection=self.conn,
            defaults={"status": TelegramPlacementStatus.PLACED, "error_detail": None},
        )
        count = TelegramPlacement.objects.filter(projection=self.proj, connection=self.conn).count()
        self.assertEqual(count, 1, "update_or_create must keep exactly one record")
        fetched = TelegramPlacement.objects.get(projection=self.proj, connection=self.conn)
        self.assertEqual(fetched.status, "placed")


# ---------------------------------------------------------------------------
# (b) Report verb — writes record, 422 on forbidden fields
# ---------------------------------------------------------------------------


class TelegramPlacementReportVerbTest(TestCase):
    """
    (b) POST /api/telegram/placements:
    - Writes/updates TelegramPlacement record under identity auth.
    - Returns 422 on session/content fields (ADR-018 D4).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="report-verb-agent", email="report@example.com")
        self.profile = _make_profile(slug="report-verb-org")
        from organizers.models import ProfileClaim

        ProfileClaim.objects.create(user=self.user, profile=self.profile)
        self.token = _issue_identity_token(self.user)
        self.event = _make_event(slug="report-verb-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)
        self.conn = _make_connection(
            self.profile, destination_id="-1009999999999", postability="agent"
        )
        self.proj = _make_ready_promotion_projection(self.conn, self.post)

    def _post_placements(self, payload, token=None):
        """POST to the placements verb with identity-token auth."""
        if token is None:
            token = self.token
        return self.client.post(
            "/api/telegram/placements",
            data=json.dumps(payload),
            content_type="application/json",
            **_auth_headers(token),
        )

    def test_verb_writes_placed_record(self):
        """POST with status=placed creates a TelegramPlacement record."""
        from syndication.models import TelegramPlacement

        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "placed",
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 200, response.content)

        # Assert DB state: record exists
        placement = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).first()
        self.assertIsNotNone(placement, "A TelegramPlacement record must be created")
        self.assertEqual(placement.status, "placed")

    def test_verb_writes_failed_record_with_error_detail(self):
        """POST with status=failed and error_detail stores the error."""
        from syndication.models import TelegramPlacement

        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "failed",
                "error_detail": "saveDraft returned error 400",
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 200, response.content)

        placement = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).first()
        self.assertIsNotNone(placement)
        self.assertEqual(placement.status, "failed")
        self.assertEqual(placement.error_detail, "saveDraft returned error 400")

    def test_verb_writes_skipped_record(self):
        """POST with status=skipped-pre-existing-draft creates a skipped record."""
        from syndication.models import TelegramPlacement

        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "skipped-pre-existing-draft",
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 200, response.content)

        placement = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).first()
        self.assertIsNotNone(placement)
        self.assertEqual(placement.status, "skipped-pre-existing-draft")

    def test_verb_updates_existing_record(self):
        """Re-POST with a different status updates the existing record in place."""
        from syndication.models import TelegramPlacement

        # First POST: failed
        self._post_placements(
            [{"destination_id": self.conn.destination_id, "status": "failed", "error_detail": "first try"}]
        )
        # Second POST: placed (retry succeeded)
        self._post_placements(
            [{"destination_id": self.conn.destination_id, "status": "placed"}]
        )

        count = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).count()
        self.assertEqual(count, 1, "Re-POST must update the existing record, not create a new one")
        fetched = TelegramPlacement.objects.get(projection=self.proj, connection=self.conn)
        self.assertEqual(fetched.status, "placed")

    def test_unauthenticated_request_rejected_401(self):
        """Request without auth must be rejected with HTTP 401."""
        payload = [{"destination_id": self.conn.destination_id, "status": "placed"}]
        response = self.client.post(
            "/api/telegram/placements",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401, response.content)

    def test_payload_with_session_string_rejected_422(self):
        """Payload carrying session_string must be rejected with HTTP 422 (ADR-018 D4)."""
        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "placed",
                "session_string": "AAABBBCCC",  # forbidden field
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_payload_with_access_hash_rejected_422(self):
        """Payload carrying access_hash must be rejected with HTTP 422 (ADR-018 D4)."""
        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "placed",
                "access_hash": 12345678901234567890,  # forbidden field
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_payload_with_content_field_rejected_422(self):
        """Payload carrying a 'content' field must be rejected with HTTP 422 (ADR-018 D4)."""
        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "placed",
                "content": "Some draft text",  # forbidden field
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_no_record_created_when_forbidden_field_rejected(self):
        """When 422 is returned on a forbidden field, no TelegramPlacement is created."""
        from syndication.models import TelegramPlacement

        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "placed",
                "session_string": "leaked-credential",
            }
        ]
        self._post_placements(payload)
        count = TelegramPlacement.objects.filter(connection=self.conn).count()
        self.assertEqual(count, 0, "No placement record must be created when payload is rejected")

    def test_sent_status_rejected_422(self):
        """Attempting to POST status='sent' must be rejected with 422 (ADR-018 D2)."""
        payload = [
            {
                "destination_id": self.conn.destination_id,
                "status": "sent",  # NOT a valid status — must be rejected
            }
        ]
        response = self._post_placements(payload)
        self.assertEqual(
            response.status_code,
            422,
            f"status='sent' must be rejected 422; got: {response.content}",
        )


# ---------------------------------------------------------------------------
# (c) Bot-tier inline write — placed on ok, failed on error, fail-loud on divergence
# ---------------------------------------------------------------------------


class BotTierInlineWriteTest(TestCase):
    """
    (c) publish_telegram_promotion writes a TelegramPlacement record inline
    at call-return. On Bot-API success → placed. On error → failed.
    Fail-loud if placement write diverges from projection status transition
    (ADR-008 D3 phantom-pending guard).
    """

    def setUp(self):
        self.profile = _make_profile(slug="bot-tier-write-org")
        self.event = _make_event(slug="bot-tier-write-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)
        self.conn = _make_connection(self.profile, destination_id="-1001111111111", postability="bot")
        self.proj = _make_ready_promotion_projection(self.conn, self.post)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_bot_api_success_writes_placed_record(self, mock_post):
        """After a successful Bot API call, a TelegramPlacement record with status=placed is created."""
        from syndication.adapters import publish_telegram_promotion
        from syndication.models import TelegramPlacement

        mock_post.return_value = _make_bot_api_success_response(message_id=42)
        publish_telegram_promotion(self.proj)

        placement = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).first()
        self.assertIsNotNone(placement, "A TelegramPlacement record must be created after Bot API success")
        self.assertEqual(placement.status, "placed")

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_bot_api_error_writes_failed_record(self, mock_post):
        """After a Bot API error (400), a TelegramPlacement record with status=failed is created."""
        from syndication.adapters import publish_telegram_promotion
        from syndication.models import TelegramPlacement

        mock_post.return_value = _make_bot_api_error_response()

        with self.assertRaises(ValueError):
            publish_telegram_promotion(self.proj)

        placement = TelegramPlacement.objects.filter(
            projection=self.proj,
            connection=self.conn,
        ).first()
        self.assertIsNotNone(placement, "A TelegramPlacement record must be created even on Bot API failure")
        self.assertEqual(placement.status, "failed")

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_bot_api_success_projection_status_is_published(self, mock_post):
        """After a successful Bot API call, the projection status is published (regression guard)."""
        from syndication.adapters import publish_telegram_promotion

        mock_post.return_value = _make_bot_api_success_response(message_id=42)
        publish_telegram_promotion(self.proj)
        self.proj.refresh_from_db()
        self.assertEqual(self.proj.status, PlatformProjection.Status.PUBLISHED)

    @override_settings(TELEGRAM_BOT_TOKEN="test-bot-token")
    @patch("httpx.post")
    def test_fail_loud_on_placement_write_divergence_raises(self, mock_post):
        """
        ADR-008 D3: if the Bot API succeeds but the placement write fails,
        the function must RAISE (not silently leave a published projection
        with phantom-pending destination).

        We simulate placement write failure by patching TelegramPlacement.objects
        inside the adapter to raise an exception.
        """
        from syndication.adapters import publish_telegram_promotion

        mock_post.return_value = _make_bot_api_success_response(message_id=42)

        # Simulate the placement write failing (e.g., DB error)
        with patch("syndication.adapters.TelegramPlacement") as mock_placement_cls:
            mock_manager = MagicMock()
            mock_placement_cls.objects = mock_manager
            mock_manager.update_or_create.side_effect = Exception("DB write failure")

            with self.assertRaises(Exception) as ctx:
                publish_telegram_promotion(self.proj)

            # The exception must propagate — it must NOT be silently swallowed
            self.assertIn("DB write failure", str(ctx.exception))


# ---------------------------------------------------------------------------
# (d) Reconciliation service
# ---------------------------------------------------------------------------


class ReconciliationServiceTest(TestCase):
    """
    (d) reconcile_telegram_coverage returns:
    - placed/failed/skipped from records for bot/agent connections with records
    - 'pending' for selected bot/agent connections with no record
    - deep-link affordance for selected public-tier connections (NOT placed, NOT pending)
    - flagged_missing destinations surfaced as flagged
    """

    def setUp(self):
        self.profile = _make_profile(slug="reconcile-test-org")
        self.event = _make_event(slug="reconcile-test-event")
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        self.post = _make_post(self.event)

    def _make_conn(self, destination_id, postability="bot", flagged=False, promoted=True):
        kinds = ["promotion"] if promoted else []
        return _make_connection(
            self.profile,
            destination_id=destination_id,
            postability=postability,
            kinds=kinds,
            flagged_missing=flagged,
        )

    def _make_placement(self, proj, conn, status, error_detail=None):
        from syndication.models import TelegramPlacement

        placement, _ = TelegramPlacement.objects.update_or_create(
            projection=proj,
            connection=conn,
            defaults={"status": status, "error_detail": error_detail},
        )
        return placement

    def test_placed_record_returns_placed_status(self):
        """A bot-tier connection with a placed record returns status='placed'."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001111111111", postability="bot")
        proj = _make_ready_promotion_projection(conn, self.post)
        self._make_placement(proj, conn, "placed")

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "placed")

    def test_failed_record_returns_failed_status(self):
        """A bot-tier connection with a failed record returns status='failed'."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001222222222", postability="bot")
        proj = _make_ready_promotion_projection(conn, self.post)
        self._make_placement(proj, conn, "failed", error_detail="Bot rejected")

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_detail"], "Bot rejected")

    def test_skipped_record_returns_skipped_status(self):
        """An agent-tier connection with a skipped record returns status='skipped-pre-existing-draft'."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001333333333", postability="agent")
        proj = _make_ready_promotion_projection(conn, self.post)
        self._make_placement(proj, conn, "skipped-pre-existing-draft")

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "skipped-pre-existing-draft")

    def test_bot_tier_no_record_returns_pending(self):
        """A selected bot-tier connection with no record returns status='pending'."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001444444444", postability="bot")
        proj = _make_ready_promotion_projection(conn, self.post)
        # No TelegramPlacement record for this connection

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["status"],
            "pending",
            "A selected bot-tier connection with no record must return 'pending'",
        )

    def test_agent_tier_no_record_returns_pending(self):
        """A selected agent-tier connection with no record returns status='pending'."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001555555555", postability="agent")
        proj = _make_ready_promotion_projection(conn, self.post)
        # No TelegramPlacement record for this connection

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertEqual(
            result["status"],
            "pending",
            "A selected agent-tier connection with no record must return 'pending'",
        )

    def test_public_tier_returns_deep_link_affordance_not_placed_not_pending(self):
        """
        A selected public-tier connection returns a 'deep-link' affordance
        — NOT 'placed', NOT 'pending' (ADR-018 D2 / kb-56c2 D6).
        """
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001666666666", postability="public")
        proj = _make_ready_promotion_projection(conn, self.post)
        # No TelegramPlacement record (public-tier never receives a bot/agent record)

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertNotEqual(
            result["status"],
            "placed",
            "Public-tier connection must NOT return 'placed' (fabricated state, ADR-018 D2)",
        )
        self.assertNotEqual(
            result["status"],
            "pending",
            "Public-tier connection must NOT return 'pending' (silent ghost, ADR-008 D3)",
        )
        self.assertEqual(
            result["status"],
            "deep-link",
            "Public-tier connection must return 'deep-link' human-action affordance (kb-56c2 D6)",
        )

    def test_flagged_missing_connection_surfaced_flagged(self):
        """A flagged_missing connection must be surfaced with is_flagged_missing=True."""
        from syndication.services import reconcile_telegram_coverage

        conn = self._make_conn("-1001777777777", postability="agent", flagged=True)
        proj = _make_ready_promotion_projection(conn, self.post)

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == conn.pk), None)
        self.assertIsNotNone(result)
        self.assertTrue(
            result.get("is_flagged_missing"),
            "A flagged_missing connection must be surfaced with is_flagged_missing=True",
        )

    def test_pending_not_returned_for_public_tier_no_record(self):
        """
        Public-tier destinations with no record must NOT appear as 'pending'
        (they are outside the four-state machine — D6 exclusion).
        """
        from syndication.services import reconcile_telegram_coverage

        public_conn = self._make_conn("-1001888888888", postability="public")
        proj = _make_ready_promotion_projection(public_conn, self.post)

        results = reconcile_telegram_coverage(projection=proj)
        result = next((r for r in results if r["connection_id"] == public_conn.pk), None)
        self.assertIsNotNone(result)
        self.assertNotEqual(
            result["status"],
            "pending",
            "Public-tier connection must NEVER appear as 'pending' (D6 exclusion)",
        )

    def test_no_sent_status_in_reconciliation_output(self):
        """
        (e) 'sent' must never appear in reconciliation output (ADR-018 D2).
        """
        from syndication.services import reconcile_telegram_coverage

        conn_bot = self._make_conn("-1001991111111", postability="bot")
        conn_agent = self._make_conn("-1001992222222", postability="agent")
        conn_public = self._make_conn("-1001993333333", postability="public")
        proj = _make_ready_promotion_projection(conn_bot, self.post)

        results = reconcile_telegram_coverage(projection=proj)
        for result in results:
            self.assertNotEqual(
                result.get("status"),
                "sent",
                f"'sent' must NEVER appear in reconciliation output — got {result}",
            )

    def test_mixed_tier_returns_all_correct_statuses(self):
        """
        Mixed scenario: bot+placed, agent+no-record, public → correct statuses.
        """
        from syndication.services import reconcile_telegram_coverage

        bot_conn = self._make_conn("-1002001111111", postability="bot")
        agent_conn = self._make_conn("-1002002222222", postability="agent")
        public_conn = self._make_conn("-1002003333333", postability="public")
        proj = _make_ready_promotion_projection(bot_conn, self.post)

        # Add agent and public projections for same post
        from syndication.engine import generate_projection, transition_status

        agent_proj = generate_projection(
            kind="promotion",
            connection=agent_conn,
            source_post=self.post,
            mode="rule_based",
        )
        transition_status(agent_proj, "ready")
        public_proj = generate_projection(
            kind="promotion",
            connection=public_conn,
            source_post=self.post,
            mode="rule_based",
        )
        transition_status(public_proj, "ready")

        self._make_placement(proj, bot_conn, "placed")
        # agent and public have no placement records

        results = reconcile_telegram_coverage(projection=proj)
        statuses = {r["connection_id"]: r["status"] for r in results}

        self.assertEqual(statuses[bot_conn.pk], "placed")
        self.assertIn(agent_conn.pk, statuses)
        self.assertEqual(statuses[agent_conn.pk], "pending")
        self.assertIn(public_conn.pk, statuses)
        self.assertEqual(statuses[public_conn.pk], "deep-link")
