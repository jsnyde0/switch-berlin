"""sb-7wzb.20: staff report of "maybe the same" Profile and Venue names.

Fixture names come from the read-only spike on the dev DB (sb-x5xh.2 notes,
'## Spike result'). The report only shows pairs; staff merge in the admin.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from organizers.duplicate_names import candidate_pairs, jaro_winkler, normalize
from organizers.models import Profile
from venues.models import Venue


def _run():
    out = StringIO()
    call_command("duplicate_names", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_profile_name_variant_is_listed_as_a_pair():
    Profile.objects.create(name="Visionary Body", slug="visionary-body")
    Profile.objects.create(name="Visionary Body (Mareen Scholl)", slug="visionary-body-mareen")
    Profile.objects.create(name="Wild Woman Reborn", slug="wild-woman-reborn")

    out = _run()

    pair_lines = [line for line in out.splitlines() if "Visionary Body (Mareen Scholl)" in line]
    assert len(pair_lines) == 1
    assert "'Visionary Body'" in pair_lines[0]
    assert "review" in pair_lines[0]
    assert "Wild Woman Reborn" not in out


@pytest.mark.django_db
def test_venue_false_positive_is_shown_not_merged():
    Venue.objects.create(name="Haus Lebenskraft Potsdam", slug="haus-lebenskraft-potsdam")
    Venue.objects.create(name="Haus Lebenskunst", slug="haus-lebenskunst")

    out = _run()

    pair_lines = [line for line in out.splitlines() if "Haus Lebenskraft Potsdam" in line]
    assert len(pair_lines) == 1
    assert "Haus Lebenskunst" in pair_lines[0]
    # Shown, not merged: both rows survive the run.
    assert Venue.objects.filter(name__in=["Haus Lebenskraft Potsdam", "Haus Lebenskunst"]).count() == 2


@pytest.mark.django_db
def test_command_writes_nothing():
    Profile.objects.create(name="Soma House", slug="soma-house")
    Profile.objects.create(name="SOMA House", slug="soma-house-2")
    Venue.objects.create(name="Soma House", slug="soma-house-v")
    Venue.objects.create(name="Soma House Kreuzberg", slug="soma-house-kreuzberg")

    with CaptureQueriesContext(connection) as ctx:
        out = _run()

    assert "exact" in out
    assert ctx.captured_queries, "the report should read the DB"
    for q in ctx.captured_queries:
        assert q["sql"].lstrip().upper().startswith("SELECT"), q["sql"]


def test_normalize_matches_geo_analysis_rules():
    assert normalize("  SOMA House ") == "soma house"
    assert normalize("Luhmen d'Arc") == "luhmen darc"
    assert normalize("Till & Shirka - sexpositive  Workshops") == "till shirka sexpositive workshops"
    assert normalize("Healix/House") == "healix house"


def test_jaro_winkler_reference_values():
    assert jaro_winkler("martha", "marhta") == pytest.approx(0.961, abs=1e-3)
    assert jaro_winkler("dwayne", "duane") == pytest.approx(0.84, abs=1e-3)
    assert jaro_winkler("abc", "abc") == 1.0
    assert jaro_winkler("", "abc") == 0.0


# Every review-band pair the spike printed (sb-x5xh.2 '## Spike result',
# scores from DuckDB's jaro_winkler_similarity on the normalized names).
# DuckDB scores UTF-8 bytes; we score characters, so names with a non-ASCII
# dash or symbol drift by up to ~0.01 and 'Secret Location' crosses into high.
SPIKE_REVIEW_BAND = [
    ("Secret Location — Berlin Mitte", "Secret location, Berlin-Mitte", 0.947),
    ("IKSK Berlin (Holzmarkt 25, Berlin)", "IKSK Berlin (Holzmarkt 25, Haus 2)", 0.929),
    ("Soma House", "Soma House Kreuzberg", 0.900),
    ("Haus Lebenskraft Potsdam", "Haus Lebenskunst", 0.877),
    ("Healix House", "Helix House, Moabit", 0.865),
    ("Soma House", "SOMA HOUSE, Mehringdamm 70, Berlin", 0.859),
    ("Visionary Body", "Visionary Body (Mareen Scholl)", 0.893),
    ("Luhmen d'Arc", "luhmen d'arc – D & elsewhere", 0.881),
    ("Gili Jala", "Gili Jala ❂ Play & Practice", 0.867),
]


@pytest.mark.parametrize(("a", "b", "spike_score"), SPIKE_REVIEW_BAND)
def test_spike_review_band_pairs_are_candidates(a, b, spike_score):
    pairs = candidate_pairs([(1, a), (2, b)])
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.band in ("review", "high")
    tolerance = 1e-3 if (a + b).isascii() else 0.015
    assert pair.score == pytest.approx(spike_score, abs=tolerance)


def test_unrelated_names_are_not_candidates():
    assert candidate_pairs([(1, "Tina"), (2, "Martina Lutz, Ricardo Roehmer & Mal Weeraratne")]) == []
