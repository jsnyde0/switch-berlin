"""sb-7wzb.25: seed_collector_sources creates the profiles and venues a source config names, on purpose.

Collection never creates config-named entities (a typo must not make a public profile),
so a fresh database needs them seeded; the command is idempotent and merge-aware.
"""

import textwrap
from io import StringIO

import pytest
from django.core.management import call_command

from organizers.merge import merge_profiles, merge_venues
from organizers.models import Profile
from venues.models import Venue

CONFIG = """
[[source]]
name = "Soma page"
shape = "website"
default_organizer = "Soma House"
venue = "Soma Space"
venue_run_by = "Soma House"

[[source]]
name = "Board"
shape = "telegram_telethon"
default_organizer = "poster"

[[source]]
name = "Held"
shape = "telegram_telethon"
"""


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text(textwrap.dedent(CONFIG))
    return str(path)


def _seed(config):
    out = StringIO()
    call_command("seed_collector_sources", config=config, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_creates_missing_profiles_venues_and_run_by_links(config):
    output = _seed(config)
    profile = Profile.objects.get(name="Soma House")
    assert (profile.status, profile.kind) == ("approved", "collective")
    venue = Venue.objects.get(name="Soma Space")
    assert venue.run_by == profile
    assert Profile.objects.count() == 1  # "poster" and an unset organizer create nothing
    assert "Soma House" in output and "Soma Space" in output


@pytest.mark.django_db
def test_second_run_creates_nothing(config):
    _seed(config)
    counts = (Profile.objects.count(), Venue.objects.count())
    output = _seed(config)
    assert (Profile.objects.count(), Venue.objects.count()) == counts
    assert "created" not in output.lower().replace("created nothing", "")


@pytest.mark.django_db
def test_a_merged_away_config_name_resolves_to_the_winner(config):
    winner = Profile.objects.create(name="Soma Haus", slug="soma-haus")
    loser = Profile.objects.create(name="Soma House", slug="soma-house")
    merge_profiles(winner, loser, None)
    v_winner = Venue.objects.create(name="Space A", slug="space-a")
    v_loser = Venue.objects.create(name="Soma Space", slug="soma-space")
    merge_venues(v_winner, v_loser, None)
    _seed(config)
    assert list(Profile.objects.values_list("name", flat=True)) == ["Soma Haus"]
    assert list(Venue.objects.values_list("name", flat=True)) == ["Space A"]
    v_winner.refresh_from_db()
    assert v_winner.run_by == winner


@pytest.mark.django_db
def test_an_existing_run_by_is_never_overwritten(config):
    other = Profile.objects.create(name="Other", slug="other")
    Venue.objects.create(name="Soma Space", slug="soma-space", run_by=other)
    _seed(config)
    assert Venue.objects.get(name="Soma Space").run_by == other


@pytest.mark.django_db
def test_the_shipped_config_seeds_without_error():
    _seed(None)
    assert Profile.objects.filter(name="IKSK Berlin").exists()
