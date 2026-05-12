"""
TDD tests for bead kb-8qn.9: Event review display gates (step-7a).

Tests verify:
- EVENT_REVIEWS_DISPLAYED=False hides star chip and reviews section
- EVENT_REVIEWS_DISPLAYED=True but rating_count < threshold hides both
- EVENT_REVIEWS_DISPLAYED=True and rating_count >= threshold shows both
- Only hidden=False reviews appear in the reviews section
- Changing threshold.event_ratings_display via FeatureFlag hides display
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from a_core.models import FeatureFlag
from events.models import Event
from organizers.models import Profile
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_organizer(slug="test-org-rd"):
    return Profile.objects.create(
        name="Test Org RD",
        slug=slug,
        status="approved",
    )


def _make_event(organizer, slug="test-event-rd", rating_count=0, avg_rating=None):
    """Create a published future event with optional aggregate fields."""
    return Event.objects.create(
        title="Review Display Test Event",
        slug=slug,
        organizer=organizer,
        status="published",
        start=timezone.now() + timezone.timedelta(days=7),
        rating_count=rating_count,
        avg_rating=avg_rating,
    )


def _make_review(event, rating=4, hidden=False, username_suffix=""):
    """Create a Review for the event with a unique author."""
    author = User.objects.create_user(
        username=f"reviewer_rd{username_suffix}_{event.pk}_{rating}_{hidden}",
        email=f"reviewer_rd{username_suffix}@example.com",
        password="testpass123",
    )
    return Review.objects.create(
        author=author,
        event=event,
        rating=rating,
        hidden=hidden,
    )


def _set_flag(key, enabled=True, numeric_value=None):
    """Upsert a FeatureFlag; clear cache so get_flag/get_numeric see the change."""
    FeatureFlag.objects.update_or_create(
        key=key,
        defaults={"enabled": enabled, "numeric_value": numeric_value},
    )
    cache.clear()


# ---------------------------------------------------------------------------
# Tests: event list page — star chip
# ---------------------------------------------------------------------------


class EventListStarChipTest(TestCase):
    """Star chip on /events list is controlled by dual gate."""

    def setUp(self):
        cache.clear()
        self.organizer = _make_organizer()

    def tearDown(self):
        cache.clear()

    def _get_event_list(self):
        return self.client.get("/events/")

    # --- Gate: EVENT_REVIEWS_DISPLAYED=False ---

    def test_star_chip_hidden_when_flag_off_regardless_of_count(self):
        """Flag off → chip absent even when rating_count=10."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=False)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        _make_event(self.organizer, rating_count=10, avg_rating=4.2)
        response = self._get_event_list()
        self.assertEqual(response.status_code, 200)
        # Star chip HTML must not appear
        self.assertNotContains(response, "&#9733;")
        self.assertNotContains(response, "★")

    # --- Gate: flag True but count below threshold ---

    def test_star_chip_hidden_when_count_below_threshold(self):
        """Flag True + rating_count=2 (below threshold=3) → chip absent."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        _make_event(
            self.organizer,
            slug="event-rd-below",
            rating_count=2,
            avg_rating=4.2,
        )
        response = self._get_event_list()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "&#9733;")
        self.assertNotContains(response, "★")

    # --- Both gates pass ---

    def test_star_chip_shown_when_both_gates_pass(self):
        """Flag True + rating_count>=3 → chip renders with avg and count."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        _make_event(
            self.organizer,
            slug="event-rd-pass",
            rating_count=3,
            avg_rating=4.2,
        )
        response = self._get_event_list()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "4.2")
        self.assertContains(response, "(3)")

    def test_star_chip_format_with_exact_values(self):
        """Star chip content matches expected format X.X (N)."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        _make_event(
            self.organizer,
            slug="event-rd-fmt",
            rating_count=5,
            avg_rating=3.7,
        )
        response = self._get_event_list()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3.7")
        self.assertContains(response, "(5)")

    # --- Threshold change hides chip ---

    def test_star_chip_hidden_after_threshold_raised(self):
        """Raising threshold to 10 hides chip on event with rating_count=5."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=10)
        _make_event(
            self.organizer,
            slug="event-rd-thresh",
            rating_count=5,
            avg_rating=4.0,
        )
        response = self._get_event_list()
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "&#9733;")
        self.assertNotContains(response, "★")

    # --- Flag rollback (True → False) ---

    def test_star_chip_disappears_on_flag_rollback(self):
        """Chip was shown (flag=True, count>=3); flip to False → chip gone."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        _make_event(
            self.organizer,
            slug="event-rd-rollback",
            rating_count=3,
            avg_rating=4.2,
        )
        # Verify shown first
        response = self._get_event_list()
        self.assertContains(response, "4.2")
        # Flip flag off
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=False)
        response = self._get_event_list()
        self.assertNotContains(response, "&#9733;")
        self.assertNotContains(response, "★")


# ---------------------------------------------------------------------------
# Tests: event detail page — reviews section
# ---------------------------------------------------------------------------


class EventDetailReviewsSectionTest(TestCase):
    """Reviews section on event detail is controlled by dual gate."""

    def setUp(self):
        cache.clear()
        self.organizer = _make_organizer(slug="org-detail-rd")
        self.event = _make_event(
            self.organizer,
            slug="event-detail-rd",
            rating_count=3,
            avg_rating=4.0,
        )
        self.url = f"/events/{self.organizer.slug}/{self.event.slug}/"

    def tearDown(self):
        cache.clear()

    # --- Gate: EVENT_REVIEWS_DISPLAYED=False ---

    def test_reviews_section_hidden_when_flag_off(self):
        """Flag off → reviews section absent even with rating_count=10."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=False)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=10)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Reviews")

    # --- Gate: flag True but count below threshold ---

    def test_reviews_section_hidden_when_count_below_threshold(self):
        """Flag True + rating_count=2 (below threshold=3) → section absent."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=2)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        # "Reviews" heading not present
        self.assertNotContains(response, "<h2")

    # --- Both gates pass ---

    def test_reviews_section_renders_when_both_gates_pass(self):
        """Flag True + rating_count=3 (>= threshold=3) → reviews section renders."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reviews")

    def test_reviews_section_shows_only_unhidden_reviews(self):
        """Reviews section includes hidden=False reviews, excludes hidden=True."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)

        _make_review(self.event, rating=5, hidden=False, username_suffix="v1")
        _make_review(self.event, rating=1, hidden=True, username_suffix="h1")

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reviews")
        # Visible review's rating must appear; hidden review's rating must not
        self.assertContains(response, "5/5")
        self.assertNotContains(response, "1/5")

    def test_reviews_section_shows_empty_state_when_no_reviews(self):
        """Reviews section renders empty-state text when no visible reviews exist."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No reviews yet")

    # --- Threshold change ---

    def test_reviews_section_hidden_after_threshold_raised(self):
        """Raising threshold to 10 hides section on event with rating_count=5."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=10)
        Event.objects.filter(pk=self.event.pk).update(rating_count=5)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<h2")

    # --- Flag rollback ---

    def test_reviews_section_disappears_on_flag_rollback(self):
        """Section was shown; flip EVENT_REVIEWS_DISPLAYED=False → gone."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)
        # Verify shown
        response = self.client.get(self.url)
        self.assertContains(response, "Reviews")
        # Rollback
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=False)
        response = self.client.get(self.url)
        self.assertNotContains(response, "Reviews")

    # --- Context variables in view ---

    def test_detail_view_passes_event_reviews_to_context(self):
        """event_detail view passes event_reviews queryset to template context."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)
        review = _make_review(self.event, rating=4, username_suffix="ctx1")
        response = self.client.get(self.url)
        self.assertIn("event_reviews", response.context)
        pks = [r.pk for r in response.context["event_reviews"]]
        self.assertIn(review.pk, pks)

    def test_detail_view_excludes_hidden_reviews_from_context(self):
        """event_detail view excludes hidden=True reviews from event_reviews."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        Event.objects.filter(pk=self.event.pk).update(rating_count=3)
        hidden_review = _make_review(
            self.event, hidden=True, username_suffix="hctx1"
        )
        response = self.client.get(self.url)
        pks = [r.pk for r in response.context["event_reviews"]]
        self.assertNotIn(hidden_review.pk, pks)

    def test_detail_view_passes_flag_context_vars(self):
        """event_detail view passes EVENT_REVIEWS_DISPLAYED and THRESHOLD."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        response = self.client.get(self.url)
        self.assertIn("EVENT_REVIEWS_DISPLAYED", response.context)
        self.assertIn("EVENT_RATING_THRESHOLD", response.context)

    # --- List view context ---

    def test_list_view_passes_flag_context_vars(self):
        """event_list view passes EVENT_REVIEWS_DISPLAYED and THRESHOLD."""
        _set_flag("EVENT_REVIEWS_DISPLAYED", enabled=True)
        _set_flag("threshold.event_ratings_display", enabled=True, numeric_value=3)
        response = self.client.get("/events/")
        self.assertIn("EVENT_REVIEWS_DISPLAYED", response.context)
        self.assertIn("EVENT_RATING_THRESHOLD", response.context)
