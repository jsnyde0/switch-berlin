"""
TDD tests for kb-m69.8: ClaimIntent model.

RED phase: written BEFORE implementation.
Per ADR-014 D2 — admin-review fallback track captures the user's intent to claim.
Cheap-foresight cols: rejected_at, rejected_by_admin, rejection_reason, resolved_at.
Per ADR-003 — cheap foresight (nullable columns, no behavioral branching in V0).
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# Model importable + fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_claim_intent_importable():
    """ClaimIntent is importable from organizers.models."""
    from organizers.models import ClaimIntent

    assert ClaimIntent is not None


@pytest.mark.django_db
def test_claim_intent_fields_required():
    """ClaimIntent has user, profile, created_at (required per ADR-014 D2)."""
    from organizers.models import ClaimIntent, Profile

    user = User.objects.create_user(
        username="ci_user", email="ci_user@example.com", password="x"
    )
    profile = Profile.objects.create(name="CI Profile", slug="ci-profile")

    intent = ClaimIntent.objects.create(user=user, profile=profile)

    assert intent.user == user
    assert intent.profile == profile
    assert intent.created_at is not None


@pytest.mark.django_db
def test_claim_intent_cheap_foresight_fields_nullable():
    """ClaimIntent cheap-foresight cols are nullable/blank by default.

    Checks: rejected_at, rejected_by_admin, rejection_reason, resolved_at.
    """
    from organizers.models import ClaimIntent, Profile

    user = User.objects.create_user(
        username="ci_cf_user", email="ci_cf@example.com", password="x"
    )
    profile = Profile.objects.create(name="CF Profile", slug="cf-profile")

    intent = ClaimIntent.objects.create(user=user, profile=profile)

    assert intent.rejected_at is None
    assert intent.rejected_by_admin is None
    assert intent.rejection_reason == ""
    assert intent.resolved_at is None


@pytest.mark.django_db
def test_claim_intent_rejected_by_admin_is_user_fk():
    """ClaimIntent.rejected_by_admin is a FK to User (nullable)."""
    from organizers.models import ClaimIntent, Profile

    claimer = User.objects.create_user(
        username="ci_claimer", email="ci_claimer@example.com", password="x"
    )
    admin_user = User.objects.create_user(
        username="ci_admin", email="ci_admin@example.com", password="x"
    )
    profile = Profile.objects.create(name="Rejected Profile", slug="rejected-profile")

    from django.utils import timezone

    intent = ClaimIntent.objects.create(
        user=claimer,
        profile=profile,
        rejected_at=timezone.now(),
        rejected_by_admin=admin_user,
        rejection_reason="Insufficient evidence",
    )

    assert intent.rejected_by_admin == admin_user
    assert intent.rejection_reason == "Insufficient evidence"
    assert intent.rejected_at is not None


@pytest.mark.django_db
def test_claim_intent_str():
    """ClaimIntent __str__ is informative."""
    from organizers.models import ClaimIntent, Profile

    user = User.objects.create_user(
        username="ci_str_user", email="ci_str@example.com", password="x"
    )
    profile = Profile.objects.create(name="STR Profile", slug="str-ci-profile")

    intent = ClaimIntent.objects.create(user=user, profile=profile)

    s = str(intent)
    assert "ci_str_user" in s or "ci_str@example.com" in s or "STR Profile" in s
