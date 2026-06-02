"""
TDD tests for kb-m69.9: ClaimIntentAdmin — approve + reject actions.

RED phase: written BEFORE implementation.

Coverage:
(A) ClaimIntentAdmin is registered in Django admin
(B) approve action creates ProfileClaim with verified_method='admin_review',
    sets resolved_at on intent (atomic)
(C) approve on already-active claimant fails loud (ADR-008 D3)
(D) approve on already-resolved intent fails loud (ADR-008 D3)
(E) reject action sets rejected_at + rejected_by_admin + rejection_reason,
    no ProfileClaim
(F) is_pending computed: resolved_at IS NULL AND rejected_at IS NULL
(G) list_display includes user, profile, created_at, is_pending
(H) list_filter on pending/resolved/rejected
"""

import pytest
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.utils import timezone

from organizers.models import ClaimIntent, Profile, ProfileClaim

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user(db):
    return User.objects.create_superuser(username="admin_test", email="admin_test@example.com", password="adminpass")


@pytest.fixture
def regular_user(db):
    return User.objects.create_user(username="claimer_ci", email="claimer_ci@example.com", password="x")


@pytest.fixture
def profile(db):
    return Profile.objects.create(name="Test CI Profile", slug="test-ci-profile")


@pytest.fixture
def pending_intent(db, regular_user, profile):
    return ClaimIntent.objects.create(user=regular_user, profile=profile)


# ---------------------------------------------------------------------------
# (A) Registration
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_intent_admin_registered():
    """ClaimIntentAdmin is registered in Django admin."""
    from organizers.admin import ClaimIntentAdmin

    assert ClaimIntent in admin.site._registry, "ClaimIntent not registered in admin"
    assert isinstance(admin.site._registry[ClaimIntent], ClaimIntentAdmin)


# ---------------------------------------------------------------------------
# (B) Approve action: creates ProfileClaim, sets resolved_at
# ---------------------------------------------------------------------------


def make_request(admin_user):
    from django.contrib.messages.storage.fallback import FallbackStorage
    from django.test import RequestFactory

    rf = RequestFactory()
    request = rf.post("/admin/organizers/claimintent/")
    request.user = admin_user
    request.session = "session"
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_approve_creates_profile_claim(admin_user, regular_user, profile, pending_intent):
    """Approve action creates a ProfileClaim with verified_method='admin_review'."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    request = make_request(admin_user)

    queryset = ClaimIntent.objects.filter(pk=pending_intent.pk)
    intent_admin.approve_claim(request, queryset)

    # ProfileClaim should be created
    assert ProfileClaim.objects.filter(
        profile=profile,
        user=regular_user,
        verified_method="admin_review",
    ).exists()

    # Intent resolved_at should be set
    pending_intent.refresh_from_db()
    assert pending_intent.resolved_at is not None


@pytest.mark.django_db
def test_approve_sets_verified_by_admin(admin_user, regular_user, profile, pending_intent):
    """Approve action sets verified_by_admin to the admin username."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    request = make_request(admin_user)

    queryset = ClaimIntent.objects.filter(pk=pending_intent.pk)
    intent_admin.approve_claim(request, queryset)

    claim = ProfileClaim.objects.get(profile=profile, user=regular_user)
    assert claim.verified_by_admin == admin_user.username


# ---------------------------------------------------------------------------
# (C) Approve fails loud if user is already active claimant (ADR-008 D3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_fails_loud_on_duplicate_active_claimant(admin_user, regular_user, profile, pending_intent):
    """Approve on a user who is already an active claimant fails loud — no duplicate
    ProfileClaim."""
    from organizers.admin import ClaimIntentAdmin

    # Pre-create an active ProfileClaim
    ProfileClaim.objects.create(
        profile=profile,
        user=regular_user,
        verified_method="email_domain",
        role="admin",
    )

    request = make_request(admin_user)
    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)

    queryset = ClaimIntent.objects.filter(pk=pending_intent.pk)
    intent_admin.approve_claim(request, queryset)

    # No additional ProfileClaim should be created (unique_together enforced)
    assert ProfileClaim.objects.filter(profile=profile, user=regular_user).count() == 1

    # Intent should NOT be resolved (action failed)
    pending_intent.refresh_from_db()
    assert pending_intent.resolved_at is None


