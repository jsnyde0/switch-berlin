"""
Track A Telegram collector (sb-7wzb.4): one row per post, an album folded into
one row, its photos carried along for the extractor. Read-only fake client.
"""

import asyncio
import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from switch_cli.telegram.read import collect_telegram

NOW = datetime.now(UTC)


def _msg(id, text="", photo=False, grouped_id=None, age_hours=1):
    return SimpleNamespace(
        id=id,
        message=text,
        photo=object() if photo else None,
        grouped_id=grouped_id,
        date=NOW - timedelta(hours=age_hours),
        sender_id=777,
    )


class FakeClient:
    """Answers only the read calls collect_telegram makes; newest message first, as Telethon does."""

    def __init__(self, messages):
        self.messages = messages

    async def get_dialogs(self):
        return []

    async def get_entity(self, chat):
        return SimpleNamespace(id=1, title="IKSK Berlin", username=chat.lstrip("@"))

    async def iter_messages(self, entity, reply_to=None, limit=None):
        for m in self.messages:
            yield m

    async def download_media(self, msg, file=None):
        assert file is bytes
        return f"jpeg-{msg.id}".encode()


SOURCE = {"name": "@IKSKBerlin", "shape": "telegram_telethon", "chat": "@IKSKBerlin", "publish": True}


def _collect(messages):
    rows, report = asyncio.run(collect_telegram(FakeClient(messages), [SOURCE], days=14, include_private=False))
    return rows, report


def test_album_becomes_one_row_with_all_its_photos():
    rows, _ = _collect(
        [
            _msg(12, photo=True, grouped_id=5),
            _msg(11, photo=True, grouped_id=5),
            _msg(10, "THURSDAY 1.10.26", photo=True, grouped_id=5),
        ]
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["message_id"] == "10"  # lowest id in the album: stable across re-collects
    assert "THURSDAY 1.10.26" in row["text"]
    assert [base64.b64decode(b) for b in row["raw_payload"]["images"]] == [b"jpeg-10", b"jpeg-11", b"jpeg-12"]
    assert row["raw_payload"]["url"] == "https://t.me/IKSKBerlin/10"


def test_short_and_image_only_posts_are_collected_empty_ones_are_not():
    rows, report = _collect([_msg(3, "Tonight 20h!"), _msg(2, photo=True), _msg(1)])
    assert [r["message_id"] for r in rows] == ["3", "2"]
    assert "images" not in rows[0]["raw_payload"]
    assert len(rows[1]["raw_payload"]["images"]) == 1
    assert report == [{"source": "@IKSKBerlin", "rows": 2, "posts_in_window": 3}]


def test_posts_older_than_the_window_stop_the_read():
    rows, _ = _collect([_msg(2, "new post"), _msg(1, "old post", age_hours=24 * 20)])
    assert [r["message_id"] for r in rows] == ["2"]


def test_push_splits_rows_into_requests_under_the_body_limit(monkeypatch):
    import json

    from switch_cli import client as client_mod

    bodies = []

    def fake_post(url, json=None, headers=None, timeout=None):
        bodies.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {"created": len(json), "already_collected": 0})

    monkeypatch.setattr(client_mod.SwitchClient, "_exchange", lambda self, key: "tok")
    monkeypatch.setattr(client_mod.httpx, "post", fake_post)
    monkeypatch.setattr(client_mod, "PUSH_BODY_LIMIT", 1000)
    rows = [{"text": "x" * 300, "n": i} for i in range(7)]

    result = client_mod.SwitchClient(base_url="http://sw", api_key="k").push_collected_rows(rows)

    assert result == {"created": 7, "already_collected": 0}
    assert len(bodies) > 1
    assert all(len(json.dumps(b)) <= 1000 for b in bodies)
    assert [r["n"] for b in bodies for r in b] == list(range(7))


def _rows_file(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_text('{"source_type": "telegram_private_group", "raw_payload": {"images": ["AAAA"]}}\n')
    return path


def _push(monkeypatch, path, *extra, fail=False):
    from click.testing import CliRunner
    from switch_cli import cli as cli_mod

    class FakeSwitch:
        def push_collected_rows(self, rows):
            if fail:
                raise cli_mod.APIError(500, "boom")
            return {"created": len(rows)}

    monkeypatch.setattr(cli_mod, "SwitchClient", FakeSwitch)
    return CliRunner().invoke(cli_mod.cli, ["collect", "push", str(path), *extra])


def test_push_deletes_the_rows_file_after_a_successful_push(monkeypatch, tmp_path):
    path = _rows_file(tmp_path)
    result = _push(monkeypatch, path)
    assert result.exit_code == 0
    assert not path.exists()
    assert '"rows_file_deleted": true' in result.output


def test_push_keep_leaves_the_rows_file(monkeypatch, tmp_path):
    path = _rows_file(tmp_path)
    result = _push(monkeypatch, path, "--keep")
    assert result.exit_code == 0
    assert path.exists()
    assert '"rows_file_deleted": false' in result.output


def test_failed_push_leaves_the_rows_file_for_a_retry(monkeypatch, tmp_path):
    path = _rows_file(tmp_path)
    result = _push(monkeypatch, path, fail=True)
    assert result.exit_code != 0
    assert path.exists()
