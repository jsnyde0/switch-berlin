"""
switch-cli: command-line interface for the Switch syndication HTTP API.

Agent-shaped tool (ADR-011 D1 agent-extended scope): external personal agents
and power-users drive Switch by shelling out to this CLI. All output is
machine-parseable JSON to stdout.

Auth chain (ADR-016 D3):
1. configure  — store base_url + Bearer API key to config file
2. All other commands — exchange stored Bearer key for identity token, then call API

Verbs:
- configure           Store API base URL + Bearer key (never prints the key back)
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

from switch_cli.client import APIError, AuthError, SwitchClient
from switch_cli.config import ConfigError, save_config


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
@click.option("--api-key", required=True, help="Bearer API key from agents/register")
def configure(base_url: str, api_key: str):
    """
    Store API base URL + Bearer key in the config file.

    The key is stored but never printed back. Run agents/register via the
    web UI or `curl` to obtain the key, then configure here once.
    """
    save_config(base_url=base_url, api_key=api_key)
    _output({"configured": True, "base_url": base_url})


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
