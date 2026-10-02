"""
EventArtist — an artist credit on an event (ADR-007 D2, sb-x5xh.4).

An artist credit is a display name, optionally linked to a Profile. Artists are
credited only: they cannot edit the event (ADR-017 D1), and their names stay out
of structured data, meta/OG tags, sitemaps and search (sb-7wzb.17 safeguard).
"""

from unittest.mock import patch

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


class ArtistNamesStayOutOfIndexingTest(TestCase):
    """sb-7wzb.17 safeguard: artist names never reach JSON-LD, meta/OG, sitemap or search."""

    NAME = "Zephyrine Quill"

    def setUp(self):
        self.organizer = Profile.objects.create(name="Host Collective", slug="host-collective", status="approved")
        self.event = _event(organizer=self.organizer, visibility="public", description="A night of rope.")
        self.artist = Profile.objects.create(name=self.NAME, slug="zephyrine-quill", status="approved")
        EventArtist.objects.create(event=self.event, profile=self.artist, name=self.NAME)
        EventArtist.objects.create(event=self.event, name="Lu Unlinked")

    def _detail_html(self):
        with patch("a_core.context_processors.get_flag", return_value=True):
            response = self.client.get(f"/events/{self.organizer.slug}/{self.event.slug}/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_page_renders_the_artist_but_not_in_head_or_structured_data(self):
        html = self._detail_html()
        self.assertIn(self.NAME, html)  # visible credit
        head = html[: html.index("</head>")]
        self.assertIn('property="og:title"', head)
        self.assertNotIn(self.NAME, head)
        self.assertNotIn("Lu Unlinked", head)
        self.assertNotIn("performer", html)
        for block in html.split('type="application/ld+json"')[1:]:
            self.assertNotIn(self.NAME, block.split("</script>")[0])

    def test_sitemap_carries_no_artist_name(self):
        from events.sitemap import EventSitemap

        sitemap = EventSitemap()
        items = list(sitemap.items())
        self.assertIn(self.event, items)
        for item in items:
            self.assertNotIn("zephyrine", sitemap.location(item))

    def test_list_filter_does_not_match_artist(self):
        response = self.client.get("/events/", {"organizer": self.artist.slug})
        self.assertNotContains(response, "Artist Night")

    def test_admin_search_does_not_match_artist_name(self):
        User.objects.create_superuser(username="staff", email="s@test.com", password="x")
        self.client.login(username="staff", password="x")
        response = self.client.get("/admin/events/event/", {"q": "Zephyrine", "status__exact": "published"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["cl"].result_count, 0)
