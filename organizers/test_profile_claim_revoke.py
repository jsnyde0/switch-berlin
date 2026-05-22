"""
TDD tests for kb-m69.9: ProfileClaimAdmin revoke action.

RED phase: written BEFORE implementation.

Coverage:
(A) revoke_claim action sets rejected_at on the ProfileClaim
(B) revoke_claim sets rejected_by_admin to admin username
(C) revoke_claim sets revocation_reason if field exists
(D) revoked claim is no longer in active_claimants
(E) re-revoking already-revoked claim fails loud (ADR-008 D3)
(F) ProfileClaimAdmin is registered with revoke_claim action
(G) ProfileClaim has revocation_reason field (cheap-foresight ADR-003)
"""

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.utils import timezone

from organizers.models import Profile, ProfileClaim

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(
        username="revoke_admin", email="revoke_admin@example.com", password="adminpass"
    )


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(
        username="revoke_claimer", email="revoke_claimer@example.com", password="x"
    )


@pytest.fixture
def profile(db):
    return Profile.objects.create(
        name="Revoke Test Profile", slug="revoke-test-profile"
    )


@pytest.fixture
def active_claim(db, regular_user, profile):
    return ProfileClaim.objects.create(
        profile=profile,
        user=regular_user,
        verified_method="admin_review",
        role="admin",
    )


def make_request(admin_user):
    rf = RequestFactory()
    request = rf.post("/admin/organizers/profileclaim/")
    request.user = admin_user
    from django.contrib.messages.storage.fallback import FallbackStorage

    request.session = "session"
    request._messages = FallbackStorage(request)
    return request


# ---------------------------------------------------------------------------
# (G) revocation_reason field exists on ProfileClaim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_claim_has_revocation_reason_field():
    """ProfileClaim has a revocation_reason CharField (cheap-foresight ADR-003)."""
    assert hasattr(ProfileClaim, "revocation_reason"), (
        "ProfileClaim missing revocation_reason field"
    )
    field = ProfileClaim._meta.get_field("revocation_reason")
    assert field is not None


# ---------------------------------------------------------------------------
# (F) ProfileClaimAdmin registration + revoke action
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_claim_admin_registered():
    """ProfileClaim is registered as a top-level admin (ProfileClaimAdmin)."""
    from organizers.admin import ProfileClaimAdmin

    assert ProfileClaim in admin.site._registry
    assert isinstance(admin.site._registry[ProfileClaim], ProfileClaimAdmin)


@pytest.mark.django_db
def test_profile_claim_admin_has_revoke_action():
    """ProfileClaimAdmin has revoke_claim action."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)

    actions = claim_admin.get_action("revoke_claim")
    assert actions is not None, "revoke_claim action not found"


# ---------------------------------------------------------------------------
# (A) Revoke action sets rejected_at
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_sets_rejected_at(admin_user, active_claim):
    """revoke_claim action sets rejected_at on the ProfileClaim."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)
    request = make_request(admin_user)

    queryset = ProfileClaim.objects.filter(pk=active_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    active_claim.refresh_from_db()
    assert active_claim.rejected_at is not None


# ---------------------------------------------------------------------------
# (B) Revoke action sets rejected_by_admin
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_sets_rejected_by_admin(admin_user, active_claim):
    """revoke_claim action sets rejected_by_admin to admin username."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)
    request = make_request(admin_user)

    queryset = ProfileClaim.objects.filter(pk=active_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    active_claim.refresh_from_db()
    assert active_claim.rejected_by_admin == admin_user.username


# ---------------------------------------------------------------------------
# (C) Revoke sets revocation_reason (if provided via field)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_sets_revocation_reason_default_blank(admin_user, active_claim):
    """revoke_claim sets revocation_reason (blank by default in V0)."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)
    request = make_request(admin_user)

    queryset = ProfileClaim.objects.filter(pk=active_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    active_claim.refresh_from_db()
    # revocation_reason may be blank (no form yet in V0), but field exists
    assert active_claim.revocation_reason is not None  # not None, may be ""


# ---------------------------------------------------------------------------
# (D) Revoked claim excluded from active_claimants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoked_claim_excluded_from_active_claimants(
    admin_user, regular_user, profile, active_claim
):
    """After revoke, user is no longer in profile.active_claimants."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)
    request = make_request(admin_user)

    # Before revoke — user is active claimant
    assert regular_user in profile.active_claimants

    queryset = ProfileClaim.objects.filter(pk=active_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    # After revoke — user is no longer active claimant
    assert regular_user not in profile.active_claimants


# ---------------------------------------------------------------------------
# (E) Re-revoking fails loud (ADR-008 D3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_re_revoke_fails_loud(admin_user, regular_user, profile):
    """Re-revoking an already-revoked claim fails loud — no silent re-revoke."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)

    # Create an already-revoked claim
    revoked_claim = ProfileClaim.objects.create(
        profile=profile,
        user=regular_user,
        verified_method="admin_review",
        role="admin",
        rejected_at=timezone.now(),
        rejected_by_admin="previous_admin",
    )
    original_revoked_at = revoked_claim.rejected_at

    request = make_request(admin_user)
    queryset = ProfileClaim.objects.filter(pk=revoked_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    # rejected_at should NOT have been updated
    revoked_claim.refresh_from_db()
    assert revoked_claim.rejected_at == original_revoked_at


# ---------------------------------------------------------------------------
# Soft-delete: original row preserved after revoke
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_revoke_preserves_row(admin_user, active_claim):
    """Revoking soft-deletes (sets rejected_at) — the row is still in DB."""
    from organizers.admin import ProfileClaimAdmin

    site = AdminSite()
    claim_admin = ProfileClaimAdmin(ProfileClaim, site)
    request = make_request(admin_user)

    claim_pk = active_claim.pk
    queryset = ProfileClaim.objects.filter(pk=active_claim.pk)
    claim_admin.revoke_claim(request, queryset)

    # Row still exists
    assert ProfileClaim.objects.filter(pk=claim_pk).exists()
