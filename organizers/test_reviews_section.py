"""Tests for the organizer profile reviews section (bead kb-7s2).

Covers:
- sort=recent (default): order_by('-created_at')
- sort=highest: order_by('-rating', '-created_at')
- sort=lowest: order_by('rating', '-created_at')
- hidden reviews excluded from queryset
- section gate: rating_count >= threshold.organizer_ratings_display
- anonymous user sees section (PUBLIC_READ semantics)
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from organizers.models import Organizer
from reviews.models import Review

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def anon_client():
    return Client()


@pytest.fixture
def org(db):
    return Organizer.objects.create(
        name="Sort Test Organizer",
        slug="sort-test-org",
        status="approved",
    )


def _make_review(org, rating, body="", hidden=False):
    """Create a unique user and return a Review for the given org."""
    import uuid
    uid = uuid.uuid4().hex[:8]
    author = User.objects.create_user(
        username=f"rev_user_{uid}",
        email=f"rev_user_{uid}@example.com",
        password="testpass",
    )
    return Review.objects.create(
        author=author,
        organizer=org,
        rating=rating,
        body=body,
        hidden=hidden,
    )


# ---------------------------------------------------------------------------
# Tests: sort param
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_default_sort_is_recent(org):
    """No ?sort param → reviews context ordered by -created_at."""
    r1 = _make_review(org, rating=3, body="oldest")
    r2 = _make_review(org, rating=5, body="newest")
    # Set rating_count so the section is shown (threshold default=3)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    # newest created_at first
    assert reviews[0].pk == r2.pk
    assert reviews[1].pk == r1.pk


@pytest.mark.django_db
def test_sort_recent_explicit(org):
    """?sort=recent → ordered by -created_at."""
    r1 = _make_review(org, rating=3)
    r2 = _make_review(org, rating=5)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url, {"sort": "recent"})

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    assert reviews[0].pk == r2.pk
    assert reviews[1].pk == r1.pk


@pytest.mark.django_db
def test_sort_highest_orders_by_rating_desc(org):
    """?sort=highest → ordered by -rating, -created_at."""
    r_low = _make_review(org, rating=1)
    r_mid = _make_review(org, rating=3)
    r_high = _make_review(org, rating=5)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=3.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url, {"sort": "highest"})

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    assert reviews[0].pk == r_high.pk
    assert reviews[1].pk == r_mid.pk
    assert reviews[2].pk == r_low.pk


@pytest.mark.django_db
def test_sort_lowest_orders_by_rating_asc(org):
    """?sort=lowest → ordered by rating, -created_at."""
    r_low = _make_review(org, rating=1)
    r_mid = _make_review(org, rating=3)
    r_high = _make_review(org, rating=5)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=3.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url, {"sort": "lowest"})

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    assert reviews[0].pk == r_low.pk
    assert reviews[1].pk == r_mid.pk
    assert reviews[2].pk == r_high.pk


@pytest.mark.django_db
def test_invalid_sort_falls_back_to_recent(org):
    """Unknown ?sort value defaults to recent ordering."""
    r1 = _make_review(org, rating=3)
    r2 = _make_review(org, rating=5)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url, {"sort": "bogus"})

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    # newest first (recent)
    assert reviews[0].pk == r2.pk
    assert reviews[1].pk == r1.pk


# ---------------------------------------------------------------------------
# Tests: hidden reviews excluded
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hidden_reviews_excluded_from_queryset(org):
    """Reviews with hidden=True must not appear in the reviews context."""
    visible = _make_review(org, rating=4, body="visible")
    _make_review(org, rating=5, body="hidden", hidden=True)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    reviews = list(resp.context["reviews"])
    pks = [r.pk for r in reviews]
    assert visible.pk in pks
    # hidden review must NOT be present
    for r in reviews:
        assert r.hidden is False


# ---------------------------------------------------------------------------
# Tests: gate — rating_count vs threshold
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reviews_section_hidden_when_below_threshold(org, db):
    """rating_count < threshold → show_rating False, reviews section absent."""
    _make_review(org, rating=4)
    _make_review(org, rating=5)
    # Set count explicitly below default threshold (3)
    Organizer.objects.filter(pk=org.pk).update(rating_count=2, avg_rating=4.5)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.context["show_rating"] is False
    # The template must not show the reviews section
    content = resp.content.decode()
    assert "sort-test-org-reviews" not in content


@pytest.mark.django_db
def test_reviews_section_visible_when_at_threshold(org, db):
    """rating_count == threshold → show_rating True, reviews section present."""
    _make_review(org, rating=4)
    _make_review(org, rating=5)
    _make_review(org, rating=3)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.context["show_rating"] is True
    content = resp.content.decode()
    # The reviews section heading should be present
    assert "Reviews" in content


@pytest.mark.django_db
def test_reviews_section_visible_above_threshold(org, db):
    """rating_count > threshold → show_rating True."""
    for rating in [4, 5, 3, 4, 5]:
        _make_review(org, rating=rating)
    Organizer.objects.filter(pk=org.pk).update(rating_count=5, avg_rating=4.2)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    assert resp.context["show_rating"] is True


@pytest.mark.django_db
def test_gate_respects_db_threshold_flag(org, db):
    """Changing threshold.organizer_ratings_display DB flag changes gate behavior."""
    from a_core.models import FeatureFlag

    # Lower threshold to 2 via DB flag
    flag, _ = FeatureFlag.objects.get_or_create(
        key="threshold.organizer_ratings_display",
        defaults={"enabled": True, "numeric_value": 2},
    )
    if flag.numeric_value != 2:
        flag.numeric_value = 2
        flag.save()

    _make_review(org, rating=4)
    _make_review(org, rating=5)
    Organizer.objects.filter(pk=org.pk).update(rating_count=2, avg_rating=4.5)
    org.refresh_from_db()

    client = Client()
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = client.get(url)

    assert resp.status_code == 200
    # With threshold=2 and rating_count=2, should be visible
    assert resp.context["show_rating"] is True


# ---------------------------------------------------------------------------
# Tests: anonymous user sees section (PUBLIC_READ semantics)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_anonymous_user_sees_reviews_section(org, anon_client):
    """Anonymous users can see reviews section when above threshold."""
    _make_review(org, rating=4)
    _make_review(org, rating=5)
    _make_review(org, rating=3)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = anon_client.get(url)

    assert resp.status_code == 200
    assert resp.context["show_rating"] is True
    reviews = list(resp.context["reviews"])
    assert len(reviews) == 3


@pytest.mark.django_db
def test_anonymous_user_same_visibility_as_authenticated(org, db):
    """Anonymous and authenticated users receive identical reviews context."""
    _make_review(org, rating=4)
    _make_review(org, rating=5)
    _make_review(org, rating=3)
    Organizer.objects.filter(pk=org.pk).update(rating_count=3, avg_rating=4.0)
    org.refresh_from_db()

    url = reverse("organizer-profile", kwargs={"slug": org.slug})

    anon_resp = Client().get(url)

    # Create an approved user and log in
    auth_user = User.objects.create_user(
        username="auth_test", email="auth@example.com", password="testpass"
    )
    auth_user.is_approved = True
    auth_user.save()
    auth_client = Client()
    auth_client.force_login(auth_user)
    auth_resp = auth_client.get(url)

    anon_pks = [r.pk for r in anon_resp.context["reviews"]]
    auth_pks = [r.pk for r in auth_resp.context["reviews"]]
    assert anon_pks == auth_pks


# ---------------------------------------------------------------------------
# Tests: sort context key
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_sort_key_in_context_defaults_to_recent(org):
    """'sort' context key is 'recent' when no ?sort param given."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url)
    assert resp.status_code == 200
    assert resp.context["sort"] == "recent"


@pytest.mark.django_db
def test_sort_key_in_context_reflects_param(org):
    """'sort' context key matches the ?sort param value."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url, {"sort": "highest"})
    assert resp.status_code == 200
    assert resp.context["sort"] == "highest"


@pytest.mark.django_db
def test_sort_key_defaults_for_invalid_param(org):
    """'sort' context key is 'recent' for unknown ?sort values."""
    url = reverse("organizer-profile", kwargs={"slug": org.slug})
    resp = Client().get(url, {"sort": "garbage"})
    assert resp.status_code == 200
    assert resp.context["sort"] == "recent"
