"""
Unit tests for switch-cli CLI commands.

Uses Click's test runner to invoke commands without a real HTTP server.
HTTP calls are mocked via httpx's MockTransport / pytest monkeypatching.

RED-GREEN-REFACTOR per TDD discipline.
"""

import json
from unittest.mock import MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner
from switch_cli.cli import cli
from switch_cli.config import save_config


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def configured_env(tmp_path, monkeypatch):
    """
    Provide a temp config file pre-written with a fake base_url and api_key.
    Also patches httpx.post to return a fake identity token exchange response,
    so SwitchClient() can be constructed without a real server.
    """
    config_path = tmp_path / "config.toml"
    monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
    save_config(base_url="http://fake-switch.test", api_key="fake-bearer-key")
    return config_path


class TestConfigureCommand:
    """switch-cli configure stores base_url only (no raw --api-key paste path)."""

    def test_configure_exits_zero(self, runner, tmp_path, monkeypatch):
        """configure --base-url exits with code 0."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        result = runner.invoke(cli, [
            "configure",
            "--base-url", "http://localhost:8000",
        ])
        assert result.exit_code == 0, result.output

    def test_configure_output_is_json(self, runner, tmp_path, monkeypatch):
        """configure outputs JSON confirming base_url."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        result = runner.invoke(cli, [
            "configure",
            "--base-url", "http://localhost:8000",
        ])
        data = json.loads(result.output)
        assert data["configured"] is True
        assert data["base_url"] == "http://localhost:8000"

    def test_configure_creates_config_file(self, runner, tmp_path, monkeypatch):
        """configure creates the config file on disk."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        assert not config_path.exists()
        runner.invoke(cli, [
            "configure",
            "--base-url", "http://localhost:8000",
        ])
        assert config_path.exists()

    def test_configure_does_not_accept_api_key_option(self, runner, tmp_path, monkeypatch):
        """
        configure must NOT accept --api-key (raw-key paste path removed per ADR-016 D3).
        The long-lived key is obtained only via `pair <pairing-token>`.
        """
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        result = runner.invoke(cli, [
            "configure",
            "--base-url", "http://localhost:8000",
            "--api-key", "should-be-rejected",
        ])
        # Click exits with code 2 for unrecognised options
        assert result.exit_code == 2


class TestPairCommand:
    """switch-cli pair <pairing-token> redeems the token and stores the api_key."""

    def _mock_redeem_response(self, api_key="returned-bearer-key"):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"api_key": api_key}
        return mock_resp

    def test_pair_exits_zero(self, runner, tmp_path, monkeypatch):
        """pair command exits with code 0 on a successful redeem."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response()
        with patch("httpx.post", return_value=redeem_resp):
            result = runner.invoke(cli, [
                "pair",
                "my-pairing-token",
                "--base-url", "http://localhost:8000",
            ])
        assert result.exit_code == 0, result.output

    def test_pair_posts_to_agents_redeem(self, runner, tmp_path, monkeypatch):
        """pair POSTs to /api/agents/redeem with pairing_token in the body."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response()
        with patch("httpx.post", return_value=redeem_resp) as mock_post:
            runner.invoke(cli, [
                "pair",
                "test-token-123",
                "--base-url", "http://localhost:8000",
            ])
        call = mock_post.call_args
        assert "/api/agents/redeem" in call[0][0]
        assert call.kwargs.get("json", {}).get("pairing_token") == "test-token-123"

    def test_pair_stores_api_key_in_config(self, runner, tmp_path, monkeypatch):
        """pair stores the returned api_key in the config file."""
        from switch_cli.config import load_config
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response(api_key="stored-bearer-key")
        with patch("httpx.post", return_value=redeem_resp):
            runner.invoke(cli, [
                "pair",
                "test-token-456",
                "--base-url", "http://localhost:8000",
            ])
        cfg = load_config()
        assert cfg["api_key"] == "stored-bearer-key"
        assert cfg["base_url"] == "http://localhost:8000"

    def test_pair_does_not_print_api_key(self, runner, tmp_path, monkeypatch):
        """pair output must NOT contain the Bearer key value."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response(api_key="super-secret-bearer-key")
        with patch("httpx.post", return_value=redeem_resp):
            result = runner.invoke(cli, [
                "pair",
                "token-789",
                "--base-url", "http://localhost:8000",
            ])
        assert "super-secret-bearer-key" not in result.output

    def test_pair_does_not_print_pairing_token(self, runner, tmp_path, monkeypatch):
        """pair output must NOT echo the pairing token back."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response()
        with patch("httpx.post", return_value=redeem_resp):
            result = runner.invoke(cli, [
                "pair",
                "pairing-token-do-not-echo",
                "--base-url", "http://localhost:8000",
            ])
        assert "pairing-token-do-not-echo" not in result.output

    def test_pair_outputs_success_json(self, runner, tmp_path, monkeypatch):
        """pair outputs JSON success metadata (not the key)."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response()
        with patch("httpx.post", return_value=redeem_resp):
            result = runner.invoke(cli, [
                "pair",
                "tok",
                "--base-url", "http://localhost:8000",
            ])
        data = json.loads(result.output)
        assert data.get("paired") is True

    def test_pair_reads_base_url_from_config(self, runner, tmp_path, monkeypatch):
        """pair uses base_url from existing config when --base-url is not given."""
        from switch_cli.config import save_config
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        # Write a partial config with only base_url
        save_config(base_url="http://from-config.test", api_key="placeholder")
        redeem_resp = self._mock_redeem_response(api_key="new-bearer-key")
        with patch("httpx.post", return_value=redeem_resp) as mock_post:
            result = runner.invoke(cli, [
                "pair",
                "tok-from-config",
            ])
        assert result.exit_code == 0, result.output
        call = mock_post.call_args
        assert "http://from-config.test" in call[0][0]

    def test_pair_invalid_token_exits_nonzero(self, runner, tmp_path, monkeypatch):
        """pair exits non-zero when the server rejects the pairing token (401)."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 401
        error_resp.json.return_value = {"detail": "Invalid pairing token."}
        error_resp.text = "Invalid pairing token."
        with patch("httpx.post", return_value=error_resp):
            result = runner.invoke(cli, [
                "pair",
                "bad-token",
                "--base-url", "http://localhost:8000",
            ])
        assert result.exit_code != 0

    def test_pair_no_auth_header_on_redeem_call(self, runner, tmp_path, monkeypatch):
        """pair sends no Authorization header on the redeem call (unauthenticated)."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        redeem_resp = self._mock_redeem_response()
        with patch("httpx.post", return_value=redeem_resp) as mock_post:
            runner.invoke(cli, [
                "pair",
                "tok",
                "--base-url", "http://localhost:8000",
            ])
        call = mock_post.call_args
        headers = call.kwargs.get("headers", {}) or {}
        assert "Authorization" not in headers


