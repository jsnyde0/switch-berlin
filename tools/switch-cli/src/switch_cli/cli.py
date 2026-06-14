"""
switch-cli: command-line interface for the Switch syndication HTTP API.

Agent-shaped tool (ADR-011 D1 agent-extended scope): external personal agents
and power-users drive Switch by shelling out to this CLI. All output is
machine-parseable JSON to stdout.

Auth chain (ADR-016 D3 v0 pairing mechanic):
1. configure --base-url <url>  — store the non-secret API base URL.
2. pair <pairing-token>        — redeem one-time token for the long-lived Bearer key;
                                  stores api_key in config. The Bearer key NEVER
                                  transits the facilitator's clipboard.
3. All other commands          — exchange stored Bearer key for identity token, then call API.

Verbs:
- configure           Store API base URL (no raw key paste — key is obtained via pair)
- pair                Redeem one-time pairing token → store Bearer key in config
- create-event        Create a canonical Event
- create-post         Create a Post (references an Event)
- approve-projection  Transition a projection draft→ready
- publish-projection  Transition a projection ready→published
- mark-published      Mark a projection as externally published
- list-projections    List projections for authenticated user
"""

import json
import sys

import click

from switch_cli.client import APIError, AuthError, SwitchClient, redeem_pairing_token
from switch_cli.config import ConfigError, load_base_url, load_config, save_base_url, save_config
from switch_cli.telegram.draft import UnknownDestinationError, run_distribute
from switch_cli.telegram.enumerate import NoSessionError, run_sync
from switch_cli.telegram.session import (
    QRLoginTimeoutError,
    SessionCorruptError,
    TelegramConfigError,
    _get_config_dir,
    run_connect,
)


def _output(data) -> None:
    """Write machine-parseable JSON to stdout. Agents consume this."""
    click.echo(json.dumps(data, default=str))


def _error(message: str, exit_code: int = 1) -> None:
    """Write error JSON to stderr and exit."""
    click.echo(json.dumps({"error": message}), err=True)
    sys.exit(exit_code)


@click.group()
def cli():
    """Switch syndication CLI — agent-shaped REST client."""


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


@cli.command("configure")
@click.option("--base-url", required=True, help="Switch API base URL (e.g. https://switch.example.com)")
def configure(base_url: str):
    """
    Store the API base URL in the config file (non-secret setup step).

    After configuring, run `switch-cli pair <pairing-token>` to obtain and
    store the Bearer API key via the pairing-token redemption flow.

    ADR-016 D3: the Bearer key is obtained by redemption, never pasted directly.
    """
    save_base_url(base_url=base_url)
    _output({"configured": True, "base_url": base_url.rstrip("/")})


# ---------------------------------------------------------------------------
# pair
# ---------------------------------------------------------------------------


@cli.command("pair")
@click.argument("pairing_token")
@click.option(
    "--base-url",
    default=None,
    help="Switch API base URL (falls back to configured base_url if omitted)",
)
def pair(pairing_token: str, base_url: str):
    """
    Redeem a one-time pairing token to obtain and store the Bearer API key.

    The facilitator mints a pairing token at /syndication/agents/pair/ and
    hands it to their agent. The agent calls this verb — which POSTs to
    /api/agents/redeem — to receive the long-lived Bearer key. The key is
    stored in the config file and never printed.

    ADR-016 D3: the Bearer key NEVER transits the facilitator's clipboard.
    """
    # Resolve base_url: flag > config file > error
    if base_url is None:
        try:
            base_url = load_base_url()
        except (FileNotFoundError, ConfigError) as exc:
            _error(f"No --base-url given and none in config: {exc}. Run `switch-cli configure --base-url <url>` first.")
    try:
        api_key = redeem_pairing_token(pairing_token=pairing_token, base_url=base_url)
    except AuthError as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"Redemption failed {exc.status_code}: {exc.detail}")
    # Store base_url + api_key atomically
    save_config(base_url=base_url, api_key=api_key)
    # Print only success metadata — never the key or the pairing token
    _output({"paired": True, "base_url": base_url.rstrip("/")})


