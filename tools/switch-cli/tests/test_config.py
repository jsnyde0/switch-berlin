"""
Unit tests for switch-cli config module.

RED-GREEN-REFACTOR per TDD discipline.
These run entirely within the switch-cli venv — no Django needed.
"""

import pytest
from switch_cli.config import load_config, save_config


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    """
    Fixture: redirect SWITCH_CLI_CONFIG to a temp file path.
    Yields the path (does NOT create the file — tests that check load_config
    before configure will trigger FileNotFoundError correctly).
    """
    config_file = tmp_path / "config.toml"
    monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_file))
    yield config_file


class TestSaveConfig:
    """save_config writes the expected TOML fields."""

    def test_save_creates_file(self, temp_config):
        """save_config creates the config file."""
        assert not temp_config.exists()
        save_config(base_url="http://localhost:8000", api_key="test-key")
        assert temp_config.exists()

    def test_save_writes_base_url(self, temp_config):
        """Saved config contains the base_url."""
        save_config(base_url="http://localhost:8000", api_key="test-key")
        cfg = load_config()
        assert cfg["base_url"] == "http://localhost:8000"

    def test_save_strips_trailing_slash(self, temp_config):
        """Base URL trailing slashes are stripped."""
        save_config(base_url="http://localhost:8000/", api_key="test-key")
        cfg = load_config()
        assert cfg["base_url"] == "http://localhost:8000"

    def test_api_key_stored_not_printed(self, temp_config, capsys):
        """
        The api_key is stored but save_config prints nothing to stdout.
        (The key is in the file; we verify stdout is empty.)
        """
        save_config(base_url="http://localhost:8000", api_key="secret-key")
        captured = capsys.readouterr()
        assert "secret-key" not in captured.out
        assert "secret-key" not in captured.err


class TestLoadConfig:
    """load_config reads the config file correctly."""

    def test_load_raises_if_not_configured(self, temp_config):
        """load_config raises FileNotFoundError if config doesn't exist."""
        assert not temp_config.exists()
        with pytest.raises(FileNotFoundError):
            load_config()

    def test_load_returns_base_url(self, temp_config):
        """load_config returns the stored base_url."""
        save_config(base_url="http://switch.test", api_key="k")
        cfg = load_config()
        assert cfg["base_url"] == "http://switch.test"

    def test_load_returns_api_key(self, temp_config):
        """load_config returns the stored api_key."""
        save_config(base_url="http://switch.test", api_key="my-bearer-key")
        cfg = load_config()
        assert cfg["api_key"] == "my-bearer-key"
