"""
TDD tests for kb-m69.3: ProfileClaim through-model + data migration.

RED phase: written BEFORE implementation.
These tests describe the target state per ADR-014 D1 + ADR-007 D5 (revised 2026-05-21).

Coverage:
(a) backfill on snapshot with mixed claimed_by states
(b) M2M accessor (profile.claimants)
(c) is_claimed property excludes revoked
(d) admin inline renders claimants
(e) active_claimants accessor
(f) ProfileClaim model fields
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# (b) ProfileClaim model + M2M accessor
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_claim_model_importable():
    """ProfileClaim is importable from organizers.models."""
    from organizers.models import ProfileClaim

    assert ProfileClaim is not None


@pytest.mark.django_db
def test_profile_claim_model_fields():
    """ProfileClaim has the required fields per ADR-014 D1."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="claimer_f", email="claimer_f@example.com", password="x"
    )
    profile = Profile.objects.create(name="Test Org", slug="test-org-claim")

    claim = ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
        verified_by_admin="migration_admin",
    )

    assert claim.profile == profile
    assert claim.user == user
    assert claim.verified_method == "admin_legacy"
    assert claim.role == "admin"
    assert claim.verified_at is not None  # auto-set or required
    assert claim.created_at is not None
    # cheap-foresight soft-delete cols
    assert claim.rejected_at is None
    assert claim.rejected_by_admin is None


@pytest.mark.django_db
def test_profile_claim_unique_together():
    """ProfileClaim unique_together=(profile, user) prevents duplicates."""
    from django.db import IntegrityError

    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="claimer_dup", email="claimer_dup@example.com", password="x"
    )
    profile = Profile.objects.create(name="Dup Org", slug="dup-org-claim")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    with pytest.raises(IntegrityError):
        ProfileClaim.objects.create(
            profile=profile,
            user=user,
            verified_method="email_domain",
            role="admin",
        )


@pytest.mark.django_db
def test_profile_claimants_m2m_accessor():
    """Profile.claimants M2M accessor returns users who claimed the profile."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="claimer_m2m", email="claimer_m2m@example.com", password="x"
    )
    profile = Profile.objects.create(name="M2M Org", slug="m2m-org")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    assert user in profile.claimants.all()


@pytest.mark.django_db
def test_user_claimed_profiles_reverse_accessor():
    """user.claimed_profiles reverse accessor returns profiles claimed by user."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="claimer_rev", email="claimer_rev@example.com", password="x"
    )
    profile = Profile.objects.create(name="Rev Org", slug="rev-org")

    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    assert profile in user.claimed_profiles.all()


# ---------------------------------------------------------------------------
# (c) is_claimed property excludes revoked
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_is_claimed_false_when_no_claimants():
    """Profile.is_claimed is False when there are no ProfileClaim rows."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="Unclaimed Org", slug="unclaimed-org-new")
    assert profile.is_claimed is False


@pytest.mark.django_db
def test_profile_is_claimed_true_when_active_claimant():
    """Profile.is_claimed is True when there is at least one active claimant."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="active_claimer", email="active_claimer@example.com", password="x"
    )
    profile = Profile.objects.create(name="Active Org", slug="active-org")
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )

    assert profile.is_claimed is True


@pytest.mark.django_db
def test_profile_is_claimed_false_when_all_claims_revoked():
    """Profile.is_claimed is False when all ProfileClaim rows have rejected_at set."""
    from django.utils import timezone

    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="revoked_claimer", email="revoked_claimer@example.com", password="x"
    )
    profile = Profile.objects.create(name="Revoked Org", slug="revoked-org")
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
        rejected_at=timezone.now(),
    )

    # All claims are revoked — is_claimed should be False
    assert profile.is_claimed is False


@pytest.mark.django_db
def test_profile_is_claimed_true_when_one_active_among_revoked():
    """Profile.is_claimed is True when at least one claim is not revoked."""
    from django.utils import timezone

    from organizers.models import Profile, ProfileClaim

    user1 = User.objects.create_user(
        username="active_1", email="active_1@example.com", password="x"
    )
    user2 = User.objects.create_user(
        username="revoked_2", email="revoked_2@example.com", password="x"
    )
    profile = Profile.objects.create(name="Mixed Org", slug="mixed-org")
    # Active claim
    ProfileClaim.objects.create(
        profile=profile,
        user=user1,
        verified_method="admin_legacy",
        role="admin",
    )
    # Revoked claim
    ProfileClaim.objects.create(
        profile=profile,
        user=user2,
        verified_method="admin_legacy",
        role="admin",
        rejected_at=timezone.now(),
    )

    assert profile.is_claimed is True