# ---------------------------------------------------------------------------
# create-event
# ---------------------------------------------------------------------------


@cli.command("create-event")
@click.option("--title", required=True, help="Event title")
@click.option("--slug", required=True, help="URL slug (unique)")
@click.option("--start", required=True, help="Start datetime (ISO 8601)")
@click.option("--end", default=None, help="End datetime (ISO 8601)")
@click.option("--description", default="", help="Event description")
@click.option("--dress-code", default="", help="Dress code")
@click.option("--content-warnings", default=None, multiple=True, help="Warnings")
@click.option("--age-restriction", default=None, type=int, help="Minimum age")
@click.option("--capacity", default=None, type=int, help="Event capacity")
@click.option("--visibility", default="public", help="Visibility tier (public/private)")
@click.option("--language", default="", help="Language code")
@click.option("--is-free", is_flag=True, default=False, help="Event is free")
@click.option("--price-min-cents", default=None, type=int, help="Min price in cents")
@click.option("--price-max-cents", default=None, type=int, help="Max price in cents")
@click.option("--currency", default="EUR", help="Currency code (default: EUR)")
@click.option("--sliding-scale", is_flag=True, default=False, help="Sliding scale")
@click.option("--price-description", default="", help="Price description")
@click.option("--external-url", default="", help="External event URL")
@click.option("--tickets-url", default="", help="Tickets URL")
@click.option("--registration-required", is_flag=True, default=False, help="Registration required")  # noqa: E501
@click.option("--registration-url", default="", help="Registration URL")
@click.option("--registration-email", default="", help="Registration email")
def create_event(**kwargs):
    """
    Create a new canonical Event via the Switch API.
    Outputs the created Event as JSON to stdout.
    """
    # Map click's kebab-case back to API snake_case field names
    content_warnings = list(kwargs.pop("content_warnings") or [])
    payload = {
        "title": kwargs["title"],
        "slug": kwargs["slug"],
        "start": kwargs["start"],
        "description": kwargs["description"],
        "dress_code": kwargs["dress_code"],
        "content_warnings": content_warnings,
        "visibility": kwargs["visibility"],
        "language": kwargs["language"],
        "is_free": kwargs["is_free"],
        "currency": kwargs["currency"],
        "sliding_scale": kwargs["sliding_scale"],
        "price_description": kwargs["price_description"],
        "external_url": kwargs["external_url"],
        "tickets_url": kwargs["tickets_url"],
        "registration_required": kwargs["registration_required"],
        "registration_url": kwargs["registration_url"],
        "registration_email": kwargs["registration_email"],
    }
    if kwargs.get("end"):
        payload["end"] = kwargs["end"]
    if kwargs.get("age_restriction") is not None:
        payload["age_restriction"] = kwargs["age_restriction"]
    if kwargs.get("capacity") is not None:
        payload["capacity"] = kwargs["capacity"]
    if kwargs.get("price_min_cents") is not None:
        payload["price_min_cents"] = kwargs["price_min_cents"]
    if kwargs.get("price_max_cents") is not None:
        payload["price_max_cents"] = kwargs["price_max_cents"]

    try:
        client = SwitchClient()
        result = client.create_event(**payload)
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# create-post
# ---------------------------------------------------------------------------


@cli.command("create-post")
@click.option("--event-id", required=True, type=int, help="Event ID to attach post to")
@click.option("--headline", required=True, help="Post headline / hook")
@click.option("--body", required=True, help="Post body text")
@click.option("--cta", default="", help="Call-to-action text or URL")
@click.option("--voice", default="", help="Voice/tone (e.g. playful, formal)")
@click.option(
    "--imagery",
    multiple=True,
    default=None,
    help="Image URL (repeatable — pass once per image URL)",
)
def create_post(event_id: int, headline: str, body: str, cta: str, voice: str, imagery: tuple):
    """
    Create a Post attached to an Event via the Switch API.
    Outputs the created Post as JSON to stdout.
    """
    imagery_list = list(imagery) if imagery else None
    try:
        client = SwitchClient()
        result = client.create_post(
            event_id=event_id,
            headline=headline,
            body=body,
            cta=cta,
            voice=voice,
            imagery=imagery_list,
        )
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# approve-projection  (draft→ready lifecycle transition)
# ---------------------------------------------------------------------------


