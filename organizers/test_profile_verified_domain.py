"""
TDD tests for kb-m69.4: Profile.verified_domain field.

RED phase: written BEFORE implementation.
Per ADR-014 D2 (verified_domain admin-set, fast-path) + ADR-008 (fail loud).

Coverage:
(a) verified_domain field exists with correct type/constraints
(b) verified_domain is None/blank by default
(c) admin can set verified_domain
(d) field is queryable by domain
(e) Profile.is_claimed still works after adding verified_domain (regression guard)
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# (a) verified_domain field existence and type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_has_verified_domain_field():
    """Profile has a verified_domain field."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="Domain Org", slug="domain-org")
    assert hasattr(profile, "verified_domain")


@pytest.mark.django_db
def test_profile_verified_domain_field_type():
    """Profile.verified_domain is a CharField (string-type)."""
    from django.db.models import CharField

    from organizers.models import Profile

    field = Profile._meta.get_field("verified_domain")
    assert isinstance(field, CharField), f"Expected CharField, got {type(field)}"


@pytest.mark.django_db
def test_profile_verified_domain_field_constraints():
    """Profile.verified_domain max_length=253, blank=True, null=True, db_index=True."""
    from organizers.models import Profile

    field = Profile._meta.get_field("verified_domain")
    assert field.max_length == 253
    assert field.blank is True
    assert field.null is True
    assert field.db_index is True


# ---------------------------------------------------------------------------
# (b) verified_domain is None/blank by default
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_verified_domain_defaults_to_none():
    """Profile.verified_domain defaults to None (not set)."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="Default Domain Org", slug="default-domain-org")
    assert profile.verified_domain is None


# ---------------------------------------------------------------------------
# (c) admin can set verified_domain
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_verified_domain_can_be_set():
    """Profile.verified_domain can be set by admin."""
    from organizers.models import Profile

    profile = Profile.objects.create(
        name="Set Domain Org",
        slug="set-domain-org",
        verified_domain="example.org",
    )
    assert profile.verified_domain == "example.org"


@pytest.mark.django_db
def test_profile_verified_domain_can_be_updated():
    """Profile.verified_domain can be updated."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="Update Domain Org", slug="update-domain-org")
    profile.verified_domain = "updated.example.org"
    profile.save()

    profile.refresh_from_db()
    assert profile.verified_domain == "updated.example.org"


# ---------------------------------------------------------------------------
# (d) field is queryable by domain
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_verified_domain_queryable():
    """Profile objects can be filtered by verified_domain."""
    from organizers.models import Profile

    Profile.objects.create(
        name="Queryable Org A",
        slug="queryable-org-a",
        verified_domain="query-a.example.org",
    )
    Profile.objects.create(
        name="Queryable Org B",
        slug="queryable-org-b",
        verified_domain="query-b.example.org",
    )
    Profile.objects.create(
        name="No Domain Org",
        slug="no-domain-org",
    )

    results = Profile.objects.filter(verified_domain="query-a.example.org")
    assert results.count() == 1
    assert results.first().slug == "queryable-org-a"


@pytest.mark.django_db
def test_profile_verified_domain_null_queryable():
    """Profile objects can be filtered for NULL verified_domain."""
    from organizers.models import Profile

    Profile.objects.create(
        name="Has Domain Org",
        slug="has-domain-org",
        verified_domain="has-domain.example.org",
    )
    Profile.objects.create(
        name="Null Domain Org",
        slug="null-domain-org",
    )

    null_results = Profile.objects.filter(verified_domain__isnull=True)
    # The count will include the profile with no domain, plus others in the test DB
    # Just check the specific slug is in the results
    slugs = list(null_results.values_list("slug", flat=True))
    assert "null-domain-org" in slugs
    assert "has-domain-org" not in slugs


# ---------------------------------------------------------------------------
# (e) Regression guard: is_claimed still works
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_is_claimed_still_works_after_verified_domain():
    """Profile.is_claimed still passes through active_claimants.exists()
    (regression guard)."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(username="vd_claimer", email="vd_claimer@example.com", password="x")
    profile = Profile.objects.create(
        name="VD Claimed Org",
        slug="vd-claimed-org",
        verified_domain="claimed.example.org",
    )
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    assert profile.is_claimed is True

    # Unclaimed profile with domain also not claimed
    profile2 = Profile.objects.create(
        name="VD Unclaimed Org",
        slug="vd-unclaimed-org",
        verified_domain="unclaimed.example.org",
    )
    assert profile2.is_claimed is False
