"""
Unit tests for switch-cli telegram connect command.

Tests drive the Telethon QR-login codepath with a mocked Telethon client.
No live MTProto connection is made — live handshake deferred to integration
child kb-ru55.6.

TDD discipline: RED → GREEN → REFACTOR.

Acceptance criteria:
- (1) `connect` invokes the qr_login codepath and persists the returned
      StringSession to the config dir.
- (2) A reload reads the StringSession back from config.
- (3) A second invocation reuses the stored session (no re-login).
- (4) No server-bound payload carries the session string (ADR-018 D4 / D2 FIRM).
- (5) Fail-loud on missing api creds / corrupt session (ADR-008 D3 FIRM).
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from click.testing import CliRunner
from switch_cli.cli import cli
from switch_cli.config import save_config
from switch_cli.telegram.session import (
    QRLoginTimeoutError,
    SessionCorruptError,
    TelegramConfigError,
    load_telegram_session,
    run_connect,
    save_telegram_session,
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
    Redirect SWITCH_CLI_CONFIG to a temp dir and pre-write base api creds.
    Returns the config dir (not the file).
    """
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_file))
    # Pre-configure telegram api creds in the config
    save_config(base_url="http://fake-switch.test", api_key="fake-bearer-key")
    # Write telegram section into config
    import tomllib

    import tomli_w

    with open(config_file, "rb") as f:
        cfg = tomllib.load(f)
    cfg["telegram"] = {"api_id": 12345, "api_hash": "deadbeef1234"}
    with open(config_file, "wb") as f:
        tomli_w.dump(cfg, f)
    return tmp_path


