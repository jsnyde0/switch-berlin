"""Smoke tests for the seed_spike_data management command."""

import pytest
from django.core.management import call_command

from events.models import Event, Tag
from organizers.models import Profile
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
    assert Profile.objects.filter(name__startswith="SpikeSeed-").count() >= 8


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
            event_organizer_set__profile__name__startswith="SpikeSeed-",
            event_organizer_set__is_primary=True,
        ).values_list("pk", flat=True)
    )

    call_command("seed_spike_data", wipe=True, force=True)
    second_event_pks = set(
        Event.objects.filter(
            event_organizer_set__profile__name__startswith="SpikeSeed-",
            event_organizer_set__is_primary=True,
        ).values_list("pk", flat=True)
    )

    # After wipe+reseed, old PKs should be gone (new rows created)
    assert not first_event_pks.intersection(second_event_pks)
    assert (
        Event.objects.filter(
            event_organizer_set__profile__name__startswith="SpikeSeed-",
            event_organizer_set__is_primary=True,
        ).count()
        >= 500
    )


@pytest.mark.django_db
def test_seed_refuses_to_run_twice_without_wipe():
    """Running seed twice without --wipe raises CommandError."""
    from django.core.management.base import CommandError

    call_command("seed_spike_data", force=True)
    with pytest.raises(CommandError, match="already present"):
        call_command("seed_spike_data", force=True)


@pytest.mark.django_db
def test_seed_creates_9_tags():
    """seed_spike_data creates exactly 9 tags (3 kinds: theme, format, identity)."""
    call_command("seed_spike_data", force=True)
    assert Tag.objects.count() == 9


@pytest.mark.django_db
def test_seed_tags_cover_three_kinds():
    """seed_spike_data creates tags across theme, format, and identity kinds."""
    call_command("seed_spike_data", force=True)
    kinds = set(Tag.objects.values_list("kind", flat=True))
    assert kinds == {"theme", "format", "identity"}


@pytest.mark.django_db
def test_seed_all_events_have_tags():
    """Every seeded event has at least one tag assigned."""
    call_command("seed_spike_data", force=True)
    events_without_tags = Event.objects.filter(tags__isnull=True).count()
    assert events_without_tags == 0


@pytest.mark.django_db
def test_seed_events_have_at_most_3_tags():
    """No seeded event has more than 3 tags (sample k max is 3)."""
    call_command("seed_spike_data", force=True)
    for event in Event.objects.all():
        assert event.tags.count() <= 3


@pytest.mark.django_db
def test_seed_events_have_pricing_fields_set():
    """All seeded events have pricing fields explicitly set (not default null)."""
    call_command("seed_spike_data", force=True)
    # Every event must have is_free or sliding_scale or non-null prices
    events = Event.objects.all()
    for event in events:
        if event.is_free:
            assert event.price_min_cents == 0
            assert event.price_max_cents == 0
        else:
            assert event.price_min_cents is not None
            assert event.price_max_cents is not None


@pytest.mark.django_db
def test_seed_roughly_40_percent_free():
    """~40% of seeded events should be free (within a reasonable band)."""
    call_command("seed_spike_data", force=True)
    total = Event.objects.count()
    free_count = Event.objects.filter(is_free=True).count()
    ratio = free_count / total
    # Expect ~40% — allow generous band [0.25, 0.55] for deterministic RNG
    assert 0.25 <= ratio <= 0.55, f"Free ratio {ratio:.2%} outside expected range"


@pytest.mark.django_db
def test_seed_wipe_removes_tags():
    """--wipe removes seeded tags before reseeding."""
    call_command("seed_spike_data", force=True)
    first_tag_pks = set(Tag.objects.values_list("pk", flat=True))

    call_command("seed_spike_data", wipe=True, force=True)
    second_tag_pks = set(Tag.objects.values_list("pk", flat=True))

    # After wipe+reseed, old tag PKs should be gone (new rows)
    assert not first_tag_pks.intersection(second_tag_pks)
    assert Tag.objects.count() == 9


@pytest.mark.django_db
def test_seed_tags_idempotent_via_get_or_create():
    """Tags use get_or_create so running with --wipe doesn't leave orphan tags."""
    call_command("seed_spike_data", force=True)
    call_command("seed_spike_data", wipe=True, force=True)
    # After two runs, still exactly 9 tags
    assert Tag.objects.count() == 9