# ---------------------------------------------------------------------------
# (D) Approve fails loud on already-resolved intent (ADR-008 D3)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_approve_fails_loud_on_already_resolved_intent(admin_user, regular_user, profile):
    """Approve on a resolved intent fails loud — no new ProfileClaim."""
    from organizers.admin import ClaimIntentAdmin

    # Intent already resolved
    resolved_intent = ClaimIntent.objects.create(
        user=regular_user,
        profile=profile,
        resolved_at=timezone.now(),
    )

    request = make_request(admin_user)
    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)

    queryset = ClaimIntent.objects.filter(pk=resolved_intent.pk)
    intent_admin.approve_claim(request, queryset)

    assert ProfileClaim.objects.filter(profile=profile, user=regular_user).count() == 0


# ---------------------------------------------------------------------------
# (E) Reject action: sets soft-delete fields, no ProfileClaim created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reject_sets_soft_delete_fields(admin_user, regular_user, profile, pending_intent):
    """Reject action sets rejected_at, rejected_by_admin, rejection_reason."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    request = make_request(admin_user)

    queryset = ClaimIntent.objects.filter(pk=pending_intent.pk)
    intent_admin.reject_claim(request, queryset)

    pending_intent.refresh_from_db()
    assert pending_intent.rejected_at is not None
    assert pending_intent.rejected_by_admin == admin_user


@pytest.mark.django_db
def test_reject_does_not_create_profile_claim(admin_user, regular_user, profile, pending_intent):
    """Reject action does NOT create a ProfileClaim row."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    request = make_request(admin_user)

    queryset = ClaimIntent.objects.filter(pk=pending_intent.pk)
    intent_admin.reject_claim(request, queryset)

    assert ProfileClaim.objects.filter(profile=profile, user=regular_user).count() == 0


# ---------------------------------------------------------------------------
# (F) is_pending computed property
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_is_pending_true_when_unresolved(admin_user, pending_intent):
    """is_pending returns True when resolved_at IS NULL and rejected_at IS NULL."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)

    assert intent_admin.is_pending(pending_intent) is True


@pytest.mark.django_db
def test_is_pending_false_when_resolved(admin_user, regular_user, profile):
    """is_pending returns False when resolved_at is set."""
    from organizers.admin import ClaimIntentAdmin

    intent = ClaimIntent.objects.create(
        user=regular_user,
        profile=profile,
        resolved_at=timezone.now(),
    )
    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    assert intent_admin.is_pending(intent) is False


@pytest.mark.django_db
def test_is_pending_false_when_rejected(admin_user, regular_user, profile):
    """is_pending returns False when rejected_at is set."""
    from organizers.admin import ClaimIntentAdmin

    intent = ClaimIntent.objects.create(
        user=regular_user,
        profile=profile,
        rejected_at=timezone.now(),
    )
    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)
    assert intent_admin.is_pending(intent) is False


# ---------------------------------------------------------------------------
# (G) list_display fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_intent_admin_list_display():
    """ClaimIntentAdmin list_display includes required fields."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)

    required = {"user", "profile", "created_at", "is_pending"}
    assert required.issubset(set(intent_admin.list_display)), (
        f"Missing from list_display: {required - set(intent_admin.list_display)}"
    )


# ---------------------------------------------------------------------------
# (H) list_filter
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_intent_admin_has_list_filter():
    """ClaimIntentAdmin has list_filter configured."""
    from organizers.admin import ClaimIntentAdmin

    site = AdminSite()
    intent_admin = ClaimIntentAdmin(ClaimIntent, site)

    assert intent_admin.list_filter, "list_filter should not be empty"