@pytest.fixture()
def temp_config_no_telegram(tmp_path, monkeypatch):
    """Config file without telegram section — triggers fail-loud."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_file))
    save_config(base_url="http://fake-switch.test", api_key="fake-bearer-key")
    return tmp_path


@pytest.fixture()
def fake_session_string():
    return "1BVtsOKEBu_some_fake_string_session_value_for_testing"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_qr_login(session_string: str):
    """
    Return a mock TelegramClient and a mock QR-login result that mirrors the
    real Telethon QRLogin object.

    The real QRLogin (telethon/tl/custom/qrlogin.py) exposes:
    - .url  — str property
    - .wait(timeout=None) — async method that returns the logged-in User
    - .recreate() — async method to refresh the QR token
    There is NO .login() method on the real object; using .wait() here ensures
    the mock boundary matches the real API, so a typo to the wrong method name
    would cause AttributeError rather than a silent pass.

    The client mock exposes connect() / disconnect() as async methods (D1 fix).
    client.start() is set to raise RuntimeError so any code that accidentally
    calls it (via __aenter__ or directly) will cause a visible failure — this
    is the regression lock for the D1 bug.
    """
    mock_qr = MagicMock(spec=["url", "wait", "recreate"])
    mock_qr.url = "tg://some-qr-url"
    mock_qr.wait = AsyncMock(return_value=MagicMock())  # returns a User-like object
    mock_qr.recreate = AsyncMock()

    mock_client = MagicMock()
    # start() must NEVER be called in the fresh-login path — make it raise so
    # any accidental call (including via __aenter__) is immediately detectable.
    mock_client.start = AsyncMock(side_effect=RuntimeError(
        "BUG: client.start() called in qr_connect — this triggers phone-input prompt. "
        "Use client.connect() instead."
    ))
    mock_client.__aenter__ = mock_client.start  # __aenter__ calls start() in real Telethon
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.connect = AsyncMock()
    mock_client.disconnect = AsyncMock()
    mock_client.qr_login = AsyncMock(return_value=mock_qr)
    mock_client.is_connected = MagicMock(return_value=True)

    # session.save() stores the string
    mock_session = MagicMock()
    mock_session.save = MagicMock(return_value=session_string)
    mock_client.session = mock_session

    return mock_client, mock_qr


# ---------------------------------------------------------------------------
# (1) connect invokes qr_login and persists the StringSession
# ---------------------------------------------------------------------------


class TestConnectInvokesQrLogin:
    """The connect command calls qr_login and saves the session."""

    def test_connect_calls_qr_login(self, runner, temp_config, fake_session_string):
        """connect invokes TelegramClient.qr_login() then awaits qr.wait()."""
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        mock_client.session.save.return_value = fake_session_string

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, result.output
        mock_client.qr_login.assert_awaited_once()
        # Must call qr.wait(), not the non-existent qr.login()
        mock_qr.wait.assert_awaited_once()

    def test_connect_persists_session_to_config_dir(self, runner, temp_config, fake_session_string):
        """connect writes the StringSession to the config dir after QR login."""
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        mock_client.session.save.return_value = fake_session_string

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, result.output
        # Session file should exist alongside config.toml
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        session_path = os.path.join(config_dir, "telegram_session.txt")
        assert os.path.exists(session_path), f"Expected session file at {session_path}"
        with open(session_path) as f:
            stored = f.read().strip()
        assert stored == fake_session_string

    def test_connect_outputs_success_json(self, runner, temp_config, fake_session_string):
        """connect outputs JSON with connected=True on success."""
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        mock_client.session.save.return_value = fake_session_string

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, result.output
        # Extract the JSON line from output (other lines may be informational stderr)
        json_lines = [line for line in result.output.splitlines() if line.strip().startswith("{")]
        assert json_lines, f"No JSON found in output: {result.output!r}"
        data = json.loads(json_lines[0])
        assert data.get("connected") is True


# ---------------------------------------------------------------------------
# (2) reload reads the StringSession back from config
# ---------------------------------------------------------------------------


class TestSessionReload:
    """load_telegram_session reads the persisted session string back."""

    def test_load_returns_saved_session(self, temp_config, fake_session_string):
        """save then load returns the same session string."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)
        loaded = load_telegram_session(config_dir=config_dir)
        assert loaded == fake_session_string

    def test_load_returns_none_if_no_session(self, temp_config):
        """load_telegram_session returns None when no session file exists."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        loaded = load_telegram_session(config_dir=config_dir)
        assert loaded is None


# ---------------------------------------------------------------------------
# (3) second invocation reuses stored session — no re-login
# ---------------------------------------------------------------------------


class TestSessionReuse:
    """A second connect call reuses the stored session, skips qr_login."""

    def test_second_connect_skips_qr_login(self, runner, temp_config, fake_session_string):
        """When a session file already exists, connect skips the QR flow."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        # Pre-persist a session string as if we already logged in
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.qr_login = AsyncMock()

        # Patch both TelegramClient and StringSession — StringSession validates
        # the real session string which we don't have in unit tests.
        mock_string_session = MagicMock()
        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.StringSession", return_value=mock_string_session):
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, result.output
        # qr_login must NOT have been called
        mock_client.qr_login.assert_not_awaited()

    def test_second_connect_outputs_reused_json(self, runner, temp_config, fake_session_string):
        """Reuse path outputs JSON with connected=True and reused=True."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.is_connected = MagicMock(return_value=True)
        mock_client.qr_login = AsyncMock()

        mock_string_session = MagicMock()
        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.StringSession", return_value=mock_string_session):
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, result.output
        # Extract the JSON line from output (other lines may be informational)
        json_lines = [line for line in result.output.splitlines() if line.strip().startswith("{")]
        assert json_lines, f"No JSON found in output: {result.output!r}"
        data = json.loads(json_lines[0])
        assert data.get("connected") is True
        assert data.get("reused") is True


# ---------------------------------------------------------------------------
# (4) no server-bound payload carries the session string (ADR-018 D4 / D2 FIRM)
# ---------------------------------------------------------------------------


class TestNoSessionInServerPayload:
    """The StringSession MUST NOT appear in any server-bound payload (FIRM)."""

    def test_session_module_has_no_http_imports(self):
        """
        Structural guard (ADR-018 D4 / D2 FIRM): the session module MUST NOT
        import any HTTP-client module (httpx, requests, SwitchClient, etc.).

        This is a REAL guard — if someone adds an httpx/requests import to
        session.py the test will fail, unlike the previous vacuous approach of
        capturing HTTP calls when connect makes zero HTTP calls.

        We scan the AST of session.py to assert no HTTP-capable name is imported.
        An AST scan catches the structural violation at the earliest possible
        point regardless of runtime code paths.
        """
        import ast
        import importlib.util
        import pathlib

        session_src = pathlib.Path(importlib.util.find_spec("switch_cli.telegram.session").origin).read_text()
        tree = ast.parse(session_src)

        forbidden_modules = {"httpx", "requests", "aiohttp", "urllib.request"}
        forbidden_names = {"SwitchClient", "httpx", "requests", "aiohttp"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top not in forbidden_modules, (
                        f"session.py imports HTTP module '{alias.name}' — "
                        "the StringSession must NEVER reach a server-bound payload (D2 FIRM)"
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                assert mod not in forbidden_modules, (
                    f"session.py imports from HTTP module '{node.module}' — "
                    "the StringSession must NEVER reach a server-bound payload (D2 FIRM)"
                )
                for alias in node.names:
                    assert alias.name not in forbidden_names, (
                        f"session.py imports forbidden name '{alias.name}' from '{node.module}' — "
                        "the StringSession must NEVER reach a server-bound payload (D2 FIRM)"
                    )

    def test_session_file_contains_only_session_string(self, temp_config, fake_session_string):
        """
        The session file is a local flat file; it is separate from any
        API payload. Verify the file is written locally and NOT posted to HTTP.
        """
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        save_telegram_session(config_dir=config_dir, session_string=fake_session_string)
        session_path = os.path.join(config_dir, "telegram_session.txt")
        with open(session_path) as f:
            content = f.read().strip()
        assert content == fake_session_string
        # The session file must live inside config_dir (local only)
        assert os.path.commonpath([session_path, config_dir]) == config_dir


# ---------------------------------------------------------------------------
# (5) fail-loud on missing api creds / corrupt session (ADR-008 D3 FIRM)
# ---------------------------------------------------------------------------


class TestFailLoud:
    """Visible errors on missing api creds or corrupt session — no silent fallback."""

    def test_connect_fails_loud_on_missing_api_id(self, runner, temp_config_no_telegram):
        """connect exits non-zero with an error message when api_id/api_hash are absent."""
        result = runner.invoke(cli, ["telegram", "connect"])
        assert result.exit_code != 0, "Expected non-zero exit for missing Telegram creds"
        # Error message must mention the missing config
        assert "api_id" in result.output or "api_hash" in result.output or "telegram" in result.output.lower()

    def test_run_connect_raises_telegram_config_error_on_missing_api_id(self, tmp_path):
        """
        run_connect() itself must raise TelegramConfigError when api_id is 0/None
        (Finding 3 — the contract documented in the docstring must be enforced
        inside run_connect, not only in cli.py, so sibling callers kb-ru55.3/.4
        get the same protection).
        """
        with pytest.raises(TelegramConfigError):
            run_connect(api_id=0, api_hash="deadbeef", config_dir=str(tmp_path))

    def test_run_connect_raises_telegram_config_error_on_missing_api_hash(self, tmp_path):
        """run_connect() raises TelegramConfigError when api_hash is empty."""
        with pytest.raises(TelegramConfigError):
            run_connect(api_id=12345, api_hash="", config_dir=str(tmp_path))

    def test_load_session_raises_on_corrupt_data(self, temp_config):
        """load_telegram_session raises SessionCorruptError when file is not a valid session."""
        import os

        config_dir = os.path.dirname(os.environ["SWITCH_CLI_CONFIG"])
        session_path = os.path.join(config_dir, "telegram_session.txt")
        # Write obviously corrupt content
        with open(session_path, "w") as f:
            f.write("")  # empty string = corrupt
        with pytest.raises(SessionCorruptError):
            load_telegram_session(config_dir=config_dir)

    def test_connect_fails_loud_on_qr_timeout(self, runner, temp_config, fake_session_string):
        """connect exits non-zero when qr.wait always raises asyncio.TimeoutError (D3 final timeout)."""
        # mock_qr.wait always raises → all refresh cycles exhausted → QRLoginTimeoutError
        mock_qr = MagicMock(spec=["url", "wait", "recreate"])
        mock_qr.url = "tg://some-qr-url"
        mock_qr.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_qr.recreate = AsyncMock()

        mock_client = MagicMock()
        mock_client.start = AsyncMock(side_effect=RuntimeError("start() must not be called"))
        mock_client.__aenter__ = mock_client.start
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.qr_login = AsyncMock(return_value=mock_qr)
        mock_client.is_connected = MagicMock(return_value=False)

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code != 0, "Expected non-zero exit on QR timeout"
        output = result.output + (result.exception.__class__.__name__ if result.exception else "")
        # Should mention timeout in error output or exception type
        assert "timeout" in output.lower() or "timed out" in output.lower() or "TimeoutError" in output, (
            f"Expected timeout error, got: {output}"
        )


# ---------------------------------------------------------------------------
# De-blinding tests — regression locks for the D1/D2/D3 bugs
# ---------------------------------------------------------------------------


class TestFreshLoginUsesConnectNotStart:
    """
    Regression lock: qr_connect() MUST use client.connect(), NEVER client.start().

    In the real Telethon, __aenter__ calls start(), which on a fresh/empty
    StringSession will block on input() for a phone number (D1 bug).
    The production code must NOT use `async with TelegramClient(...)`.
    """

    def test_fresh_login_calls_connect_not_start(self, runner, temp_config, fake_session_string):
        """
        Assert client.connect() is awaited and client.start() is NEVER called.

        The mock makes start() raise RuntimeError so if `async with` is used,
        the test fails loudly — this is the regression lock.
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, (
            f"connect failed — likely calling start() instead of connect(): {result.output!r}\n"
            f"exception: {result.exception}"
        )
        mock_client.connect.assert_awaited_once()
        mock_client.start.assert_not_awaited()
        mock_client.disconnect.assert_awaited_once()

    def test_fresh_login_disconnect_called_in_finally(self, runner, temp_config, fake_session_string):
        """
        disconnect() must be called even if qr flow fails (finally block).
        """
        mock_qr = MagicMock(spec=["url", "wait", "recreate"])
        mock_qr.url = "tg://some-qr-url"
        mock_qr.wait = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_qr.recreate = AsyncMock()

        mock_client = MagicMock()
        mock_client.start = AsyncMock(side_effect=RuntimeError("start() must not be called"))
        mock_client.__aenter__ = mock_client.start
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()
        mock_client.qr_login = AsyncMock(return_value=mock_qr)
        mock_session = MagicMock()
        mock_session.save = MagicMock(return_value=fake_session_string)
        mock_client.session = mock_session

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            runner.invoke(cli, ["telegram", "connect"])

        # disconnect() must have been called even on timeout
        mock_client.disconnect.assert_awaited()


