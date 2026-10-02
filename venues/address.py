"""Street-address detection for free-text locations (sb-x5xh.2 ruling (b)).

A location note never carries a street address: an address belongs on a Venue,
where privacy_mode applies. German street shapes cover the Berlin sources; a
postcode ("10997 Berlin") counts as an address too.
"""

import re

from django.core.exceptions import ValidationError

_SUFFIX = r"(?i:straße|strasse|str\.|allee|platz|weg|damm|ufer|ring|markt|gasse|chaussee|promenade|steig|zeile|graben)"
_NAME = r"[A-ZÄÖÜ][\wäöüß-]*"
STREET_ADDRESS = re.compile(
    rf"(?:\b{_NAME}{_SUFFIX}"  # Kastanienallee 5, Oranienstr. 12, Holzmarkt 25
    rf"|\b{_NAME}\s+{_SUFFIX}"  # Revaler Strasse 99
    rf"|\b(?:Am|An der|An den|Im|In der|Auf dem|Alt|Unter den)\s+{_NAME})"  # Am Flutgraben 3
    r"\s+\d{1,4}(?:\s?[a-zA-Z])?\b"
    r"|\b\d{5}\s+[A-ZÄÖÜ]\w+"  # 10997 Berlin
)


def contains_street_address(text: str) -> bool:
    return bool(STREET_ADDRESS.search(text or ""))


def validate_no_street_address(value: str) -> None:
    if contains_street_address(value):
        raise ValidationError("A location note must not contain a street address; put it on a venue.")


_TRAILING_POSTCODE = re.compile(r"\s*,?\s*\d{5}(?:\s+[A-ZÄÖÜ][\wäöüß-]*)?")


def split_street_address(text: str) -> tuple[str, str]:
    """(address, rest): the first street address in `text`, with a trailing postcode, and the text without it."""
    match = STREET_ADDRESS.search(text or "")
    if match is None:
        return "", text or ""
    end = match.end()
    postcode = _TRAILING_POSTCODE.match(text, end)
    if postcode:
        end = postcode.end()
    rest = text[: match.start()] + " " + text[end:]
    rest = re.sub(r"\s+([,)])", r"\1", re.sub(r"\(\s+", "(", re.sub(r"\s+", " ", rest)))
    rest = re.sub(r",\s*\(", " (", re.sub(r",+", ",", rest))
    rest = re.sub(r"\(\s*\)", "", re.sub(r",\s*\)", ")", re.sub(r"\(\s*,\s*", "(", rest)))
    return text[match.start() : end].strip(" ,"), rest.strip(" ,")
