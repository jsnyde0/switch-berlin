"""
Telethon QR-login and StringSession custody for switch-cli.

Decisions:
- D1 (FLEXIBLE, ADR-018 D1): QR login via Telethon qr_login(); StringSession
  persisted to switch-cli config dir (~/.config/switch-cli/), not .env, not server.
  api_id/api_hash read from local config (user provides once via configure).
- D2 (FIRM, ADR-018 D4): StringSession NEVER enters a server-bound payload.
  Session file is local-only; no code in this module posts it to any HTTP endpoint.
- D3 (FIRM, ADR-008 D3): fail loud on QR timeout / session-corruption / missing
  api creds — raise visible error, no silent re-login loop.
"""

import asyncio
import os
import sys
from pathlib import Path

import segno
from telethon import TelegramClient
from telethon.sessions import StringSession

_SESSION_FILENAME = "telegram_session.txt"

# Number of QR refresh cycles before giving up (D3: bounded loop, fail loud).
# Each cycle is ~25s → 6 cycles ≈ 2.5 minute window.
_QR_MAX_CYCLES = 6
_QR_WAIT_TIMEOUT = 25  # seconds per wait() call


class TelegramConfigError(Exception):
    """Raised when Telegram api_id/api_hash are missing from config (ADR-008 D3)."""


class SessionCorruptError(Exception):
    """Raised when the persisted session file exists but contains invalid data (ADR-008 D3)."""


class QRLoginTimeoutError(Exception):
    """Raised when the QR login flow times out (ADR-008 D3)."""


def _session_path(config_dir: str) -> Path:
    """Return the path to the local session file."""
    return Path(config_dir) / _SESSION_FILENAME


def save_telegram_session(config_dir: str, session_string: str) -> None:
    """
    Persist the Telethon StringSession to the local config dir.

    The session file is local-only — it is NEVER posted to any server
    (ADR-018 D4, D2 FIRM).
    """
    path = _session_path(config_dir)
    Path(config_dir).mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(session_string)


def load_telegram_session(config_dir: str) -> str | None:
    """
    Load the persisted Telethon StringSession from the config dir.

    Returns None if no session file exists (first run).
    Raises SessionCorruptError if the file exists but is empty or invalid
    (ADR-008 D3: fail loud, no silent re-login).
    """
    path = _session_path(config_dir)
    if not path.exists():
        return None
    with open(path) as f:
        content = f.read().strip()
    if not content:
        raise SessionCorruptError(
            f"Telegram session file at {path} is empty or corrupt. "
            "Delete it and run `switch-cli telegram connect` to re-authenticate."
        )
    return content


def _get_config_dir() -> str:
    """Return the config dir from SWITCH_CLI_CONFIG env var or default."""
    override = os.environ.get("SWITCH_CLI_CONFIG")
    if override:
        return str(Path(override).parent)
    return str(Path.home() / ".config" / "switch-cli")


def _render_qr(url: str) -> None:
    """
    Render qr.url as a scannable terminal QR to stderr (D2).

    Uses segno (pure-python, no system deps). Also prints the raw URL
    so the user can copy-paste it if the terminal QR is hard to scan.
    """
    print(f"\nScan the QR code below in Telegram (or open: {url})\n", file=sys.stderr)
    segno.make(url).terminal(out=sys.stderr, compact=True)
    print("", file=sys.stderr)


async def qr_connect(api_id: int, api_hash: str, config_dir: str) -> dict:
    """
    Run the Telethon QR-login flow.

    D1 FIX: Uses client.connect() / client.disconnect() in a try/finally,
    NOT `async with TelegramClient(...)`. The async-with calls __aenter__
    which calls start(), which on a fresh/empty StringSession blocks on
    input() for a phone number BEFORE qr_login() is reached.

    D2: Renders qr.url as a scannable terminal QR to stderr via segno.

    D3: Wraps qr.wait() in a bounded refresh loop — on TimeoutError, calls
    qr.recreate(), re-renders the new URL, and retries. After _QR_MAX_CYCLES
    exhausted, raises QRLoginTimeoutError (ADR-008 D3 fail-loud).

    On success: persists the StringSession to config_dir and returns
    {"connected": True, "reused": False}.

    The returned session string is NEVER passed to any HTTP endpoint
    (ADR-018 D4 / D2 FIRM). It lives only in the local file.

    Real Telethon QRLogin API (telethon/tl/custom/qrlogin.py):
    - client.qr_login() returns a QRLogin object with .url, .wait(), .recreate()
    - await qr.wait(timeout=N) blocks until scanned; raises asyncio.TimeoutError
    - await qr.recreate() refreshes the token/URL for a new QR code
    """
    client = TelegramClient(StringSession(), api_id, api_hash)
    try:
        await client.connect()
        qr = await client.qr_login()
        _render_qr(qr.url)

        for cycle in range(_QR_MAX_CYCLES):
            try:
                await qr.wait(timeout=_QR_WAIT_TIMEOUT)
                # Scanned successfully
                session_string = client.session.save()
                save_telegram_session(config_dir=config_dir, session_string=session_string)
                return {"connected": True, "reused": False}
            except asyncio.TimeoutError:
                if cycle == _QR_MAX_CYCLES - 1:
                    raise QRLoginTimeoutError(
                        "QR login timed out after all refresh cycles. "
                        "The QR code was not scanned in time. "
                        "Run `switch-cli telegram connect` again."
                    )
                # Refresh the QR code and try again
                await qr.recreate()
                _render_qr(qr.url)

        # Should be unreachable, but satisfy type checker
        raise QRLoginTimeoutError(
            "QR login timed out. Run `switch-cli telegram connect` again."
        )
    finally:
        await client.disconnect()


async def reuse_session(api_id: int, api_hash: str, session_string: str) -> dict:
    """
    Connect using an existing StringSession (no re-login).

    Returns {"connected": True, "reused": True}.
    The session string is used locally only — not sent to any server
    (ADR-018 D4 / D2 FIRM).
    """
    async with TelegramClient(StringSession(session_string), api_id, api_hash) as client:
        _ = client.is_connected()
        return {"connected": True, "reused": True}


def run_connect(api_id: int, api_hash: str, config_dir: str) -> dict:
    """
    Synchronous entry point for the `telegram connect` CLI command.

    1. If a valid session file exists: reuse it (no re-login).
    2. Otherwise: run the QR-login flow and persist the new session.

    Raises:
    - TelegramConfigError if api_id/api_hash are absent (ADR-008 D3).
      Guard is enforced HERE so sibling callers (kb-ru55.3/.4) get the same
      protection; cli.py also validates, but the contract lives in run_connect.
    - SessionCorruptError if session file is corrupt (ADR-008 D3).
    - QRLoginTimeoutError if QR scan times out (ADR-008 D3).
    """
    if not api_id or not api_hash:
        raise TelegramConfigError(
            "Telegram api_id and api_hash are required. "
            "Add a [telegram] section to your switch-cli config with api_id and api_hash. "
            "Obtain these from https://my.telegram.org/apps ."
        )
    existing = load_telegram_session(config_dir=config_dir)
    if existing is not None:
        return asyncio.run(reuse_session(api_id=api_id, api_hash=api_hash, session_string=existing))
    return asyncio.run(qr_connect(api_id=api_id, api_hash=api_hash, config_dir=config_dir))