class TestQRRenderToStderr:
    """
    D2 regression lock: qr.url must be rendered as a scannable terminal QR
    to stderr, not just printed as a raw URL.
    """

    def test_qr_render_called_with_qr_url(self, runner, temp_config, fake_session_string):
        """
        Assert the QR renderer (segno) is invoked with qr.url during fresh login.
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.segno") as mock_segno:
                mock_qr_code = MagicMock()
                mock_segno.make.return_value = mock_qr_code
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, f"connect failed: {result.output!r}\nexc: {result.exception}"
        mock_segno.make.assert_called_once_with(mock_qr.url)
        mock_qr_code.terminal.assert_called_once()

    def test_qr_render_re_invoked_after_recreate(self, runner, temp_config, fake_session_string):
        """
        After recreate(), the renderer is called again with the new qr.url.
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        # wait raises once (triggers recreate), then succeeds
        mock_qr.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), MagicMock()])

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.segno") as mock_segno:
                mock_qr_code = MagicMock()
                mock_segno.make.return_value = mock_qr_code
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, f"connect failed: {result.output!r}\nexc: {result.exception}"
        # Renderer called at least twice (initial + after recreate)
        assert mock_segno.make.call_count >= 2, (
            f"Expected segno.make called ≥2 times (initial + after recreate), got {mock_segno.make.call_count}"
        )


