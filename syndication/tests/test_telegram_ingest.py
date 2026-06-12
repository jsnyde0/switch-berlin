"""
TDD tests for the Telegram-inventory ingest API verb (kb-ru55.2).

Contract:
- PlatformConnection gains topic_id, type, title, postability fields via migration.
- POST /api/telegram/inventory upserts one PlatformConnection per postable destination
  (topic_id set for forum-topic rows). Auth: identity-token (IdentityTokenAuth).
- Payload carrying content / access_hash / session material → HTTP 422 (fail loud,
  ADR-008 D3, bead D2).
- Re-POST is idempotent — no duplicate rows (assert by row count).
- A destination absent from a later sync is flagged (not deleted, ADR-008 D3, bead D3).
- Cross-surface equality: stored `type` values == canonical TelegramDialogType set
  (NOT a substring check — a value like `forum_group` outside the set must FAIL).

Asserts DB state, not just response codes (per harness.md Templates § guidance).
"""

from django.test import TestCase

from organizers.models import Profile
from syndication.models import (
    IdentityToken,
    PlatformConnection,
    TelegramDialogType,
    TelegramPostability,
)


def _issue_identity_token(user):
    """Helper: issue a fresh identity token for a user."""
    return IdentityToken.issue(user)


def _auth_headers(token: IdentityToken) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}


class TelegramDialogTypeChoicesTest(TestCase):
    """
    Cross-surface equality: TelegramDialogType must define EXACTLY the canonical
    set (channel, group, supergroup, forum_topic). A value outside this set
    (e.g. forum_group) must fail this test.

    This is D1a in kb-ru55.2 — the SINGLE resolution point for the type vocabulary.
    kb-sbhs's picker reads this same set; any drift here is an enum-vocabulary-drift.
    """

    def test_canonical_type_set_is_exactly_channel_group_supergroup_forum_topic(self):
        """
        The canonical TelegramDialogType values must equal exactly:
        {channel, group, supergroup, forum_topic}

        This is a cross-surface equality assertion per bead D1a and commit e93c4ec.
        A value like 'forum_group' not in this set must cause this test to fail.
        """
        canonical_values = {v for v, _label in TelegramDialogType.choices}
        self.assertEqual(
            canonical_values,
            {"channel", "group", "supergroup", "forum_topic"},
            "TelegramDialogType values must be exactly: channel, group, supergroup, "
            "forum_topic — not a superset or subset. If you add 'forum_group' here "
            "that would constitute enum-vocabulary-drift from kb-sbhs's picker tree.",
        )

    def test_divergent_value_forum_group_is_not_in_canonical_set(self):
        """
        Explicitly assert a known-wrong value is NOT in the set.
        This ensures the test cannot pass trivially with a superset.
        """
        canonical_values = {v for v, _label in TelegramDialogType.choices}
        self.assertNotIn(
            "forum_group",
            canonical_values,
            "forum_group must NOT be in TelegramDialogType — it is NOT a postable "
            "destination (a forum group is not postable; only specific topics are).",
        )


class TelegramPostabilityChoicesTest(TestCase):
    """
    Cross-surface equality: TelegramPostability must define EXACTLY the canonical
    set (bot, agent, public). A value outside this set must fail this test.

    This is Finding 1 from the re-verify of kb-ru55.2 — the SINGLE resolution
    point for the postability vocabulary. kb-sbhs's capability-ladder picker
    reads this same set; any drift here silently breaks the picker (ADR-008 D3).
    """

    def test_canonical_postability_set_is_exactly_bot_agent_public(self):
        """
        The canonical TelegramPostability values must equal exactly:
        {bot, agent, public}

        This is a cross-surface equality assertion (not substring) per bead D1a
        intent and commit e93c4ec pattern. A value like 'admin' not in this set
        must cause this test to fail.
        """
        canonical_values = {v for v, _label in TelegramPostability.choices}
        self.assertEqual(
            canonical_values,
            {"bot", "agent", "public"},
            "TelegramPostability values must be exactly: bot, agent, public — "
            "not a superset or subset. This set matches the capability-ladder tiers "
            "documented in kb-sbhs D4 picker rendering.",
        )

    def test_divergent_value_admin_is_not_in_canonical_postability_set(self):
        """
        Explicitly assert a known-wrong value is NOT in the set.
        This ensures the test cannot pass trivially with a superset.
        """
        canonical_values = {v for v, _label in TelegramPostability.choices}
        self.assertNotIn(
            "admin",
            canonical_values,
            "admin must NOT be in TelegramPostability — it is not a capability-ladder tier.",
        )


