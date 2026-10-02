"""sb-7wzb.25: one merge-aware name resolver for Profiles and Venues (rule 5, end to end)."""

import pytest

from organizers.merge import merge_profiles, merge_venues
from organizers.models import MergeRecord, Profile
from organizers.names import find_profile, find_venue
from venues.models import Venue


@pytest.mark.django_db
def test_find_profile_matches_by_normalized_name():
    p = Profile.objects.create(name="Soma House", slug="soma-house")
    assert find_profile("  soma HOUSE ") == p
    assert find_profile("Soma Haus") is None  # never fuzzy


@pytest.mark.django_db
def test_find_profile_resolves_a_merged_away_name_to_the_winner():
    winner = Profile.objects.create(name="Soma House", slug="soma-house")
    loser = Profile.objects.create(name="SOMA House Berlin", slug="soma-house-berlin")
    merge_profiles(winner, loser, None)
    assert find_profile("SOMA House Berlin") == winner


@pytest.mark.django_db
def test_find_profile_follows_a_chain_of_merges():
    a = Profile.objects.create(name="Alpha", slug="alpha")
    b = Profile.objects.create(name="Beta", slug="beta")
    c = Profile.objects.create(name="Gamma", slug="gamma")
    merge_profiles(b, a, None)
    merge_profiles(c, b, None)
    assert find_profile("Alpha") == c


@pytest.mark.django_db
def test_a_live_profile_wins_over_an_older_merge_record():
    winner = Profile.objects.create(name="Soma House", slug="soma-house")
    loser = Profile.objects.create(name="Soma Berlin", slug="soma-berlin")
    merge_profiles(winner, loser, None)
    reborn = Profile.objects.create(name="Soma Berlin", slug="soma-berlin-2")
    assert find_profile("Soma Berlin") == reborn


@pytest.mark.django_db
def test_a_venue_merge_record_never_resolves_a_profile_name():
    winner = Venue.objects.create(name="Club A", slug="club-a")
    loser = Venue.objects.create(name="Club A Berlin", slug="club-a-berlin")
    merge_venues(winner, loser, None)
    assert find_profile("Club A Berlin") is None
    assert find_venue("Club A Berlin") == winner


@pytest.mark.django_db
def test_find_venue_by_name_and_by_address():
    v = Venue.objects.create(name="Club A", slug="club-a", address="Main St 1")
    assert find_venue("club a") == v
    assert find_venue("Club A", "main st 1") == v
    assert find_venue("Club A", "Other 2") is None


@pytest.mark.django_db
def test_merge_record_loser_normalized_is_indexed():
    assert MergeRecord._meta.get_field("loser_normalized").db_index is True


@pytest.mark.django_db
def test_a_merged_away_name_matches_under_the_same_key_as_a_live_name():
    winner = Profile.objects.create(name="Winner", slug="winner")
    loser = Profile.objects.create(name="Foo-Bar", slug="foo-bar")
    merge_profiles(winner, loser, None)
    assert find_profile("Foo Bar") == winner
    assert find_profile("foo, bar!") == winner  # punctuation the live-row key drops


@pytest.mark.django_db
def test_find_venue_follows_a_chain_of_merges_under_one_key():
    a = Venue.objects.create(name="Club-A", slug="club-a")
    b = Venue.objects.create(name="Club B", slug="club-b")
    c = Venue.objects.create(name="Club C", slug="club-c")
    merge_venues(b, a, None)
    merge_venues(c, b, None)
    assert find_venue("Club A") == c
    assert find_venue("club, b") == c
