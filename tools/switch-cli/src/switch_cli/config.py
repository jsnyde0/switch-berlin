"""
Config management for switch-cli.

Config lives at SWITCH_CLI_CONFIG env var, or ~/.config/switch-cli/config.toml.
Stores: base_url (API base URL), api_key (Bearer API key — stored, never printed).

ADR-016 D3 v0 pairing mechanic:
  1. `configure --base-url <url>` — store the non-secret base URL.
  2. `pair <pairing-token>` — POST to /api/agents/redeem, receive + store the Bearer key.
  The raw Bearer key NEVER transits the facilitator's clipboard.

Security: the api_key is stored in the config file but never printed/logged.
"""

import os
import tomllib
from pathlib import Path

import tomli_w

_REQUIRED_KEYS = ("base_url", "api_key")


class ConfigError(Exception):
    """Raised when the config file is missing required keys (ADR-008 D3: fail loud)."""


def _config_path() -> Path:
    """Return the config file path, respecting SWITCH_CLI_CONFIG env override."""
    override = os.environ.get("SWITCH_CLI_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "switch-cli" / "config.toml"


def load_config() -> dict:
    """
    Load config from disk.

    Raises FileNotFoundError if the config file does not exist.
    Raises ConfigError if required keys (base_url, api_key) are missing.
    Returns dict with at minimum 'base_url' and 'api_key'.
    """
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"switch-cli is not configured. "
            f"Run `switch-cli configure --base-url <url>` then `switch-cli pair <token>`.\n"
            f"Config path: {path}"
        )
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(
            f"Config at {path} is missing required keys: {', '.join(missing)}. "
            "Run `switch-cli configure --base-url <url>` then `switch-cli pair <token>`."
        )
    return cfg


def load_base_url() -> str:
    """
    Load only base_url from config (does not require api_key to be present).
    Used by `pair` which needs base_url before the api_key exists.

    Raises FileNotFoundError if config file does not exist.
    Raises ConfigError if base_url is missing.
    """
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"switch-cli is not configured. "
            f"Run `switch-cli configure --base-url <url>` first.\n"
            f"Config path: {path}"
        )
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    if "base_url" not in cfg:
        raise ConfigError(
            f"Config at {path} is missing base_url. "
            "Run `switch-cli configure --base-url <url>` first."
        )
    return cfg["base_url"]


def save_config(base_url: str, api_key: str) -> None:
    """
    Write full config (base_url + api_key) to disk.
    Never prints the api_key. Creates parent directories if needed.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
    }
    with open(path, "wb") as f:
        tomli_w.dump(config, f)


def save_base_url(base_url: str) -> None:
    """
    Write only base_url to config. Preserves existing api_key if present.
    Used by `configure --base-url` — the non-secret setup step.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve existing keys (e.g. api_key) if already present
    existing: dict = {}
    if path.exists():
        with open(path, "rb") as f:
            existing = tomllib.load(f)
    existing["base_url"] = base_url.rstrip("/")
    with open(path, "wb") as f:
        tomli_w.dump(existing, f)
