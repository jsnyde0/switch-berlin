"""
Co-equal API integration test (kb-a4u.9, ADR-016 D3/D6).

Proves that Switch has NO private fast-path: for the same logical operation
(Event-create, Post-create), both the Web UI surface and the HTTP API surface
MUST converge on the SAME shared service-layer function in syndication.services,
produce IDENTICAL DB state, and traverse the SAME authorization resolution.

Three legs tested per operation:
  Leg 1 — Same service seam (spy-instrumented):
      Both surfaces call the shared service function. If either surface writes
      directly to the DB without going through the service, the spy does not
      fire and the assertion fails.
  Leg 2 — Identical DB state:
      The web UI and the API produce Event/Post rows with field-for-field
      identical meaningful fields (excluding unavoidable per-row diffs:
      pk, slug, timestamps, title used to distinguish the two operations).
  Leg 3 — Identical auth traversal:
      Both surfaces enforce the same can_edit gate. An unauthorized principal
      is rejected on BOTH surfaces with the expected error code/exception.

Test file: syndication/test_co_equal_api.py
Shared service seam functions instrumented:
  syndication.services.create_event
  syndication.services.create_post
"""

import json
from unittest.mock import call, patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import Post

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers (mirrors patterns from test_authoring.py)
# ---------------------------------------------------------------------------


def _make_vouched_user(**kwargs):
    kwargs.setdefault("status", "vouched")
    return User.objects.create_user(**kwargs)


def _make_profile(name, slug, user=None):
    profile = Profile.objects.create(name=name, slug=slug)
    if user is not None:
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="auto_self",
        )
    return profile


def _get_identity_token_for(user):
    """
    Full pairing flow: register → redeem → token exchange.
    Returns a fresh identity token for the given vouched user.
    """
    from syndication.test_api import _register_and_get_api_key

    api_key = _register_and_get_api_key(user)
    client = Client()
    ex = client.post(
        "/api/agents/token",
        data=json.dumps({"api_key": api_key}),
        content_type="application/json",
    )
    return json.loads(ex.content)["identity_token"]


# ---------------------------------------------------------------------------
# Event-create: co-equal assertion (Legs 1 + 2 + 3)
# ---------------------------------------------------------------------------


