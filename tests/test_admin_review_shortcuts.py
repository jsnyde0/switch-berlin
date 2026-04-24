"""
Tests for kb-58l: Admin keyboard shortcuts for review queues.

Covers:
- EventAdmin.Media.js includes review_shortcuts.js
- FlagAdmin.Media.js includes review_shortcuts.js
- FlagAdmin has resolve_approved and resolve_rejected bulk actions
"""

import pytest


def test_event_admin_media_includes_review_shortcuts():
    """EventAdmin.Media.js must include the review_shortcuts.js file."""
    from events.admin import EventAdmin

    media_js = EventAdmin.Media.js
    assert any("review_shortcuts.js" in f for f in media_js), (
        f"review_shortcuts.js not found in EventAdmin.Media.js: {media_js}"
    )


def test_flag_admin_media_includes_review_shortcuts():
    """FlagAdmin.Media.js must include the review_shortcuts.js file."""
    from reviews.admin import FlagAdmin

    media_js = FlagAdmin.Media.js
    assert any("review_shortcuts.js" in f for f in media_js), (
        f"review_shortcuts.js not found in FlagAdmin.Media.js: {media_js}"
    )


def test_flag_admin_has_resolve_approved_action():
    """FlagAdmin must have a resolve_approved bulk action."""
    from reviews.admin import FlagAdmin

    assert "resolve_approved" in FlagAdmin.actions, (
        f"resolve_approved not in FlagAdmin.actions: {FlagAdmin.actions}"
    )


def test_flag_admin_has_resolve_rejected_action():
    """FlagAdmin must have a resolve_rejected bulk action."""
    from reviews.admin import FlagAdmin

    assert "resolve_rejected" in FlagAdmin.actions, (
        f"resolve_rejected not in FlagAdmin.actions: {FlagAdmin.actions}"
    )


def test_event_admin_has_publish_events_action():
    """EventAdmin must have a publish_events action (GDPR-correct publish)."""
    from events.admin import EventAdmin

    assert "publish_events" in EventAdmin.actions, (
        f"publish_events not in EventAdmin.actions: {EventAdmin.actions}"
    )


def test_js_shortcut_uses_publish_events_not_publish_selected_for_approve():
    """review_shortcuts.js 'A' shortcut must target publish_events for EventAdmin.

    The approve shortcut (A key) must prefer publish_events over publish_selected
    so that GDPR consent capture and published_at timestamping are performed.
    """
    import os

    js_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "static",
        "admin",
        "js",
        "review_shortcuts.js",
    )
    with open(js_path) as f:
        content = f.read()

    # The approve shortcut must reference publish_events (GDPR-correct action)
    assert "'publish_events'" in content, (
        "publish_events not found in JS — 'A' shortcut must target publish_events"
    )

    # publish_events must appear before resolve_approved so EventAdmin hits it first
    idx_publish_events = content.find("'publish_events'")
    idx_resolve_approved = content.find("'resolve_approved'")
    assert idx_resolve_approved != -1, "resolve_approved not found in JS shortcut"
    assert idx_publish_events < idx_resolve_approved, (
        "JS shortcut should check publish_events before resolve_approved; "
        f"publish_events={idx_publish_events}, resolve_approved={idx_resolve_approved}"
    )


@pytest.mark.django_db
def test_flag_admin_resolve_approved_sets_distinct_resolution_notes(superuser, client):
    """resolve_approved must set resolution_notes indicating approval."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from reviews.models import Flag

    event = Event.objects.create(
        title="Test Event Shortcut Notes A",
        slug="test-event-shortcut-notes-a",
        start=timezone.now() + datetime.timedelta(days=1),
        status="draft",
    )
    flag = Flag.objects.create(event=event, reason="spam")

    client.force_login(superuser)
    client.post(
        "/admin/reviews/flag/",
        {"action": "resolve_approved", "_selected_action": [str(flag.pk)]},
    )

    flag.refresh_from_db()
    assert "approved" in flag.resolution_notes.lower(), (
        f"Expected 'approved' in resolution_notes, got: {flag.resolution_notes!r}"
    )


@pytest.mark.django_db
def test_flag_admin_resolve_rejected_sets_distinct_resolution_notes(superuser, client):
    """resolve_rejected must set resolution_notes indicating rejection."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from reviews.models import Flag

    event = Event.objects.create(
        title="Test Event Shortcut Notes R",
        slug="test-event-shortcut-notes-r",
        start=timezone.now() + datetime.timedelta(days=1),
        status="draft",
    )
    flag = Flag.objects.create(event=event, reason="spam")

    client.force_login(superuser)
    client.post(
        "/admin/reviews/flag/",
        {"action": "resolve_rejected", "_selected_action": [str(flag.pk)]},
    )

    flag.refresh_from_db()
    assert "rejected" in flag.resolution_notes.lower(), (
        f"Expected 'rejected' in resolution_notes, got: {flag.resolution_notes!r}"
    )


@pytest.mark.django_db
def test_flag_admin_resolve_approved_marks_resolved(superuser, client):
    """resolve_approved action must set resolved=True on selected flags."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from reviews.models import Flag

    event = Event.objects.create(
        title="Test Event Shortcut",
        slug="test-event-shortcut",
        start=timezone.now() + datetime.timedelta(days=1),
        status="draft",
    )
    flag = Flag.objects.create(
        event=event,
        reason="spam",
    )

    client.force_login(superuser)
    response = client.post(
        "/admin/reviews/flag/",
        {
            "action": "resolve_approved",
            "_selected_action": [str(flag.pk)],
        },
    )
    assert response.status_code in (200, 302)

    flag.refresh_from_db()
    assert flag.resolved is True


@pytest.mark.django_db
def test_flag_admin_resolve_rejected_marks_resolved(superuser, client):
    """resolve_rejected action must set resolved=True on selected flags."""
    import datetime

    from django.utils import timezone

    from events.models import Event
    from reviews.models import Flag

    event = Event.objects.create(
        title="Test Event Shortcut 2",
        slug="test-event-shortcut-2",
        start=timezone.now() + datetime.timedelta(days=1),
        status="draft",
    )
    flag = Flag.objects.create(
        event=event,
        reason="spam",
    )

    client.force_login(superuser)
    response = client.post(
        "/admin/reviews/flag/",
        {
            "action": "resolve_rejected",
            "_selected_action": [str(flag.pk)],
        },
    )
    assert response.status_code in (200, 302)

    flag.refresh_from_db()
    assert flag.resolved is True
