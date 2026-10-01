"""
Track A event collector, website half (sb-7wzb.2).

Collectors turn a source into rows for the Switch RawMessage seam
(POST /api/ingest/raw-messages). One row = one event candidate; the server
extracts, dedupes, and lands it by claim state at the source's tier.

Two website parsers, one per site: plain functions, no source framework
(sb-7wzb.2 D3 — extract shared code at the third feed).
"""

import html
import re
import tomllib
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_SOURCES = Path(__file__).resolve().parents[2] / "collector_sources.toml"
# Karada's WAF answers 403 to httpx's default Accept-Encoding (br/zstd); gzip passes.
_UA = {"User-Agent": "switch-berlin-collector/0.1 (+https://switch.berlin)", "Accept-Encoding": "gzip"}

_MONTHS = {
    m: i + 1
    for i, names in enumerate(
        [
            ("january", "januar"),
            ("february", "februar"),
            ("march", "märz", "maerz"),
            ("april",),
            ("may", "mai"),
            ("june", "juni"),
            ("july", "juli"),
            ("august",),
            ("september",),
            ("october", "oktober"),
            ("november",),
            ("december", "dezember"),
        ]
    )
    for m in names
}


_WEEKDAYS = {"montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"}


def load_sources(path: Path = DEFAULT_SOURCES) -> list[dict]:
    with open(path, "rb") as f:
        return tomllib.load(f)["source"]


def collected_row(source: dict, channel_id: str, message_id: str, text: str, **payload) -> dict:
    """A collected row in the shape the ingest verb accepts."""
    raw_payload = {"source": source["name"], **payload}
    if source.get("organizer"):
        raw_payload["organizer"] = source["organizer"]
    return {
        "source_type": source["shape"],
        "channel_id": channel_id[:100],
        "message_id": message_id[:100],
        "text": text,
        "raw_payload": raw_payload,
        "collect_only": not source["publish"],
    }


def _parse_day(label: str, today: date) -> date | None:
    """'Oktober 1' / 'September 28' → the nearest such date on or after today-60d."""
    m = re.match(r"\s*([A-Za-zäÄ]+)\s+(\d{1,2})\s*$", label)
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    candidate = date(today.year, month, day)
    return candidate if candidate >= today - timedelta(days=60) else date(today.year + 1, month, day)


_IKSK_HOSTS = {"iksk-berlin.de", "www.iksk-berlin.de"}