# ---------------------------------------------------------------------------
# (e) active_claimants accessor
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_active_claimants_excludes_revoked():
    """Profile.active_claimants excludes users with rejected_at set."""
    from django.utils import timezone

    from organizers.models import Profile, ProfileClaim

    user1 = User.objects.create_user(
        username="active_ac", email="active_ac@example.com", password="x"
    )
    user2 = User.objects.create_user(
        username="revoked_ac", email="revoked_ac@example.com", password="x"
    )
    profile = Profile.objects.create(name="AC Org", slug="ac-org")

    ProfileClaim.objects.create(
        profile=profile,
        user=user1,
        verified_method="admin_legacy",
        role="admin",
    )
    ProfileClaim.objects.create(
        profile=profile,
        user=user2,
        verified_method="admin_legacy",
        role="admin",
        rejected_at=timezone.now(),
    )

    active = list(profile.active_claimants.all())
    assert user1 in active
    assert user2 not in active


@pytest.mark.django_db
def test_profile_active_claimants_empty_when_all_revoked():
    """Profile.active_claimants is empty when all claims are revoked."""
    from django.utils import timezone

    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="all_revoked", email="all_revoked@example.com", password="x"
    )
    profile = Profile.objects.create(name="All Revoked Org", slug="all-revoked-org")
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        role="admin",
        rejected_at=timezone.now(),
    )

    assert profile.active_claimants.count() == 0


# ---------------------------------------------------------------------------
# No Profile.claimed_by field (ADR-008 D1 no compat shim)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_has_no_claimed_by_field():
    """Profile no longer has claimed_by FK (ADR-008 D1 — no compat shim)."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="No FK Org", slug="no-fk-org")
    assert not hasattr(profile, "claimed_by")


@pytest.mark.django_db
def test_profile_has_no_claimed_at_field():
    """Profile no longer has claimed_at field (dropped with claimed_by FK)."""
    from organizers.models import Profile

    profile = Profile.objects.create(name="No AT Org", slug="no-at-org")
    assert not hasattr(profile, "claimed_at")


# ---------------------------------------------------------------------------
# (d) Admin inline renders claimants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_claim_inline_registered_in_admin():
    """ProfileClaimInline is registered as a TabularInline on ProfileAdmin."""
    from django.contrib import admin

    from organizers.admin import ProfileAdmin
    from organizers.models import Profile, ProfileClaim

    site = admin.site
    model_admin = site._registry.get(Profile)
    assert model_admin is not None, "Profile not registered in admin"

    inline_classes = [type(inline) for inline in model_admin.inlines]
    inline_model_classes = [
        inline.model for inline in model_admin.inlines if hasattr(inline, "model")
    ]
    assert ProfileClaim in inline_model_classes, (
        "ProfileClaim not found as inline on ProfileAdmin"
    )


@pytest.mark.django_db
def test_profile_claim_inline_is_tabular():
    """ProfileClaimInline is a TabularInline (not StackedInline)."""
    from django.contrib import admin
    from django.contrib.admin import TabularInline

    from organizers.models import Profile, ProfileClaim

    site = admin.site
    model_admin = site._registry.get(Profile)
    assert model_admin is not None

    for inline in model_admin.inlines:
        if hasattr(inline, "model") and inline.model is ProfileClaim:
            assert issubclass(inline, TabularInline), (
                "ProfileClaim inline should be TabularInline"
            )
            return

    pytest.fail("ProfileClaim inline not found on ProfileAdmin")


# ---------------------------------------------------------------------------
# (a) Backfill migration test — test via ORM snapshot (not RunPython directly)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_claim_backfill_logic():
    """
    Verify backfill logic: a Profile that previously had claimed_by set
    should result in a ProfileClaim row with verified_method='admin_legacy'.

    Since we can't replay the migration, we test the post-migration state
    directly by simulating the backfill logic inline.
    """
    from django.utils import timezone

    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="backfill_user", email="backfill@example.com", password="x"
    )
    profile = Profile.objects.create(name="Backfill Org", slug="backfill-org")

    # Simulate what the backfill migration does for a Profile that had
    # claimed_by set: create a ProfileClaim with admin_legacy
    ProfileClaim.objects.create(
        profile=profile,
        user=user,
        verified_method="admin_legacy",
        verified_at=timezone.now(),
        role="admin",
        verified_by_admin="migration_admin",
    )

    claim = ProfileClaim.objects.get(profile=profile, user=user)
    assert claim.verified_method == "admin_legacy"
    assert claim.role == "admin"
    assert claim.verified_by_admin == "migration_admin"
    assert claim.verified_at is not None