class PlatformConnectionFieldsTest(TestCase):
    """
    Migration adds four new fields to PlatformConnection:
      - topic_id (nullable BigIntegerField)
      - type (nullable CharField with TelegramDialogType choices)
      - title (nullable CharField)
      - postability (nullable CharField)

    Also includes a flagged_missing field for vanished-destination tracking (D3).
    """

    def setUp(self):
        self.profile = Profile.objects.create(
            name="Telegram Test Organizer",
            slug="telegram-test-org",
        )

    def test_platform_connection_has_topic_id_field(self):
        """topic_id is nullable — set for forum_topic rows, null for others."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567890",
            topic_id=12345,
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.topic_id, 12345)

    def test_platform_connection_topic_id_is_nullable(self):
        """topic_id must be nullable for non-forum-topic rows."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567891",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertIsNone(fetched.topic_id)

    def test_platform_connection_has_type_field(self):
        """type stores the TelegramDialogType value."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567892",
            type=TelegramDialogType.CHANNEL,
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.type, TelegramDialogType.CHANNEL)

    def test_platform_connection_type_is_nullable(self):
        """type is nullable (non-Telegram connections have no type)."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertIsNone(fetched.type)

    def test_platform_connection_has_title_field(self):
        """title stores the human-readable dialog name."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567893",
            title="My Kinky Channel",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.title, "My Kinky Channel")

    def test_platform_connection_title_is_nullable(self):
        """title is nullable for non-Telegram connections."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user2",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertIsNone(fetched.title)

    def test_platform_connection_has_postability_field(self):
        """postability stores the capability-ladder tier (e.g. 'bot', 'agent', 'public')."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567894",
            postability="bot",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertEqual(fetched.postability, "bot")

    def test_platform_connection_postability_is_nullable(self):
        """postability is nullable for non-Telegram connections."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="fetlife",
            destination_id="fl-user3",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertIsNone(fetched.postability)

    def test_platform_connection_has_flagged_missing_field(self):
        """flagged_missing supports vanished-destination detection (bead D3)."""
        conn = PlatformConnection.objects.create(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001234567895",
        )
        fetched = PlatformConnection.objects.get(pk=conn.pk)
        self.assertFalse(fetched.flagged_missing)


