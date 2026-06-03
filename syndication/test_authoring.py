"""
TDD tests for C3 Event + Post CRUD authoring (kb-a4u.3).

Harness targets:
- Event authored via web form persists ALL ADR-016 D1 fields.
- Post authored persists with FK to Event.
- Eager draft projections created per enabled connection on Event/Post creation.
- can_edit / can_publish seam in syndication.authz.
- API endpoints for Event CRUD (create/read/update/list/detail).
- API endpoints for Post CRUD scoped to Event.

Co-equal seam: both web form and JSON API use syndication.services functions
(not parallel implementations).
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventFacilitator, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import PlatformConnection, PlatformProjection, Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name="Test Organizer", slug="test-organizer", user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _make_connection(profile, platform="switch", destination_id="own-page", kinds=None, enabled=True):
    return PlatformConnection.objects.create(
        organizer=profile,
        platform=platform,
        destination_id=destination_id,
        kinds=kinds or ["listing"],
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# 1. Authorization seam (ADR-017 D1/D2)
# ---------------------------------------------------------------------------


class AuthorizationSeamTest(TestCase):
    """
    can_edit / can_publish gate in syndication.authz (ADR-017 D2).

    Policy: edit/publish iff user is a claimant of an EventOrganizer Profile of the Event.
    EventFacilitators are credited-only.
    """

    def setUp(self):
        self.user_organizer = _make_vouched_user(username="org_user", email="org@test.com", password="x")
        self.user_facilitator = _make_vouched_user(username="fac_user", email="fac@test.com", password="x")
        self.user_stranger = _make_vouched_user(username="stranger", email="stranger@test.com", password="x")
        self.profile = _make_profile(name="Org Profile", slug="org-profile", user=self.user_organizer)
        self.fac_profile = _make_profile(name="Fac Profile", slug="fac-profile", user=self.user_facilitator)
        self.event = Event.objects.create(
            title="Auth Test Event",
            slug="auth-test-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)
        EventFacilitator.objects.create(event=self.event, profile=self.fac_profile)

    def test_can_edit_returns_true_for_organizer_claimant(self):
        """Organizer Profile claimant may edit."""
        from syndication.authz import can_edit

        self.assertTrue(can_edit(self.user_organizer, self.event))

    def test_can_edit_returns_false_for_facilitator(self):
        """Facilitator (credited-only) may NOT edit."""
        from syndication.authz import can_edit

        self.assertFalse(can_edit(self.user_facilitator, self.event))

    def test_can_edit_returns_false_for_stranger(self):
        """User with no relationship to the event may NOT edit."""
        from syndication.authz import can_edit

        self.assertFalse(can_edit(self.user_stranger, self.event))

    def test_can_publish_returns_true_for_organizer_claimant(self):
        """Organizer Profile claimant may publish."""
        from syndication.authz import can_publish

        self.assertTrue(can_publish(self.user_organizer, self.event))

    def test_can_publish_returns_false_for_facilitator(self):
        """Facilitator may NOT publish."""
        from syndication.authz import can_publish

        self.assertFalse(can_publish(self.user_facilitator, self.event))

    def test_can_publish_returns_false_for_stranger(self):
        """Stranger may NOT publish."""
        from syndication.authz import can_publish

        self.assertFalse(can_publish(self.user_stranger, self.event))


# ---------------------------------------------------------------------------
# 2. Service layer: create_event persists ALL ADR-016 D1 fields
# ---------------------------------------------------------------------------


class CreateEventServiceTest(TestCase):
    """
    syndication.services.create_event persists all ADR-016 D1 fields and
    creates EventOrganizer row.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="ev_creator", email="ev@test.com", password="x")
        self.profile = _make_profile(name="Creator Profile", slug="creator-profile", user=self.user)

    def test_create_event_returns_event_instance(self):
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Service Event",
            slug="service-event",
            start=timezone.now(),
        )
        self.assertIsInstance(event, Event)
        self.assertIsNotNone(event.pk)

    def test_create_event_persists_title(self):
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Unique Title Here",
            slug="unique-title-here",
            start=timezone.now(),
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(fetched.title, "Unique Title Here")

    def test_create_event_persists_all_adr016_d1_fields(self):
        """
        Harness item: an Event authored via the service persists scalar ADR-016 D1 fields.
        Covers: title, description, start, end, dress_code, content_warnings,
        age_restriction, capacity, visibility, language, pricing fields, external links.

        Note: tags (M2M) and venue (FK) round-trip coverage lives in
        CreateEventServiceAllFieldsTest and EventWebFormTest.
        Registration field round-trip: CreateEventServiceAllFieldsTest.
        """
        from syndication.services import create_event

        now = timezone.now()
        event = create_event(
            user=self.user,
            title="Full Fields Event",
            slug="full-fields-event",
            start=now,
            end=now,
            description="A great event",
            dress_code="Fetish attire",
            content_warnings=["nudity", "bdsm"],
            age_restriction=18,
            capacity=50,
            visibility="public",
            language="en",
            is_free=False,
            price_min_cents=2000,
            price_max_cents=4000,
            currency="EUR",
            sliding_scale=False,
            price_description="Early bird 20€ / Normal 40€",
            external_url="https://example.com/event",
            tickets_url="https://tickets.example.com/event",
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(fetched.description, "A great event")
        self.assertEqual(fetched.dress_code, "Fetish attire")
        self.assertEqual(fetched.content_warnings, ["nudity", "bdsm"])
        self.assertEqual(fetched.age_restriction, 18)
        self.assertEqual(fetched.capacity, 50)
        self.assertEqual(fetched.visibility, "public")
        self.assertEqual(fetched.language, "en")
        self.assertFalse(fetched.is_free)
        self.assertEqual(fetched.price_min_cents, 2000)
        self.assertEqual(fetched.price_max_cents, 4000)
        self.assertEqual(fetched.price_description, "Early bird 20€ / Normal 40€")
        self.assertEqual(fetched.external_url, "https://example.com/event")
        self.assertEqual(fetched.tickets_url, "https://tickets.example.com/event")

    def test_create_event_creates_event_organizer_row(self):
        """Creating an event via the service creates an EventOrganizer through-table row."""
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Organizer Row Event",
            slug="organizer-row-event",
            start=timezone.now(),
        )
        self.assertTrue(EventOrganizer.objects.filter(event=event, profile=self.profile, is_primary=True).exists())

    def test_create_event_status_defaults_to_draft(self):
        """New events default to draft status (ADR-016 D5 — save-always)."""
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Draft Status Event",
            slug="draft-status-event",
            start=timezone.now(),
        )
        self.assertEqual(event.status, "draft")

    def test_create_event_without_organizer_profile_raises(self):
        """Creating an event requires the user to have an associated profile."""
        from syndication.services import create_event

        no_profile_user = _make_vouched_user(username="no_profile_user", email="noprofile@test.com", password="x")
        with self.assertRaises(ValueError):
            create_event(
                user=no_profile_user,
                title="No Profile Event",
                slug="no-profile-event",
                start=timezone.now(),
            )


