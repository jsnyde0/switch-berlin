"""
Round-trip test: CLI pairing flow → create-event → event reachable via ORM + API GET + web hub.

Acceptance for kb-a4u.7:
- switch-cli pair <pairing-token> redeems the token and stores the Bearer key.
- switch-cli create-event ... creates an Event via the real HTTP API.
- That same Event is verifiable via:
  (1) direct ORM query (Event.objects.get)
  (2) API GET /api/events/{id}/ with a valid identity token
  (3) web event-hub URL /syndication/events/{id}/ (HTTP 200, event title in body)

The test uses Django's StaticLiveServerTestCase so the CLI subprocess (or its
HTTP client function) hits a real HTTP server backed by the real test DB.

Auth chain exercised end-to-end per ADR-016 D3 v0 pairing mechanic:
  1. Facilitator hits agents/register → pairing token (minted here via API directly).
  2. CLI `pair <pairing-token>` → POSTs to /api/agents/redeem → receives + stores Bearer key.
  3. CLI `create-event` exchanges Bearer key for identity token (POST /api/agents/token).
  4. CLI posts to /api/events/ with identity token.
  5. Test verifies the event in three ways (ORM, API, web).

NOTE: kb-a4u.9 (co-equal handler introspection) is OUT OF SCOPE here.
This test only proves "CLI-created event is reachable via web + API".
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase

from events.models import Event
from organizers.models import Profile, ProfileClaim

User = get_user_model()

# Absolute path to the switch-cli package root
SWITCH_CLI_DIR = Path(__file__).parent.parent / "tools" / "switch-cli"


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(user, name="Test Org", slug="test-org"):
    profile = Profile.objects.create(name=name, slug=slug)
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="auto_self",
    )
    return profile


class CLICreateEventRoundTripTest(LiveServerTestCase):
    """
    CLI create-event round-trip: event created via CLI is reachable via
    ORM, API GET, and web event-hub view.

    Uses the v0 pairing mechanic (ADR-016 D3): `pair <token>` redeems the
    one-time pairing token for the long-lived Bearer key — no raw key paste.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="cli_rt_user",
            email="cli_rt@example.com",
            password="testpass123",
        )
        self.profile = _make_profile(self.user)

    def _invoke_cli(self, *args, config_file=None):
        """
        Invoke the switch-cli via `uv run` as a subprocess.

        Passes SWITCH_CLI_CONFIG env var to point at a temp config file
        so tests don't clobber ~/.config/switch-cli/config.toml.
        Returns (returncode, stdout, stderr).
        """
        env_overrides = {}
        if config_file:
            env_overrides["SWITCH_CLI_CONFIG"] = str(config_file)

        env = os.environ.copy()
        env.update(env_overrides)

        uv_bin = shutil.which("uv") or "uv"
        result = subprocess.run(
            [
                uv_bin, "run",
                "--directory", str(SWITCH_CLI_DIR),
                "switch-cli",
                *args,
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def _mint_pairing_token(self):
        """
        Mint a pairing token via the agents/register endpoint (simulates the
        facilitator's browser action). Returns the raw pairing_token string.
        """
        from django.test import Client as DjangoClient
        client = DjangoClient()
        client.force_login(self.user)
        response = client.post("/api/agents/register")
        self.assertEqual(response.status_code, 200, f"register failed: {response.content}")
        return response.json()["pairing_token"]

    def _get_identity_token_from_key(self, raw_api_key: str):
        """
        Exchange a raw Bearer API key for an identity token via the live server.
        This exercises leg 2 of the auth chain (ADR-016 D3).
        """
        import httpx
        response = httpx.post(
            f"{self.live_server_url}/api/agents/token",
            json={"api_key": raw_api_key},
        )
        self.assertEqual(
            response.status_code, 200,
            f"Token exchange failed: {response.text}",
        )
        return response.json()["identity_token"]

    def test_cli_pair_then_create_event_round_trip(self):
        """
        Core acceptance (ADR-016 D3 pairing mechanic):
        1. Mint pairing token via agents/register (simulating facilitator browser step).
        2. Run: switch-cli configure --base-url <url>
        3. Run: switch-cli pair <pairing-token>  → stores Bearer key in config.
        4. Run: switch-cli create-event <fields> → uses stored Bearer key.
        5. Assert ORM: Event.objects.get(pk=event_id) succeeds.
        6. Assert API GET: /api/events/{event_id}/ returns the event.
        7. Assert web: /syndication/events/{event_id}/ returns 200 with title.
        """
        with tempfile.NamedTemporaryFile(
            suffix=".toml", mode="w", delete=False
        ) as f:
            config_path = f.name
            # Start with an empty file — configure and pair will populate it

        self.addCleanup(lambda: os.unlink(config_path) if os.path.exists(config_path) else None)

        # Step 1: Mint a real pairing token via the live server's API
        pairing_token = self._mint_pairing_token()

        # Step 2: configure (stores base_url only — no api_key paste)
        rc, out, err = self._invoke_cli(
            "configure",
            "--base-url", self.live_server_url,
            config_file=config_path,
        )
        self.assertEqual(rc, 0, f"configure failed.\nstdout: {out}\nstderr: {err}")

        # Step 3: pair (redeems pairing token → stores Bearer key in config)
        rc, out, err = self._invoke_cli(
            "pair",
            pairing_token,
            config_file=config_path,
        )
        self.assertEqual(rc, 0, f"pair failed.\nstdout: {out}\nstderr: {err}")
        pair_data = json.loads(out)
        self.assertTrue(pair_data.get("paired"), f"pair did not return paired=true: {pair_data}")

        # Step 4: create-event (uses the stored Bearer key)
        start_dt = "2027-06-15T19:00:00"
        event_title = "CLI Round-Trip Test Event"
        event_slug = "cli-round-trip-test"

        rc, stdout, stderr = self._invoke_cli(
            "create-event",
            "--title", event_title,
            "--slug", event_slug,
            "--start", start_dt,
            "--description", "Created by CLI round-trip test.",
            config_file=config_path,
        )

        self.assertEqual(
            rc, 0,
            f"CLI exited non-zero.\nstdout: {stdout}\nstderr: {stderr}"
        )

        # Parse machine-readable JSON output from CLI
        try:
            result = json.loads(stdout)
        except json.JSONDecodeError as e:
            self.fail(f"CLI stdout is not valid JSON: {e}\nstdout: {stdout}")

        self.assertIn("id", result, f"CLI JSON response missing 'id': {result}")
        event_id = result["id"]

        # --- Assertion 1: ORM ---
        try:
            event = Event.objects.get(pk=event_id)
        except Event.DoesNotExist:
            self.fail(f"Event {event_id} not found in DB after CLI create-event")

        self.assertEqual(event.title, event_title)
        self.assertEqual(event.slug, event_slug)

        # --- Assertion 2: API GET (read back the api_key from config to get identity token) ---
        import tomllib
        with open(config_path, "rb") as fh:
            stored_cfg = tomllib.load(fh)
        identity_token = self._get_identity_token_from_key(stored_cfg["api_key"])

        import httpx
        api_response = httpx.get(
            f"{self.live_server_url}/api/events/{event_id}/",
            headers={"Authorization": f"Bearer {identity_token}"},
        )
        self.assertEqual(
            api_response.status_code, 200,
            f"API GET returned {api_response.status_code}: {api_response.text}"
        )
        api_data = api_response.json()
        self.assertEqual(api_data["title"], event_title)
        self.assertEqual(api_data["id"], event_id)

        # --- Assertion 3: Web event-hub view ---
        from django.test import Client
        web_client = Client()
        web_client.force_login(self.user)
        web_response = web_client.get(f"/syndication/events/{event_id}/")
        self.assertEqual(
            web_response.status_code, 200,
            f"Web hub returned {web_response.status_code}"
        )
        # Title must appear somewhere in the HTML body
        self.assertContains(web_response, event_title)
