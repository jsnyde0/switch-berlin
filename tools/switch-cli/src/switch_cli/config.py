"""
Config management for switch-cli.

Config lives at SWITCH_CLI_CONFIG env var, or ~/.config/switch-cli/config.toml.
Stores: base_url (API base URL), api_key (Bearer API key — stored, never printed).

ADR-016 D3: the Bearer API key is long-lived and reusable. We store it so the
CLI can exchange it for an identity token on each command invocation.

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
            f"switch-cli is not configured. Run `switch-cli configure` first.\n"
            f"Config path: {path}"
        )
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    missing = [k for k in _REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(
            f"Config at {path} is missing required keys: {', '.join(missing)}. "
            "Run `switch-cli configure` to fix."
        )
    return cfg


def save_config(base_url: str, api_key: str) -> None:
    """
    Write config to disk. Never prints the api_key.
    Creates parent directories if needed.
    """
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
    }
    with open(path, "wb") as f:
        tomli_w.dump(config, f)