@cli.command("approve-projection")
@click.option("--projection-id", required=True, type=int, help="Projection ID")
def approve_projection(projection_id: int):
    """
    Approve a projection (draft→ready transition).
    Maps to POST /api/projections/{id}/approve/.
    Outputs the updated projection as JSON to stdout.
    """
    try:
        client = SwitchClient()
        result = client.approve_projection(projection_id=projection_id)
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# publish-projection  (ready→published lifecycle transition)
# ---------------------------------------------------------------------------


@cli.command("publish-projection")
@click.option("--projection-id", required=True, type=int, help="Projection ID")
def publish_projection(projection_id: int):
    """
    Publish a ready projection (ready→published transition).
    Maps to POST /api/projections/{id}/publish/.
    Outputs the updated projection as JSON to stdout.
    """
    try:
        client = SwitchClient()
        result = client.publish_projection(projection_id=projection_id)
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# mark-published  (record external publication)
# ---------------------------------------------------------------------------


@cli.command("mark-published")
@click.option("--projection-id", required=True, type=int, help="Projection ID")
def mark_published(projection_id: int):
    """
    Mark a projection as externally published.
    Maps to POST /api/projections/{id}/mark-published/.
    Outputs the updated projection as JSON to stdout.
    """
    try:
        client = SwitchClient()
        result = client.mark_published(projection_id=projection_id)
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# list-projections
# ---------------------------------------------------------------------------


@cli.command("list-projections")
def list_projections():
    """
    List projections for the authenticated user.
    Outputs projections as JSON to stdout (stubbed at v0 — returns stub body).
    """
    try:
        client = SwitchClient()
        result = client.list_projections()
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")
    _output(result)


# ---------------------------------------------------------------------------
# telegram group
# ---------------------------------------------------------------------------


@cli.group("telegram")
def telegram():
    """Telegram integration commands."""


@telegram.command("connect")
def telegram_connect():
    """
    Authenticate to Telegram via QR login and persist the session locally.

    Reads api_id/api_hash from the [telegram] section of the switch-cli config.
    Persists the returned StringSession to the config dir (~/.config/switch-cli/).
    A second invocation reuses the stored session without re-login.

    The session string is NEVER sent to any server (ADR-018 D4).
    Fails loudly on QR timeout, missing creds, or corrupt session (ADR-008 D3).
    """
    try:
        cfg = load_config()
    except (FileNotFoundError, ConfigError) as exc:
        _error(str(exc))

    tg_cfg = cfg.get("telegram")
    if not tg_cfg or "api_id" not in tg_cfg or "api_hash" not in tg_cfg:
        _error(
            "Telegram api_id and api_hash are not configured. "
            "Add a [telegram] section to your switch-cli config with api_id and api_hash. "
            "Obtain these from https://my.telegram.org/apps ."
        )

    config_dir = _get_config_dir()
    try:
        result = run_connect(
            api_id=int(tg_cfg["api_id"]),
            api_hash=str(tg_cfg["api_hash"]),
            config_dir=config_dir,
        )
    except TelegramConfigError as exc:
        _error(str(exc))
    except SessionCorruptError as exc:
        _error(str(exc))
    except QRLoginTimeoutError as exc:
        _error(str(exc))
    _output(result)


