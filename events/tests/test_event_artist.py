"""
EventArtist — an artist credit on an event (ADR-007 D2, sb-x5xh.4).

An artist credit is a display name, optionally linked to a Profile. Artists are
credited only: they cannot edit the event (ADR-017 D1).
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import CASCADE, PROTECT
from django.test import TestCase
from django.utils import timezone

from events.models import Event, EventArtist, EventOrganizer
from organizers.models import Profile, ProfileClaim

User = get_user_model()


def _event(slug="artist-night", organizer=None, **kwargs):
    kwargs.setdefault("start", timezone.now() + timezone.timedelta(days=3))
    kwargs.setdefault("status", "published")
    return Event.objects.create(title="Artist Night", slug=slug, organizer=organizer, **kwargs)


class EventArtistModelTest(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(name="Lavinia", slug="lavinia", status="approved")
        self.event = _event()

    def test_profile_is_optional_and_name_is_required(self):
        f = EventArtist._meta.get_field("profile")
        self.assertTrue(f.null)
        self.assertTrue(f.blank)
        self.assertFalse(EventArtist._meta.get_field("name").blank)
        with self.assertRaises(ValidationError):
            EventArtist(event=self.event, name="").full_clean()

    def test_name_only_credit_saves(self):
        credit = EventArtist.objects.create(event=self.event, name="Lu")
        self.assertIsNone(credit.profile)
        self.assertEqual(list(self.event.artist_credits.all()), [credit])

    def test_on_delete_event_cascades_profile_protects(self):
        self.assertEqual(EventArtist._meta.get_field("event").remote_field.on_delete, CASCADE)
        self.assertEqual(EventArtist._meta.get_field("profile").remote_field.on_delete, PROTECT)

    def test_blank_role_allowed(self):
        EventArtist(event=self.event, name="Lu", role="").full_clean()

    def test_one_credit_per_linked_profile(self):
        EventArtist.objects.create(event=self.event, profile=self.profile, name="Lavinia")
        with self.assertRaises(IntegrityError):
            EventArtist.objects.create(event=self.event, profile=self.profile, name="Lavinia")

    def test_many_name_only_credits_on_one_event(self):
        EventArtist.objects.create(event=self.event, name="Lu")
        EventArtist.objects.create(event=self.event, name="Kai")
        self.assertEqual(self.event.artist_credits.count(), 2)

    def test_profile_can_organize_and_be_artist_on_same_event(self):
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        EventArtist.objects.create(event=self.event, profile=self.profile, name="Lavinia", role="Lead")
        self.assertIn(self.event, self.profile.events_organized.all())
        self.assertEqual(self.profile.artist_credits.get().event, self.event)

    def test_event_has_no_artist_profile_m2m(self):
        # Rendering reads EventArtist rows; a Profile M2M would hide name-only credits.
        profile_m2ms = [f.name for f in Event._meta.many_to_many if f.related_model is Profile]
        self.assertEqual(profile_m2ms, ["organizers"])


class EventArtistRenderingTest(TestCase):
    def setUp(self):
        self.organizer = Profile.objects.create(name="Host Collective", slug="host-collective", status="approved")
        self.event = _event(organizer=self.organizer, description="A night of rope.")
        self.url = f"/events/{self.organizer.slug}/{self.event.slug}/"

    def test_detail_shows_organized_by(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Organized by")
        self.assertContains(response, f'href="/p/{self.organizer.slug}/"')

    def test_name_only_artist_renders_unlinked_under_artists(self):
        EventArtist.objects.create(event=self.event, name="Lu")
        response = self.client.get(self.url)
        html = response.content.decode()
        self.assertIn("Artists", html)
        artists = html[html.index("Artists") :]
        self.assertIn(">Lu<", artists.replace("\n", "").replace(" ", ""))
        self.assertNotIn(">Lu</a>", html.replace(" ", ""))

    def test_linked_artist_renders_profile_link(self):
        artist = Profile.objects.create(name="Kai Rope", slug="kai-rope", status="approved")
        EventArtist.objects.create(event=self.event, profile=artist, name="Kai Rope")
        response = self.client.get(self.url)
        self.assertContains(response, 'href="/p/kai-rope/"')
        self.assertContains(response, "Kai Rope")

    def test_no_artists_section_without_credits(self):
        response = self.client.get(self.url)
        self.assertNotContains(response, "Artists")

    def test_card_shows_artists(self):
        EventArtist.objects.create(event=self.event, name="Lu")
        response = self.client.get("/events/")
        self.assertContains(response, "Organized by")
        self.assertContains(response, "Lu")


class ArtistCannotEditTest(TestCase):
    def test_artist_profile_managers_cannot_edit(self):
        from syndication.authz import can_edit

        manager = User.objects.create_user(username="lu", email="lu@test.com", password="x", status="vouched")
        artist = Profile.objects.create(name="Lu", slug="lu")
        ProfileClaim.objects.create(profile=artist, user=manager, verified_method="auto_self")
        event = _event(organizer=Profile.objects.create(name="Org", slug="org"))
        EventArtist.objects.create(event=event, profile=artist, name="Lu")
        self.assertFalse(can_edit(manager, event))


class EventArtistMigrationsTest(TestCase):
    """0019/0020 fail loud instead of losing or synthesizing data (ADR-008 D3)."""

    def _migration(self, name):
        import importlib

        return importlib.import_module(f"events.migrations.{name}")

    def test_backfill_raises_on_empty_profile_name(self):
        from django.apps import apps

        backfill_name = self._migration("0020_eventartist_backfill_name").backfill_name
        profile = Profile.objects.create(name="", slug="nameless", status="approved")
        EventArtist.objects.create(event=_event(), profile=profile, name="")
        with self.assertRaisesRegex(RuntimeError, "empty name"):
            backfill_name(apps, None)

    def test_backfill_copies_profile_name(self):
        from django.apps import apps

        backfill_name = self._migration("0020_eventartist_backfill_name").backfill_name
        profile = Profile.objects.create(name="Lavinia", slug="lavinia", status="approved")
        credit = EventArtist.objects.create(event=_event(), profile=profile, name="")
        backfill_name(apps, None)
        credit.refresh_from_db()
        self.assertEqual(credit.name, "Lavinia")

    def test_0019_is_irreversible(self):
        migration = self._migration("0019_eventartist").Migration
        self.assertFalse(all(op.reversible for op in migration.operations))
