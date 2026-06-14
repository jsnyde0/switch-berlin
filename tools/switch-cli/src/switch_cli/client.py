"""
HTTP client for the Switch syndication API.

Auth chain (ADR-016 D3):
1. Bearer API key (AgentCredential) — long-lived, reusable, stored in config.
2. Exchange Bearer key for short-lived (~1h) identity token — REUSABLE within TTL.
3. Protected endpoints called with identity token as Bearer header.

The client exchanges the stored Bearer key for an identity token on each
SwitchClient instantiation. Callers should cache the client within a
command invocation if they make multiple API calls.

Security: the raw api_key is never logged or printed.
"""

import httpx

from switch_cli.config import load_base_url, load_config


class AuthError(Exception):
    """Raised when authentication fails (invalid/revoked API key or 401)."""


class APIError(Exception):
    """Raised when the API returns an unexpected error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API error {status_code}: {detail}")


class SwitchClient:
    """
    Authenticated HTTP client for the Switch API.

    On construction, exchanges the stored Bearer API key for an identity token.
    All subsequent calls use the identity token as the Bearer credential.
    """

    def __init__(self, base_url: str = None, api_key: str = None):
        if base_url is None or api_key is None:
            cfg = load_config()
            base_url = base_url or cfg["base_url"]
            api_key = api_key or cfg["api_key"]

        self._base_url = base_url.rstrip("/")
        # Exchange for identity token — api_key is not stored after exchange
        self._identity_token = self._exchange(api_key)

    def _exchange(self, api_key: str) -> str:
        """
        Leg 2: POST /api/agents/token with the Bearer API key.
        Returns the short-lived identity token string (UUID).
        Raises AuthError on failure.
        """
        url = f"{self._base_url}/api/agents/token"
        response = httpx.post(url, json={"api_key": api_key})
        if response.status_code == 401:
            raise AuthError("Invalid or revoked API key. Re-run `switch-cli configure` with a fresh API key.")
        if response.status_code != 200:
            raise AuthError(f"Unexpected response from /api/agents/token: {response.status_code} {response.text}")
        return response.json()["identity_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._identity_token}"}

    def _check(self, response: httpx.Response) -> dict:
        """Raise APIError for non-2xx; return parsed JSON on success."""
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except Exception:
                detail = response.text
            raise APIError(response.status_code, detail)
        return response.json()

    # ------------------------------------------------------------------
    # Event verbs
    # ------------------------------------------------------------------

    def create_event(self, **kwargs) -> dict:
        """POST /api/events/ — create a canonical Event. Returns event dict."""
        response = httpx.post(
            f"{self._base_url}/api/events/",
            json=kwargs,
            headers=self._headers(),
        )
        return self._check(response)

    def get_event(self, event_id: int) -> dict:
        """GET /api/events/{event_id}/ — fetch a single Event."""
        response = httpx.get(
            f"{self._base_url}/api/events/{event_id}/",
            headers=self._headers(),
        )
        return self._check(response)

    def list_events(self) -> list:
        """GET /api/events/ — list all Events for the authenticated user."""
        response = httpx.get(
            f"{self._base_url}/api/events/",
            headers=self._headers(),
        )
        return self._check(response)

    # ------------------------------------------------------------------
    # Post verbs
    # ------------------------------------------------------------------

    def create_post(self, event_id: int, imagery=None, **kwargs) -> dict:
        """POST /api/events/{event_id}/posts/ — create a Post for an Event."""
        payload = dict(kwargs)
        if imagery is not None:
            payload["imagery"] = imagery
        response = httpx.post(
            f"{self._base_url}/api/events/{event_id}/posts/",
            json=payload,
            headers=self._headers(),
        )
        return self._check(response)

    # ------------------------------------------------------------------
    # Projection verbs
    # ------------------------------------------------------------------

    def list_projections(self) -> dict:
        """GET /api/projections/ — list projections (stubbed at v0)."""
        response = httpx.get(
            f"{self._base_url}/api/projections/",
            headers=self._headers(),
        )
        return self._check(response)

    def approve_projection(self, projection_id: int) -> dict:
        """POST /api/projections/{projection_id}/approve/ — draft→ready transition."""
        response = httpx.post(
            f"{self._base_url}/api/projections/{projection_id}/approve/",
            headers=self._headers(),
        )
        return self._check(response)

    def publish_projection(self, projection_id: int) -> dict:
        """POST /api/projections/{projection_id}/publish/ — ready→published."""
        response = httpx.post(
            f"{self._base_url}/api/projections/{projection_id}/publish/",
            headers=self._headers(),
        )
        return self._check(response)

    def mark_published(self, projection_id: int) -> dict:
        """POST /api/projections/{projection_id}/mark-published/ — record external publication."""
        response = httpx.post(
            f"{self._base_url}/api/projections/{projection_id}/mark-published/",
            headers=self._headers(),
        )
        return self._check(response)

    # ------------------------------------------------------------------
    # Telegram inventory ingest verb (kb-ru55.2 / kb-ru55.3)
    # ------------------------------------------------------------------

    def push_telegram_inventory(self, inventory: list[dict]) -> dict:
        """
        POST /api/telegram/inventory — push a metadata-only Telegram destination inventory.

        Payload: list of dicts with keys chat_id, title, type, topic_id, postability.
        The payload is METADATA-ONLY — no session_string, access_hash, or content
        (ADR-018 D4 / bead D2 FIRM). The server's extra="forbid" schema will 422 on
        any forbidden field.

        Returns dict with upserted and flagged counts.
        """
        response = httpx.post(
            f"{self._base_url}/api/telegram/inventory",
            json=inventory,
            headers=self._headers(),
        )
        return self._check(response)

    def report_telegram_placements(self, placements: list[dict]) -> dict:
        """
        POST /api/telegram/placements — report agent-tier placement outcomes.

        Payload: list of dicts with keys destination_id, status, topic_id?, error_detail?.
        The payload is METADATA-ONLY — no session_string, access_hash, or content
        (ADR-018 D4 / kb-56c2.1 D2 FIRM). The server's extra="forbid" schema will 422
        on any forbidden field.

        status values: {placed, failed, skipped-pre-existing-draft}.
        "sent" is NOT a valid status (ADR-018 D2 FIRM draft-only firewall).

        Returns dict with written count and per-item errors list.
        """
        response = httpx.post(
            f"{self._base_url}/api/telegram/placements",
            json=placements,
            headers=self._headers(),
        )
        return self._check(response)


def redeem_pairing_token(pairing_token: str, base_url: str = None) -> str:
    """
    Bootstrap step (ADR-016 D3): POST /api/agents/redeem with the pairing token.
    Returns the long-lived Bearer api_key string.

    This is NOT a SwitchClient method because it is the bootstrap step — it runs
    BEFORE the Bearer key exists. It takes the pairing token as its sole credential
    and sends NO Authorization header (the endpoint is unauthenticated).

    Raises AuthError on 401 (invalid/unknown pairing token).
    Raises APIError on other non-200 responses.

    Security: the returned api_key is NOT printed or logged by this function.
    """
    if base_url is None:
        base_url = load_base_url()
    base_url = base_url.rstrip("/")
    url = f"{base_url}/api/agents/redeem"
    response = httpx.post(url, json={"pairing_token": pairing_token})
    if response.status_code == 401:
        raise AuthError("Invalid or unknown pairing token.")
    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise APIError(response.status_code, detail)
    return response.json()["api_key"]
