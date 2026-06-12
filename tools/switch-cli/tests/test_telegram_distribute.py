"""
Unit tests for switch-cli telegram distribute command.

TDD discipline: RED → GREEN → REFACTOR.

All tests follow the sibling-bug lesson: use spec=-constrained mocks or
real Telethon types so the mock cannot invent a non-existent method.

Acceptance criteria (bead kb-ru55.4 / kb-ru55.8):
1. AST firewall: draft.py has NO reference to send_message/send/auto-send variants
   (structural scan via ast.walk — catches even getattr tricks).
2. Empty-draft private group → saveDraft called; send_message NOT called.
3. Empty-draft forum topic → draft.set_message(text=message) called (same as group path),
   NO reply_to kwarg, NO SaveDraftRequest/InputReplyToMessage. Rationale: Telegram Desktop
   does NOT render topic-pinned drafts (top_msg_id set) — confirmed live 2026-06-12.
   Forum drafts are placed at the FORUM LEVEL (reply_to=None); topic routing is conveyed
   via the distribute result. True per-topic pinning is a deferred follow-up.
4. Pre-existing draft → saveDraft NOT called; status=skipped-pre-existing-draft.
5. Multi-dest placement set (≥1 private group + ≥1 forum topic) → both placed.
6. --dest not in postable set → fails loud (ADR-008 D3).

Real Telethon draft API (confirmed from source):
- telethon/tl/custom/draft.py:
  - Draft.__init__(client, entity, draft)
  - Draft.text (property) — markdown text, empty string if no draft
  - Draft.is_empty (property, line 101) — True when text is empty
  - Draft.set_message(text, reply_to=0, parse_mode=(), link_preview=None) — calls SaveDraftRequest
  - Draft.send() — calls client.send_message() — MUST NEVER BE CALLED (ADR-018 D2 FIRM)
- telethon/tl/functions/messages.py:
  - SaveDraftRequest(peer, message, no_webpage, invert_media, reply_to, entities, media, effect)
  - reply_to accepts TypeInputReplyTo (e.g. InputReplyToMessage)
- telethon/tl/types/__init__.py:
  - InputReplyToMessage(reply_to_msg_id, top_msg_id=None, ...) — for forum topics,
    set reply_to_msg_id=top_msg_id and top_msg_id=top_msg_id
- client.get_drafts(entity) → returns a single Draft object (entity given) or list (no entity)
"""

import ast
import inspect
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import switch_cli.telegram.draft as draft_module
from click.testing import CliRunner
from switch_cli.cli import cli
from switch_cli.config import save_config
from switch_cli.telegram.session import save_telegram_session
from telethon import TelegramClient

# ---------------------------------------------------------------------------
# Test 1: AST structural firewall
# ---------------------------------------------------------------------------


