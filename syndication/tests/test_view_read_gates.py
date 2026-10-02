"""
[sb-7wzb.26.4] Every syndication entry point that renders an Event/Post (or its
version/projection fragments) by pk denies with 403 when the requesting user
cannot edit it, on HX and non-HX paths. 403 is the studio's existing no-claim contract (ADR-008 D3). A manager of the
organizer still gets through (control).
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events.models import Event, EventOrganizer
from organizers.models import Profile, ProfileClaim
from syndication.models import ContentVersion, PlatformConnection, PlatformProjection, Post

User = get_user_model()

EVENT_MARKER = "Zebra Secret Draft Title"
POST_MARKER = "Zebra Secret Post Headline"


def _client(username):
    user = User.objects.create_user(username=username, email=f"{username}@example.com", password="x")
    user.status = "vouched"
    user.save(update_fields=["status"])
    client = Client()
    client.cookies["age_gate"] = "ok"
    client.force_login(user)
    return user, client


@pytest.fixture
def world(db):
    org = Profile.objects.create(name="Gate Org", slug="gate-org", status="approved")
    event = Event.objects.create(title=EVENT_MARKER, slug="zebra-draft", start=timezone.now(), status="draft")
    EventOrganizer.objects.create(event=event, profile=org, is_primary=True)
    post = Post.objects.create(event=event, headline=POST_MARKER, body="post body")
    conn = PlatformConnection.objects.create(
        organizer=org, platform="fetlife", destination_id="fl-x", kinds=["listing", "promotion"]
    )
    event_cv = ContentVersion.objects.create(
        event=event, name="canonical", provenance=ContentVersion.Provenance.RULE_TEMPLATE
    )
    post_cv = ContentVersion.objects.create(
        post=post, name="canonical", provenance=ContentVersion.Provenance.RULE_TEMPLATE
    )
    event_proj = PlatformProjection.objects.create(
        connection=conn, kind="listing", source_event=event, content_version=event_cv
    )
    post_proj = PlatformProjection.objects.create(
        connection=conn, kind="promotion", source_post=post, content_version=post_cv
    )
    manager, manager_client = _client("manager")
    ProfileClaim.objects.create(profile=org, user=manager, verified_method="auto_self")
    _, stranger_client = _client("stranger")
    return {
        "event": event,
        "post": post,
        "event_cv": event_cv,
        "post_cv": post_cv,
        "event_proj": event_proj,
        "post_proj": post_proj,
        "manager": manager_client,
        "stranger": stranger_client,
    }


def _entry_points(w):
    """(label, method, url, data, marker) for every entry point."""
    return [
        ("event_hub", "get", reverse("syndication:event-hub", kwargs={"pk": w["event"].pk}), {}, EVENT_MARKER),
        (
            "fragment_event_facts",
            "get",
            reverse("syndication:fragment-event-facts", kwargs={"pk": w["event"].pk}),
            {},
            EVENT_MARKER,
        ),
        (
            "fragment_event_posts",
            "get",
            reverse("syndication:fragment-event-posts", kwargs={"pk": w["event"].pk}),
            {},
            POST_MARKER,
        ),
        (
            "fragment_event_syndication",
            "get",
            reverse("syndication:fragment-event-syndication", kwargs={"pk": w["event"].pk}),
            {},
            EVENT_MARKER,
        ),
        ("post_hub", "get", reverse("syndication:post-hub", kwargs={"pk": w["post"].pk}), {}, POST_MARKER),
        (
            "fragment_post_syndication",
            "get",
            reverse("syndication:fragment-post-syndication", kwargs={"pk": w["post"].pk}),
            {},
            POST_MARKER,
        ),
        (
            "version_copy_to (event, empty target)",
            "post",
            reverse("syndication:version-copy-to", kwargs={"pk": w["event_cv"].pk}),
            {},
            EVENT_MARKER,
        ),
        (
            "version_copy_to (post, empty target)",
            "post",
            reverse("syndication:version-copy-to", kwargs={"pk": w["post_cv"].pk}),
            {},
            POST_MARKER,
        ),
        (
            "version_copy_from (event, empty source)",
            "post",
            reverse("syndication:version-copy-from", kwargs={"pk": w["event_proj"].pk}),
            {},
            EVENT_MARKER,
        ),
        (
            "version_copy_from (post, empty source)",
            "post",
            reverse("syndication:version-copy-from", kwargs={"pk": w["post_proj"].pk}),
            {},
            POST_MARKER,
        ),
    ]


_STUB = type("Stub", (), {"pk": 1})()
ENTRY_LABELS = [
    e[0]
    for e in _entry_points(dict.fromkeys(("event", "post", "event_cv", "post_cv", "event_proj", "post_proj"), _STUB))
]


@pytest.mark.parametrize("hx", [False, True], ids=["non-hx", "hx"])
@pytest.mark.parametrize("index", range(len(ENTRY_LABELS)), ids=ENTRY_LABELS)
def test_non_manager_gets_403_and_no_leak(world, index, hx):
    label, method, url, data, marker = _entry_points(world)[index]
    kwargs = {"HTTP_HX_REQUEST": "true"} if hx else {}
    response = getattr(world["stranger"], method)(url, data, **kwargs)
    assert response.status_code == 403, label
    body = response.content.decode(errors="replace")
    assert marker not in body, label


@pytest.mark.parametrize("hx", [False, True], ids=["non-hx", "hx"])
@pytest.mark.parametrize("index", range(len(ENTRY_LABELS)), ids=ENTRY_LABELS)
def test_manager_still_passes(world, index, hx):
    label, method, url, data, _marker = _entry_points(world)[index]
    kwargs = {"HTTP_HX_REQUEST": "true"} if hx else {}
    response = getattr(world["manager"], method)(url, data, **kwargs)
    assert response.status_code in (200, 302), label
