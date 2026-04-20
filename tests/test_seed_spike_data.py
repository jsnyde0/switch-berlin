"""Smoke tests for the seed_spike_data management command."""

import pytest
from django.core.management import call_command

from events.models import Event
from organizers.models import Organizer
from venues.models import Venue


@pytest.mark.django_db
def test_seed_creates_500_plus_events():
    """seed_spike_data creates at least 500 events."""
    call_command("seed_spike_data", force=True)
    assert Event.objects.count() >= 500


@pytest.mark.django_db
def test_seed_creates_8_plus_organizers():
    """seed_spike_data creates at least 8 organizers."""
    call_command("seed_spike_data", force=True)
    assert Organizer.objects.filter(name__startswith="SpikeSeed-").count() >= 8


@pytest.mark.django_db
def test_seed_venues_have_both_privacy_modes():
    """seed_spike_data creates venues with both public and private privacy modes."""
    call_command("seed_spike_data", force=True)
    privacy_modes = set(
        Venue.objects.filter(name__startswith="SpikeSeed-").values_list(
            "privacy_mode", flat=True
        )
    )
    assert "public" in privacy_modes
    assert len(privacy_modes) >= 2  # at least public + one non-public


@pytest.mark.django_db
def test_seed_wipe_clears_and_reseeds():
    """--wipe flag clears seed data and reseeds cleanly."""
    call_command("seed_spike_data", force=True)
    first_event_pks = set(
        Event.objects.filter(
            organizer__name__startswith="SpikeSeed-"
        ).values_list("pk", flat=True)
    )

    call_command("seed_spike_data", wipe=True, force=True)
    second_event_pks = set(
        Event.objects.filter(
            organizer__name__startswith="SpikeSeed-"
        ).values_list("pk", flat=True)
    )

    # After wipe+reseed, old PKs should be gone (new rows created)
    assert not first_event_pks.intersection(second_event_pks)
    assert Event.objects.filter(
        organizer__name__startswith="SpikeSeed-"
    ).count() >= 500


@pytest.mark.django_db
def test_seed_refuses_to_run_twice_without_wipe():
    """Running seed twice without --wipe raises CommandError."""
    from django.core.management.base import CommandError

    call_command("seed_spike_data", force=True)
    with pytest.raises(CommandError, match="already present"):
        call_command("seed_spike_data", force=True)