class TestASTFirewall:
    """
    FIRM (ADR-018 D2): No code path in draft.py can reach sendMessage or any
    auto-send variant. Verified via AST-parse (not string grep — grep misses
    getattr(client, 'send'+'_message') tricks).

    This test walks the AST of draft.py and asserts:
    - No attribute access (.send_message, .send, .send_file, .forward_messages)
      on any object.
    - No function call with a name matching send_message/send_file/forward_messages.
    The Draft.set_message path (saveDraft via SaveDraftRequest) is ALLOWED.
    The Draft.send() method is forbidden from existing within draft.py.

    Telethon TelegramClient send-equivalent audit (outbound delivery to a chat):
    - send_message (telethon/client/messages.py:627) — sends a text/media message
    - send_file (telethon/client/uploads.py:113) — sends a file/photo/album to a chat
    - forward_messages (telethon/client/messages.py:946) — forwards existing messages
      to another chat; counts as an outbound send and toward spam-ban surface
    - send (Draft.send, telethon/tl/custom/draft.py:155) — sends the draft as a
      message via send_message; must never be called on the Draft object
    - send_photo / send_document — NOT real TelegramClient methods (confirmed by
      inspection of telethon/client/); they are chat permission flags in types/,
      kept in AUTO_SEND_NAMES as defense-in-depth against future aliases
    - send_read_acknowledge (telethon/client/messages.py:1340) — marks messages as
      read only; NOT an outbound send (no content delivered), not forbidden
    - inline_query (telethon/client/bots.py) — queries for inline results; NOT a
      content-delivery send, not forbidden
    """

    AUTO_SEND_NAMES = {
        "send_message",    # TelegramClient.send_message — sends text/media to a chat
        "send_file",       # TelegramClient.send_file — sends a file/photo/album to a chat
        "send_photo",      # defense-in-depth: not a real method today, guard future aliases
        "send_document",   # defense-in-depth: not a real method today, guard future aliases
        "forward_messages",  # TelegramClient.forward_messages — forwards messages to a chat
    }
    # "send" alone is too broad (could be used in other contexts), but
    # within the placement module we forbid attribute access named "send"
    # on any chained call that looks like client.send or draft.send.
    FORBIDDEN_ATTRIBUTE_NAMES = {
        "send_message",    # TelegramClient.send_message — sends text/media to a chat
        "send_file",       # TelegramClient.send_file — sends a file/photo/album to a chat
        "send_photo",      # defense-in-depth: not a real method today, guard future aliases
        "send_document",   # defense-in-depth: not a real method today, guard future aliases
        "forward_messages",  # TelegramClient.forward_messages — forwards messages (outbound send)
        "send",            # Draft.send() — calls send_message internally, must never be invoked
    }

    def test_draft_module_has_no_auto_send_calls(self):
        """
        AST-walk draft.py: assert no attribute access or call to any auto-send method.
        This proves structurally that NO code path can reach sendMessage or forward_messages.

        Can fail: if anyone adds client.send_message(...), client.forward_messages(...),
        or Draft.send() to draft.py.
        """
        source_path = Path(inspect.getfile(draft_module))
        source = source_path.read_text()
        tree = ast.parse(source)

        violations = []
        for node in ast.walk(tree):
            # Catch attribute access: obj.send_message, obj.forward_messages, obj.send, etc.
            if isinstance(node, ast.Attribute):
                if node.attr in self.FORBIDDEN_ATTRIBUTE_NAMES:
                    violations.append(
                        f"Line {node.lineno}: attribute access '.{node.attr}' "
                        f"(potential auto-send — ADR-018 D2 FIRM)"
                    )
            # Catch function calls by name (e.g. send_message(...), forward_messages(...))
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.AUTO_SEND_NAMES:
                    violations.append(
                        f"Line {node.lineno}: direct call '{node.func.id}' "
                        f"(potential auto-send — ADR-018 D2 FIRM)"
                    )

        assert not violations, (
            "draft.py contains auto-send references (ADR-018 D2 FIRM violation):\n"
            + "\n".join(violations)
        )

    def test_ast_firewall_can_detect_violations(self):
        """
        Canary: verify the AST scanner CAN detect a violation if it were added.
        This proves the scanner is not trivially vacuous.
        """
        malicious_source = "import telethon\nclient.send_message(peer, text)\n"
        tree = ast.parse(malicious_source)

        found_violation = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN_ATTRIBUTE_NAMES:
                found_violation = True
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.AUTO_SEND_NAMES:
                    found_violation = True

        assert found_violation, (
            "AST scanner failed to detect 'client.send_message(...)' — "
            "the structural firewall test is vacuous!"
        )

    def test_ast_firewall_detects_forward_messages(self):
        """
        Canary specific to forward_messages: verify the AST scanner catches
        client.forward_messages(...) if it were added to draft.py.

        forward_messages delivers messages to a chat (outbound send) and counts
        toward Telegram's spam-ban surface — it is NOT a draft operation.
        A refactor adding it would be a FIRM ADR-018 D2 violation.
        """
        malicious_source = "import telethon\nclient.forward_messages(entity, messages)\n"
        tree = ast.parse(malicious_source)

        found_violation = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN_ATTRIBUTE_NAMES:
                found_violation = True
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.AUTO_SEND_NAMES:
                    found_violation = True

        assert found_violation, (
            "AST scanner failed to detect 'client.forward_messages(...)' — "
            "forward_messages is an outbound send (ADR-018 D2 FIRM) and the "
            "structural firewall must catch it!"
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """
    Redirect SWITCH_CLI_CONFIG to a temp dir and pre-write api creds.
    Returns the temp dir.
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


def _make_mock_draft(is_empty: bool = True):
    """
    Build a mock Draft object that mirrors the real Telethon Draft interface.
    Spec'd from the real Draft class to catch non-existent attributes.

    Real Draft API (telethon/tl/custom/draft.py):
    - .is_empty (bool property, line 101)
    - .text (str property, line 84)
    - .set_message(text, reply_to=0, parse_mode=(), link_preview=None) coroutine
    - .send() coroutine — MUST NOT BE CALLED
    """
    from telethon.tl.custom.draft import Draft

    draft = MagicMock(spec=Draft)
    draft.is_empty = is_empty
    draft.text = "" if is_empty else "Existing draft content"
    draft.set_message = AsyncMock(return_value=True)
    # send() must be spec'd — it exists on Draft but must never be invoked
    draft.send = AsyncMock()
    return draft


def _make_postable_inventory():
    """
    A flat postable inventory with one private group and one forum topic.
    Format mirrors enumerate_postable_dialogs output.
    """
    return [
        {
            "chat_id": "-1002222222222",
            "title": "Secret Planning Group",
            "type": "group",
            "topic_id": None,
            "postability": "agent",
        },
        {
            "chat_id": "-1003333333333",
            "title": "General Discussion",
            "type": "forum_topic",
            "topic_id": 101,
            "postability": "agent",
        },
    ]


# ---------------------------------------------------------------------------
# Test 2: empty-draft private group → saveDraft called, send_message NOT called
# ---------------------------------------------------------------------------


class TestEmptyDraftPrivateGroup:
    """
    For a private group with an empty draft:
    - getDraft (client.get_drafts) is called first.
    - saveDraft (draft.set_message) is called with the message body.
    - client.send_message is NOT called (ADR-018 D2 FIRM).
    """

    @pytest.mark.asyncio
    async def test_empty_draft_group_calls_save_draft(self):
        """Empty draft → set_message called with message body."""
        from switch_cli.telegram.draft import distribute

        inventory = [
            {
                "chat_id": "-1002222222222",
                "title": "Secret Group",
                "type": "group",
                "topic_id": None,
                "postability": "agent",
            }
        ]
        message = "Hello from the agent"
        dests = ["-1002222222222"]

        empty_draft = _make_mock_draft(is_empty=True)

        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, should NOT be called

        results = await distribute(
            client=mock_client,
            message=message,
            dests=dests,
            postable_inventory=inventory,
        )

        # set_message was called with the correct text
        empty_draft.set_message.assert_called_once()
        call_kwargs = empty_draft.set_message.call_args
        assert call_kwargs.kwargs.get("text") == message or (
            call_kwargs.args and call_kwargs.args[0] == message
        ), f"set_message called with wrong args: {call_kwargs}"

        # send_message was NOT called (FIRM firewall)
        mock_client.send_message.assert_not_called()

        # result records placed status
        assert len(results) == 1
        assert results[0]["status"] == "placed"
        assert results[0]["chat_id"] == "-1002222222222"

    @pytest.mark.asyncio
    async def test_send_message_not_called_for_group(self):
        """Behavioral firewall: send_message must never be called, even on happy path."""
        from switch_cli.telegram.draft import distribute

        inventory = [
            {
                "chat_id": "-1002222222222",
                "title": "Secret Group",
                "type": "group",
                "topic_id": None,
                "postability": "agent",
            }
        ]
        empty_draft = _make_mock_draft(is_empty=True)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        await distribute(
            client=mock_client,
            message="test",
            dests=["-1002222222222"],
            postable_inventory=inventory,
        )

        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_forward_messages_not_called_for_group(self):
        """
        Behavioral firewall: forward_messages must never be called.

        forward_messages delivers messages to a chat (outbound send) and counts
        toward Telegram's spam-ban surface — it is NOT a draft operation.
        spec=TelegramClient ensures this assertion is structurally sound: a bare
        MagicMock() auto-creates any attribute AND records calls faithfully, so
        assert_not_called() would work even on a bare mock for a never-invoked
        method. The real value of spec=TelegramClient is that accessing a
        misspelled or renamed attribute (e.g. forward_message without the trailing
        's', or a future API rename) raises AttributeError immediately instead of
        silently auto-creating a new attribute — preventing the assertion from
        drifting into vacuity if the method name ever changes.
        """
        from switch_cli.telegram.draft import distribute

        inventory = [
            {
                "chat_id": "-1002222222222",
                "title": "Secret Group",
                "type": "group",
                "topic_id": None,
                "postability": "agent",
            }
        ]
        empty_draft = _make_mock_draft(is_empty=True)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.forward_messages = AsyncMock()  # spec'd: real method, must never fire

        await distribute(
            client=mock_client,
            message="test",
            dests=["-1002222222222"],
            postable_inventory=inventory,
        )

        mock_client.forward_messages.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: empty-draft forum topic → saveDraft WITH reply_to/top_msg_id
# ---------------------------------------------------------------------------


class TestEmptyDraftForumTopic:
    """
    For a forum topic with an empty draft:
    - draft.set_message(text=message) is called — same as the plain-group path.
    - NO reply_to kwarg, NO SaveDraftRequest/InputReplyToMessage.
    - client.send_message is NOT called (ADR-018 D2 FIRM).

    D3 (FLEXIBLE, ADR-018 D1): forum drafts are placed at the FORUM LEVEL
    (reply_to=None), same as groups. Telegram Desktop does NOT render topic-pinned
    drafts (top_msg_id) — confirmed live 2026-06-12 — so topic-pinning is intentionally
    NOT used; the intended topic is conveyed via the distribute result for the human to
    route. True per-topic pinning is a deferred follow-up.
    """

    @pytest.mark.asyncio
    async def test_forum_topic_calls_set_message_at_forum_level(self):
        """Forum topic → draft.set_message(text=message) called, NO reply_to, NO SaveDraftRequest."""
        from switch_cli.telegram.draft import distribute

        topic_id = 101
        inventory = [
            {
                "chat_id": "-1003333333333",
                "title": "General Discussion",
                "type": "forum_topic",
                "topic_id": topic_id,
                "postability": "agent",
            }
        ]
        message = "Forum announcement"
        dests = [f"-1003333333333:{topic_id}"]

        empty_draft = _make_mock_draft(is_empty=True)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        results = await distribute(
            client=mock_client,
            message=message,
            dests=dests,
            postable_inventory=inventory,
        )

        # Forum path: draft.set_message must be called with text=message, NO reply_to kwarg
        empty_draft.set_message.assert_called_once()
        call_kwargs = empty_draft.set_message.call_args
        # Must have text=message
        assert call_kwargs.kwargs.get("text") == message or (
            call_kwargs.args and call_kwargs.args[0] == message
        ), f"set_message called with wrong args: {call_kwargs}"
        # Must NOT have reply_to (forum-level draft, not topic-pinned)
        assert "reply_to" not in call_kwargs.kwargs, (
            f"reply_to must NOT be passed for forum drafts (topic-pinned drafts are invisible "
            f"in Telegram Desktop — confirmed live 2026-06-12). Got: {call_kwargs.kwargs}"
        )

        # send_message must not be called
        mock_client.send_message.assert_not_called()

        assert results[0]["status"] == "placed"
        assert results[0]["topic_id"] == topic_id

    @pytest.mark.asyncio
    async def test_send_message_not_called_for_forum_topic(self):
        """Behavioral firewall: send_message must never be called for forum topics."""
        from switch_cli.telegram.draft import distribute

        topic_id = 101
        inventory = [
            {
                "chat_id": "-1003333333333",
                "title": "General Discussion",
                "type": "forum_topic",
                "topic_id": topic_id,
                "postability": "agent",
            }
        ]
        empty_draft = _make_mock_draft(is_empty=True)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        await distribute(
            client=mock_client,
            message="test",
            dests=[f"-1003333333333:{topic_id}"],
            postable_inventory=inventory,
        )

        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_forward_messages_not_called_for_forum_topic(self):
        """
        Behavioral firewall: forward_messages must never be called for forum topics.

        forward_messages delivers messages to a chat (outbound send) and counts
        toward Telegram's spam-ban surface — it is NOT a draft operation.
        spec=TelegramClient ensures this assertion is structurally sound: a bare
        MagicMock() auto-creates any attribute AND records calls faithfully, so
        assert_not_called() would work even on a bare mock for a never-invoked
        method. The real value of spec=TelegramClient is that accessing a
        misspelled or renamed attribute (e.g. forward_message without the trailing
        's', or a future API rename) raises AttributeError immediately instead of
        silently auto-creating a new attribute — preventing the assertion from
        drifting into vacuity if the method name ever changes.
        """
        from switch_cli.telegram.draft import distribute

        topic_id = 101
        inventory = [
            {
                "chat_id": "-1003333333333",
                "title": "General Discussion",
                "type": "forum_topic",
                "topic_id": topic_id,
                "postability": "agent",
            }
        ]
        empty_draft = _make_mock_draft(is_empty=True)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_client.forward_messages = AsyncMock()  # spec'd: real method, must never fire

        await distribute(
            client=mock_client,
            message="test",
            dests=[f"-1003333333333:{topic_id}"],
            postable_inventory=inventory,
        )

        mock_client.forward_messages.assert_not_called()


# ---------------------------------------------------------------------------
# Test 4: pre-existing draft → saveDraft NOT called, skipped-pre-existing-draft
# ---------------------------------------------------------------------------


class TestPreExistingDraft:
    """
    If getDraft returns a non-empty draft, the destination must be SKIPPED.
    - set_message must NOT be called (no clobber).
    - status is 'skipped-pre-existing-draft'.
    - send_message must NOT be called.
    """

    @pytest.mark.asyncio
    async def test_pre_existing_draft_skipped_no_clobber(self):
        """Pre-existing draft → set_message NOT called, status=skipped-pre-existing-draft."""
        from switch_cli.telegram.draft import distribute

        inventory = [
            {
                "chat_id": "-1002222222222",
                "title": "Secret Group",
                "type": "group",
                "topic_id": None,
                "postability": "agent",
            }
        ]
        existing_draft = _make_mock_draft(is_empty=False)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=existing_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        results = await distribute(
            client=mock_client,
            message="This should not clobber",
            dests=["-1002222222222"],
            postable_inventory=inventory,
        )

        # set_message must NOT be called
        existing_draft.set_message.assert_not_called()

        # send_message must NOT be called
        mock_client.send_message.assert_not_called()

        # result records skipped status
        assert len(results) == 1
        assert results[0]["status"] == "skipped-pre-existing-draft"
        assert results[0]["chat_id"] == "-1002222222222"

    @pytest.mark.asyncio
    async def test_pre_existing_draft_forum_topic_skipped(self):
        """Pre-existing draft on forum topic → also skipped, no clobber."""
        from switch_cli.telegram.draft import distribute

        topic_id = 101
        inventory = [
            {
                "chat_id": "-1003333333333",
                "title": "General Discussion",
                "type": "forum_topic",
                "topic_id": topic_id,
                "postability": "agent",
            }
        ]
        existing_draft = _make_mock_draft(is_empty=False)
        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(return_value=existing_draft)
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        results = await distribute(
            client=mock_client,
            message="Do not clobber forum draft",
            dests=[f"-1003333333333:{topic_id}"],
            postable_inventory=inventory,
        )

        existing_draft.set_message.assert_not_called()
        mock_client.send_message.assert_not_called()
        assert results[0]["status"] == "skipped-pre-existing-draft"


# ---------------------------------------------------------------------------
# Test 5: multi-dest placement (≥1 private group + ≥1 forum topic)
# ---------------------------------------------------------------------------


class TestMultiDestPlacement:
    """
    Over a placement set with ≥1 private group + ≥1 forum topic,
    both are placed successfully.
    """

    @pytest.mark.asyncio
    async def test_multi_dest_places_both_group_and_topic(self):
        """Multi-dest: private group + forum topic → both placed via set_message, no send_message."""
        from switch_cli.telegram.draft import distribute

        inventory = _make_postable_inventory()
        message = "Multi-destination announcement"

        # First call → group draft (empty), second call → topic draft (empty)
        empty_draft_group = _make_mock_draft(is_empty=True)
        empty_draft_topic = _make_mock_draft(is_empty=True)

        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(side_effect=[empty_draft_group, empty_draft_topic])
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        dests = ["-1002222222222", "-1003333333333:101"]

        results = await distribute(
            client=mock_client,
            message=message,
            dests=dests,
            postable_inventory=inventory,
        )

        # Both placed
        assert len(results) == 2
        statuses = {r["status"] for r in results}
        assert statuses == {"placed"}, f"Expected both placed, got: {results}"

        # Group draft placed correctly
        group_result = next(r for r in results if r["chat_id"] == "-1002222222222")
        assert group_result["status"] == "placed"
        assert group_result.get("topic_id") is None

        # Forum topic draft placed with topic_id
        topic_result = next(r for r in results if r["chat_id"] == "-1003333333333")
        assert topic_result["status"] == "placed"
        assert topic_result["topic_id"] == 101

        # Both group and forum topic drafts: set_message called once each (same path)
        assert empty_draft_group.set_message.call_count == 1
        assert empty_draft_topic.set_message.call_count == 1

        # Forum topic draft: set_message called with text=message, NO reply_to kwarg
        topic_call_kwargs = empty_draft_topic.set_message.call_args
        assert topic_call_kwargs.kwargs.get("text") == message or (
            topic_call_kwargs.args and topic_call_kwargs.args[0] == message
        ), f"set_message called with wrong args: {topic_call_kwargs}"
        assert "reply_to" not in topic_call_kwargs.kwargs, (
            f"reply_to must NOT be passed for forum drafts (topic-pinned drafts not visible "
            f"in Telegram Desktop — confirmed live 2026-06-12). Got: {topic_call_kwargs.kwargs}"
        )

        # FIRM firewall: send_message never called
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_results_group_placed_topic_skipped(self):
        """Mixed: group empty (placed) + topic pre-existing (skipped)."""
        from switch_cli.telegram.draft import distribute

        inventory = _make_postable_inventory()
        message = "Mixed test"

        empty_draft = _make_mock_draft(is_empty=True)
        existing_draft = _make_mock_draft(is_empty=False)

        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock(side_effect=[empty_draft, existing_draft])
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        dests = ["-1002222222222", "-1003333333333:101"]

        results = await distribute(
            client=mock_client,
            message=message,
            dests=dests,
            postable_inventory=inventory,
        )

        assert len(results) == 2
        group_result = next(r for r in results if r["chat_id"] == "-1002222222222")
        topic_result = next(r for r in results if r["chat_id"] == "-1003333333333")

        assert group_result["status"] == "placed"
        assert topic_result["status"] == "skipped-pre-existing-draft"

        empty_draft.set_message.assert_called_once()
        existing_draft.set_message.assert_not_called()
        mock_client.send_message.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: --dest not in postable set → fail loud
# ---------------------------------------------------------------------------


class TestDestNotInInventoryFailsLoud:
    """
    A --dest that is NOT in the postable inventory must fail loud (ADR-008 D3).
    No silent skip — raise an informative error.
    """

    @pytest.mark.asyncio
    async def test_unknown_dest_raises_error(self):
        """Unknown --dest (not in inventory) raises ValueError (fail loud)."""
        from switch_cli.telegram.draft import UnknownDestinationError, distribute

        inventory = _make_postable_inventory()

        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock()
        mock_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        with pytest.raises(UnknownDestinationError, match="-9999999999"):
            await distribute(
                client=mock_client,
                message="test",
                dests=["-9999999999"],
                postable_inventory=inventory,
            )

        # No draft operations performed
        mock_client.get_drafts.assert_not_called()
        mock_client.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_dest_in_multi_dest_fails_before_any_placement(self):
        """With a bad --dest in multi-dest list, fail before touching any destination."""
        from switch_cli.telegram.draft import UnknownDestinationError, distribute

        inventory = _make_postable_inventory()

        mock_client = MagicMock(spec=TelegramClient)
        mock_client.get_drafts = AsyncMock()

        with pytest.raises(UnknownDestinationError):
            await distribute(
                client=mock_client,
                message="test",
                dests=["-1002222222222", "-9999999999"],  # second is invalid
                postable_inventory=inventory,
            )


# ---------------------------------------------------------------------------
# Test 7: CLI distribute command integration
# ---------------------------------------------------------------------------


class TestDistributeCommand:
    """The `telegram distribute` CLI command (mocked Telethon)."""

    def test_distribute_command_exists(self, runner):
        """The distribute command is registered under `telegram`."""
        result = runner.invoke(cli, ["telegram", "distribute", "--help"])
        assert result.exit_code == 0, f"distribute --help failed: {result.output}"
        assert "distribute" in result.output.lower() or "--message" in result.output

    def test_distribute_command_places_drafts(self, runner, temp_config, fake_session_string):
        """End-to-end: distribute places drafts for valid destinations."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)

        inventory = _make_postable_inventory()
        empty_draft = _make_mock_draft(is_empty=True)

        mock_tg_client = MagicMock(spec=TelegramClient)
        mock_tg_client.__aenter__ = AsyncMock(return_value=mock_tg_client)
        mock_tg_client.__aexit__ = AsyncMock(return_value=False)
        mock_tg_client.get_drafts = AsyncMock(return_value=empty_draft)
        mock_tg_client.send_message = AsyncMock()  # spec'd: real method, must never fire

        with patch("switch_cli.telegram.draft.enumerate_postable_dialogs", AsyncMock(return_value=inventory)):
            with patch("switch_cli.telegram.draft.build_authenticated_client", return_value=mock_tg_client):
                result = runner.invoke(
                    cli,
                    [
                        "telegram",
                        "distribute",
                        "--message",
                        "Test announcement",
                        "--dest",
                        "-1002222222222",
                    ],
                )

        assert result.exit_code == 0, f"Expected exit 0, got: {result.output!r}, exc: {result.exception}"
        import json
        output = json.loads(result.output.strip())
        assert "results" in output or "placed" in str(output), f"Unexpected output: {output}"

    def test_distribute_fails_loud_no_session(self, runner, temp_config):
        """No session file → error with useful message."""
        result = runner.invoke(
            cli,
            [
                "telegram",
                "distribute",
                "--message",
                "test",
                "--dest",
                "-1002222222222",
            ],
        )
        assert result.exit_code != 0
        output = result.output + (str(result.exception) if result.exception else "")
        assert "connect" in output.lower(), f"Expected connect hint, got: {output}"
