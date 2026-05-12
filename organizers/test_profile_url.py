"""
TDD tests for kb-ltr: Profile public page at /p/<slug>/ + redirect /o/<slug>/.

RED phase: these tests are written BEFORE the implementation.
They describe the target URL routing state after the change.

Acceptance clauses covered:
  Clause 1: GET /p/<slug>/ for approved+visible Profile → 200
  Clause 2: GET /o/<slug>/ → 301 (permanent redirect)
  Clause 3: Query string preserved through the 301
  Clause 4: reverse('organizer-profile', slug=x) == '/p/x/'
  Clause 5: /o/<slug>/follow/ still routes correctly (not swallowed by redirect)
  Clause 6: follow path takes precedence over redirect path in URL resolution
  Clause 8: hidden or non-approved Profile → 404 at /p/
"""

import pytest
from django.test import Client
from django.urls import reverse

from organizers.models import Profile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_profile(db):
    return Profile.objects.create(
        name="Test Org",
        slug="test-org",
        status="approved",
        hidden=False,
    )


@pytest.fixture
def hidden_profile(db):
    return Profile.objects.create(
        name="Hidden Org",
        slug="hidden-org",
        status="approved",
        hidden=True,
    )


@pytest.fixture
def unapproved_profile(db):
    return Profile.objects.create(
        name="Candidate Org",
        slug="candidate-org",
        status="candidate",
        hidden=False,
    )


# ---------------------------------------------------------------------------
# Clause 1: GET /p/<slug>/ → 200 for approved+visible profile
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_p_slug_returns_200_for_approved_visible(approved_profile):
    """Clause 1: /p/<slug>/ returns 200 for approved, visible profile."""
    client = Client()
    response = client.get(f"/p/{approved_profile.slug}/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Clause 2: GET /o/<slug>/ → 301 permanent redirect
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_o_slug_returns_301(approved_profile):
    """Clause 2: /o/<slug>/ returns 301 (permanent redirect)."""
    client = Client()
    response = client.get(f"/o/{approved_profile.slug}/", follow=False)
    assert response.status_code == 301


@pytest.mark.django_db
def test_o_slug_redirects_to_p_slug(approved_profile):
    """Clause 2: /o/<slug>/ redirect Location points to /p/<slug>/."""
    client = Client()
    response = client.get(f"/o/{approved_profile.slug}/", follow=False)
    assert response["Location"] == f"/p/{approved_profile.slug}/"


# ---------------------------------------------------------------------------
# Clause 3: Query string preserved through 301
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_o_slug_preserves_query_string_in_redirect(approved_profile):
    """Clause 3: /o/<slug>/?k=v redirect preserves the query string."""
    client = Client()
    qs = "event_sort=lowest_rated&sort=highest"
    response = client.get(f"/o/{approved_profile.slug}/?{qs}", follow=False)
    assert response.status_code == 301
    location = response["Location"]
    assert "event_sort=lowest_rated" in location
    assert "sort=highest" in location


@pytest.mark.django_db
def test_o_slug_no_query_string_location_clean(approved_profile):
    """Clause 3 (edge): /o/<slug>/ with no query string → Location has no '?'."""
    client = Client()
    response = client.get(f"/o/{approved_profile.slug}/", follow=False)
    assert response.status_code == 301
    assert "?" not in response["Location"]


# ---------------------------------------------------------------------------
# Clause 4: reverse('organizer-profile') resolves to /p/<slug>/
# ---------------------------------------------------------------------------


def test_reverse_organizer_profile_resolves_to_p_path():
    """Clause 4: reverse('organizer-profile', slug='x') == '/p/x/'."""
    url = reverse("organizer-profile", kwargs={"slug": "x"})
    assert url == "/p/x/"


# ---------------------------------------------------------------------------
# Clause 5+6: /o/<slug>/follow/ NOT swallowed by redirect
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_follow_url_not_affected_by_redirect(approved_profile):
    """Clause 5: /o/<slug>/follow/ is a distinct path from /o/<slug>/ redirect.
    The follow URL must resolve to organizer-follow (not profile-legacy-redirect).
    """
    url = reverse("organizer-follow", kwargs={"slug": approved_profile.slug})
    assert url == f"/o/{approved_profile.slug}/follow/"


@pytest.mark.django_db
def test_follow_url_does_not_return_301(approved_profile):
    """Clause 6: GET /o/<slug>/follow/ should NOT be a 301 redirect.
    (It requires POST; GET returns 405, not 301 — proving follow path is separate.)
    """
    client = Client()
    # GET to a POST-only view should return 405, not a redirect
    response = client.get(f"/o/{approved_profile.slug}/follow/", follow=False)
    assert response.status_code != 301


# ---------------------------------------------------------------------------
# Clause 8: hidden/non-approved profile → 404 at /p/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_p_slug_returns_404_for_hidden_profile(hidden_profile):
    """Clause 8: /p/<slug>/ returns 404 for a hidden profile."""
    client = Client()
    response = client.get(f"/p/{hidden_profile.slug}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_p_slug_returns_404_for_unapproved_profile(unapproved_profile):
    """Clause 8: /p/<slug>/ returns 404 for a non-approved profile."""
    client = Client()
    response = client.get(f"/p/{unapproved_profile.slug}/")
    assert response.status_code == 404
