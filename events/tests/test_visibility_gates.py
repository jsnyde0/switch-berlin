"""
[sb-7wzb.26] Visibility-gate audit: a non-public collected event never reaches
anonymous or under-tier viewers on any exposure surface.

Human ruling 2026-10-02 (sb-7wzb.17, LIA §3a): artist names show from all
sources; the event's visibility tier (ADR-012 D2/D3, ADR-017 D4) is the only
protection. Each test below seeds a semi_public and an unlisted *collected*
event (RawMessage provenance) carrying artist credits, a cover image and a
private-venue address, then asserts none of those parts appear on one surface
for anonymous and under-tier viewers. Positive controls prove the markers
would be detected if they leaked.

The surface table lives in the sb-7wzb.26 bead notes.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Attendance, Event, EventArtist, EventImage, Tag
from events.sitemap import EventSitemap
from ingestion.models import RawMessage
from organizers.models import Follow, Profile
from venues.models import Venue

User = get_user_model()

NON_PUBLIC_TIERS = ("semi_public", "unlisted")
UNDER_TIER_STATUSES = ("open", "suspended_pending_investigation", "banned")

# 1x1 transparent GIF.
_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00"
    b"\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def organizer(db):
    return Profile.objects.create(name="Gate Org", slug="gate-org", status="approved")


@pytest.fixture
def private_venue(db):
    return Venue.objects.create(
        name="Kellerverlies",
        slug="kellerverlies",
        address="Geheimstrasse 77",
        neighborhood="Wedding",
        privacy_mode="private",
        latitude="52.540000",
        longitude="13.360000",
    )


@pytest.fixture
def tag(db):
    return Tag.objects.create(slug="gate-tag", label="Gate Tag", kind="activity")


def _collected_event(tier, organizer, venue, tag, *, status="published", hidden=False, label=None):
    """A collected event (RawMessage provenance) with artist credit, cover and private venue."""
    label = label or tier
    raw = RawMessage.objects.create(source_type="telegram_private_channel", raw_payload={}, text="flyer")
    event = Event.objects.create(
        title=f"Leakcheck {label} Night",
        slug=f"leakcheck-{label}-night",
        description=f"Leakcheck {label} description body",
        organizer=organizer,
        venue=venue,
        start=timezone.now() + timedelta(days=3),
        status=status,
        hidden=hidden,
        visibility=tier,
        is_free=False,
        raw_message=raw,
    )
    event.tags.add(tag)
    EventArtist.objects.create(event=event, name=f"Mistress Nightshade {label}")
    EventImage.objects.create(
        event=event,
        is_cover=True,
        image=SimpleUploadedFile(f"leakcover-{label}.gif", _GIF, content_type="image/gif"),
    )
    return event


def _markers(event):
    """Every string that would betray the event if it appeared on a page."""
    cover = event.images.get(is_cover=True)
    return [
        event.title,
        event.slug,
        event.description[:24],
        *(credit.name for credit in event.artist_credits.all()),
        event.venue.address,
        cover.image.name.rsplit("/", 1)[-1].rsplit(".", 1)[0],
        cover.image.name,
    ]


@pytest.fixture
def non_public_events(organizer, private_venue, tag):
    return [_collected_event(tier, organizer, private_venue, tag) for tier in NON_PUBLIC_TIERS]


def _make_user(username, status):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    user.status = status
    user.save(update_fields=["status"])
    return user


def _client_for(user=None):
    client = Client()
    client.cookies["age_gate"] = "ok"
    if user is not None:
        client.force_login(user)
    return client


@pytest.fixture(params=("anonymous",) + UNDER_TIER_STATUSES)
def under_tier_client(request, db):
    """Anonymous visitor, or a logged-in user whose status is below the trusted tier."""
    if request.param == "anonymous":
        return _client_for()
    return _client_for(_make_user(f"viewer-{request.param[:12]}", request.param))


@pytest.fixture
def vouched_client(db):
    return _client_for(_make_user("vouched-viewer", "vouched"))


def assert_no_leak(response, events):
    body = response.content.decode(errors="replace")
    for event in events:
        for marker in _markers(event):
            assert marker not in body, f"{marker!r} leaked on {response.request['PATH_INFO']}"


# ---------------------------------------------------------------------------
# S1-S3 — events list page, HTMX partial, markers-data map JSON
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEventList:
    def test_list_page_absent(self, under_tier_client, non_public_events):
        response = under_tier_client.get(reverse("event-list"))
        assert response.status_code == 200
        assert_no_leak(response, non_public_events)

    def test_htmx_partial_absent(self, under_tier_client, non_public_events):
        response = under_tier_client.get(reverse("event-list"), HTTP_HX_REQUEST="true")
        assert response.status_code == 200
        assert_no_leak(response, non_public_events)

    def test_markers_json_absent(self, under_tier_client, non_public_events):
        response = under_tier_client.get(reverse("event-list"))
        slugs = {f["properties"]["event_slug"] for f in response.context["markers_geojson"]["features"]}
        assert not slugs & {e.slug for e in non_public_events}

    def test_unlisted_absent_from_list_even_for_vouched(self, vouched_client, non_public_events):
        """unlisted is URL-keyed: never listed, not even for trusted viewers (ADR-012 D3)."""
        unlisted = next(e for e in non_public_events if e.visibility == "unlisted")
        response = vouched_client.get(reverse("event-list"))
        assert_no_leak(response, [unlisted])

    def test_positive_control_vouched_sees_semi_public(self, vouched_client, non_public_events):
        semi = next(e for e in non_public_events if e.visibility == "semi_public")
        body = vouched_client.get(reverse("event-list")).content.decode()
        assert semi.title in body
        assert f"Mistress Nightshade {semi.visibility}" in body


# ---------------------------------------------------------------------------
# S4 — list filters and sorts (every filter narrows the gated queryset)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "params",
    [
        {"organizer": "gate-org"},
        {"tags": "gate-tag"},
        {"price": "paid"},
        {"sort": "trending"},
        {"from": "2000-01-01", "to": "2100-01-01"},
        {"bounds": "52.0,13.0,53.0,14.0"},
        {"filter": "following"},
    ],
    ids=lambda p: ",".join(p),
)
def test_list_filters_absent(under_tier_client, non_public_events, organizer, params):
    if under_tier_client.session.get("_auth_user_id"):
        user = User.objects.get(pk=under_tier_client.session["_auth_user_id"])
        Follow.objects.get_or_create(user=user, profile=organizer)
    response = under_tier_client.get(reverse("event-list"), params)
    assert response.status_code == 200
    assert_no_leak(response, non_public_events)


# ---------------------------------------------------------------------------
# S5-S6 — event detail page (incl. OG/link-preview meta) and attend endpoint
# ---------------------------------------------------------------------------


def _detail_url(event):
    return reverse("event-detail", kwargs={"org_slug": event.organizer.slug, "event_slug": event.slug})


@pytest.mark.django_db
class TestEventDetail:
    def test_detail_404(self, under_tier_client, non_public_events):
        for event in non_public_events:
            response = under_tier_client.get(_detail_url(event))
            assert response.status_code == 404
            assert_no_leak(response, non_public_events)

    def test_link_preview_bot_gets_404_and_no_og_tags(self, non_public_events):
        """Social unfurlers bypass the age gate; they must still hit the tier gate."""
        bot = Client(HTTP_USER_AGENT="facebookexternalhit/1.1")
        for event in non_public_events:
            response = bot.get(_detail_url(event))
            assert response.status_code == 404
            assert b"og:image" not in response.content
            assert_no_leak(response, non_public_events)

    def test_positive_control_vouched_sees_unlisted_by_url(self, vouched_client, non_public_events):
        unlisted = next(e for e in non_public_events if e.visibility == "unlisted")
        response = vouched_client.get(_detail_url(unlisted))
        assert response.status_code == 200
        body = response.content.decode()
        assert unlisted.title in body
        assert "leakcover-unlisted" in body
        # Private venue address stays hidden even from trusted viewers who are not going.
        assert unlisted.venue.address not in body

    def test_attend_rejected(self, under_tier_client, non_public_events):
        for event in non_public_events:
            url = reverse("event-attend", kwargs={"org_slug": event.organizer.slug, "event_slug": event.slug})
            response = under_tier_client.post(url, {"status": "going"})
            assert response.status_code in (302, 403, 404)
            assert_no_leak(response, non_public_events)
        assert not Attendance.objects.filter(event__in=non_public_events).exists()


# ---------------------------------------------------------------------------
# S7 — organizer profile page (upcoming + past)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOrganizerProfile:
    def test_profile_absent(self, under_tier_client, non_public_events, organizer, private_venue, tag):
        past = _collected_event("semi_public", organizer, private_venue, tag)
        Event.objects.filter(pk=past.pk).update(slug="leakcheck-past", start=timezone.now() - timedelta(days=3))
        response = under_tier_client.get(reverse("organizer-profile", kwargs={"slug": organizer.slug}))
        assert response.status_code == 200
        assert_no_leak(response, non_public_events)

    def test_positive_control_vouched_sees_semi_public(self, vouched_client, non_public_events, organizer):
        semi = next(e for e in non_public_events if e.visibility == "semi_public")
        body = vouched_client.get(reverse("organizer-profile", kwargs={"slug": organizer.slug})).content.decode()
        assert semi.title in body


# ---------------------------------------------------------------------------
# S8 — sitemap (not yet routed; items() and location() are the contract)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSitemap:
    def test_non_public_tiers_excluded(self, non_public_events):
        assert not set(EventSitemap().items()) & set(non_public_events)

    def test_hidden_and_draft_public_events_excluded(self, organizer, private_venue, tag):
        hidden = _collected_event("public", organizer, private_venue, tag, hidden=True)
        draft = _collected_event("public", organizer, private_venue, tag, status="draft")
        Event.objects.filter(pk=draft.pk).update(slug="leakcheck-draft")
        items = set(EventSitemap().items())
        assert hidden not in items
        assert draft.pk not in {e.pk for e in items}

    def test_location_reverses_event_detail(self, organizer, private_venue, tag):
        """sb-wd6e: location() resolves the hyphenated 'event-detail' route."""
        public = _collected_event("public", organizer, private_venue, tag)
        assert EventSitemap().location(public) == "/events/gate-org/leakcheck-public-night/"


# ---------------------------------------------------------------------------
# S9 — /me/ (attendance list; login wall admits only trusted viewers)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_me_page_blocks_under_tier(under_tier_client, non_public_events):
    if under_tier_client.session.get("_auth_user_id"):
        user = User.objects.get(pk=under_tier_client.session["_auth_user_id"])
        # Attended while vouched, then downgraded.
        for event in non_public_events:
            Attendance.objects.create(user=user, event=event, status="going")
    response = under_tier_client.get(reverse("me"))
    assert response.status_code in (302, 403)
    assert_no_leak(response, non_public_events)


# ---------------------------------------------------------------------------
# S10 — HTTP API (/api/, django-ninja)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_api_event_endpoints_reject_under_tier(under_tier_client, non_public_events):
    paths = ["/api/events/", "/api/posts/", "/api/projections/"]
    paths += [f"/api/events/{e.pk}/" for e in non_public_events]
    paths += [f"/api/events/{e.pk}/posts/" for e in non_public_events]
    for path in paths:
        response = under_tier_client.get(path)
        assert response.status_code in (401, 403), path
        assert_no_leak(response, non_public_events)


# ---------------------------------------------------------------------------
# S11 — syndication studio / event hub / fragments (login wall: vouched only)
# ---------------------------------------------------------------------------


def _syndication_paths(event):
    return [
        reverse("studio"),
        reverse("syndication:event-hub", kwargs={"pk": event.pk}),
        reverse("syndication:fragment-event-facts", kwargs={"pk": event.pk}),
        reverse("syndication:fragment-event-posts", kwargs={"pk": event.pk}),
        reverse("syndication:fragment-event-syndication", kwargs={"pk": event.pk}),
    ]


@pytest.mark.django_db
def test_syndication_views_block_under_tier(under_tier_client, non_public_events):
    for event in non_public_events:
        for path in _syndication_paths(event):
            for headers in ({}, {"HTTP_HX_REQUEST": "true"}):
                response = under_tier_client.get(path, **headers)
                assert response.status_code in (302, 403), path
                assert_no_leak(response, non_public_events)


@pytest.mark.django_db
@pytest.mark.xfail(
    strict=True,
    reason=(
        "sb-7wzb.26.4: syndication event-hub and fragments resolve any Event pk "
        "with no can_edit deny, so a vouched non-manager reads another organizer's draft collected event."
    ),
)
def test_syndication_fragment_denies_non_manager_draft(vouched_client, private_venue, tag):
    other_org = Profile.objects.create(name="Other Org", slug="other-org", status="approved")
    draft = _collected_event("semi_public", other_org, private_venue, tag, status="draft")
    response = vouched_client.get(
        reverse("syndication:fragment-event-facts", kwargs={"pk": draft.pk}), HTTP_HX_REQUEST="true"
    )
    assert response.status_code in (403, 404)
    assert_no_leak(response, [draft])


# ---------------------------------------------------------------------------
# S12 — Django admin (staff only)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_blocks_under_tier(under_tier_client, non_public_events):
    paths = [reverse("admin:events_event_changelist")]
    paths += [reverse("admin:events_event_change", args=[e.pk]) for e in non_public_events]
    for path in paths:
        response = under_tier_client.get(path)
        assert response.status_code in (302, 403), path
        assert_no_leak(response, non_public_events)


# ---------------------------------------------------------------------------
# S13-S14 — reviews flag + DSA takedown (existence-only; no event fields)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_endpoint_blocks_under_tier(under_tier_client, non_public_events):
    for event in non_public_events:
        response = under_tier_client.post(
            reverse("flag-target"), {"target_type": "event", "target_id": event.pk, "reason": "spam"}
        )
        assert response.status_code in (302, 403), response.status_code
        assert_no_leak(response, non_public_events)


@pytest.mark.django_db
def test_takedown_renders_no_event_fields(non_public_events):
    """Takedown must accept any event URL (legal reach); it must echo nothing of the event back."""
    client = _client_for()
    for event in non_public_events:
        response = client.post(
            reverse("takedown"),
            {
                "event_url": f"http://testserver{_detail_url(event)}",
                "reason": "spam",
                "body": "report",
                "good_faith_confirmed": "on",
            },
        )
        assert response.status_code in (200, 302)
        body = response.content.decode()
        for marker in _markers(event):
            if marker == event.slug:
                continue  # the reporter's own submitted URL may be echoed back
            assert marker not in body


# ---------------------------------------------------------------------------
# Withheld states — collected events land as DRAFTS; moderation HIDES events.
# Tier is public here on purpose, so only the status/hidden filter protects them.
# ---------------------------------------------------------------------------


@pytest.fixture
def withheld_events(organizer, private_venue, tag):
    return [
        _collected_event("public", organizer, private_venue, tag, status="draft", label="draft"),
        _collected_event("public", organizer, private_venue, tag, hidden=True, label="hidden"),
    ]


@pytest.fixture(params=("anonymous", "vouched", "staff"))
def any_viewer_client(request, db):
    if request.param == "anonymous":
        return _client_for()
    user = _make_user(f"withheld-{request.param}", "vouched")
    if request.param == "staff":
        user.is_staff = True
        user.save(update_fields=["is_staff"])
    return _client_for(user)


@pytest.mark.django_db
class TestDraftAndHiddenWithheld:
    def test_list_and_markers_absent(self, any_viewer_client, withheld_events):
        response = any_viewer_client.get(reverse("event-list"))
        assert response.status_code == 200
        assert_no_leak(response, withheld_events)
        slugs = {f["properties"]["event_slug"] for f in response.context["markers_geojson"]["features"]}
        assert not slugs & {e.slug for e in withheld_events}

    def test_detail_404(self, any_viewer_client, withheld_events):
        for event in withheld_events:
            response = any_viewer_client.get(_detail_url(event))
            assert response.status_code == 404
            assert_no_leak(response, withheld_events)

    def test_profile_absent(self, any_viewer_client, withheld_events, organizer):
        response = any_viewer_client.get(reverse("organizer-profile", kwargs={"slug": organizer.slug}))
        assert response.status_code == 200
        assert_no_leak(response, withheld_events)

    def test_sitemap_absent(self, withheld_events):
        assert not {e.pk for e in EventSitemap().items()} & {e.pk for e in withheld_events}


# ---------------------------------------------------------------------------
# Approved but under-tier — passes the login wall and approved_required, fails the
# tier gate. Simulates EVENT_VISIBILITY_TRUSTED_STATUSES (FLEXIBLE, ADR-012 D3)
# diverging from the wall's hard-coded "vouched", so the tier gate itself is exercised.
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_under_tier_user(settings, db):
    settings.EVENT_VISIBILITY_TRUSTED_STATUSES = ()
    user = _make_user("approved-under-tier", "vouched")
    user.art9_consent_given_at = timezone.now()
    user.save(update_fields=["art9_consent_given_at"])
    return user


@pytest.mark.django_db
class TestApprovedButUnderTier:
    def test_list_and_detail_withheld(self, approved_under_tier_user, non_public_events):
        client = _client_for(approved_under_tier_user)
        assert_no_leak(client.get(reverse("event-list")), non_public_events)
        for event in non_public_events:
            response = client.get(_detail_url(event))
            assert response.status_code == 404

    def test_attend_404(self, approved_under_tier_user, non_public_events):
        client = _client_for(approved_under_tier_user)
        for event in non_public_events:
            url = reverse("event-attend", kwargs={"org_slug": event.organizer.slug, "event_slug": event.slug})
            response = client.post(url, {"status": "going"})
            assert response.status_code == 404
            assert_no_leak(response, non_public_events)
        assert not Attendance.objects.filter(event__in=non_public_events).exists()

    def test_flag_404(self, approved_under_tier_user, non_public_events):
        from reviews.models import Flag

        client = _client_for(approved_under_tier_user)
        for event in non_public_events:
            response = client.post(reverse("flag-target"), {"target_type": "event", "target_id": event.pk})
            assert response.status_code == 404
        assert not Flag.objects.filter(event__in=non_public_events).exists()

    def test_review_submit_404(self, approved_under_tier_user, non_public_events):
        from reviews.models import Review

        client = _client_for(approved_under_tier_user)
        for event in non_public_events:
            Attendance.objects.create(user=approved_under_tier_user, event=event, status="went")
            response = client.post(
                reverse("review-submit"),
                {"target_type": "event", "target_id": event.pk, "rating": 4, "body": "ok"},
            )
            assert response.status_code == 404
        assert not Review.objects.filter(event__in=non_public_events).exists()

    def test_me_page_omits_attended_non_public_events(self, approved_under_tier_user, non_public_events):
        for event in non_public_events:
            Attendance.objects.create(user=approved_under_tier_user, event=event, status="going")
        response = _client_for(approved_under_tier_user).get(reverse("me"))
        assert response.status_code == 200
        assert_no_leak(response, non_public_events)


# ---------------------------------------------------------------------------
# Sitemap: an organizer-less event has no routable URL (ADR-008 D3: no silent fallback)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSitemapOrganizerless:
    def _organizerless(self):
        return Event.objects.create(
            title="Orphan", slug="orphan", start=timezone.now(), status="published", visibility="public"
        )

    def test_organizerless_event_excluded_from_items(self):
        orphan = self._organizerless()
        assert orphan.pk not in {e.pk for e in EventSitemap().items()}

    def test_location_raises_without_organizer(self):
        with pytest.raises(ValueError):
            EventSitemap().location(self._organizerless())