# ---------------------------------------------------------------------------
# 3. Eager projection creation on Event creation (ADR-016 D4)
# ---------------------------------------------------------------------------


class EagerProjectionOnEventTest(TestCase):
    """
    ADR-016 D4: Authoring an Event eager-creates draft listing projections
    for each enabled listing-capable connection.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="eager_event_user", email="eager_ev@test.com", password="x")
        self.profile = _make_profile(name="Eager Profile", slug="eager-profile", user=self.user)

    def test_creating_event_eager_creates_listing_projections(self):
        """
        When an Event is created, each enabled connection that supports 'listing'
        gets a draft PlatformProjection.
        """
        conn_switch = _make_connection(self.profile, platform="switch", destination_id="own-page", kinds=["listing"])
        conn_fetlife = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-user", kinds=["listing", "promotion"]
        )

        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Eager Test Event",
            slug="eager-test-event",
            start=timezone.now(),
        )

        listing_projs = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
            status=PlatformProjection.Status.DRAFT,
        )
        self.assertEqual(listing_projs.count(), 2)
        conn_ids = set(listing_projs.values_list("connection_id", flat=True))
        self.assertIn(conn_switch.pk, conn_ids)
        self.assertIn(conn_fetlife.pk, conn_ids)

    def test_disabled_connection_does_not_get_eager_projection(self):
        """Disabled connections are skipped in eager creation."""
        _make_connection(self.profile, platform="switch", destination_id="own-page", kinds=["listing"], enabled=True)
        _make_connection(
            self.profile, platform="tickettailor", destination_id="tt-acc", kinds=["listing"], enabled=False
        )

        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Disabled Skip Event",
            slug="disabled-skip-event",
            start=timezone.now(),
        )

        listing_projs = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
        )
        self.assertEqual(listing_projs.count(), 1)

    def test_promotion_only_connection_not_included_in_event_eager_creation(self):
        """A promotion-only connection (e.g. Telegram) is not included on Event create."""
        _make_connection(
            self.profile, platform="telegram", destination_id="channel-1", kinds=["promotion"], enabled=True
        )

        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="No Promo Event",
            slug="no-promo-event",
            start=timezone.now(),
        )

        listing_projs = PlatformProjection.objects.filter(
            source_event=event,
            kind=PlatformProjection.Kind.LISTING,
        )
        self.assertEqual(listing_projs.count(), 0)


# ---------------------------------------------------------------------------
# 4. Service layer: create_post + eager promotion projections
# ---------------------------------------------------------------------------


class CreatePostServiceTest(TestCase):
    """
    syndication.services.create_post persists Post with FK to Event and
    eager-creates draft promotion projections per enabled promotion-capable connection.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="post_user", email="post@test.com", password="x")
        self.profile = _make_profile(name="Post Profile", slug="post-profile", user=self.user)
        self.event = Event.objects.create(
            title="Post Target Event",
            slug="post-target-event",
            start=timezone.now(),
        )
        EventOrganizer.objects.create(event=self.event, profile=self.profile, is_primary=True)

    def test_create_post_returns_post_instance(self):
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Test Headline",
            body="Test body text.",
        )
        self.assertIsInstance(post, Post)
        self.assertIsNotNone(post.pk)

    def test_create_post_persists_fk_to_event(self):
        """Post has FK to the event it's about."""
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="FK Test Post",
            body="Body.",
        )
        fetched = Post.objects.get(pk=post.pk)
        self.assertEqual(fetched.event, self.event)

    def test_create_post_persists_headline_and_body(self):
        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="My Headline",
            body="My body text.",
        )
        fetched = Post.objects.get(pk=post.pk)
        self.assertEqual(fetched.headline, "My Headline")
        self.assertEqual(fetched.body, "My body text.")

    def test_create_post_eager_creates_promotion_projections(self):
        """
        ADR-016 D4: Authoring a Post eager-creates draft promotion projections
        for each enabled promotion-capable connection.
        """
        conn_telegram = _make_connection(
            self.profile, platform="telegram", destination_id="channel-123", kinds=["promotion"], enabled=True
        )
        conn_fetlife = _make_connection(
            self.profile, platform="fetlife", destination_id="fl-promo", kinds=["listing", "promotion"], enabled=True
        )
        _make_connection(self.profile, platform="switch", destination_id="own-page", kinds=["listing"], enabled=True)

        from syndication.services import create_post

        post = create_post(
            user=self.user,
            event=self.event,
            headline="Save the Date!",
            body="Come join us.",
        )

        promo_projs = PlatformProjection.objects.filter(
            source_post=post,
            kind=PlatformProjection.Kind.PROMOTION,
            status=PlatformProjection.Status.DRAFT,
        )
        self.assertEqual(promo_projs.count(), 2)
        conn_ids = set(promo_projs.values_list("connection_id", flat=True))
        self.assertIn(conn_telegram.pk, conn_ids)
        self.assertIn(conn_fetlife.pk, conn_ids)

    def test_create_post_requires_can_edit_permission(self):
        """Creating a post requires the user to be able to edit the event."""
        stranger = _make_vouched_user(username="stranger_post", email="stranger_post@test.com", password="x")
        from syndication.services import create_post

        with self.assertRaises(PermissionError):
            create_post(
                user=stranger,
                event=self.event,
                headline="Unauthorized Post",
                body="Should fail.",
            )


