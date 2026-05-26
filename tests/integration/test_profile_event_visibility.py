"""Regression: the organizer profile event list must be viewer-tier-aware.

ADR-012 D3 — semi_public events are visible only to trusted (vouched/staff)
viewers. The profile page (/p/<slug>/) lists an organizer's events; that list
must respect the same tier gate as the event detail view, otherwise an
open-tier or anonymous viewer sees semi_public events as clickable links that
then 404 on the (correctly-gated) detail view.

Surfaced during local smoke test 2026-05-26: open-tier user saw a semi_public
event under /p/demo-seed-collective/ but the detail page 404'd.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from events.models import Event
from organizers.models import Profile

User = get_user_model()


def make_org():
    return Profile.objects.create(
        name="Vis Test Org", slug=f"vis-org-{uuid.uuid4().hex[:8]}", status="approved"
    )


def make_event(org, visibility, title):
    event = Event.objects.create(
        title=title,
        slug=f"{visibility}-{uuid.uuid4().hex[:6]}",
        start=timezone.now() + timezone.timedelta(days=7),
        status="published",
        visibility=visibility,
    )
    event.organizer = org  # compat setter creates the primary EventOrganizer row
    return event


def make_user(status):
    username = f"{status}-{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(
        username=username, email=f"{username}@example.com", password="x"
    )
    user.status = status
    user.save(update_fields=["status"])
    return user


@pytest.fixture
def org_with_two_events(db):
    org = make_org()
    public = make_event(org, "public", "Public Workshop")
    semi = make_event(org, "semi_public", "Semi Salon")
    return org, public, semi


@pytest.mark.django_db
def test_anonymous_sees_only_public_event_in_profile_list(client, org_with_two_events):
    org, public, semi = org_with_two_events
    response = client.get(f"/p/{org.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    assert public.slug in content
    assert semi.slug not in content


@pytest.mark.django_db
def test_open_tier_sees_only_public_event_in_profile_list(client, org_with_two_events):
    org, public, semi = org_with_two_events
    client.force_login(make_user("open"))
    response = client.get(f"/p/{org.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    assert public.slug in content
    assert semi.slug not in content


@pytest.mark.django_db
def test_vouched_sees_both_events_in_profile_list(client, org_with_two_events):
    org, public, semi = org_with_two_events
    client.force_login(make_user("vouched"))
    response = client.get(f"/p/{org.slug}/")
    assert response.status_code == 200
    content = response.content.decode()
    assert public.slug in content
    assert semi.slug in content
