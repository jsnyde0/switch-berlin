"""Tests that FlagAdmin bulk resolve actions write ModerationAction rows.

Bulk shortcut actions must not diverge from process_action's audit surface —
ModerationAction is the DSA/GDPR audit trail (ADR-005 Bundle A).
"""

from datetime import timedelta

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from django.test import TestCase
from django.utils import timezone

from a_core.models import ModerationAction
from events.models import Event
from organizers.models import Organizer
from reviews.admin import FlagAdmin
from reviews.models import Flag

User = get_user_model()


class BulkResolveAuditTest(TestCase):
    def setUp(self):
        self.moderator = User.objects.create_user(
            username="mod", password="x", is_staff=True, is_superuser=True
        )
        self.reporter = User.objects.create_user(username="rep", password="x")
        self.organizer = Organizer.objects.create(
            name="Org", slug="org", status="approved"
        )
        self.event = Event.objects.create(
            title="E",
            slug="e",
            organizer=self.organizer,
            status="published",
            start=timezone.now() + timedelta(days=1),
        )
        self.flag1 = Flag.objects.create(
            reporter=self.reporter, event=self.event, reason="other", body="b1"
        )
        self.flag2 = Flag.objects.create(
            reporter=self.reporter, organizer=self.organizer, reason="other", body="b2"
        )
        self.admin = FlagAdmin(Flag, AdminSite())
        self.request = HttpRequest()
        self.request.user = self.moderator

    def test_resolve_approved_creates_moderation_action_per_flag(self):
        qs = Flag.objects.filter(pk__in=[self.flag1.pk, self.flag2.pk])
        self.admin.resolve_approved(self.request, qs)
        self.assertEqual(ModerationAction.objects.count(), 2)
        self.flag1.refresh_from_db()
        self.flag2.refresh_from_db()
        self.assertTrue(self.flag1.resolved)
        self.assertTrue(self.flag2.resolved)
        self.assertEqual(self.flag1.resolved_by, self.moderator)
        self.assertEqual(
            self.flag1.resolution_notes, "Bulk approved via admin shortcut"
        )
        # ModerationAction has the moderator, flag link, target repr.
        ma1 = ModerationAction.objects.get(flag=self.flag1)
        self.assertEqual(ma1.moderator, self.moderator)
        self.assertEqual(ma1.action, "resolved")
        self.assertEqual(ma1.target_type, "event")
        self.assertEqual(ma1.target_id, self.event.pk)

    def test_resolve_rejected_creates_moderation_action_per_flag(self):
        qs = Flag.objects.filter(pk=self.flag1.pk)
        self.admin.resolve_rejected(self.request, qs)
        self.assertEqual(ModerationAction.objects.count(), 1)
        self.flag1.refresh_from_db()
        self.assertEqual(
            self.flag1.resolution_notes, "Bulk rejected via admin shortcut"
        )
