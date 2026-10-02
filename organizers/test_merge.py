"""sb-7wzb.22: staff merge of duplicate Profiles and Venues, with a merge record.

Rule 5 of the sb-x5xh.2 ruling: duplicates are merged, never recreated. The
merge repoints every relation from the loser to the winner, fills the winner's
empty fields from the loser, deletes the loser and writes one MergeRecord.
"""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.utils import timezone

from events.models import Event, EventArtist, EventOrganizer
from organizers.merge import MergeRefused, merge_profiles, merge_venues
from organizers.models import ClaimIntent, Follow, MergeRecord, Profile, ProfileClaim
from reviews.models import Review
from venues.models import Venue

User = get_user_model()


def _event(slug):
    return Event.objects.create(
        title=slug, slug=slug, start=timezone.now() + datetime.timedelta(days=1), status="draft"
    )


@pytest.fixture
def staff(db):
    return User.objects.create_superuser(username="staff", email="staff@example.com", password="x")


@pytest.fixture
def pair(db):
    winner = Profile.objects.create(name="Soma House", slug="soma-house", description="Tantra space")
    loser = Profile.objects.create(
        name="SOMA House Berlin", slug="soma-house-berlin", website="https://soma.example", pronouns=""
    )
    return winner, loser


# --- (1) profiles: event roles and claims repoint, loser deleted ------------


@pytest.mark.django_db
def test_merge_profiles_repoints_event_roles_and_claims_and_deletes_loser(pair, staff):
    winner, loser = pair
    ev = _event("ev-a")
    EventOrganizer.objects.create(event=ev, profile=loser, is_primary=True)
    EventArtist.objects.create(event=_event("ev-b"), profile=loser, name=loser.name, role="DJ")
    manager = User.objects.create_user(username="m", email="m@example.com", password="x")
    ProfileClaim.objects.create(profile=loser, user=manager, verified_method="admin_review")
    ClaimIntent.objects.create(profile=loser, user=manager)
    Follow.objects.create(profile=loser, user=manager)
    Review.objects.create(organizer=loser, author=manager, rating=5)

    merge_profiles(winner, loser, staff)

    assert not Profile.objects.filter(pk=loser.pk).exists()
    assert EventOrganizer.objects.get(event=ev).profile == winner
    assert EventArtist.objects.get(event__slug="ev-b").profile == winner
    assert ProfileClaim.objects.get(user=manager).profile == winner
    assert ClaimIntent.objects.get(user=manager).profile == winner
    assert Follow.objects.get(user=manager).profile == winner
    assert Review.objects.get(author=manager).organizer == winner


@pytest.mark.django_db
def test_merge_profiles_repoints_venue_run_by(pair, staff):
    winner, loser = pair
    venue = Venue.objects.create(name="Soma", slug="soma", run_by=loser)

    merge_profiles(winner, loser, staff)

    venue.refresh_from_db()
    assert venue.run_by == winner


@pytest.mark.django_db
def test_merge_profiles_keeps_winner_fields_and_fills_its_gaps(pair, staff):
    winner, loser = pair
    loser.description = "Loser text"
    loser.save()

    merge_profiles(winner, loser, staff)

    winner.refresh_from_db()
    assert winner.name == "Soma House"
    assert winner.slug == "soma-house"
    assert winner.description == "Tantra space"  # filled on winner: kept
    assert winner.website == "https://soma.example"  # empty on winner: filled


@pytest.mark.django_db
def test_both_organizers_of_one_event_collapse_to_one_row_keeping_primary(pair, staff):
    winner, loser = pair
    ev = _event("ev-shared")
    EventOrganizer.objects.create(event=ev, profile=winner, is_primary=False)
    EventOrganizer.objects.create(event=ev, profile=loser, is_primary=True)

    merge_profiles(winner, loser, staff)

    rows = EventOrganizer.objects.filter(event=ev)
    assert rows.count() == 1
    assert rows.get().profile == winner
    assert rows.get().is_primary is True


@pytest.mark.django_db
def test_both_artists_of_one_event_collapse_to_one_row(pair, staff):
    winner, loser = pair
    ev = _event("ev-art")
    EventArtist.objects.create(event=ev, profile=winner, name=winner.name, role="")
    EventArtist.objects.create(event=ev, profile=loser, name=loser.name, role="DJ")

    merge_profiles(winner, loser, staff)

    row = EventArtist.objects.get(event=ev)
    assert row.profile == winner
    assert row.role == "DJ"