class TelegramInventoryIngestTest(TestCase):
    """
    Core ingest verb tests: POST /api/telegram/inventory
    - Upserts one PlatformConnection per postable destination.
    - Sets topic_id for forum_topic rows.
    - Idempotent (no duplicate rows on re-POST).
    - Rejects payloads carrying content/access_hash/session material → 422.
    - Flags vanished destinations, never deletes them.

    Asserts DB state (row count + field values), not just HTTP status codes.
    """

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.user = User.objects.create_user(
            username="telegram-test-agent",
            email="agent@example.com",
            password="testpass",
            status="vouched",
        )
        self.profile = Profile.objects.create(
            name="Telegram Ingest Organizer",
            slug="telegram-ingest-org",
        )
        # Bind user to profile via ProfileClaim
        from organizers.models import ProfileClaim

        ProfileClaim.objects.create(
            user=self.user,
            profile=self.profile,
        )
        self.token = _issue_identity_token(self.user)

    def _post_inventory(self, payload, token=None):
        """POST to the ingest verb with identity-token auth."""
        import json

        if token is None:
            token = self.token
        return self.client.post(
            "/api/telegram/inventory",
            data=json.dumps(payload),
            content_type="application/json",
            **_auth_headers(token),
        )

    # ----- happy-path upsert -----

    def test_ingest_creates_one_row_per_postable_destination(self):
        """
        POST a 3-item inventory (channel, group, forum_topic) — expect 3 rows
        (all postable by definition since the agent sends only postable ones).
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
            },
            {
                "chat_id": "-1002222222222",
                "title": "Private Group",
                "type": "group",
                "postability": "agent",
            },
            {
                "chat_id": "-1003333333333",
                "title": "General",
                "type": "forum_topic",
                "topic_id": 1,
                "postability": "agent",
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 200, response.content)

        # Assert DB state: 3 rows created for this organizer
        conns = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        )
        self.assertEqual(conns.count(), 3)

    def test_ingest_sets_topic_id_for_forum_topic_rows(self):
        """forum_topic rows must have topic_id set from the payload."""
        payload = [
            {
                "chat_id": "-1003333333333",
                "title": "General",
                "type": "forum_topic",
                "topic_id": 42,
                "postability": "agent",
            },
        ]
        self._post_inventory(payload)
        conn = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1003333333333",
        )
        self.assertEqual(conn.topic_id, 42)
        self.assertEqual(conn.type, "forum_topic")

    def test_ingest_topic_id_null_for_non_forum_rows(self):
        """Non-forum-topic rows must have topic_id=None."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload)
        conn = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        )
        self.assertIsNone(conn.topic_id)

    def test_ingest_stores_title_and_postability(self):
        """title and postability are stored on the PlatformConnection row."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Public Channel",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload)
        conn = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        )
        self.assertEqual(conn.title, "My Public Channel")
        self.assertEqual(conn.postability, "bot")

    # ----- idempotency -----

    def test_repost_same_inventory_is_idempotent(self):
        """Re-POST of the same inventory must NOT create duplicate rows."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload)
        self._post_inventory(payload)

        count = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        ).count()
        self.assertEqual(count, 1, "Re-POST must be idempotent — no duplicate rows")

    def test_repost_updates_fields_on_existing_row(self):
        """Re-POST with updated title must update the existing row, not create a new one."""
        payload_v1 = [
            {
                "chat_id": "-1001111111111",
                "title": "Original Title",
                "type": "channel",
                "postability": "bot",
            },
        ]
        payload_v2 = [
            {
                "chat_id": "-1001111111111",
                "title": "Updated Title",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload_v1)
        self._post_inventory(payload_v2)

        conn = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        )
        self.assertEqual(conn.title, "Updated Title")
        total_count = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        ).count()
        self.assertEqual(total_count, 1, "Must still be exactly one row after re-POST")

    # ----- vanished-destination flagging -----

    def test_vanished_destination_is_flagged_not_deleted(self):
        """
        A destination present in a prior sync but absent from a later sync
        must be FLAGGED (flagged_missing=True), NOT deleted (ADR-008 D3, bead D3).
        """
        # First sync: two destinations
        payload_v1 = [
            {
                "chat_id": "-1001111111111",
                "title": "Channel A",
                "type": "channel",
                "postability": "bot",
            },
            {
                "chat_id": "-1002222222222",
                "title": "Channel B",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload_v1)

        # Second sync: only one destination (Channel B vanished)
        payload_v2 = [
            {
                "chat_id": "-1001111111111",
                "title": "Channel A",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload_v2)

        # Channel B must still exist but be flagged
        conn_b = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1002222222222",
        )
        self.assertTrue(
            conn_b.flagged_missing,
            "Vanished destination must be flagged (flagged_missing=True), not deleted",
        )

        # Channel A must NOT be flagged
        conn_a = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        )
        self.assertFalse(conn_a.flagged_missing)

        # Total row count: still 2 (not deleted)
        total = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        ).count()
        self.assertEqual(total, 2, "Vanished destination must not be deleted")

    def test_reflagged_destination_is_unflagged_on_reappearance(self):
        """A destination that was flagged missing and reappears must be un-flagged."""
        # Sync 1: two channels
        payload_v1 = [
            {
                "chat_id": "-1001111111111",
                "title": "Channel A",
                "type": "channel",
                "postability": "bot",
            },
            {
                "chat_id": "-1002222222222",
                "title": "Channel B",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload_v1)

        # Sync 2: Channel B vanishes
        payload_v2 = [
            {
                "chat_id": "-1001111111111",
                "title": "Channel A",
                "type": "channel",
                "postability": "bot",
            },
        ]
        self._post_inventory(payload_v2)

        # Sync 3: Channel B comes back
        self._post_inventory(payload_v1)

        conn_b = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1002222222222",
        )
        self.assertFalse(
            conn_b.flagged_missing,
            "Destination that reappears after being flagged must be un-flagged",
        )

    # ----- content/credential rejection (D2 — fail loud) -----

    def test_payload_with_session_string_is_rejected_422(self):
        """Payload carrying session_string must be rejected with HTTP 422."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
                "session_string": "AAABBBCCC",  # forbidden field
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_payload_with_access_hash_is_rejected_422(self):
        """Payload carrying access_hash must be rejected with HTTP 422."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
                "access_hash": 12345678901234567890,  # forbidden field
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_payload_with_content_field_is_rejected_422(self):
        """Payload carrying a 'content' field must be rejected with HTTP 422."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
                "content": "Some message text",  # forbidden field
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 422, response.content)

    def test_no_rows_created_when_payload_rejected(self):
        """When 422 is returned, no PlatformConnection rows should be created."""
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
                "session_string": "AAABBBCCC",
            },
        ]
        self._post_inventory(payload)
        count = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        ).count()
        self.assertEqual(count, 0, "No rows must be created when payload is rejected")

    # ----- auth -----

    def test_unauthenticated_request_is_rejected_401(self):
        """Request without auth must be rejected with HTTP 401."""
        import json

        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
            },
        ]
        response = self.client.post(
            "/api/telegram/inventory",
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401, response.content)

    # ----- Finding 1: non-canonical type value rejected at ingest boundary (D1a) -----

    def test_non_canonical_type_value_is_rejected_422(self):
        """
        A payload with a non-canonical type value (e.g. 'forum_group') must be
        rejected with HTTP 422 at the API boundary — NOT stored.

        This is Finding 1 from the review: the enum guard must be enforced at
        ingest, not just at definition. A type not in TelegramDialogType is
        arbitrary-string drift (ADR-018 D4 / D1a single-resolution-point intent).
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "Some Forum Group",
                "type": "forum_group",  # NOT in canonical TelegramDialogType set
                "postability": "agent",
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(
            response.status_code,
            422,
            f"Non-canonical type 'forum_group' must be rejected 422; got: {response.content}",
        )

    def test_non_canonical_type_not_stored(self):
        """
        When a non-canonical type value is rejected, no PlatformConnection row
        must be created.
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "Some Forum Group",
                "type": "forum_group",
                "postability": "agent",
            },
        ]
        self._post_inventory(payload)
        count = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        ).count()
        self.assertEqual(count, 0, "No row must be created for a non-canonical type value")

    # ----- Finding 1 (re-verify): non-canonical postability value rejected at ingest boundary -----

    def test_non_canonical_postability_value_is_rejected_422(self):
        """
        A payload with a non-canonical postability value (e.g. 'bogus') must be
        rejected with HTTP 422 at the API boundary — NOT stored.

        Finding 1 (re-verify kb-ru55.2): postability was left soft (plain str).
        Now constrained to TelegramPostability enum values: bot, agent, public.
        A non-canonical value must be rejected loud (ADR-008 D3).
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bogus",  # NOT in canonical TelegramPostability set
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(
            response.status_code,
            422,
            f"Non-canonical postability 'bogus' must be rejected 422; got: {response.content}",
        )

    def test_non_canonical_postability_not_stored(self):
        """
        When a non-canonical postability value is rejected, no PlatformConnection row
        must be created.
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bogus",
            },
        ]
        self._post_inventory(payload)
        count = PlatformConnection.objects.filter(
            organizer=self.profile,
            platform="telegram",
        ).count()
        self.assertEqual(count, 0, "No row must be created for a non-canonical postability value")

    def test_valid_postability_agent_ingests_fine(self):
        """
        A payload with a valid postability value 'agent' must be accepted (HTTP 200).
        Regression guard: ensuring the constraint doesn't over-block.
        """
        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "Private Group",
                "type": "group",
                "postability": "agent",
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 200, response.content)
        conn = PlatformConnection.objects.get(
            organizer=self.profile,
            platform="telegram",
            destination_id="-1001111111111",
        )
        self.assertEqual(conn.postability, "agent")

    # ----- Finding 4: response body shape pinned -----

    def test_happy_path_response_body_shape(self):
        """
        A successful ingest must return JSON with exactly the keys 'upserted' and
        'flagged' — so a future return-key rename can't silently break the contract.

        Finding 4: the response body shape was previously unpinned.
        """
        import json

        payload = [
            {
                "chat_id": "-1001111111111",
                "title": "My Channel",
                "type": "channel",
                "postability": "bot",
            },
            {
                "chat_id": "-1002222222222",
                "title": "Private Group",
                "type": "group",
                "postability": "agent",
            },
        ]
        response = self._post_inventory(payload)
        self.assertEqual(response.status_code, 200, response.content)
        data = json.loads(response.content)
        self.assertIn("upserted", data, "Response must contain 'upserted' key")
        self.assertIn("flagged", data, "Response must contain 'flagged' key")
        self.assertEqual(data["upserted"], 2, "upserted count must equal number of items")
        self.assertEqual(data["flagged"], 0, "flagged count must be 0 when no rows vanished")
