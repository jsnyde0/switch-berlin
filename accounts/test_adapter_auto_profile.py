"""
TDD tests for kb-m69.4: auto-Profile(kind=person) on signup.

Updated kb-m69.12: NoSignupAdapter deleted per ADR-008 D1; tests now use
OpenSignupAdapter (the active adapter per ACCOUNT_ADAPTER in settings).

Per ADR-013 D2 (two signup paths), ADR-007 D1 (unified Profile with kind),
ADR-008 D2 (adapter not signal — one clear path), ADR-008 D3 (fail loud).

Coverage:
(a) signup creates exactly one Profile(kind=person) + one
    ProfileClaim(verified_method='auto_self')
(b) ProfileClaim has verified_at set (not NULL)
(c) Profile+ProfileClaim creation is atomic with User creation (DB constraint failure
    rolls back)
(d) Idempotency: running _create_owned_profile twice doesn't create duplicates
(e) Profile name is derived from user.get_full_name() falling back to email
(f) _create_owned_profile is accessible as a named method on the adapter
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# (a) signup creates exactly one Profile + ProfileClaim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_created_on_save_user():
    """
    Calling adapter._create_owned_profile for a new user creates a
    Profile(kind='person') and a ProfileClaim(verified_method='auto_self').
    """
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile, ProfileClaim

    adapter = OpenSignupAdapter()

    user = User.objects.create_user(
        username="auto_profile_user",
        email="auto@example.com",
        password="x",
    )
    adapter._create_owned_profile(user)

    profiles = Profile.objects.filter(claimants=user)
    assert profiles.count() == 1
    profile = profiles.first()
    assert profile.kind == "person"

    claims = ProfileClaim.objects.filter(profile=profile, user=user)
    assert claims.count() == 1
    claim = claims.first()
    assert claim.verified_method == "auto_self"


@pytest.mark.django_db
def test_save_user_creates_profile_and_claim():
    """
    _create_owned_profile creates a Profile(kind='person') AND a ProfileClaim
    for the new user (verified_method='auto_self').
    """
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile, ProfileClaim

    adapter = OpenSignupAdapter()

    user = User.objects.create_user(
        username="full_save_user",
        email="fullsave@example.com",
        password="x",
    )

    adapter._create_owned_profile(user)

    assert Profile.objects.filter(claimants=user, kind="person").count() == 1
    assert (
        ProfileClaim.objects.filter(user=user, verified_method="auto_self").count() == 1
    )


# ---------------------------------------------------------------------------
# (b) ProfileClaim has verified_at set
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_claim_has_verified_at():
    """ProfileClaim created by _create_owned_profile has verified_at set (not NULL)."""
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import ProfileClaim

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="vat_user", email="vat@example.com", password="x"
    )
    adapter._create_owned_profile(user)

    claim = ProfileClaim.objects.get(user=user, verified_method="auto_self")
    assert claim.verified_at is not None


# ---------------------------------------------------------------------------
# (c) Atomicity: if Profile insert fails, no orphan objects
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_creation_is_atomic():
    """
    If Profile creation fails inside _create_owned_profile, no Profile or ProfileClaim
    rows are left behind (transaction rolls back).
    """
    from unittest.mock import patch

    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="atomic_user", email="atomic@example.com", password="x"
    )

    with pytest.raises(RuntimeError):
        with patch(
            "organizers.models.ProfileClaim.objects.create",
            side_effect=RuntimeError("DB failure"),
        ):
            adapter._create_owned_profile(user)

    # Profile should NOT persist because the transaction rolled back
    assert Profile.objects.filter(claimants=user).count() == 0


# ---------------------------------------------------------------------------
# (d) Idempotency: duplicate call doesn't create duplicate Profile/Claim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_creation_is_idempotent():
    """
    Calling _create_owned_profile twice for the same user doesn't create duplicates.
    Second call should be a no-op.
    """
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile, ProfileClaim

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="idempotent_user", email="idempotent@example.com", password="x"
    )

    adapter._create_owned_profile(user)
    adapter._create_owned_profile(user)  # second call should be a no-op

    assert Profile.objects.filter(claimants=user).count() == 1
    assert (
        ProfileClaim.objects.filter(user=user, verified_method="auto_self").count() == 1
    )


# ---------------------------------------------------------------------------
# (e) Profile name derived from full_name → email fallback
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_name_from_full_name():
    """Profile.name is set from user.get_full_name() when available."""
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="fullname_user",
        email="fullname@example.com",
        password="x",
        first_name="Jane",
        last_name="Doe",
    )
    adapter._create_owned_profile(user)

    profile = Profile.objects.get(claimants=user)
    assert profile.name == "Jane Doe"


@pytest.mark.django_db
def test_auto_profile_name_falls_back_to_email():
    """Profile.name falls back to user.email when get_full_name() is empty."""
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="nofullname_user",
        email="nofullname@example.com",
        password="x",
    )
    adapter._create_owned_profile(user)

    profile = Profile.objects.get(claimants=user)
    assert profile.name == "nofullname@example.com"


# ---------------------------------------------------------------------------
# (f) _create_owned_profile is accessible as a named method on the adapter
# ---------------------------------------------------------------------------


def test_adapter_has_create_owned_profile_method():
    """OpenSignupAdapter has a _create_owned_profile method."""
    from accounts.adapter import OpenSignupAdapter

    adapter = OpenSignupAdapter()
    assert hasattr(adapter, "_create_owned_profile")
    assert callable(adapter._create_owned_profile)


# ---------------------------------------------------------------------------
# (g) Auto-created Profile has status='approved'
#     (Fix 4 — ADR-014 D1 + owner reachability)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_auto_profile_has_status_approved():
    """Auto-created Profile must have status='approved' so owner can view their profile.

    ADR-014 D1: auto_self ProfileClaim is already a verified ownership signal.
    Setting status='approved' makes the Profile visible to the owner (and others)
    via the organizer_profile view which filters by status='approved'.
    """
    from accounts.adapter import OpenSignupAdapter
    from organizers.models import Profile

    adapter = OpenSignupAdapter()
    user = User.objects.create_user(
        username="approved_status_user",
        email="approved_status@example.com",
        password="x",
    )
    adapter._create_owned_profile(user)

    profile = Profile.objects.get(claimants=user, kind="person")
    assert profile.status == "approved", (
        f"Auto-created Profile must have status='approved' so owner can view it;"
        f" got '{profile.status}'"
    )