@pytest.mark.django_db
def test_same_manager_on_both_keeps_one_active_claim(pair, staff):
    winner, loser = pair
    manager = User.objects.create_user(username="m2", email="m2@example.com", password="x")
    ProfileClaim.objects.create(
        profile=winner, user=manager, verified_method="admin_review", rejected_at=timezone.now()
    )
    ProfileClaim.objects.create(profile=loser, user=manager, verified_method="admin_review")
    Follow.objects.create(profile=winner, user=manager)
    Follow.objects.create(profile=loser, user=manager)

    merge_profiles(winner, loser, staff)

    claim = ProfileClaim.objects.get(user=manager)
    assert claim.profile == winner
    assert claim.rejected_at is None
    assert Follow.objects.filter(user=manager, profile=winner).count() == 1


@pytest.mark.django_db
def test_unresolvable_conflict_refuses_and_changes_nothing(pair, staff):
    winner, loser = pair
    author = User.objects.create_user(username="a", email="a@example.com", password="x")
    Review.objects.create(organizer=winner, author=author, rating=5)
    Review.objects.create(organizer=loser, author=author, rating=1)

    with pytest.raises(MergeRefused, match="Review"):
        merge_profiles(winner, loser, staff)

    assert Profile.objects.filter(pk=loser.pk).exists()
    assert Review.objects.filter(organizer=loser).count() == 1
    assert not MergeRecord.objects.exists()


@pytest.mark.django_db
def test_merge_with_itself_refuses(pair, staff):
    winner, _ = pair
    with pytest.raises(MergeRefused):
        merge_profiles(winner, winner, staff)


# --- (2) venues: events and run_by repoint ---------------------------------


@pytest.mark.django_db
def test_merge_venues_repoints_events_and_fills_run_by(pair, staff):
    profile, _ = pair
    winner = Venue.objects.create(name="Haus Lebenskunst", slug="haus-lebenskunst")
    loser = Venue.objects.create(name="Haus Lebenskunst Berlin", slug="hl-berlin", run_by=profile, address="Str 1")
    ev = _event("ev-v")
    ev.venue = loser
    ev.save()

    merge_venues(winner, loser, staff)

    assert not Venue.objects.filter(pk=loser.pk).exists()
    ev.refresh_from_db()
    assert ev.venue == winner
    winner.refresh_from_db()
    assert winner.run_by == profile
    assert winner.address == "Str 1"


# --- (3) the merge record --------------------------------------------------


@pytest.mark.django_db
def test_merge_record_holds_both_names(pair, staff):
    winner, loser = pair

    merge_profiles(winner, loser, staff)

    record = MergeRecord.objects.get()
    assert record.kind == "profile"
    assert record.winner_id == winner.pk
    assert record.winner_name == "Soma House"
    assert record.loser_name == "SOMA House Berlin"
    assert record.winner_normalized == "soma house"
    assert record.loser_normalized == "soma house berlin"
    assert record.merged_by == staff


@pytest.mark.django_db
def test_venue_merge_record_kind(staff):
    a = Venue.objects.create(name="Kitkat", slug="kitkat")
    b = Venue.objects.create(name="KitKat Club", slug="kitkat-club")
    merge_venues(a, b, staff)
    assert MergeRecord.objects.get().kind == "venue"


# --- the admin action, and (4) staff-only ----------------------------------


@pytest.mark.django_db
def test_admin_action_shows_confirmation_then_merges(client, pair, staff):
    winner, loser = pair
    client.force_login(staff)
    url = "/admin/organizers/profile/"
    selected = [str(winner.pk), str(loser.pk)]

    page = client.post(url, {"action": "merge_into", "_selected_action": selected})
    assert page.status_code == 200
    assert b"SOMA House Berlin" in page.content
    assert Profile.objects.filter(pk=loser.pk).exists()

    done = client.post(
        url, {"action": "merge_into", "_selected_action": selected, "winner": str(winner.pk), "apply": "1"}
    )
    assert done.status_code == 302
    assert not Profile.objects.filter(pk=loser.pk).exists()
    assert MergeRecord.objects.get().winner_id == winner.pk


