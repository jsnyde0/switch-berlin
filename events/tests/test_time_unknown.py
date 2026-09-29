"""
Date-only events (sb-7wzb.4, granter ruling C): an event whose source gives a
date but no time carries start_time_unknown and shows "time to be announced"
wherever its start time would show, never a synthesized 00:00 (ADR-008 D3).
"""

from datetime import datetime, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import Profile


class TimeUnknownRenderTest(TestCase):
    def setUp(self):
        self.org = Profile.objects.create(name="Shirka & Till", slug="shirka-till", status="approved")
        day = (timezone.localtime() + timedelta(days=5)).date()
        self.event = Event.objects.create(
            title="Berlin Temple",
            slug="berlin-temple",
            organizer=self.org,
            start=timezone.make_aware(datetime(day.year, day.month, day.day)),
            start_time_unknown=True,
            status="published",
            published_at=timezone.now(),
        )

    def test_detail_says_time_to_be_announced(self):
        resp = self.client.get(
            reverse("event-detail", kwargs={"org_slug": self.org.slug, "event_slug": self.event.slug})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "time to be announced")
        self.assertNotContains(resp, "00:00")

    def test_list_card_says_time_to_be_announced(self):
        resp = self.client.get(reverse("event-list"))
        self.assertContains(resp, "Berlin Temple")
        self.assertContains(resp, "time to be announced")
        self.assertNotContains(resp, "00:00")

    def test_listing_projection_text_carries_the_date_only(self):
        from syndication.engine import _compose_listing_body

        body = _compose_listing_body(self.event, "telegram")
        self.assertIn(f"Date: {timezone.localtime(self.event.start):%Y-%m-%d} (time to be announced)", body)
        self.assertNotIn("00:00", body)


class TimeUnknownClearsOnRealStartTest(TestCase):
    """B1 (review round 2026-09-29): once anyone writes a real start time, the
    event stops saying "time to be announced" — through the studio form, the
    Django admin and the event API alike."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        from organizers.models import ProfileClaim

        self.user = get_user_model().objects.create_user(
            username="claimant", email="claimant@test.com", password="x", status="vouched"
        )
        self.org = Profile.objects.create(name="Shirka & Till", slug="shirka-till", status="approved")
        ProfileClaim.objects.create(profile=self.org, user=self.user, verified_method="auto_self")
        self.day = (timezone.localtime() + timedelta(days=5)).date()
        self.event = Event.objects.create(
            title="Berlin Temple",
            slug="berlin-temple",
            organizer=self.org,
            start=timezone.make_aware(datetime(self.day.year, self.day.month, self.day.day)),
            start_time_unknown=True,
            status="published",
            published_at=timezone.now(),
        )

    def _detail(self):
        return self.client.get(
            reverse("event-detail", kwargs={"org_slug": self.org.slug, "event_slug": self.event.slug})
        )

    def _real_start(self):
        return timezone.make_aware(datetime(self.day.year, self.day.month, self.day.day, 19, 30))

    def test_studio_form_edit_with_real_time_clears_the_flag(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {"title": self.event.title, "slug": self.event.slug, "start": f"{self.day:%Y-%m-%d}T19:30"},
            HTTP_HX_REQUEST="true",
        )
        self.assertLess(resp.status_code, 400)
        self.event.refresh_from_db()
        self.assertFalse(self.event.start_time_unknown)
        detail = self._detail()
        self.assertNotContains(detail, "time to be announced")
        self.assertContains(detail, "19:30")

    def test_studio_form_edit_that_keeps_the_date_only_start_keeps_the_flag(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("syndication:event-edit", kwargs={"pk": self.event.pk}),
            {"title": "Berlin Temple (renamed)", "slug": self.event.slug, "start": f"{self.day:%Y-%m-%d}T00:00"},
            HTTP_HX_REQUEST="true",
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Berlin Temple (renamed)")
        self.assertTrue(self.event.start_time_unknown)

    def test_admin_save_with_real_time_clears_the_flag(self):
        from django.contrib import admin
        from django.test import RequestFactory

        model_admin = admin.site._registry[Event]
        request = RequestFactory().post("/admin/")
        request.user = self.user
        self.event.start = self._real_start()
        model_admin.save_model(request, self.event, form=None, change=True)
        self.event.refresh_from_db()
        self.assertFalse(self.event.start_time_unknown)
        self.assertNotContains(self._detail(), "time to be announced")

    def test_api_patch_with_real_time_clears_the_flag(self):
        import json

        from syndication.test_api import _get_identity_token_for_user

        token = _get_identity_token_for_user(self.user)
        resp = self.client.patch(
            f"/api/events/{self.event.pk}/",
            data=json.dumps({"start": self._real_start().isoformat()}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.event.refresh_from_db()
        self.assertFalse(self.event.start_time_unknown)
        self.assertNotContains(self._detail(), "time to be announced")