@telegram.command("sync")
def telegram_sync():
    """
    Enumerate Telegram dialogs, apply the can-post filter, and push the
    metadata-only inventory to the Switch ingest verb.

    Reads api_id/api_hash from the [telegram] section of the switch-cli config.
    Requires an existing session (run `switch-cli telegram connect` first).

    Can-post filter:
    - broadcast-only subscriptions → excluded
    - own/admin channel, group, supergroup → included
    - forum group → expanded into one row per topic (the group itself is excluded)

    Payload is METADATA-ONLY — no session_string, access_hash, or content
    (ADR-018 D4). Fails loudly if no session exists (ADR-008 D3).
    """
    import asyncio

    try:
        cfg = load_config()
    except (FileNotFoundError, ConfigError) as exc:
        _error(str(exc))

    tg_cfg = cfg.get("telegram")
    if not tg_cfg or "api_id" not in tg_cfg or "api_hash" not in tg_cfg:
        _error(
            "Telegram api_id and api_hash are not configured. "
            "Add a [telegram] section to your switch-cli config with api_id and api_hash. "
            "Obtain these from https://my.telegram.org/apps ."
        )

    config_dir = _get_config_dir()
    try:
        inventory = asyncio.run(
            run_sync(
                api_id=int(tg_cfg["api_id"]),
                api_hash=str(tg_cfg["api_hash"]),
                config_dir=config_dir,
            )
        )
    except NoSessionError as exc:
        _error(str(exc))
    except SessionCorruptError as exc:
        _error(str(exc))
    except TelegramConfigError as exc:
        _error(str(exc))

    try:
        client = SwitchClient()
        result = client.push_telegram_inventory(inventory)
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))
    except APIError as exc:
        _error(f"API error {exc.status_code}: {exc.detail}")

    _output({"synced": True, "upserted": result.get("upserted", 0), "flagged": result.get("flagged", 0)})


@telegram.command("distribute")
@click.option("--message", required=True, help="Draft body text to place in destination(s)")
@click.option(
    "--dest",
    "dests",
    required=True,
    multiple=True,
    help=(
        "Destination: <chat_id> for a group/channel, "
        "<chat_id>:<topic_id> for a forum topic. Repeatable."
    ),
)
def telegram_distribute(message: str, dests: tuple):
    """
    Place a draft in one or more Telegram destinations.

    For each --dest: checks for a pre-existing draft first (getDraft). If the
    draft is empty, places the message as a draft (saveDraft). If a draft
    already exists, it is skipped with status=skipped-pre-existing-draft
    (no clobber — ADR-008 D3).

    Forum-topic destinations use the <chat_id>:<topic_id> format. The draft is
    placed into the topic via reply_to=top_msg_id.

    FIRM (ADR-018 D2): this command NEVER sends a message. All placement is
    via the Telegram draft mechanism only.

    Requires an existing session (run `switch-cli telegram connect` first).
    Fails loudly if a --dest is not in the synced inventory (ADR-008 D3).
    """
    import asyncio

    try:
        cfg = load_config()
    except (FileNotFoundError, ConfigError) as exc:
        _error(str(exc))

    tg_cfg = cfg.get("telegram")
    if not tg_cfg or "api_id" not in tg_cfg or "api_hash" not in tg_cfg:
        _error(
            "Telegram api_id and api_hash are not configured. "
            "Add a [telegram] section to your switch-cli config with api_id and api_hash. "
            "Obtain these from https://my.telegram.org/apps ."
        )

    config_dir = _get_config_dir()

    # Build a SwitchClient for placement reporting (kb-56c2.3 — C3a co-equal seam).
    # Fail loud on auth/config error before starting the Telegram session.
    try:
        switch_client = SwitchClient()
    except (AuthError, FileNotFoundError, ConfigError) as exc:
        _error(str(exc))

    try:
        results = asyncio.run(
            run_distribute(
                api_id=int(tg_cfg["api_id"]),
                api_hash=str(tg_cfg["api_hash"]),
                config_dir=config_dir,
                message=message,
                dests=list(dests),
                switch_client=switch_client,
            )
        )
    except NoSessionError as exc:
        _error(str(exc))
    except SessionCorruptError as exc:
        _error(str(exc))
    except UnknownDestinationError as exc:
        _error(str(exc))

    _output({"distributed": True, "results": results})
