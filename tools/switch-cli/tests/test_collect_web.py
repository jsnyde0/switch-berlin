"""
IKSK website collector (sb-7wzb.15): each grid cell's same-host detail page is
fetched once and its visible prose carried as the row's link content; a cell linking off-site
names IKSK as the venue and the linked site as the host.
"""

from datetime import date

import httpx
from switch_cli.collect import iksk_rows

SOURCE = {
    "name": "IKSK program page",
    "shape": "website",
    "parser": "iksk",
    "url": "https://iksk-berlin.de/Program",
    "default_organizer": "IKSK Berlin",
    "publish": True,
}

GRID = """
<html><body><table>
<tr><td>Oktober 6</td><td>Oktober 7</td></tr>
<tr>
  <td><a href="/bondage-jam">19 00 - 23 00 Bondage Jam</a></td>
  <td><a href="https://www.ashrafalali.com/cali-session">18 00 - 20 00 Cali Sessions w/ Ashraf</a></td>
</tr>
<tr>
  <td><a href="/bondage-jam">10 00 - 12 00 Bondage Jam Morning</a></td>
  <td><a href="/gone">20 00 - 22 00 Gone Workshop</a></td>
</tr>
</table></body></html>
"""

PROSE = (
    "Bondage Jam every Tuesday. Open practice, everybody welcome. "
    "Bring your own rope or borrow ours; a teacher walks the room. " * 10
)

DETAIL = f"""
<html><head><script>var tracking = 1;</script><style>.x{{}}</style></head><body>
<nav>PROGRAM PEOPLE POLITICS</nav>
<div role="main"><h1>Bondage Jam</h1><p>{PROSE}</p></div>
<footer>IMPRESSUM Newsletter Join us on Telegram</footer>
</body></html>
"""


def _client(calls):
    def handler(request):
        calls.append(str(request.url))
        if request.url.host == "iksk-berlin.de":
            return httpx.Response(301, headers={"Location": f"https://www.iksk-berlin.de{request.url.path}"})
        if request.url.path == "/bondage-jam":
            return httpx.Response(200, text=DETAIL)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _rows():
    calls = []
    rows, errors = iksk_rows(SOURCE, GRID, date(2026, 10, 1), date(2026, 10, 31), _client(calls))
    return {r["message_id"].split("|")[1]: r for r in rows}, errors, calls


def test_row_link_content_carries_the_detail_page_prose():
    rows, _, _ = _rows()
    row = rows["19 00 - 23 00 Bondage Jam"]
    content = row["enriched_payload"]["url_content"]
    assert PROSE.strip()[:200] in content
    assert len(content) >= 500
    assert "tracking" not in content and "IMPRESSUM" not in content and "PROGRAM PEOPLE" not in content
    assert PROSE.strip()[:200] not in row["text"]


def test_each_distinct_detail_page_is_fetched_once_and_off_site_never():
    _, _, calls = _rows()
    fetched = [c for c in calls if c.endswith("/bondage-jam")]
    assert fetched == ["https://iksk-berlin.de/bondage-jam", "https://www.iksk-berlin.de/bondage-jam"]
    assert not any("ashrafalali" in c for c in calls)


def test_off_site_cell_names_iksk_as_venue_and_the_linked_site_as_host():
    rows, _, _ = _rows()
    row = rows["18 00 - 20 00 Cali Sessions w/ Ashraf"]
    assert "Host: ashrafalali.com" in row["text"]
    assert "Venue: IKSK Berlin, Holzmarkt 25, Berlin" in row["text"]
    assert "default_organizer" not in row["raw_payload"]


def test_same_host_cell_keeps_iksk_as_declared_organizer():
    rows, _, _ = _rows()
    assert rows["19 00 - 23 00 Bondage Jam"]["raw_payload"]["default_organizer"] == "IKSK Berlin"
    # The row names the venue only; organizer wording in the text would read as an explicit organizer (ADR-007 D9).
    assert "Venue: IKSK Berlin, Holzmarkt 25, Berlin" in rows["19 00 - 23 00 Bondage Jam"]["text"]
    assert "organizer" not in rows["19 00 - 23 00 Bondage Jam"]["text"].lower()


def test_a_failed_detail_fetch_is_reported_and_the_row_still_lands():
    rows, errors, _ = _rows()
    assert "Gone Workshop" in rows["20 00 - 22 00 Gone Workshop"]["text"]
    assert "enriched_payload" not in rows["20 00 - 22 00 Gone Workshop"]
    assert errors == ["https://iksk-berlin.de/gone: HTTPStatusError 404"]


def test_source_default_venue_and_its_runner_ride_the_row():
    from switch_cli.collect import collected_row

    source = {**SOURCE, "venue": "IKSK Berlin (Holzmarkt 25, Haus 2)", "venue_run_by": "IKSK Berlin"}
    payload = collected_row(source, "iksk-berlin.de", "m1", "text")["raw_payload"]
    assert payload["venue"] == "IKSK Berlin (Holzmarkt 25, Haus 2)"
    assert payload["venue_run_by"] == "IKSK Berlin"
    assert "venue" not in collected_row(SOURCE, "iksk-berlin.de", "m1", "text")["raw_payload"]


def test_shipped_iksk_sources_name_the_iksk_venue_run_by_iksk():
    from switch_cli.collect import load_sources

    iksk = {s["name"]: s for s in load_sources() if s["name"] in ("IKSK program page", "@IKSKBerlin")}
    assert len(iksk) == 2
    for source in iksk.values():
        assert source["venue"] == "IKSK Berlin (Holzmarkt 25, Haus 2)"
        assert source["venue_run_by"] == "IKSK Berlin"


def test_default_organizer_rides_the_row_and_no_shipped_source_uses_the_retired_keys():
    from switch_cli.collect import collected_row, load_sources

    payload = collected_row({**SOURCE, "default_organizer": "poster"}, "x", "m1", "text")["raw_payload"]
    assert payload["default_organizer"] == "poster"
    sources = load_sources()
    assert [s["name"] for s in sources if {"organizer", "aggregator"} & s.keys()] == []
    assert [s["name"] for s in sources if "channel_organizer" in s] == []  # config names organizers, never titles
    assert [s["name"] for s in sources if s.get("default_organizer") == "poster"] == [
        "Conscious Events Berlin / Love",
        "Sober Events in Berlin / Sex-positive offerings",
    ]


def test_row_names_its_listing_day_and_title_for_the_pre_ai_dedup():
    rows, _, _ = _rows()
    assert rows["19 00 - 23 00 Bondage Jam"]["raw_payload"]["listing"] == {
        "date": "2026-10-06",
        "title": "19 00 - 23 00 Bondage Jam",
    }
