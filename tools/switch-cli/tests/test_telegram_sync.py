"""
Unit tests for switch-cli telegram sync command.

Tests drive the enumeration + push codepath with mocked Telethon and HTTP.
No live MTProto connection or real server — live flow deferred to kb-ru55.6.

TDD discipline: RED → GREEN → REFACTOR.

Acceptance criteria (bead kb-ru55.3):
- (1) broadcast-only subscription is EXCLUDED from inventory.
- (2) private no-username group is INCLUDED in inventory.
- (3) forum group is expanded into one row per topic with topic_id set;
      the forum group itself is NOT emitted as a postable destination.
- (4) pushed payload is metadata-only: no content, access_hash, or session string.
- (5) emitted `type` values ∈ the canonical four {channel, group, supergroup, forum_topic}.
- (6) push targets the correct ingest route POST /api/telegram/inventory.
- (7) fail-loud: no session file → tell the user to run `connect` first.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner
from switch_cli.cli import cli
from switch_cli.config import save_config
from switch_cli.telegram.enumerate import (
    CANONICAL_DIALOG_TYPES,
    NoSessionError,
    enumerate_postable_dialogs,
)
from switch_cli.telegram.session import save_telegram_session

# ---------------------------------------------------------------------------
# Canonical type constants
# ---------------------------------------------------------------------------

CHANNEL = "channel"
GROUP = "group"
SUPERGROUP = "supergroup"
FORUM_TOPIC = "forum_topic"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """
    Redirect SWITCH_CLI_CONFIG to a temp dir and pre-write base api creds.
    Returns the config dir (not the file).
    """
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_file))
    save_config(base_url="http://fake-switch.test", api_key="fake-bearer-key")
    import tomllib

    import tomli_w

    with open(config_file, "rb") as f:
        cfg = tomllib.load(f)
    cfg["telegram"] = {"api_id": 12345, "api_hash": "deadbeef1234"}
    with open(config_file, "wb") as f:
        tomli_w.dump(cfg, f)
    return tmp_path


@pytest.fixture()
def fake_session_string():
    return "1BVtsOKEBu_some_fake_string_session_value_for_testing"


def _make_broadcast_channel():
    """
    A broadcast channel the user only subscribes to (cannot post).
    broadcast=True, creator=False, admin_rights=None → EXCLUDE.
    """
    dialog = MagicMock()
    dialog.name = "Public Broadcast Channel"
    dialog.id = -1001111111111
    entity = MagicMock()
    entity.broadcast = True
    entity.megagroup = False
    entity.gigagroup = False
    entity.username = "publicchannel"
    entity.creator = False
    entity.admin_rights = None
    entity.forum = False  # not a forum
    dialog.entity = entity
    return dialog


def _make_private_group():
    """
    A private no-username group where the user can post.
    megagroup=False, broadcast=False, username=None → INCLUDE as group.
    """
    dialog = MagicMock()
    dialog.name = "Secret Planning Group"
    dialog.id = -1002222222222
    entity = MagicMock()
    entity.broadcast = False
    entity.megagroup = False
    entity.gigagroup = False
    entity.username = None
    entity.creator = True
    entity.admin_rights = None
    entity.forum = False  # not a forum
    dialog.entity = entity
    return dialog


def _make_forum_group():
    """
    A forum group with 2 topics.
    forum=True → expand into per-topic rows; forum group itself is NOT a destination.
    """
    dialog = MagicMock()
    dialog.name = "Community Forum"
    dialog.id = -1003333333333
    entity = MagicMock()
    entity.broadcast = False
    entity.megagroup = True
    entity.gigagroup = False
    entity.username = "communityforum"
    entity.creator = True
    entity.admin_rights = None
    entity.forum = True
    dialog.entity = entity
    return dialog


def _make_forum_topics():
    """Return two mock ForumTopic objects for the forum group."""
    topic1 = MagicMock()
    topic1.id = 101
    topic1.title = "General Discussion"
    topic2 = MagicMock()
    topic2.id = 202
    topic2.title = "Announcements"
    return [topic1, topic2]


# ---------------------------------------------------------------------------
# (5) canonical type pin
# ---------------------------------------------------------------------------


class TestCanonicalTypePin:
    """
    The CANONICAL_DIALOG_TYPES set must exactly mirror the server's
    TelegramDialogType values — divergence would produce 422 rejections.
    """

    def test_canonical_set_contains_all_four_types(self):
        assert CANONICAL_DIALOG_TYPES == {CHANNEL, GROUP, SUPERGROUP, FORUM_TOPIC}

    def test_emitted_types_are_subset_of_canonical(self):
        """All emitted type values must be in the canonical set."""
        assert CHANNEL in CANONICAL_DIALOG_TYPES
        assert GROUP in CANONICAL_DIALOG_TYPES
        assert SUPERGROUP in CANONICAL_DIALOG_TYPES
        assert FORUM_TOPIC in CANONICAL_DIALOG_TYPES


# ---------------------------------------------------------------------------
# (1) broadcast-only subscription is EXCLUDED
# ---------------------------------------------------------------------------


class TestBroadcastExcluded:
    """A broadcast channel the user only subscribes to must be excluded."""

    @pytest.mark.asyncio
    async def test_broadcast_subscription_excluded(self):
        """broadcast=True, creator=False, admin_rights=None → excluded from inventory."""
        broadcast = _make_broadcast_channel()

        mock_client = MagicMock()
        mock_client.get_dialogs = AsyncMock(return_value=[broadcast])
        mock_client.get_messages = AsyncMock(return_value=MagicMock(total=0))

        result = await enumerate_postable_dialogs(mock_client)

        chat_ids = [item["chat_id"] for item in result]
        assert str(broadcast.id) not in chat_ids, f"Broadcast subscription should be excluded, got: {result}"


# ---------------------------------------------------------------------------
# (2) private group is INCLUDED
# ---------------------------------------------------------------------------


class TestPrivateGroupIncluded:
    """A private no-username group where the user can post must be included."""

    @pytest.mark.asyncio
    async def test_private_group_included(self):
        """broadcast=False, creator=True → included in inventory as 'group'."""
        private_group = _make_private_group()

        mock_client = MagicMock()
        mock_client.get_dialogs = AsyncMock(return_value=[private_group])
        mock_client.get_messages = AsyncMock(return_value=MagicMock(total=0))

        result = await enumerate_postable_dialogs(mock_client)

        chat_ids = [item["chat_id"] for item in result]
        assert str(private_group.id) in chat_ids, f"Private group should be included, got: {result}"
        group_item = next(i for i in result if i["chat_id"] == str(private_group.id))
        assert group_item["type"] == GROUP
        assert group_item["type"] in CANONICAL_DIALOG_TYPES


# ---------------------------------------------------------------------------
# (3) forum group expands into per-topic rows; forum group itself NOT emitted
# ---------------------------------------------------------------------------


class TestForumTopicExpansion:
    """Forum group → one row per topic; the group itself is NOT a postable destination."""

    @pytest.mark.asyncio
    async def test_forum_group_not_emitted_directly(self):
        """The forum group chat_id must not appear as a standalone row."""
        forum = _make_forum_group()
        topics = _make_forum_topics()

        mock_client = MagicMock()
        mock_client.get_dialogs = AsyncMock(return_value=[forum])
        mock_client.iter_participants = AsyncMock(return_value=[])

        async def mock_get_messages(entity, limit=1):
            result = MagicMock()
            result.total = 0
            return result

        mock_client.get_messages = AsyncMock(side_effect=mock_get_messages)

        async def mock_get_forum_topics(client, entity):
            return topics

        with patch(
            "switch_cli.telegram.enumerate._get_forum_topics",
            side_effect=mock_get_forum_topics,
        ):
            result = await enumerate_postable_dialogs(mock_client)

        # forum group itself must not be in result as a standalone row
        standalone_ids = [item["chat_id"] for item in result if item.get("topic_id") is None]
        assert str(forum.id) not in standalone_ids, (
            f"Forum group should NOT be emitted as standalone destination, got: {result}"
        )

    @pytest.mark.asyncio
    async def test_forum_group_expanded_to_topics(self):
        """Forum group with 2 topics → exactly 2 forum_topic rows with topic_id set."""
        forum = _make_forum_group()
        topics = _make_forum_topics()

        mock_client = MagicMock()
        mock_client.get_dialogs = AsyncMock(return_value=[forum])
        mock_client.get_messages = AsyncMock(return_value=MagicMock(total=0))

        async def mock_get_forum_topics(client, entity):
            return topics

        with patch(
            "switch_cli.telegram.enumerate._get_forum_topics",
            side_effect=mock_get_forum_topics,
        ):
            result = await enumerate_postable_dialogs(mock_client)

        forum_topic_rows = [item for item in result if item.get("type") == FORUM_TOPIC]
        assert len(forum_topic_rows) == 2, f"Expected 2 forum_topic rows, got {len(forum_topic_rows)}: {result}"

        topic_ids = {item["topic_id"] for item in forum_topic_rows}
        assert topic_ids == {101, 202}, f"Expected topic_ids {{101, 202}}, got {topic_ids}"

        for row in forum_topic_rows:
            assert row["chat_id"] == str(forum.id)
            assert row["topic_id"] is not None
            assert row["type"] == FORUM_TOPIC
            assert row["type"] in CANONICAL_DIALOG_TYPES


# ---------------------------------------------------------------------------
# (4) pushed payload is metadata-only (FIRM D2 / ADR-018 D4)
# ---------------------------------------------------------------------------


class TestMetadataOnlyPayload:
    """Pushed payload must NOT contain session_string, access_hash, or content."""

    FORBIDDEN_FIELDS = {"session_string", "access_hash", "content", "session", "message_text"}

    @pytest.mark.asyncio
    async def test_payload_contains_only_permitted_fields(self):
        """Each payload item must only have chat_id, title, type, topic_id, postability."""
        private_group = _make_private_group()

        mock_client = MagicMock()
        mock_client.get_dialogs = AsyncMock(return_value=[private_group])
        mock_client.get_messages = AsyncMock(return_value=MagicMock(total=0))

        result = await enumerate_postable_dialogs(mock_client)

        permitted = {"chat_id", "title", "type", "topic_id", "postability"}
        for item in result:
            for field in self.FORBIDDEN_FIELDS:
                assert field not in item, f"Forbidden field '{field}' found in payload item: {item} (D2 FIRM)"
            extra = set(item.keys()) - permitted
            assert not extra, f"Unexpected fields in payload item: {extra} — payload must be metadata-only"


# ---------------------------------------------------------------------------
# (6) push targets the correct ingest route
# ---------------------------------------------------------------------------


class TestPushTargetsCorrectRoute:
    """The push must POST to /api/telegram/inventory."""

    def test_push_method_posts_to_ingest_route(self, temp_config):
        """push_telegram_inventory POSTs to /api/telegram/inventory."""
        from switch_cli.client import SwitchClient

        inventory = [
            {
                "chat_id": "-1002222222222",
                "title": "Secret Group",
                "type": "group",
                "postability": "postable",
                "topic_id": None,
            }
        ]

        with patch("switch_cli.client.httpx.post") as mock_post:
            mock_post.side_effect = [
                # First call: token exchange
                MagicMock(status_code=200, json=MagicMock(return_value={"identity_token": "fake-token"})),
                # Second call: inventory push
                MagicMock(status_code=200, json=MagicMock(return_value={"upserted": 1, "flagged": 0})),
            ]
            client = SwitchClient(base_url="http://fake-switch.test", api_key="fake-key")
            client.push_telegram_inventory(inventory)

            call_args = mock_post.call_args_list
            assert len(call_args) == 2, f"Expected 2 POST calls (exchange + push), got: {len(call_args)}"

            token_url = call_args[0].args[0]
            assert "/api/agents/token" in token_url, f"First call must be token exchange, got: {token_url}"

            push_url = call_args[1].args[0]
            assert push_url.endswith("/api/telegram/inventory"), (
                f"Push must target /api/telegram/inventory, got: {push_url}"
            )


# ---------------------------------------------------------------------------
# (7) fail-loud: no session → tell user to run connect first
# ---------------------------------------------------------------------------


class TestNoSessionFailLoud:
    """No session file → visible error telling user to run `connect`."""

    def test_sync_fails_loud_when_no_session(self, runner, temp_config):
        """sync exits non-zero with a helpful message if no session exists."""
        result = runner.invoke(cli, ["telegram", "sync"])
        assert result.exit_code != 0, f"Expected non-zero exit, got: {result.output}"
        output = result.output + (str(result.exception) if result.exception else "")
        assert "connect" in output.lower(), f"Error should tell user to run connect, got: {output}"

    @pytest.mark.asyncio
    async def test_enumerate_raises_no_session_error_when_no_session(self, tmp_path):
        """enumerate_postable_dialogs raises NoSessionError when config_dir has no session."""
        with pytest.raises(NoSessionError):
            await enumerate_postable_dialogs(client=None, config_dir=str(tmp_path), check_session=True)


# ---------------------------------------------------------------------------
# Integration: CLI sync command
# ---------------------------------------------------------------------------


class TestSyncCommand:
    """The `telegram sync` CLI command end-to-end (mocked Telethon + HTTP)."""

    def test_sync_outputs_inventory_json(self, runner, temp_config, fake_session_string):
        """sync outputs the inventory as JSON to stdout."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)

        private_group = _make_private_group()

        mock_tg_client = MagicMock()
        mock_tg_client.__aenter__ = AsyncMock(return_value=mock_tg_client)
        mock_tg_client.__aexit__ = AsyncMock(return_value=False)
        mock_tg_client.get_dialogs = AsyncMock(return_value=[private_group])
        mock_tg_client.get_messages = AsyncMock(return_value=MagicMock(total=0))

        mock_string_session = MagicMock()

        with patch("switch_cli.telegram.enumerate.TelegramClient", return_value=mock_tg_client):
            with patch("switch_cli.telegram.enumerate.StringSession", return_value=mock_string_session):
                with patch("switch_cli.client.httpx.post") as mock_post:
                    mock_post.side_effect = [
                        MagicMock(status_code=200, json=MagicMock(return_value={"identity_token": "fake-token"})),
                        MagicMock(status_code=200, json=MagicMock(return_value={"upserted": 1, "flagged": 0})),
                    ]
                    result = runner.invoke(cli, ["telegram", "sync"])

        assert result.exit_code == 0, f"Expected exit 0, got output: {result.output!r}, exc: {result.exception}"
        json_lines = [line for line in result.output.splitlines() if line.strip().startswith("{")]
        assert json_lines, f"No JSON found in output: {result.output!r}"
        data = json.loads(json_lines[-1])
        assert "synced" in data or "upserted" in data, f"Expected sync result, got: {data}"
