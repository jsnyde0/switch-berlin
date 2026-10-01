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
    "organizer": "IKSK Berlin",
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
    assert "Organizer/host venue: IKSK Berlin" not in row["text"]
    assert "organizer" not in row["raw_payload"]


def test_same_host_cell_keeps_iksk_as_declared_organizer():
    rows, _, _ = _rows()
    assert rows["19 00 - 23 00 Bondage Jam"]["raw_payload"]["organizer"] == "IKSK Berlin"


def test_a_failed_detail_fetch_is_reported_and_the_row_still_lands():
    rows, errors, _ = _rows()
    assert "Gone Workshop" in rows["20 00 - 22 00 Gone Workshop"]["text"]
    assert "enriched_payload" not in rows["20 00 - 22 00 Gone Workshop"]
    assert errors == ["https://iksk-berlin.de/gone: HTTPStatusError 404"]