class TestCreateEventCommand:
    """switch-cli create-event talks to the API and returns JSON."""

    def _mock_token_response(self):
        """Return a mock httpx.Response for the token exchange."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "identity_token": "fake-identity-token-uuid",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        return mock_resp

    def _mock_event_response(self, event_id=42, title="Test Event", slug="test-event"):
        """Return a mock httpx.Response for the events create endpoint."""
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "id": event_id,
            "title": title,
            "slug": slug,
            "start": "2027-06-15T19:00:00",
            "end": None,
            "description": "",
            "status": "draft",
            "visibility": "public",
            "dress_code": "",
            "content_warnings": [],
            "age_restriction": None,
            "capacity": None,
            "language": "",
            "is_free": False,
            "price_min_cents": None,
            "price_max_cents": None,
            "currency": "EUR",
            "sliding_scale": False,
            "price_description": "",
            "external_url": "",
            "tickets_url": "",
            "registration_required": False,
            "registration_url": "",
            "registration_email": "",
        }
        return mock_resp

    def test_create_event_outputs_json_with_id(self, runner, configured_env):
        """create-event outputs JSON containing the event id."""
        token_resp = self._mock_token_response()
        event_resp = self._mock_event_response(event_id=99, title="My Test Event")

        with patch("httpx.post", side_effect=[token_resp, event_resp]):
            result = runner.invoke(cli, [
                "create-event",
                "--title", "My Test Event",
                "--slug", "my-test-event",
                "--start", "2027-06-15T19:00:00",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == 99
        assert data["title"] == "My Test Event"

    def test_create_event_calls_agents_token_first(self, runner, configured_env):
        """create-event exchanges the Bearer key for an identity token first."""
        token_resp = self._mock_token_response()
        event_resp = self._mock_event_response()

        with patch("httpx.post", side_effect=[token_resp, event_resp]) as mock_post:
            runner.invoke(cli, [
                "create-event",
                "--title", "Event",
                "--slug", "event",
                "--start", "2027-06-15T19:00:00",
            ])

        # First post call is to /api/agents/token
        first_call = mock_post.call_args_list[0]
        assert "/api/agents/token" in first_call[0][0]

    def test_create_event_uses_identity_token_as_bearer(self, runner, configured_env):
        """create-event uses the identity token on the /api/events/ endpoint."""
        token_resp = self._mock_token_response()
        event_resp = self._mock_event_response()

        with patch("httpx.post", side_effect=[token_resp, event_resp]) as mock_post:
            runner.invoke(cli, [
                "create-event",
                "--title", "Event",
                "--slug", "event",
                "--start", "2027-06-15T19:00:00",
            ])

        # Second post call to /api/events/ carries Bearer identity token
        second_call = mock_post.call_args_list[1]
        # Assert URL — a path typo would fail the test
        assert "/api/events/" in second_call[0][0]
        headers = second_call.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer fake-identity-token-uuid"

    def test_create_event_auth_error_exits_nonzero(self, runner, configured_env):
        """create-event exits non-zero when auth fails (401 on token exchange)."""
        error_resp = MagicMock(spec=httpx.Response)
        error_resp.status_code = 401
        error_resp.json.return_value = {"detail": "Invalid or revoked API key."}
        error_resp.text = "Invalid or revoked API key."

        with patch("httpx.post", return_value=error_resp):
            result = runner.invoke(cli, [
                "create-event",
                "--title", "Event",
                "--slug", "event",
                "--start", "2027-06-15T19:00:00",
            ])

        assert result.exit_code != 0


class TestCreatePostCommand:
    """switch-cli create-post talks to the event posts endpoint."""

    def test_create_post_calls_event_posts_endpoint(self, runner, configured_env):
        """create-post sends request to /api/events/{event_id}/posts/."""
        token_resp = MagicMock(spec=httpx.Response)
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "identity_token": "tok",
            "expires_at": "2027-01-01Z",
        }

        post_resp = MagicMock(spec=httpx.Response)
        post_resp.status_code = 201
        post_resp.json.return_value = {
            "id": 5,
            "event_id": 10,
            "headline": "Big Headline",
            "body": "Post body",
            "cta": "",
            "voice": "",
        }

        with patch("httpx.post", side_effect=[token_resp, post_resp]) as mock_post:
            result = runner.invoke(cli, [
                "create-post",
                "--event-id", "10",
                "--headline", "Big Headline",
                "--body", "Post body",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == 5
        assert data["event_id"] == 10

        # Second call must target the posts endpoint
        second_call = mock_post.call_args_list[1]
        assert "/api/events/10/posts/" in second_call[0][0]


class TestCreatePostCommand_Imagery:
    """switch-cli create-post sends imagery field when --imagery is given."""

    def test_create_post_sends_imagery_in_request_body(self, runner, configured_env):
        """create-post sends imagery list in the POST body."""
        token_resp = MagicMock(spec=httpx.Response)
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "identity_token": "tok",
            "expires_at": "2027-01-01Z",
        }

        post_resp = MagicMock(spec=httpx.Response)
        post_resp.status_code = 201
        post_resp.json.return_value = {
            "id": 7,
            "event_id": 11,
            "headline": "Headline",
            "body": "Body",
            "cta": "",
            "voice": "",
        }

        with patch("httpx.post", side_effect=[token_resp, post_resp]) as mock_post:
            result = runner.invoke(cli, [
                "create-post",
                "--event-id", "11",
                "--headline", "Headline",
                "--body", "Body",
                "--imagery", "https://img.test/a.jpg",
                "--imagery", "https://img.test/b.jpg",
            ])

        assert result.exit_code == 0, result.output

        # Second call must include imagery in JSON body
        second_call = mock_post.call_args_list[1]
        sent_json = second_call.kwargs.get("json", {})
        assert sent_json.get("imagery") == [
            "https://img.test/a.jpg",
            "https://img.test/b.jpg",
        ]


class TestListProjectionsCommand:
    """switch-cli list-projections calls the projections list endpoint."""

    def test_list_projections_outputs_json(self, runner, configured_env):
        """list-projections outputs JSON (stub body at v0) from /api/projections/."""
        token_resp = MagicMock(spec=httpx.Response)
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "identity_token": "tok",
            "expires_at": "2027-01-01Z",
        }

        proj_resp = MagicMock(spec=httpx.Response)
        proj_resp.status_code = 200
        proj_resp.json.return_value = {
            "stub": True,
            "detail": "Projection list not yet implemented.",
        }

        with patch("httpx.post", return_value=token_resp):
            with patch("httpx.get", return_value=proj_resp) as mock_get:
                result = runner.invoke(cli, ["list-projections"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "stub" in data

        # Assert the request went to /api/projections/
        get_call = mock_get.call_args_list[0]
        assert "/api/projections/" in get_call[0][0]


class TestApproveProjectionCommand:
    """switch-cli approve-projection maps to POST /api/projections/{id}/approve/."""

    def _mock_token_response(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "identity_token": "fake-identity-token-uuid",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        return mock_resp

    def _mock_approve_response(self, projection_id=5):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": projection_id,
            "status": "ready",
        }
        return mock_resp

    def test_approve_projection_calls_approve_endpoint(self, runner, configured_env):
        """approve-projection POSTs to /api/projections/{id}/approve/."""
        token_resp = self._mock_token_response()
        approve_resp = self._mock_approve_response(projection_id=5)

        with patch("httpx.post", side_effect=[token_resp, approve_resp]) as mock_post:
            result = runner.invoke(cli, [
                "approve-projection",
                "--projection-id", "5",
            ])

        assert result.exit_code == 0, result.output

        second_call = mock_post.call_args_list[1]
        assert "/api/projections/5/approve/" in second_call[0][0]

    def test_approve_projection_uses_identity_token_as_bearer(self, runner, configured_env):
        """approve-projection sends identity token as Bearer on approve call."""
        token_resp = self._mock_token_response()
        approve_resp = self._mock_approve_response(projection_id=5)

        with patch("httpx.post", side_effect=[token_resp, approve_resp]) as mock_post:
            runner.invoke(cli, [
                "approve-projection",
                "--projection-id", "5",
            ])

        second_call = mock_post.call_args_list[1]
        headers = second_call.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer fake-identity-token-uuid"

    def test_approve_projection_outputs_json(self, runner, configured_env):
        """approve-projection outputs the updated projection as JSON."""
        token_resp = self._mock_token_response()
        approve_resp = self._mock_approve_response(projection_id=5)

        with patch("httpx.post", side_effect=[token_resp, approve_resp]):
            result = runner.invoke(cli, [
                "approve-projection",
                "--projection-id", "5",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == 5
        assert data["status"] == "ready"


class TestPublishProjectionCommand:
    """switch-cli publish-projection maps to POST /api/projections/{id}/publish/."""

    def _mock_token_response(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "identity_token": "fake-identity-token-uuid",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        return mock_resp

    def _mock_publish_response(self, projection_id=3):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": projection_id,
            "status": "published",
        }
        return mock_resp

    def test_publish_projection_calls_publish_endpoint(self, runner, configured_env):
        """publish-projection POSTs to /api/projections/{id}/publish/."""
        token_resp = self._mock_token_response()
        publish_resp = self._mock_publish_response(projection_id=3)

        with patch("httpx.post", side_effect=[token_resp, publish_resp]) as mock_post:
            result = runner.invoke(cli, [
                "publish-projection",
                "--projection-id", "3",
            ])

        assert result.exit_code == 0, result.output

        second_call = mock_post.call_args_list[1]
        assert "/api/projections/3/publish/" in second_call[0][0]

    def test_publish_projection_uses_identity_token_as_bearer(self, runner, configured_env):
        """publish-projection sends identity token as Bearer on publish call."""
        token_resp = self._mock_token_response()
        publish_resp = self._mock_publish_response(projection_id=3)

        with patch("httpx.post", side_effect=[token_resp, publish_resp]) as mock_post:
            runner.invoke(cli, [
                "publish-projection",
                "--projection-id", "3",
            ])

        second_call = mock_post.call_args_list[1]
        headers = second_call.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer fake-identity-token-uuid"


class TestMarkPublishedCommand:
    """switch-cli mark-published maps to POST /api/projections/{id}/mark-published/."""

    def _mock_token_response(self):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "identity_token": "fake-identity-token-uuid",
            "expires_at": "2027-01-01T00:00:00Z",
        }
        return mock_resp

    def _mock_mark_published_response(self, projection_id=8):
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": projection_id,
            "status": "published",
        }
        return mock_resp

    def test_mark_published_calls_mark_published_endpoint(self, runner, configured_env):
        """mark-published POSTs to /api/projections/{id}/mark-published/."""
        token_resp = self._mock_token_response()
        mark_resp = self._mock_mark_published_response(projection_id=8)

        with patch("httpx.post", side_effect=[token_resp, mark_resp]) as mock_post:
            result = runner.invoke(cli, [
                "mark-published",
                "--projection-id", "8",
            ])

        assert result.exit_code == 0, result.output

        second_call = mock_post.call_args_list[1]
        assert "/api/projections/8/mark-published/" in second_call[0][0]

    def test_mark_published_uses_identity_token_as_bearer(self, runner, configured_env):
        """mark-published sends identity token as Bearer."""
        token_resp = self._mock_token_response()
        mark_resp = self._mock_mark_published_response(projection_id=8)

        with patch("httpx.post", side_effect=[token_resp, mark_resp]) as mock_post:
            runner.invoke(cli, [
                "mark-published",
                "--projection-id", "8",
            ])

        second_call = mock_post.call_args_list[1]
        headers = second_call.kwargs.get("headers", {})
        assert headers.get("Authorization") == "Bearer fake-identity-token-uuid"

    def test_mark_published_outputs_json(self, runner, configured_env):
        """mark-published outputs the updated projection as JSON."""
        token_resp = self._mock_token_response()
        mark_resp = self._mock_mark_published_response(projection_id=8)

        with patch("httpx.post", side_effect=[token_resp, mark_resp]):
            result = runner.invoke(cli, [
                "mark-published",
                "--projection-id", "8",
            ])

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["id"] == 8


class TestGenerateProjectionRemoved:
    """generate-projection verb must no longer exist (replaced by approve-projection)."""

    def test_generate_projection_verb_does_not_exist(self, runner, configured_env):
        """generate-projection is removed from registered CLI commands."""
        # Invoking the removed verb returns exit code 2 ("No such command")
        result = runner.invoke(cli, ["generate-projection", "--projection-id", "1"])
        assert result.exit_code == 2
        assert "No such command" in result.output


class TestMissingConfigKeys:
    """load_config raises ConfigError (not KeyError) when required keys are missing."""

    def test_missing_base_url_raises_config_error(self, runner, tmp_path, monkeypatch):
        """CLI exits non-zero with structured error when base_url is missing from config."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        # Write config with only api_key — base_url missing
        config_path.write_text('api_key = "some-key"\n')

        result = runner.invoke(cli, [
            "create-event",
            "--title", "E",
            "--slug", "e",
            "--start", "2027-01-01T00:00:00",
        ])
        assert result.exit_code != 0
        # Must NOT produce a raw Python traceback to stderr
        assert "KeyError" not in (result.output + (result.exception.__class__.__name__ if result.exception else ""))

    def test_missing_api_key_raises_config_error(self, runner, tmp_path, monkeypatch):
        """CLI exits non-zero with structured error when api_key is missing from config."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setenv("SWITCH_CLI_CONFIG", str(config_path))
        # Write config with only base_url — api_key missing
        config_path.write_text('base_url = "http://fake.test"\n')

        result = runner.invoke(cli, [
            "create-event",
            "--title", "E",
            "--slug", "e",
            "--start", "2027-01-01T00:00:00",
        ])
        assert result.exit_code != 0
        assert "KeyError" not in (result.output + (result.exception.__class__.__name__ if result.exception else ""))