# ---------------------------------------------------------------------------
# 5. API endpoint: POST /api/events/ creates event via service
# ---------------------------------------------------------------------------


class EventAPICreateTest(TestCase):
    """
    POST /api/events/ creates an Event through the service layer (co-equal with web form).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="api_event_user", email="api_event@test.com", password="x")
        self.profile = _make_profile(name="API Event Profile", slug="api-event-profile", user=self.user)

    def _get_identity_token(self):
        # Full pairing flow (kb-a4u.6): register → redeem → token exchange
        from syndication.test_api import _register_and_get_api_key

        api_key = _register_and_get_api_key(self.user)
        client = Client()
        ex = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex.content)["identity_token"]

    def test_create_event_returns_201(self):
        token = self._get_identity_token()
        client = Client()
        payload = {
            "title": "API Created Event",
            "slug": "api-created-event",
            "start": timezone.now().isoformat(),
        }
        response = client.post(
            "/api/events/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_event_persists_in_db(self):
        token = self._get_identity_token()
        client = Client()
        payload = {
            "title": "Persisted API Event",
            "slug": "persisted-api-event",
            "start": timezone.now().isoformat(),
        }
        client.post(
            "/api/events/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertTrue(Event.objects.filter(slug="persisted-api-event").exists())

    def test_list_events_returns_200(self):
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            "/api/events/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)

    def test_event_detail_returns_200(self):
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Detail Event",
            slug="detail-event",
            start=timezone.now(),
        )
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            f"/api/events/{event.pk}/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)

    def test_update_event_returns_200(self):
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Update Me",
            slug="update-me",
            start=timezone.now(),
        )
        token = self._get_identity_token()
        client = Client()
        response = client.patch(
            f"/api/events/{event.pk}/",
            data=json.dumps({"title": "Updated Title"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.title, "Updated Title")


# ---------------------------------------------------------------------------
# 6. API endpoint: POST /api/events/{id}/posts/ creates post via service
# ---------------------------------------------------------------------------


class PostAPICreateTest(TestCase):
    """
    POST /api/events/{id}/posts/ creates a Post through the service layer.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="api_post_user", email="api_post@test.com", password="x")
        self.profile = _make_profile(name="API Post Profile", slug="api-post-profile", user=self.user)
        from syndication.services import create_event

        self.event = create_event(
            user=self.user,
            title="Post Parent Event",
            slug="post-parent-event",
            start=timezone.now(),
        )

    def _get_identity_token(self):
        # Full pairing flow (kb-a4u.6): register → redeem → token exchange
        from syndication.test_api import _register_and_get_api_key

        api_key = _register_and_get_api_key(self.user)
        client = Client()
        ex = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex.content)["identity_token"]

    def test_create_post_for_event_returns_201(self):
        token = self._get_identity_token()
        client = Client()
        payload = {
            "headline": "Save the Date",
            "body": "Come join our amazing event.",
        }
        response = client.post(
            f"/api/events/{self.event.pk}/posts/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_create_post_scoped_to_event(self):
        """Post is created with correct FK to the event."""
        token = self._get_identity_token()
        client = Client()
        payload = {
            "headline": "FK Scoped Post",
            "body": "This post belongs to the event.",
        }
        client.post(
            f"/api/events/{self.event.pk}/posts/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertTrue(Post.objects.filter(event=self.event, headline="FK Scoped Post").exists())

    def test_list_posts_for_event_returns_200(self):
        token = self._get_identity_token()
        client = Client()
        response = client.get(
            f"/api/events/{self.event.pk}/posts/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# 7. Web UI form: Event creation via the web form
# ---------------------------------------------------------------------------


class EventWebFormTest(TestCase):
    """
    Web form POST to /syndication/events/new/ persists ALL ADR-016 D1 fields.

    This is the harness item: round-trip Event via web UI persisting all fields.
    Co-equal seam: the web form calls the same service layer as the API.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="form_user", email="form@test.com", password="x")
        self.profile = _make_profile(name="Form Profile", slug="form-profile", user=self.user)

    def test_event_create_form_get_returns_200(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/syndication/events/new/")
        self.assertEqual(response.status_code, 200)

    def test_event_create_form_post_creates_event(self):
        """POST to create form persists an Event in the DB."""
        client = Client()
        client.force_login(self.user)
        now = timezone.now()
        data = {
            "title": "Web Form Event",
            "slug": "web-form-event",
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "description": "Form description",
            "dress_code": "Smart casual",
            "content_warnings": '["nudity"]',
            "age_restriction": "18",
            "capacity": "100",
            "visibility": "public",
            "language": "en",
            "is_free": "false",
            "price_min_cents": "1500",
            "price_max_cents": "3000",
            "currency": "EUR",
        }
        response = client.post("/syndication/events/new/", data=data, follow=True)
        self.assertTrue(
            Event.objects.filter(slug="web-form-event").exists(),
            f"Event not created. Response status: {response.status_code}",
        )

    def test_event_create_form_post_persists_adr016_d1_fields(self):
        """
        Harness acceptance test: the Event created via the web form
        persists all ADR-016 D1 fields correctly.
        """
        client = Client()
        client.force_login(self.user)
        now = timezone.now()
        data = {
            "title": "Full Fields Web Event",
            "slug": "full-fields-web-event",
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "description": "Full description here",
            "dress_code": "Fetish attire required",
            "content_warnings": '["nudity", "bdsm"]',
            "age_restriction": "18",
            "capacity": "200",
            "visibility": "public",
            "language": "en",
            "is_free": "",  # falsy = not free
            "price_min_cents": "2000",
            "price_max_cents": "5000",
            "currency": "EUR",
            "price_description": "Early 20€ / Normal 50€",
            "external_url": "https://example.com/full-event",
            "tickets_url": "https://tickets.example.com/full-event",
        }
        client.post("/syndication/events/new/", data=data, follow=True)
        event = Event.objects.filter(slug="full-fields-web-event").first()
        self.assertIsNotNone(event, "Event was not created via web form")
        self.assertEqual(event.description, "Full description here")
        self.assertEqual(event.dress_code, "Fetish attire required")
        self.assertEqual(event.content_warnings, ["nudity", "bdsm"])
        self.assertEqual(event.age_restriction, 18)
        self.assertEqual(event.capacity, 200)
        self.assertEqual(event.visibility, "public")
        self.assertEqual(event.language, "en")
        self.assertEqual(event.price_min_cents, 2000)
        self.assertEqual(event.price_max_cents, 5000)
        self.assertEqual(event.price_description, "Early 20€ / Normal 50€")
        self.assertEqual(event.external_url, "https://example.com/full-event")
        self.assertEqual(event.tickets_url, "https://tickets.example.com/full-event")

    def test_event_create_form_post_redirects_to_hub(self):
        """After successful creation, redirect to the event hub page."""
        client = Client()
        client.force_login(self.user)
        now = timezone.now()
        data = {
            "title": "Redirect Event",
            "slug": "redirect-event",
            "start": now.strftime("%Y-%m-%dT%H:%M"),
        }
        response = client.post("/syndication/events/new/", data=data)
        self.assertEqual(response.status_code, 302, "Expected redirect after form POST")


# ---------------------------------------------------------------------------
# 8. Web UI form: Post creation via the web form
# ---------------------------------------------------------------------------


class PostWebFormTest(TestCase):
    """
    Web form POST to /syndication/events/{id}/posts/new/ creates a Post
    scoped to the Event.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="post_form_user", email="post_form@test.com", password="x")
        self.profile = _make_profile(name="Post Form Profile", slug="post-form-profile", user=self.user)
        from syndication.services import create_event

        self.event = create_event(
            user=self.user,
            title="Post Form Event",
            slug="post-form-event",
            start=timezone.now(),
        )

    def test_post_create_form_get_returns_200(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/posts/new/")
        self.assertEqual(response.status_code, 200)

    def test_post_create_form_post_creates_post(self):
        """POST to the post create form persists a Post scoped to the Event."""
        client = Client()
        client.force_login(self.user)
        data = {
            "headline": "Web Form Post",
            "body": "Come join the event!",
        }
        response = client.post(
            f"/syndication/events/{self.event.pk}/posts/new/",
            data=data,
            follow=True,
        )
        self.assertTrue(
            Post.objects.filter(event=self.event, headline="Web Form Post").exists(),
            f"Post not created. Response status: {response.status_code}",
        )

    def test_post_create_form_post_redirects_to_hub(self):
        """After creating a post, redirect back to the event hub."""
        client = Client()
        client.force_login(self.user)
        data = {
            "headline": "Redirect Post",
            "body": "Body.",
        }
        response = client.post(f"/syndication/events/{self.event.pk}/posts/new/", data=data)
        self.assertEqual(response.status_code, 302, "Expected redirect after post form POST")


# ---------------------------------------------------------------------------
# 9. Event hub page — HTMX fragments are independently addressable
# ---------------------------------------------------------------------------


class EventHubFragmentsTest(TestCase):
    """
    Event detail/edit page is an HTMX hub composed of independently-addressable
    django_cotton fragments (event_facts, event_posts, event_syndication).
    Each fragment has its own endpoint.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="hub_user", email="hub@test.com", password="x")
        self.profile = _make_profile(name="Hub Profile", slug="hub-profile", user=self.user)
        from syndication.services import create_event

        self.event = create_event(
            user=self.user,
            title="Hub Event",
            slug="hub-event",
            start=timezone.now(),
        )

    def test_event_hub_page_returns_200(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/")
        self.assertEqual(response.status_code, 200)

    def test_event_facts_fragment_returns_200(self):
        """event_facts fragment: /syndication/events/{id}/fragments/event_facts/"""
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/fragments/event_facts/")
        self.assertEqual(response.status_code, 200)

    def test_event_posts_fragment_returns_200(self):
        """event_posts fragment: /syndication/events/{id}/fragments/event_posts/"""
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/fragments/event_posts/")
        self.assertEqual(response.status_code, 200)

    def test_event_syndication_fragment_returns_200(self):
        """event_syndication fragment: /syndication/events/{id}/fragments/event_syndication/"""
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/fragments/event_syndication/")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# 10. PlatformConnection management UI
# ---------------------------------------------------------------------------


class PlatformConnectionUITest(TestCase):
    """
    PlatformConnection management: list connections, create connection, toggle enabled.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="conn_user", email="conn@test.com", password="x")
        self.profile = _make_profile(name="Conn Profile", slug="conn-profile", user=self.user)

    def test_connections_list_returns_200(self):
        client = Client()
        client.force_login(self.user)
        response = client.get("/syndication/connections/")
        self.assertEqual(response.status_code, 200)

    def test_create_connection_returns_201_or_redirect(self):
        """POST to connections create creates a PlatformConnection.

        kinds is now a MultipleChoiceField rendered as checkboxes — POST data
        uses repeated keys (one per checked value), not a JSON string.
        """
        client = Client()
        client.force_login(self.user)
        data = {
            "platform": "telegram",
            "destination_id": "my-channel-123",
            "kinds": "promotion",  # checkbox value; Django test client handles repeated keys via lists
            "enabled": "on",
        }
        response = client.post("/syndication/connections/new/", data=data)
        self.assertIn(
            response.status_code,
            [201, 302],
            f"Expected 201 or 302, got {response.status_code}",
        )
        conn = PlatformConnection.objects.filter(organizer=self.profile, platform="telegram").first()
        self.assertIsNotNone(conn, "PlatformConnection was not created")
        self.assertEqual(conn.kinds, ["promotion"], f"kinds should be ['promotion'], got {conn.kinds!r}")

    def test_toggle_connection_enabled(self):
        """POST to toggle endpoint flips the enabled flag."""
        conn = _make_connection(self.profile, platform="switch", destination_id="own-page", enabled=True)
        client = Client()
        client.force_login(self.user)
        response = client.post(f"/syndication/connections/{conn.pk}/toggle/")
        self.assertIn(response.status_code, [200, 302])
        conn.refresh_from_db()
        self.assertFalse(conn.enabled)


# ---------------------------------------------------------------------------
# 11. Event edit page — Finding 1+2: broken edit page fix
# ---------------------------------------------------------------------------


class EventEditPageTest(TestCase):
    """
    GET /syndication/events/{id}/edit/ returns 200 and renders form pre-populated.
    POST to edit page persists changes and round-trips all fields including
    registration_required/url/email (finding 9 — silent data loss).

    Finding 1+2: event_edit.html included syndication/_event_form_fields.html
    which did not exist → TemplateDoesNotExist (500). Verify the fix works.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="edit_user", email="edit@test.com", password="x")
        self.profile = _make_profile(name="Edit Profile", slug="edit-profile", user=self.user)
        from syndication.services import create_event

        now = timezone.now()
        self.event = create_event(
            user=self.user,
            title="Editable Event",
            slug="editable-event",
            start=now,
            end=now,
            description="Original description",
            dress_code="Smart casual",
            content_warnings=["nudity"],
            age_restriction=18,
            capacity=50,
            visibility="public",
            language="en",
            registration_required=True,
            registration_url="https://reg.example.com/",
            registration_email="reg@example.com",
        )

    def test_event_edit_get_returns_200(self):
        """GET on event edit page must return 200 (not 500 TemplateDoesNotExist)."""
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/edit/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_event_edit_get_prepopulates_title(self):
        """Edit form GET renders with the current title pre-filled."""
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/edit/")
        self.assertContains(response, "Editable Event")

    def test_event_edit_get_prepopulates_registration_email(self):
        """
        Edit form GET includes registration_email in the rendered form.
        (finding 9: missing from initial dict → email wiped on edit-load)
        """
        client = Client()
        client.force_login(self.user)
        response = client.get(f"/syndication/events/{self.event.pk}/edit/")
        self.assertContains(response, "reg@example.com")

    def test_event_edit_post_persists_changed_title(self):
        """POST to edit page with a new title persists the change."""
        client = Client()
        client.force_login(self.user)
        now = self.event.start
        data = {
            "title": "Edited Title",
            "slug": self.event.slug,
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "description": "Original description",
            "content_warnings": "[]",
        }
        response = client.post(f"/syndication/events/{self.event.pk}/edit/", data=data)
        self.assertIn(response.status_code, [302, 200])
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "Edited Title")

    def test_event_edit_post_roundtrips_registration_fields(self):
        """
        POST to edit page preserves registration_required/url/email.
        Proves finding 9 (ADR-008 D3 silent data-loss) is fixed.
        """
        client = Client()
        client.force_login(self.user)
        now = self.event.start
        data = {
            "title": self.event.title,
            "slug": self.event.slug,
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "description": "Updated description",
            "content_warnings": '["nudity"]',
            "registration_required": "on",
            "registration_url": "https://reg.example.com/",
            "registration_email": "reg@example.com",
        }
        response = client.post(f"/syndication/events/{self.event.pk}/edit/", data=data)
        self.assertIn(response.status_code, [302, 200])
        self.event.refresh_from_db()
        self.assertTrue(self.event.registration_required)
        self.assertEqual(self.event.registration_url, "https://reg.example.com/")
        self.assertEqual(self.event.registration_email, "reg@example.com")

    def test_event_edit_unauthorized_user_gets_403(self):
        """Non-organizer cannot edit the event (must get 403, not 200 or 500)."""
        stranger = _make_vouched_user(username="edit_stranger", email="edit_stranger@test.com", password="x")
        client = Client()
        client.force_login(stranger)
        response = client.get(f"/syndication/events/{self.event.pk}/edit/")
        self.assertEqual(response.status_code, 403)


# ---------------------------------------------------------------------------
# 12. PermissionError → 403 (Finding 5)
# ---------------------------------------------------------------------------


class PermissionErrorTo403Test(TestCase):
    """
    Finding 5: events_update and event_posts_create raise PermissionError when
    the caller is not an organizer. Without an exception handler, Ninja returns
    500. Verify the handler maps PermissionError → 403 JSON.
    """

    def setUp(self):
        self.owner = _make_vouched_user(username="perm_owner", email="perm_owner@test.com", password="x")
        self.owner_profile = _make_profile(name="Perm Owner Profile", slug="perm-owner-profile", user=self.owner)
        self.stranger = _make_vouched_user(username="perm_stranger", email="perm_stranger@test.com", password="x")
        self.stranger_profile = _make_profile(
            name="Perm Stranger Profile", slug="perm-stranger-profile", user=self.stranger
        )
        from syndication.services import create_event

        self.event = create_event(
            user=self.owner,
            title="Protected Event",
            slug="protected-event",
            start=timezone.now(),
        )

    def _get_identity_token_for(self, user):
        # Full pairing flow (kb-a4u.6): register → redeem → token exchange
        from syndication.test_api import _register_and_get_api_key

        api_key = _register_and_get_api_key(user)
        client = Client()
        ex = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex.content)["identity_token"]

    def test_patch_event_by_non_owner_returns_403_not_500(self):
        """
        A vouched user who is not an organizer of the event gets 403 on PATCH,
        not 500 (uncaught PermissionError).
        """
        token = self._get_identity_token_for(self.stranger)
        client = Client()
        response = client.patch(
            f"/api/events/{self.event.pk}/",
            data=json.dumps({"title": "Hacked Title"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_post_create_by_non_owner_returns_403_not_500(self):
        """
        A vouched user who is not an organizer gets 403 on POST /events/{id}/posts/,
        not 500 (uncaught PermissionError).
        """
        token = self._get_identity_token_for(self.stranger)
        client = Client()
        response = client.post(
            f"/api/events/{self.event.pk}/posts/",
            data=json.dumps({"headline": "Hack", "body": "Hack body"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403, response.content)

    def test_403_body_is_generic_does_not_leak_user_or_event(self):
        """
        Fix C (security — information disclosure): the 403 response body must be
        a constant generic string. It must NOT contain the user repr or event title
        (which would be present if str(exc) were returned to the caller).

        services.py raises: PermissionError(f"User {user} cannot edit event '{event}' …")
        The handler must swallow str(exc) server-side (log it) and return only
        {"detail": "Permission denied."} to the caller.
        """
        token = self._get_identity_token_for(self.stranger)
        client = Client()
        response = client.patch(
            f"/api/events/{self.event.pk}/",
            data=json.dumps({"title": "Hacked Title"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 403, response.content)
        body = json.loads(response.content)
        # Body must be the constant generic string — not the exception message.
        self.assertEqual(body["detail"], "Permission denied.")
        # Ensure the user's string representation and event title are not leaked.
        body_str = response.content.decode()
        self.assertNotIn(str(self.stranger), body_str, "Response leaks user repr")
        self.assertNotIn("Protected Event", body_str, "Response leaks event title")
        self.assertNotIn("cannot edit", body_str, "Response leaks exception message")


# ---------------------------------------------------------------------------
# 13. API round-trip: start, end, slug, registration fields in EventOut
# ---------------------------------------------------------------------------


class EventAPIRoundTripTest(TestCase):
    """
    Finding 6+7: EventOut and response dicts omit start, end, slug,
    registration_* fields → an agent cannot read back what it wrote.

    Verify create→read-back round-trips the full v0 field set.
    """

    def setUp(self):
        self.user = _make_vouched_user(username="roundtrip_user", email="roundtrip@test.com", password="x")
        self.profile = _make_profile(name="Roundtrip Profile", slug="roundtrip-profile", user=self.user)

    def _get_identity_token(self):
        # Full pairing flow (kb-a4u.6): register → redeem → token exchange
        from syndication.test_api import _register_and_get_api_key

        api_key = _register_and_get_api_key(self.user)
        client = Client()
        ex = client.post(
            "/api/agents/token",
            data=json.dumps({"api_key": api_key}),
            content_type="application/json",
        )
        return json.loads(ex.content)["identity_token"]

    def test_api_create_returns_start_and_end(self):
        """POST /api/events/ response round-trips start and end values (finding 6)."""
        token = self._get_identity_token()
        client = Client()
        now = timezone.now()
        # Use a fixed datetime string to avoid sub-millisecond drift in comparisons.
        # Replace microseconds so isoformat is stable across serialisers.
        fixed_now = now.replace(microsecond=0)
        start_iso = fixed_now.isoformat()
        end_iso = fixed_now.isoformat()
        payload = {
            "title": "Roundtrip Event",
            "slug": "roundtrip-event",
            "start": start_iso,
            "end": end_iso,
        }
        response = client.post(
            "/api/events/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = json.loads(response.content)
        self.assertIn("start", data, "Response missing 'start' field")
        self.assertIn("end", data, "Response missing 'end' field")
        self.assertIn("slug", data, "Response missing 'slug' field")
        # Round-trip equality: returned values must match what was sent.
        # A serialize-as-null bug (or lossy serialization) would fail here.
        from django.utils.dateparse import parse_datetime

        returned_start = parse_datetime(data["start"])
        returned_end = parse_datetime(data["end"])
        self.assertIsNotNone(returned_start, f"start field is not a parseable datetime: {data['start']!r}")
        self.assertIsNotNone(returned_end, f"end field is not a parseable datetime: {data['end']!r}")
        self.assertEqual(
            returned_start.replace(tzinfo=None),
            fixed_now.replace(tzinfo=None),
            "Returned start does not match sent start value",
        )
        self.assertEqual(
            returned_end.replace(tzinfo=None),
            fixed_now.replace(tzinfo=None),
            "Returned end does not match sent end value",
        )

    def test_api_create_returns_registration_fields(self):
        """POST /api/events/ response includes registration_* fields (finding 7)."""
        token = self._get_identity_token()
        client = Client()
        now = timezone.now()
        payload = {
            "title": "Reg Roundtrip Event",
            "slug": "reg-roundtrip-event",
            "start": now.isoformat(),
            "registration_required": True,
            "registration_url": "https://reg.example.com/",
            "registration_email": "reg@example.com",
        }
        response = client.post(
            "/api/events/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = json.loads(response.content)
        self.assertIn("registration_required", data)
        self.assertIn("registration_url", data)
        self.assertIn("registration_email", data)
        self.assertTrue(data["registration_required"])
        self.assertEqual(data["registration_email"], "reg@example.com")

    def test_api_update_accepts_start_and_slug(self):
        """PATCH /api/events/{id}/ accepts start, end, slug (finding 4 — EventUpdateIn parity)."""
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Update Parity Event",
            slug="update-parity-event",
            start=timezone.now(),
        )
        token = self._get_identity_token()
        client = Client()
        new_slug = "update-parity-event-v2"
        response = client.patch(
            f"/api/events/{event.pk}/",
            data=json.dumps({"slug": new_slug}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        event.refresh_from_db()
        self.assertEqual(event.slug, new_slug)

    def test_api_update_accepts_registration_fields(self):
        """PATCH /api/events/{id}/ accepts registration_* fields (finding 4)."""
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Reg Update Event",
            slug="reg-update-event",
            start=timezone.now(),
        )
        token = self._get_identity_token()
        client = Client()
        response = client.patch(
            f"/api/events/{event.pk}/",
            data=json.dumps(
                {
                    "registration_required": True,
                    "registration_url": "https://reg2.example.com/",
                    "registration_email": "reg2@example.com",
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        event.refresh_from_db()
        self.assertTrue(event.registration_required)
        self.assertEqual(event.registration_email, "reg2@example.com")


# ---------------------------------------------------------------------------
# 14. authz seam bypass fix (Finding 8)
# ---------------------------------------------------------------------------


class AuthzSeamBypassTest(TestCase):
    """
    Finding 8: views.py:222 post_create HTMX response hardcodes can_edit=True.
    Verify that the HTMX response routes through can_edit(user, event) instead.
    """

    def setUp(self):
        self.owner = _make_vouched_user(username="seam_owner", email="seam_owner@test.com", password="x")
        self.owner_profile = _make_profile(name="Seam Owner Profile", slug="seam-owner-profile", user=self.owner)
        from syndication.services import create_event

        self.event = create_event(
            user=self.owner,
            title="Seam Test Event",
            slug="seam-test-event",
            start=timezone.now(),
        )

    def test_htmx_post_create_response_uses_can_edit_seam(self):
        """
        The HTMX event_posts fragment returned after post_create must evaluate
        can_edit via the authz seam, not hardcode True.

        Falsification strategy: we patch syndication.views.can_edit to return True
        on the first call (the guard check at view entry) and False on the second
        call (the context assignment in the HTMX branch). The real code passes
        can_edit(request.user, event) as the context value, so the context will
        reflect False. If views.py hardcoded True instead of calling can_edit,
        the context would be True and this test fails.
        """
        from unittest.mock import patch

        client = Client()
        client.force_login(self.owner)
        data = {
            "headline": "Seam Post",
            "body": "Seam body.",
        }

        call_results = iter([True, False])  # guard → True, context call → False

        with patch("syndication.views.can_edit", side_effect=lambda u, e: next(call_results)):
            response = client.post(
                f"/syndication/events/{self.event.pk}/posts/new/",
                data=data,
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertContains(response, "Seam Post")
        # This is the key falsifying assertion: context["can_edit"] must be the
        # return value of the second can_edit() call (False), not a hardcoded True.
        self.assertIs(response.context["can_edit"], False)


# ---------------------------------------------------------------------------
# 15. Service-level round-trip for ALL v0 fields (fixing docstring mismatch)
# ---------------------------------------------------------------------------


class CreateEventServiceAllFieldsTest(TestCase):
    """
    Service-layer round-trip tests for v0 fields: registration_required/url/email,
    tags (M2M), and venue (FK).

    Docstring alignment: the class tests what it says — all three field groups
    are covered here (registration, tags M2M, venue FK).
    """

    def setUp(self):
        self.user = _make_vouched_user(username="full_fields_user2", email="full_fields2@test.com", password="x")
        self.profile = _make_profile(name="Full Fields Profile 2", slug="full-fields-profile-2", user=self.user)

    def test_create_event_persists_registration_required(self):
        """registration_required round-trips through the service layer."""
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="Reg Required Event",
            slug="reg-required-event",
            start=timezone.now(),
            registration_required=True,
            registration_url="https://reg.example.com/",
            registration_email="reg@example.com",
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertTrue(fetched.registration_required)
        self.assertEqual(fetched.registration_url, "https://reg.example.com/")
        self.assertEqual(fetched.registration_email, "reg@example.com")

    def test_create_event_persists_tags_m2m(self):
        """tags M2M round-trips through create_event → Event.tags.set()."""
        from events.models import Tag
        from syndication.services import create_event

        tag1 = Tag.objects.create(label="Kink Test Tag 1", slug="kink-test-tag-1", kind="theme")
        tag2 = Tag.objects.create(label="Kink Test Tag 2", slug="kink-test-tag-2", kind="theme")
        event = create_event(
            user=self.user,
            title="Tagged Event",
            slug="tagged-event",
            start=timezone.now(),
            tags=[tag1, tag2],
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertSetEqual(
            set(fetched.tags.values_list("pk", flat=True)),
            {tag1.pk, tag2.pk},
            "Event.tags must contain exactly the supplied Tag PKs after create_event.",
        )

    def test_create_event_persists_venue_fk(self):
        """venue FK round-trips through create_event → Event.venue."""
        from syndication.services import create_event
        from venues.models import Venue

        venue = Venue.objects.create(name="Test Venue", slug="test-venue-roundtrip")
        event = create_event(
            user=self.user,
            title="Venued Event",
            slug="venued-event",
            start=timezone.now(),
            venue=venue,
        )
        fetched = Event.objects.get(pk=event.pk)
        self.assertEqual(
            fetched.venue_id,
            venue.pk,
            "Event.venue must be the supplied Venue after create_event.",
        )