@pytest.mark.django_db
def test_admin_action_on_venues_merges(client, staff):
    a = Venue.objects.create(name="Kitkat", slug="kitkat")
    b = Venue.objects.create(name="KitKat Club", slug="kitkat-club")
    client.force_login(staff)
    client.post(
        "/admin/venues/venue/",
        {"action": "merge_into", "_selected_action": [str(a.pk), str(b.pk)], "winner": str(b.pk), "apply": "1"},
    )
    assert list(Venue.objects.values_list("name", flat=True)) == ["KitKat Club"]


@pytest.mark.django_db
def test_admin_action_needs_exactly_two_rows(client, pair, staff):
    winner, _ = pair
    client.force_login(staff)
    client.post("/admin/organizers/profile/", {"action": "merge_into", "_selected_action": [str(winner.pk)]})
    assert Profile.objects.count() == 2
    assert not MergeRecord.objects.exists()


@pytest.mark.django_db
def test_merge_action_unavailable_to_non_staff(client, pair):
    winner, loser = pair
    user = User.objects.create_user(username="plain", email="plain@example.com", password="x")
    client.force_login(user)

    resp = client.post(
        "/admin/organizers/profile/",
        {
            "action": "merge_into",
            "_selected_action": [str(winner.pk), str(loser.pk)],
            "winner": str(winner.pk),
            "apply": "1",
        },
    )

    assert resp.status_code in (302, 403)  # login redirect or forbidden: never the action
    assert Profile.objects.filter(pk=loser.pk).exists()
    assert not MergeRecord.objects.exists()


@pytest.mark.django_db
def test_merge_action_hidden_from_staff_without_delete_permission(client, pair):
    winner, loser = pair
    clerk = User.objects.create_user(username="clerk", email="clerk@example.com", password="x", is_staff=True)
    clerk.user_permissions.add(
        Permission.objects.get(codename="view_profile"), Permission.objects.get(codename="change_profile")
    )
    client.force_login(clerk)

    page = client.get("/admin/organizers/profile/")
    assert page.status_code == 200
    assert b"merge_into" not in page.content

    client.post(
        "/admin/organizers/profile/",
        {
            "action": "merge_into",
            "_selected_action": [str(winner.pk), str(loser.pk)],
            "winner": str(winner.pk),
            "apply": "1",
        },
    )
    assert Profile.objects.filter(pk=loser.pk).exists()


# --- review round: no field state neither side had --------------------------


@pytest.mark.django_db
def test_venue_merge_keeps_the_stricter_privacy_mode(staff):
    public = Venue.objects.create(name="Kitkat", slug="kitkat")
    private = Venue.objects.create(
        name="KitKat Club", slug="kitkat-club", address="Secret 1", privacy_mode="private", blur_radius_m=500
    )

    merge_venues(public, private, staff)

    public.refresh_from_db()
    assert public.address == "Secret 1"
    assert public.privacy_mode == "private"
    assert public.blur_radius_m == 500


@pytest.mark.django_db
def test_profile_merge_never_fills_approval_or_consent_from_the_loser(pair, staff):
    winner, loser = pair
    loser.status = "approved"
    loser.approved_at = timezone.now()
    loser.approved_by = staff
    loser.consent_recorded_at = timezone.now()
    loser.consent_method = "verified_public_source"
    loser.save()

    merge_profiles(winner, loser, staff)

    winner.refresh_from_db()
    assert winner.status == "candidate"
    assert winner.approved_at is None
    assert winner.approved_by is None
    assert winner.consent_recorded_at is None
    assert winner.consent_method == ""


@pytest.mark.django_db
def test_same_channel_on_both_keeps_one_connection(pair, staff):
    from syndication.models import PlatformConnection

    winner, loser = pair
    for p in (winner, loser):
        PlatformConnection.objects.create(organizer=p, platform="telegram", destination_id="-100123")

    merge_profiles(winner, loser, staff)

    assert PlatformConnection.objects.filter(destination_id="-100123").count() == 1


@pytest.mark.django_db
def test_merge_records_cannot_be_deleted_in_the_admin(client, staff):
    MergeRecord.objects.create(
        kind="venue", winner_id=1, winner_name="a", loser_name="b", winner_normalized="a", loser_normalized="b"
    )
    client.force_login(staff)
    page = client.get(f"/admin/organizers/mergerecord/{MergeRecord.objects.get().pk}/delete/")
    assert page.status_code == 403