class TestQRRefreshLoop:
    """
    D3 regression lock: qr.wait() timeout triggers recreate + re-render, not immediate failure.
    Bounded loop; final-timeout raises QRLoginTimeoutError.
    """

    def test_refresh_loop_calls_recreate_on_timeout(self, runner, temp_config, fake_session_string):
        """
        When wait() raises TimeoutError once, recreate() is called and login
        completes on the second attempt.
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        # Raise once, then succeed
        mock_qr.wait = AsyncMock(side_effect=[asyncio.TimeoutError(), MagicMock()])

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.segno"):
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code == 0, (
            f"Expected success after one timeout+recreate cycle, got: {result.output!r}\nexc: {result.exception}"
        )
        mock_qr.recreate.assert_awaited_once()

    def test_final_timeout_raises_qr_login_timeout_error(self, runner, temp_config, fake_session_string):
        """
        When wait() always raises TimeoutError (all cycles exhausted), the CLI
        exits non-zero and the exception is QRLoginTimeoutError (ADR-008 D3).
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        # Always timeout — all cycles exhausted
        mock_qr.wait = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.segno"):
                result = runner.invoke(cli, ["telegram", "connect"])

        assert result.exit_code != 0, "Expected non-zero exit after all QR cycles exhausted"
        # Either the output mentions timeout OR the raised exception is QRLoginTimeoutError
        output = result.output
        exc = result.exception
        assert (
            "timeout" in output.lower()
            or "timed out" in output.lower()
            or isinstance(exc, QRLoginTimeoutError)
        ), f"Expected QRLoginTimeoutError or timeout message. output={output!r}, exc={exc!r}"

    def test_final_timeout_loop_is_bounded(self, runner, temp_config, fake_session_string):
        """
        The refresh loop must terminate (bounded cycles), not loop forever.
        Verify by asserting recreate() is called a finite number of times.
        """
        mock_client, mock_qr = _make_mock_qr_login(fake_session_string)
        mock_qr.wait = AsyncMock(side_effect=asyncio.TimeoutError)

        with patch("switch_cli.telegram.session.TelegramClient", return_value=mock_client):
            with patch("switch_cli.telegram.session.segno"):
                result = runner.invoke(cli, ["telegram", "connect"])

        # Loop bound ≈ 6 cycles; recreate called at most 6 times
        assert mock_qr.recreate.await_count <= 6, (
            f"Unbounded loop? recreate called {mock_qr.recreate.await_count} times"
        )