def _iksk_detail(client: httpx.Client, href: str) -> str:
    """Visible prose of an IKSK detail page: its role=main region, scripts dropped."""
    resp = client.get(href)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    main = soup.select_one("[role=main]")
    if main is None:
        raise ValueError("no role=main region")
    for tag in main(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(main.get_text(" ").split())[:3000]


def iksk_rows(
    source: dict, html_text: str, start: date, end: date, client: httpx.Client
) -> tuple[list[dict], list[str]]:
    """IKSK /Program is a grid: per week a table whose first row carries the dates
    and whose later rows carry one entry per day column.

    A cell linking to an IKSK page gets that page's prose inlined (fetched once
    per href); URL enrichment cannot read it, the site 301s to www. A cell linking
    off-site is a third-party host using IKSK as the venue: not fetched, and the
    source's declared organizer is dropped so the host comes from the text.
    Returns the rows and one line per failed detail fetch."""
    soup = BeautifulSoup(html_text, "html.parser")
    rows, errors, details = [], [], {}
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        days = [_parse_day(td.get_text(" ", strip=True), start) for td in trs[0].find_all(["td", "th"])]
        if not any(days):
            continue
        for tr in trs[1:]:
            for col, td in enumerate(tr.find_all(["td", "th"])):
                entry = " ".join(td.get_text(" ", strip=True).split())
                day = days[col] if col < len(days) else None
                if not entry or day is None or not (start <= day <= end) or entry.lower() in _WEEKDAYS:
                    continue
                link = td.find("a")
                href = urljoin(source["url"], link["href"]) if link and link.get("href") else ""
                host = urlparse(href).netloc.lower()
                off_site = bool(href) and host not in _IKSK_HOSTS
                if href and not off_site and href not in details:
                    try:
                        details[href] = _iksk_detail(client, href)
                    except (httpx.HTTPError, ValueError) as exc:
                        details[href] = ""
                        why = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else exc
                        errors.append(f"{href}: {type(exc).__name__} {why}")
                header = (
                    f"Event listed on the IKSK Berlin program ({source['url']}).\n"
                    f"Date: {day.isoformat()} ({day.strftime('%A')})\n"
                    f"Entry (time range as 'HH MM - HH MM', then title): {entry}\n"
                )
                if off_site:
                    header += (
                        f"Host: {host.removeprefix('www.')} (the program links this event to the host's own site)\n"
                        f"Venue: IKSK Berlin, Holzmarkt 25, Berlin\n"
                    )
                else:
                    header += "Organizer/host venue: IKSK Berlin, Holzmarkt 25, Berlin\n"
                text = header + (f"Details: {href}\n" if href else "")
                if details.get(href):
                    text += f"\n{details[href]}"
                row = collected_row(source, "iksk-berlin.de", f"{day.isoformat()}|{entry[:60]}", text, url=href)
                if off_site:
                    row["raw_payload"].pop("organizer", None)
                rows.append(row)
    return rows, errors


def _strip_html(s: str) -> str:
    return " ".join(BeautifulSoup(html.unescape(s or ""), "html.parser").get_text(" ").split())


def karada_rows(source: dict, start: date, end: date) -> list[dict]:
    """Karada House runs The Events Calendar; its /event/ page is fed by the
    site's own events API, read here for the window."""
    resp = httpx.get(
        "https://karada-house.de/wp-json/tribe/events/v1/events",
        params={"start_date": start.isoformat(), "end_date": end.isoformat(), "per_page": 50},
        headers=_UA,
        timeout=30,
    )
    resp.raise_for_status()
    rows = []
    for ev in resp.json().get("events", []):
        venue = ev.get("venue") or {}
        venue_name = venue.get("venue", "") if isinstance(venue, dict) else ""
        facilitators = ", ".join(_strip_html(o.get("organizer", "")) for o in ev.get("organizer", []))
        text = (
            f"Event listed on the Karada House events page ({source['url']}).\n"
            f"Title: {_strip_html(ev['title'])}\n"
            f"Start: {ev['start_date']} (Europe/Berlin)\nEnd: {ev['end_date']}\n"
            f"Organizer/host venue: Karada House{f' ({venue_name})' if venue_name else ''}\n"
            f"Facilitators: {facilitators}\n"
            f"Price: {_strip_html(ev.get('cost', ''))}\n"
            f"Link: {ev['url']}\n\n"
            f"{_strip_html(ev.get('description', ''))[:3000]}"
        )
        rows.append(collected_row(source, "karada-house.de", str(ev["id"]), text, url=ev["url"]))
    return rows


def collect_web(sources: list[dict], days: int, today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Rows from every website source for [today, today+days]; plus a per-source report."""
    start = today or date.today()
    end = start + timedelta(days=days)
    rows, report = [], []
    for source in (s for s in sources if s["shape"] == "website"):
        detail_errors = []
        try:
            if source["parser"] == "iksk":
                with httpx.Client(headers=_UA, timeout=30, follow_redirects=True) as client:
                    resp = client.get(source["url"])
                    resp.raise_for_status()
                    got, detail_errors = iksk_rows(source, resp.text, start, end, client)
            elif source["parser"] == "karada":
                got = karada_rows(source, start, end)
            else:
                raise ValueError(f"unknown parser {source['parser']!r}")
        except Exception as exc:  # per-source failure is reported, the run continues
            report.append({"source": source["name"], "rows": 0, "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.extend(got)
        report.append({"source": source["name"], "rows": len(got)})
        if detail_errors:
            report[-1]["detail_errors"] = detail_errors
    return rows, report
