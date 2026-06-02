"""Tests for daily_flag_digest email digest enhancements (bead kb-8qn.8).

Tests:
- 5 flags across 3 targets → email body has 3 group headers
- Each flag entry includes admin URL containing '?action='
- SITE_URL appears in constructed admin URL
- _suggest_action helper returns correct action per target_type/reason
"""

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper: extract email body from mock_send call_args
# ---------------------------------------------------------------------------


def _get_body(mock_send):
    """Extract the message body from a patched send_mail call."""
    call_kwargs = mock_send.call_args
    if call_kwargs.args and len(call_kwargs.args) > 1:
        return call_kwargs.args[1]
    return call_kwargs.kwargs.get("message", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organizer(db):
    from organizers.models import Profile

    return Profile.objects.create(
        name="Test Organizer Digest",
        slug="test-organizer-digest",
        status="approved",
    )


@pytest.fixture
def event_a(db, organizer):
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Event

    now = timezone.now()
    return Event.objects.create(
        title="Event A",
        slug="event-a-digest",
        organizer=organizer,
        status="published",
        start=now + timedelta(days=1),
    )


@pytest.fixture
def event_b(db, organizer):
    from datetime import timedelta

    from django.utils import timezone

    from events.models import Event

    now = timezone.now()
    return Event.objects.create(
        title="Event B",
        slug="event-b-digest",
        organizer=organizer,
        status="published",
        start=now + timedelta(days=2),
    )


@pytest.fixture
def review_on_event(db, event_a):
    from reviews.models import Review

    user = User.objects.create_user(
        username="reviewer_digest",
        email="reviewer_digest@example.com",
        password="testpass",
    )
    return Review.objects.create(
        author=user,
        event=event_a,
        rating=3,
    )


@pytest.fixture
def five_flags(db, event_a, event_b, review_on_event):
    """5 flags: 2 on event_a, 2 on event_b, 1 on review."""
    from reviews.models import Flag

    flags = []
    # 2 flags on event_a
    for _i in range(2):
        flags.append(Flag.objects.create(event=event_a, reason="spam"))
    # 2 flags on event_b
    for _i in range(2):
        flags.append(Flag.objects.create(event=event_b, reason="harmful"))
    # 1 flag on review
    flags.append(Flag.objects.create(review=review_on_event, reason="inaccurate"))
    return flags


# ---------------------------------------------------------------------------
# Tests: _suggest_action helper
# ---------------------------------------------------------------------------


class TestSuggestAction:
    """_suggest_action returns the correct suggested admin action."""

    def test_review_always_returns_delete(self):
        from ingestion.tasks_flags import _suggest_action

        assert _suggest_action("review", "spam") == "delete"
        assert _suggest_action("review", "harmful") == "delete"
        assert _suggest_action("review", "other") == "delete"

    def test_organizer_harmful_returns_suspend(self):
        from ingestion.tasks_flags import _suggest_action

        assert _suggest_action("organizer", "harmful") == "suspend"

    def test_organizer_other_reason_returns_hide(self):
        from ingestion.tasks_flags import _suggest_action

        assert _suggest_action("organizer", "spam") == "hide"
        assert _suggest_action("organizer", "inaccurate") == "hide"

    def test_event_returns_hide(self):
        from ingestion.tasks_flags import _suggest_action

        assert _suggest_action("event", "spam") == "hide"
        assert _suggest_action("event", "harmful") == "hide"

    def test_unknown_returns_hide(self):
        from ingestion.tasks_flags import _suggest_action

        assert _suggest_action("unknown", "spam") == "hide"


# ---------------------------------------------------------------------------
# Tests: daily_flag_digest grouping and admin URLs
# ---------------------------------------------------------------------------


class TestDailyFlagDigestGrouping:
    """daily_flag_digest groups flags by target and includes admin URLs."""

    def test_email_body_has_three_group_headers(self, five_flags):
        """5 flags across 3 targets → email body contains 3 group headers."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        assert mock_send.called
        body = _get_body(mock_send)

        # Count lines that look like group headers: contain ' flags):'
        header_lines = [line for line in body.splitlines() if "flags):" in line]
        assert len(header_lines) == 3, f"Expected 3 headers, got {len(header_lines)}. Body:\n{body}"

    def test_event_a_header_shows_count_2(self, five_flags, event_a):
        """Event A has 2 flags so its header shows (2 flags):."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        assert "(2 flags):" in body, f"Expected '(2 flags):' in body:\n{body}"

    def test_each_flag_entry_has_action_param(self, five_flags):
        """Each flag entry's admin URL contains '?action='."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        # Find all admin URL lines (lines containing '?action=')
        action_lines = [line for line in body.splitlines() if "?action=" in line]
        # We have 5 flags, each should get an admin URL line
        assert len(action_lines) == 5, f"Expected 5 action URL lines, got {len(action_lines)}. Body:\n{body}"

    def test_site_url_appears_in_admin_url(self, five_flags):
        """SITE_URL is prepended to the admin URL in the email body."""
        from django.conf import settings

        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        site_url = settings.SITE_URL
        assert site_url in body, f"Expected SITE_URL '{site_url}' in body:\n{body}"

    def test_admin_url_contains_flag_change_path(self, five_flags):
        """Admin URLs point to reviews_flag_change path."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        assert "/reviews/flag/" in body, f"Expected '/reviews/flag/' in body:\n{body}"

    def test_review_flags_suggested_action_is_delete(self, five_flags):
        """Review flags get ?action=delete in admin URL."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        assert "?action=delete" in body, f"Expected '?action=delete' in body:\n{body}"

    def test_no_flags_returns_early_without_sending(self, db):
        """When there are no unresolved flags, no email is sent."""
        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        mock_send.assert_not_called()

    def test_cap_at_50_flags(self, db, organizer, event_a):
        """With >50 flags, only 50 are included in the email."""
        from reviews.models import Flag

        for _ in range(60):
            Flag.objects.create(event=event_a, reason="spam")

        from ingestion.tasks_flags import daily_flag_digest

        with patch("ingestion.tasks_flags.send_mail") as mock_send:
            daily_flag_digest()

        body = _get_body(mock_send)
        action_lines = [line for line in body.splitlines() if "?action=" in line]
        assert len(action_lines) <= 50, f"Expected at most 50 flag lines, got {len(action_lines)}"