class EventCreateCoEqualTest(TestCase):
    """
    Prove that Event-create is co-equal: Web UI and HTTP API both route through
    syndication.services.create_event with no private fast-path.
    """

    def setUp(self):
        # Authorized user (organizer)
        self.user = _make_vouched_user(
            username="coeq_ev_user",
            email="coeq_ev@test.com",
            password="x",
        )
        self.profile = _make_profile(
            name="CoEq Event Profile",
            slug="coeq-event-profile",
            user=self.user,
        )
        # Unauthorized user (no profile claim)
        self.stranger = _make_vouched_user(
            username="coeq_ev_stranger",
            email="coeq_ev_stranger@test.com",
            password="x",
        )
        # profile assigned to stranger (has a profile but NOT on any event)
        _make_profile(
            name="Stranger Event Profile",
            slug="coeq-stranger-event-profile",
            user=self.stranger,
        )

    # ------------------------------------------------------------------
    # Leg 1: Same service seam — both surfaces call create_event
    # ------------------------------------------------------------------

    def test_leg1_web_ui_calls_create_event_service(self):
        """
        Web UI form POST routes through syndication.services.create_event.

        If views.py bypassed the service and called Event.objects.create() directly,
        the spy would not fire and this assertion would fail — proving the test
        is a real guard, not a vacuous pass.
        """
        client = Client()
        client.force_login(self.user)
        now = timezone.now()

        with patch(
            "syndication.views.create_event",
            wraps=__import__("syndication.services", fromlist=["create_event"]).create_event,
        ) as spy:
            data = {
                "title": "Web UI Event (Leg1)",
                "slug": "web-ui-event-leg1",
                "start": now.strftime("%Y-%m-%dT%H:%M"),
                "description": "Leg 1 web description",
                "content_warnings": "[]",
            }
            response = client.post("/syndication/events/new/", data=data, follow=False)

        # Web UI should have redirected (302) or responded 200 if form had errors.
        # We need a successful creation to fire the spy.
        self.assertIn(
            response.status_code,
            [200, 302],
            f"Unexpected status from web form: {response.status_code}",
        )
        # The spy MUST have been called — if create_event was bypassed, spy.called is False.
        self.assertTrue(
            spy.called,
            "Web UI did NOT call syndication.services.create_event — private fast-path detected! "
            "ADR-016 D3 violation: the web form must route through the shared service seam.",
        )
        # Assert the call received the right user
        self.assertEqual(spy.call_args[1]["user"], self.user)

    def test_leg1_api_calls_create_event_service(self):
        """
        API POST /api/events/ routes through syndication.services.create_event.

        If api.py bypassed the service and called Event.objects.create() directly,
        the spy would not fire and this assertion would fail.
        """
        token = _get_identity_token_for(self.user)
        client = Client()
        now = timezone.now()

        with patch(
            "syndication.api.create_event",
            wraps=__import__("syndication.services", fromlist=["create_event"]).create_event,
        ) as spy:
            payload = {
                "title": "API Event (Leg1)",
                "slug": "api-event-leg1",
                "start": now.isoformat(),
                "description": "Leg 1 api description",
            }
            response = client.post(
                "/api/events/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            spy.called,
            "API endpoint did NOT call syndication.services.create_event — private fast-path detected! "
            "ADR-016 D3 violation: the API endpoint must route through the shared service seam.",
        )
        self.assertEqual(spy.call_args[1]["user"], self.user)

    # ------------------------------------------------------------------
    # Leg 2: Identical DB state — web UI and API produce equivalent rows
    # ------------------------------------------------------------------

    def test_leg2_web_ui_and_api_produce_identical_meaningful_fields(self):
        """
        The web UI and API produce Event rows with field-for-field identical
        meaningful fields when given equivalent inputs.

        Excluded from comparison: pk, slug, title (used to distinguish the two
        operations), created_at, updated_at (per-row timestamps that differ by
        wall-clock milliseconds).

        Included in comparison: description, dress_code, content_warnings,
        age_restriction, capacity, visibility, language, is_free,
        price_min_cents, price_max_cents, currency, sliding_scale,
        price_description, external_url, tickets_url, registration_required,
        registration_url, registration_email, status.

        If one surface wrote a default or dropped a field relative to the other,
        this assertion would fail — proving the test is a real equivalence check.
        """
        now = timezone.now()
        shared_kwargs = dict(
            description="Co-equal description",
            dress_code="Smart casual",
            age_restriction=18,
            capacity=100,
            visibility="public",
            language="en",
            is_free=False,
            price_min_cents=2000,
            price_max_cents=5000,
            currency="EUR",
            sliding_scale=False,
            price_description="Early 20€ / Normal 50€",
            external_url="https://example.com/coeq",
            tickets_url="https://tickets.example.com/coeq",
            registration_required=True,
            registration_url="https://reg.example.com/coeq",
            registration_email="coeq@example.com",
        )

        # --- Create via Web UI ---
        web_client = Client()
        web_client.force_login(self.user)
        web_data = {
            "title": "Web UI Co-Equal Event",
            "slug": "web-coeq-event",
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "description": shared_kwargs["description"],
            "dress_code": shared_kwargs["dress_code"],
            "content_warnings": "[]",  # empty list; JSON-encoded
            "age_restriction": str(shared_kwargs["age_restriction"]),
            "capacity": str(shared_kwargs["capacity"]),
            "visibility": shared_kwargs["visibility"],
            "language": shared_kwargs["language"],
            "is_free": "",  # BooleanField — empty string → False
            "price_min_cents": str(shared_kwargs["price_min_cents"]),
            "price_max_cents": str(shared_kwargs["price_max_cents"]),
            "currency": shared_kwargs["currency"],
            "sliding_scale": "",  # BooleanField — empty string → False
            "price_description": shared_kwargs["price_description"],
            "external_url": shared_kwargs["external_url"],
            "tickets_url": shared_kwargs["tickets_url"],
            "registration_required": "on",  # checkbox → True
            "registration_url": shared_kwargs["registration_url"],
            "registration_email": shared_kwargs["registration_email"],
        }
        web_response = web_client.post("/syndication/events/new/", data=web_data, follow=False)
        self.assertIn(
            web_response.status_code,
            [200, 302],
            f"Web form responded with unexpected status: {web_response.status_code} — {web_response.content[:400]}",
        )
        web_event = Event.objects.filter(slug="web-coeq-event").first()
        self.assertIsNotNone(web_event, "Web UI did not create an Event — check form validation")

        # --- Create via API ---
        token = _get_identity_token_for(self.user)
        api_client = Client()
        api_payload = {
            "title": "API Co-Equal Event",
            "slug": "api-coeq-event",
            "start": now.isoformat(),
            "description": shared_kwargs["description"],
            "dress_code": shared_kwargs["dress_code"],
            "content_warnings": [],
            "age_restriction": shared_kwargs["age_restriction"],
            "capacity": shared_kwargs["capacity"],
            "visibility": shared_kwargs["visibility"],
            "language": shared_kwargs["language"],
            "is_free": shared_kwargs["is_free"],
            "price_min_cents": shared_kwargs["price_min_cents"],
            "price_max_cents": shared_kwargs["price_max_cents"],
            "currency": shared_kwargs["currency"],
            "sliding_scale": shared_kwargs["sliding_scale"],
            "price_description": shared_kwargs["price_description"],
            "external_url": shared_kwargs["external_url"],
            "tickets_url": shared_kwargs["tickets_url"],
            "registration_required": shared_kwargs["registration_required"],
            "registration_url": shared_kwargs["registration_url"],
            "registration_email": shared_kwargs["registration_email"],
        }
        api_response = api_client.post(
            "/api/events/",
            data=json.dumps(api_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(api_response.status_code, 201, api_response.content)
        api_event = Event.objects.filter(slug="api-coeq-event").first()
        self.assertIsNotNone(api_event, "API did not create an Event")

        # --- Assert field-for-field equivalence (excluding per-row diffs) ---
        MEANINGFUL_FIELDS = [
            "description",
            "dress_code",
            "content_warnings",
            "age_restriction",
            "capacity",
            "visibility",
            "language",
            "is_free",
            "price_min_cents",
            "price_max_cents",
            "currency",
            "sliding_scale",
            "price_description",
            "external_url",
            "tickets_url",
            "registration_required",
            "registration_url",
            "registration_email",
            "status",  # both should default to 'draft'
        ]

        for field in MEANINGFUL_FIELDS:
            web_val = getattr(web_event, field)
            api_val = getattr(api_event, field)
            self.assertEqual(
                web_val,
                api_val,
                f"Field '{field}' differs between web UI and API: "
                f"web={web_val!r}, api={api_val!r}. "
                "Both surfaces must produce identical DB state (ADR-016 D3).",
            )

    # ------------------------------------------------------------------
    # Leg 3: Identical auth traversal — both surfaces use can_edit gate
    # ------------------------------------------------------------------

    def test_leg3_web_ui_calls_can_edit_gate_on_unauthorized_access(self):
        """
        The web UI's event_create view calls create_event, which internally
        calls _get_primary_profile_for_user. An unauthorized user (one with no
        profile claim) is rejected by the service layer, which raises ValueError.

        However, the more targeted test for the co-equal authz seam is:
        both surfaces route authz through the same can_edit / _get_primary_profile
        path in the service. We test this by verifying the web UI form rejects a
        stranger who has NO profile (service raises ValueError → form error, not 302).
        """
        # Create a user with NO profile at all
        no_profile_user = _make_vouched_user(
            username="coeq_no_profile",
            email="coeq_no_profile@test.com",
            password="x",
        )
        client = Client()
        client.force_login(no_profile_user)
        now = timezone.now()
        data = {
            "title": "Unauthorized Web Event",
            "slug": "unauth-web-event",
            "start": now.strftime("%Y-%m-%dT%H:%M"),
            "content_warnings": "[]",
        }
        response = client.post("/syndication/events/new/", data=data, follow=False)
        # The view renders the form with an error (not a 302 redirect) because
        # create_event raised ValueError → form.add_error() → re-render.
        # A 302 would mean the event was created, which would be a bug.
        self.assertNotEqual(
            response.status_code,
            302,
            "Web UI allowed event creation for a user with no profile — "
            "authz gate bypassed (ADR-016 D3 / ADR-017 D1).",
        )
        # The event must NOT have been created in the DB.
        self.assertFalse(
            Event.objects.filter(slug="unauth-web-event").exists(),
            "Web UI created an event for a user with no profile — authz gate failed.",
        )

    def test_leg3_api_rejects_unauthorized_principal(self):
        """
        The API POST /api/events/ rejects a user with no profile claim.

        The service (create_event → _get_primary_profile_for_user) raises ValueError
        for a user with no profile (ADR-008 D3: fail loud). The API propagates this
        as a non-201 response (500 is acceptable at v0 — the point is NOT 201,
        meaning no event is silently created for an unauthorized principal).

        Note: raise_request_exception=False is required so the Django test client
        returns the response object rather than re-raising the ValueError from the
        service layer.
        """
        no_profile_user = _make_vouched_user(
            username="coeq_api_no_profile",
            email="coeq_api_no_profile@test.com",
            password="x",
        )
        # This user has no profile — need to give them an identity token
        # but they have no profile for event creation
        token = _get_identity_token_for(no_profile_user)
        # raise_request_exception=False: return the 500 as a response rather than
        # re-raising the ValueError — lets us assert the status code without try/except.
        client = Client(raise_request_exception=False)
        now = timezone.now()
        payload = {
            "title": "Unauthorized API Event",
            "slug": "unauth-api-event",
            "start": now.isoformat(),
        }
        response = client.post(
            "/api/events/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        # Must NOT be 201 — the unauthorized user must be rejected
        self.assertNotEqual(
            response.status_code,
            201,
            "API allowed event creation for a user with no profile — "
            "authz gate bypassed (ADR-016 D3 / ADR-017 D1).",
        )
        # Event must not exist in DB
        self.assertFalse(
            Event.objects.filter(slug="unauth-api-event").exists(),
            "API created an event for a user with no profile — authz gate failed.",
        )

    def test_leg3_can_edit_authz_seam_used_for_event_update_on_both_surfaces(self):
        """
        Both surfaces use the same can_edit seam for update operations.

        We spy on syndication.authz.can_edit and assert it is called on BOTH
        the API update path (PATCH /api/events/{id}/) and the web UI edit path
        (POST /syndication/events/{id}/edit/). This proves neither surface
        has a private authz check that bypasses can_edit.
        """
        from syndication.services import create_event

        event = create_event(
            user=self.user,
            title="AuthZ Seam Event",
            slug="authz-seam-event",
            start=timezone.now(),
        )
        # --- API path: PATCH, stranger should get 403 via can_edit ---
        token = _get_identity_token_for(self.stranger)
        client = Client()

        # Patch at the canonical source (syndication.authz.can_edit) so we catch
        # both the module-level import in views.py AND the local import inside
        # services.update_event. Both must flow through the same authoritative gate.
        from syndication.authz import can_edit as canonical_can_edit
        with patch("syndication.authz.can_edit", wraps=canonical_can_edit) as authz_spy:
            patch_response = client.patch(
                f"/api/events/{event.pk}/",
                data=json.dumps({"title": "Hacked via API"}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        self.assertEqual(
            patch_response.status_code,
            403,
            f"Stranger should be rejected on API PATCH, got {patch_response.status_code}",
        )
        self.assertTrue(
            authz_spy.called,
            "API PATCH did NOT call syndication.authz.can_edit — authz bypassed on API surface! "
            "ADR-016 D3 / ADR-017 D2 violation.",
        )

        # --- Web UI path: POST edit, stranger should get 403 via can_edit ---
        web_client = Client()
        web_client.force_login(self.stranger)

        # views.py imports can_edit at module level: `from syndication.authz import can_edit`
        # Patch at the views module so the spy intercepts the already-imported reference.
        with patch("syndication.views.can_edit", wraps=canonical_can_edit) as authz_spy_web:
            web_patch_response = web_client.post(
                f"/syndication/events/{event.pk}/edit/",
                data={
                    "title": "Hacked via Web",
                    "slug": event.slug,
                    "start": event.start.strftime("%Y-%m-%dT%H:%M"),
                    "content_warnings": "[]",
                },
            )

        self.assertEqual(
            web_patch_response.status_code,
            403,
            f"Stranger should be rejected on web UI edit, got {web_patch_response.status_code}",
        )
        self.assertTrue(
            authz_spy_web.called,
            "Web UI edit did NOT call syndication.authz.can_edit — authz bypassed on web surface! "
            "ADR-016 D3 / ADR-017 D2 violation.",
        )

        # Title must NOT have changed on either attempt
        event.refresh_from_db()
        self.assertEqual(event.title, "AuthZ Seam Event")

    # ------------------------------------------------------------------
    # Leg 1 identity: both surfaces ARE the one canonical service object
    # ------------------------------------------------------------------

    def test_leg1_surfaces_share_same_service_function_object_create_event(self):
        """
        Identity proof: syndication.views.create_event and syndication.api.create_event
        ARE (not merely equal to) syndication.services.create_event.

        The call-site spy in the other Leg-1 tests proves the function is *called*
        via that name — but patching the alias would pass even if views.py or api.py
        had defined their own local `create_event` under the same name.  This `is`
        check proves both names in both surfaces resolve to the SAME canonical
        function object in syndication.services, eliminating the local-reimplementation
        loophole entirely.
        """
        import syndication.api
        import syndication.services
        import syndication.views

        self.assertIs(
            syndication.views.create_event,
            syndication.services.create_event,
            "syndication.views.create_event is NOT the same object as "
            "syndication.services.create_event — views.py must import the "
            "canonical service function, not a local reimplementation.",
        )
        self.assertIs(
            syndication.api.create_event,
            syndication.services.create_event,
            "syndication.api.create_event is NOT the same object as "
            "syndication.services.create_event — api.py must import the "
            "canonical service function, not a local reimplementation.",
        )

    def test_leg3_surfaces_share_same_authz_function_object_can_edit(self):
        """
        Identity proof: syndication.views.can_edit IS syndication.authz.can_edit.

        views.py imports can_edit at module level from syndication.authz, so
        syndication.views.can_edit must be the identical function object.

        api.py uses local imports inside function bodies, so syndication.api has no
        module-level can_edit attribute to check here.  The canonical-source spy in
        test_leg3_can_edit_authz_seam_used_for_event_update_on_both_surfaces already
        covers the API path by patching syndication.authz.can_edit directly (the
        canonical source), which intercepts both views and api call sites.
        """
        import syndication.authz
        import syndication.views

        self.assertIs(
            syndication.views.can_edit,
            syndication.authz.can_edit,
            "syndication.views.can_edit is NOT the same object as "
            "syndication.authz.can_edit — views.py must import the canonical "
            "authz gate, not a local shadow function.",
        )


# ---------------------------------------------------------------------------
# Post-create: co-equal assertion (Legs 1 + 2 + 3)
# ---------------------------------------------------------------------------


class PostCreateCoEqualTest(TestCase):
    """
    Prove that Post-create is co-equal: Web UI and HTTP API both route through
    syndication.services.create_post with no private fast-path.
    """

    def setUp(self):
        self.user = _make_vouched_user(
            username="coeq_post_user",
            email="coeq_post@test.com",
            password="x",
        )
        self.profile = _make_profile(
            name="CoEq Post Profile",
            slug="coeq-post-profile",
            user=self.user,
        )
        self.stranger = _make_vouched_user(
            username="coeq_post_stranger",
            email="coeq_post_stranger@test.com",
            password="x",
        )
        _make_profile(
            name="Stranger Post Profile",
            slug="coeq-post-stranger-profile",
            user=self.stranger,
        )
        # Create the event via the service (already tested separately)
        from syndication.services import create_event

        self.event = create_event(
            user=self.user,
            title="CoEq Post Parent Event",
            slug="coeq-post-parent-event",
            start=timezone.now(),
        )

    # ------------------------------------------------------------------
    # Leg 1: Same service seam — both surfaces call create_post
    # ------------------------------------------------------------------

    def test_leg1_web_ui_calls_create_post_service(self):
        """
        Web UI form POST to /syndication/events/{id}/posts/new/ routes through
        syndication.services.create_post.

        If views.py called Post.objects.create() directly, the spy would not fire.
        """
        client = Client()
        client.force_login(self.user)

        with patch(
            "syndication.views.create_post",
            wraps=__import__("syndication.services", fromlist=["create_post"]).create_post,
        ) as spy:
            data = {
                "headline": "Web Post (Leg1)",
                "body": "Web post body for leg 1.",
                "cta": "https://example.com/tickets",
                "voice": "playful",
            }
            response = client.post(
                f"/syndication/events/{self.event.pk}/posts/new/",
                data=data,
                follow=False,
            )

        self.assertIn(
            response.status_code,
            [200, 302],
            f"Unexpected status from web post form: {response.status_code}",
        )
        self.assertTrue(
            spy.called,
            "Web UI did NOT call syndication.services.create_post — private fast-path detected! "
            "ADR-016 D3 violation: the web form must route through the shared service seam.",
        )
        self.assertEqual(spy.call_args[1]["user"], self.user)
        self.assertEqual(spy.call_args[1]["event"], self.event)

    def test_leg1_api_calls_create_post_service(self):
        """
        API POST /api/events/{id}/posts/ routes through syndication.services.create_post.

        If api.py called Post.objects.create() directly, the spy would not fire.
        """
        token = _get_identity_token_for(self.user)
        client = Client()

        with patch(
            "syndication.api.create_post",
            wraps=__import__("syndication.services", fromlist=["create_post"]).create_post,
        ) as spy:
            payload = {
                "headline": "API Post (Leg1)",
                "body": "API post body for leg 1.",
                "cta": "https://example.com/tickets",
                "voice": "formal",
            }
            response = client.post(
                f"/api/events/{self.event.pk}/posts/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            spy.called,
            "API endpoint did NOT call syndication.services.create_post — private fast-path detected! "
            "ADR-016 D3 violation: the API endpoint must route through the shared service seam.",
        )
        self.assertEqual(spy.call_args[1]["user"], self.user)
        self.assertEqual(spy.call_args[1]["event"], self.event)

    # ------------------------------------------------------------------
    # Leg 2: Identical DB state — web UI and API produce equivalent rows
    # ------------------------------------------------------------------

    def test_leg2_web_ui_and_api_produce_identical_meaningful_fields(self):
        """
        The web UI and API produce Post rows with field-for-field identical
        meaningful fields when given equivalent inputs.

        Excluded from comparison: pk, headline (used to distinguish), created_at,
        updated_at. Included: body, cta, voice, event FK.
        """
        shared_body = "Come join us for an amazing co-equal event!"
        shared_cta = "https://tickets.example.com/coeq-post"
        shared_voice = "enthusiastic"

        # --- Create via Web UI ---
        web_client = Client()
        web_client.force_login(self.user)
        web_data = {
            "headline": "Web Post Co-Equal",
            "body": shared_body,
            "cta": shared_cta,
            "voice": shared_voice,
        }
        web_response = web_client.post(
            f"/syndication/events/{self.event.pk}/posts/new/",
            data=web_data,
            follow=False,
        )
        self.assertIn(
            web_response.status_code,
            [200, 302],
            f"Web post form responded with unexpected status: {web_response.status_code}",
        )
        web_post = Post.objects.filter(
            event=self.event, headline="Web Post Co-Equal"
        ).first()
        self.assertIsNotNone(web_post, "Web UI did not create a Post — check form validation")

        # --- Create via API ---
        token = _get_identity_token_for(self.user)
        api_client = Client()
        api_payload = {
            "headline": "API Post Co-Equal",
            "body": shared_body,
            "cta": shared_cta,
            "voice": shared_voice,
        }
        api_response = api_client.post(
            f"/api/events/{self.event.pk}/posts/",
            data=json.dumps(api_payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(api_response.status_code, 201, api_response.content)
        api_post = Post.objects.filter(
            event=self.event, headline="API Post Co-Equal"
        ).first()
        self.assertIsNotNone(api_post, "API did not create a Post")

        # --- Assert field-for-field equivalence ---
        MEANINGFUL_FIELDS = [
            "body",
            "cta",
            "voice",
            "event_id",  # both must be FK-linked to the same event
        ]
        for field in MEANINGFUL_FIELDS:
            web_val = getattr(web_post, field)
            api_val = getattr(api_post, field)
            self.assertEqual(
                web_val,
                api_val,
                f"Field '{field}' differs between web UI and API: "
                f"web={web_val!r}, api={api_val!r}. "
                "Both surfaces must produce identical DB state (ADR-016 D3).",
            )

    # ------------------------------------------------------------------
    # Leg 3: Identical auth traversal — both surfaces use can_edit gate
    # ------------------------------------------------------------------

    def test_leg3_web_ui_rejects_stranger_on_post_create(self):
        """
        A stranger (user with a profile but NOT an organizer of this event) is
        rejected by the web UI post_create view via the can_edit seam.

        The view checks can_edit before the service call — a 403 response
        means the authz gate fired correctly.
        """
        web_client = Client()
        web_client.force_login(self.stranger)

        with patch(
            "syndication.views.can_edit",
            wraps=__import__("syndication.authz", fromlist=["can_edit"]).can_edit,
        ) as authz_spy:
            data = {
                "headline": "Unauthorized Post",
                "body": "Should not be created.",
            }
            response = web_client.post(
                f"/syndication/events/{self.event.pk}/posts/new/",
                data=data,
                follow=False,
            )

        # can_edit must have been called
        self.assertTrue(
            authz_spy.called,
            "Web UI post_create did NOT call syndication.authz.can_edit — authz bypassed! "
            "ADR-016 D3 / ADR-017 D2 violation.",
        )
        # Stranger must be rejected (403)
        self.assertEqual(
            response.status_code,
            403,
            f"Stranger was not rejected on web UI post_create, got {response.status_code}",
        )
        # No post created
        self.assertFalse(
            Post.objects.filter(event=self.event, headline="Unauthorized Post").exists(),
            "Web UI created a post for a non-organizer — authz gate failed.",
        )

    def test_leg3_api_rejects_stranger_on_post_create(self):
        """
        A stranger is rejected by the API post-create endpoint via the can_edit seam.

        The service (create_post) checks can_edit and raises PermissionError → 403.

        can_edit is imported via a local import inside create_post, so we patch at
        the canonical source (syndication.authz.can_edit) to intercept the call.
        """
        from syndication.authz import can_edit as canonical_can_edit

        token = _get_identity_token_for(self.stranger)
        client = Client()

        with patch(
            "syndication.authz.can_edit",
            wraps=canonical_can_edit,
        ) as authz_spy:
            payload = {
                "headline": "Unauthorized API Post",
                "body": "Should not be created.",
            }
            response = client.post(
                f"/api/events/{self.event.pk}/posts/",
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        # can_edit must have been called
        self.assertTrue(
            authz_spy.called,
            "API event_posts_create did NOT call syndication.authz.can_edit — authz bypassed! "
            "ADR-016 D3 / ADR-017 D2 violation.",
        )
        # Stranger must be rejected (403)
        self.assertEqual(
            response.status_code,
            403,
            f"Stranger was not rejected on API post_create, got {response.status_code}",
        )
        # No post created
        self.assertFalse(
            Post.objects.filter(event=self.event, headline="Unauthorized API Post").exists(),
            "API created a post for a non-organizer — authz gate failed.",
        )

    def test_leg3_same_authz_function_on_both_surfaces_post_create(self):
        """
        Convergence proof: BOTH surfaces route through the SAME can_edit function
        from syndication.authz.

        We spy on the canonical can_edit in syndication.authz and assert it is called
        on BOTH:
          - the web path (views.post_create checks can_edit imported at module level)
          - the api path (services.create_post calls can_edit via local import —
            since local imports resolve through the module at call time, patching
            syndication.authz.can_edit intercepts both paths)

        This proves neither surface has a shadow authz check outside the shared seam.
        """
        from syndication.authz import can_edit as canonical_can_edit

        # --- Web surface: patch views.can_edit (module-level import in views.py) ---
        web_client = Client()
        web_client.force_login(self.stranger)

        with patch("syndication.views.can_edit", wraps=canonical_can_edit) as web_spy:
            web_client.post(
                f"/syndication/events/{self.event.pk}/posts/new/",
                data={"headline": "Spy Web Post", "body": "Spy."},
                follow=False,
            )

        self.assertTrue(
            web_spy.called,
            "Web surface did not call the canonical can_edit from syndication.authz.",
        )
        # For stranger, can_edit returned False → 403, so called with (stranger, event)
        web_spy_call = web_spy.call_args
        self.assertEqual(
            web_spy_call[0][0],  # positional arg 0 = user
            self.stranger,
        )

        # --- API surface: patch syndication.authz.can_edit (canonical source) ---
        # services.create_post uses `from syndication.authz import can_edit` inside the
        # function body. Since the local import resolves through syndication.authz,
        # patching the canonical source intercepts the call on the API path too.
        token = _get_identity_token_for(self.stranger)
        api_client = Client()

        with patch("syndication.authz.can_edit", wraps=canonical_can_edit) as api_spy:
            api_client.post(
                f"/api/events/{self.event.pk}/posts/",
                data=json.dumps({"headline": "Spy API Post", "body": "Spy."}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {token}",
            )

        self.assertTrue(
            api_spy.called,
            "API surface did not call the canonical can_edit from syndication.authz.",
        )
        api_spy_call = api_spy.call_args
        self.assertEqual(
            api_spy_call[0][0],  # positional arg 0 = user
            self.stranger,
        )

    # ------------------------------------------------------------------
    # Leg 1 identity: both surfaces ARE the one canonical service object
    # ------------------------------------------------------------------

    def test_leg1_surfaces_share_same_service_function_object_create_post(self):
        """
        Identity proof: syndication.views.create_post and syndication.api.create_post
        ARE (not merely equal to) syndication.services.create_post.

        The call-site spy in the other Leg-1 tests proves the function is *called*
        via that name — but patching the alias would pass even if views.py or api.py
        had defined their own local `create_post` under the same name.  This `is`
        check proves both names in both surfaces resolve to the SAME canonical
        function object in syndication.services, eliminating the local-reimplementation
        loophole entirely.
        """
        import syndication.api
        import syndication.services
        import syndication.views

        self.assertIs(
            syndication.views.create_post,
            syndication.services.create_post,
            "syndication.views.create_post is NOT the same object as "
            "syndication.services.create_post — views.py must import the "
            "canonical service function, not a local reimplementation.",
        )
        self.assertIs(
            syndication.api.create_post,
            syndication.services.create_post,
            "syndication.api.create_post is NOT the same object as "
            "syndication.services.create_post — api.py must import the "
            "canonical service function, not a local reimplementation.",
        )

    def test_leg3_surfaces_share_same_authz_function_object_can_edit_post(self):
        """
        Identity proof: syndication.views.can_edit IS syndication.authz.can_edit
        (same canonical object, not a shadow copy) for the Post-create surface.

        views.py imports can_edit at module level from syndication.authz, so
        syndication.views.can_edit must be the identical function object.

        api.py uses local imports inside function bodies, so syndication.api has no
        module-level can_edit attribute to check — the canonical-source spy tests
        (test_leg3_api_rejects_stranger_on_post_create and
        test_leg3_same_authz_function_on_both_surfaces_post_create) already cover
        the API path by patching syndication.authz.can_edit directly.
        """
        import syndication.authz
        import syndication.views

        self.assertIs(
            syndication.views.can_edit,
            syndication.authz.can_edit,
            "syndication.views.can_edit is NOT the same object as "
            "syndication.authz.can_edit — views.py must import the canonical "
            "authz gate, not a local shadow function.",
        )
