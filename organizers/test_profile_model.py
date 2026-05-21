"""
TDD tests for kb-izj: Rename Organizer → Profile with kind discriminator.

RED phase: these tests are written BEFORE the implementation.
They describe the target state of the model after the rename.

Written per ADR-007 D1 (FIRM):
  - unified Profile model with kind discriminator (person/collective)
  - ProfileClaim through-model for M2M User claim (D5 revised 2026-05-21 per ADR-014 D1)
  - pronouns field
  - telegram_link (renamed from telegram_channel)
  - all existing fields preserved

Note: claimed_by FK removed per kb-m69.3 (ADR-008 D1 no compat shim).
claim semantics now via ProfileClaim through-model (ADR-014 D1).
"""

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# RED: Profile model structure tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_profile_model_importable():
    """Profile is importable from organizers.models."""
    from organizers.models import Profile

    assert Profile is not None


@pytest.mark.django_db
def test_profile_create_collective():
    """Profile with kind='collective' can be created."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="IKSK",
        slug="iksk",
        kind="collective",
    )
    assert p.pk is not None
    assert p.kind == "collective"
    assert p.name == "IKSK"


@pytest.mark.django_db
def test_profile_create_person():
    """Profile with kind='person' can be created."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="Lavinia",
        slug="lavinia",
        kind="person",
        pronouns="she/her",
    )
    assert p.pk is not None
    assert p.kind == "person"
    assert p.pronouns == "she/her"


@pytest.mark.django_db
def test_profile_default_kind_is_collective():
    """Profile default kind is 'collective'."""
    from organizers.models import Profile

    p = Profile.objects.create(name="Test Org", slug="test-org")
    assert p.kind == "collective"


@pytest.mark.django_db
def test_profile_telegram_link_field_exists():
    """Profile has telegram_link field (renamed from telegram_channel)."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="IKSK",
        slug="iksk-tg",
        kind="collective",
        telegram_link="@iksk_channel",
    )
    assert p.telegram_link == "@iksk_channel"


@pytest.mark.django_db
def test_profile_no_telegram_channel_field():
    """Profile does NOT have a telegram_channel field (renamed to telegram_link)."""
    from organizers.models import Profile

    assert not hasattr(Profile, "telegram_channel")


@pytest.mark.django_db
def test_profile_pronouns_blank_by_default():
    """Profile pronouns field defaults to blank string."""
    from organizers.models import Profile

    p = Profile.objects.create(name="No Pronouns", slug="no-pronouns")
    assert p.pronouns == ""


@pytest.mark.django_db
def test_profile_no_claimed_by_field():
    """Profile no longer has claimed_by FK — replaced by ProfileClaim through-model (ADR-014 D1)."""
    from organizers.models import Profile

    p = Profile.objects.create(name="Unclaimed", slug="unclaimed")
    assert not hasattr(p, "claimed_by")


@pytest.mark.django_db
def test_profile_claimants_m2m_via_profile_claim():
    """Profile.claimants M2M via ProfileClaim works; user.claimed_profiles reverse works."""
    from organizers.models import Profile, ProfileClaim

    user = User.objects.create_user(
        username="claimant",
        email="claimant@example.com",
        password="x",
    )
    p = Profile.objects.create(
        name="Claimed Profile",
        slug="claimed-profile",
        kind="person",
    )
    ProfileClaim.objects.create(
        profile=p,
        user=user,
        verified_method="admin_legacy",
        role="admin",
    )
    assert user in p.claimants.all()
    assert p in user.claimed_profiles.all()


@pytest.mark.django_db
def test_profile_is_claimed_false_unclaimed():
    """Profile.is_claimed is False when there are no ProfileClaim rows."""
    from organizers.models import Profile

    p = Profile.objects.create(name="Unclaimed2", slug="unclaimed2")
    assert p.is_claimed is False


@pytest.mark.django_db
def test_profile_str_returns_name():
    """Profile.__str__ returns the name."""
    from organizers.models import Profile

    p = Profile.objects.create(name="KACHENKA", slug="kachenka")
    assert str(p) == "KACHENKA"


@pytest.mark.django_db
def test_profile_preserves_status_field():
    """Profile has status field with candidate/approved/suspended choices."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="Status Test", slug="status-test", status="approved"
    )
    assert p.status == "approved"


@pytest.mark.django_db
def test_profile_preserves_verified_badge_field():
    """Profile has verified_badge BooleanField."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="Badge Test", slug="badge-test", verified_badge=True
    )
    assert p.verified_badge is True


@pytest.mark.django_db
def test_profile_preserves_consent_fields():
    """Profile preserves consent_recorded_at, consent_method, consent_notes."""
    from django.utils import timezone

    from organizers.models import Profile

    now = timezone.now()
    p = Profile.objects.create(
        name="Consent Test",
        slug="consent-test",
        consent_recorded_at=now,
        consent_method="legitimate_interest",
        consent_notes="LIA completed",
    )
    assert p.consent_recorded_at is not None
    assert p.consent_method == "legitimate_interest"
    assert p.consent_notes == "LIA completed"


@pytest.mark.django_db
def test_profile_preserves_aggregate_fields():
    """Profile preserves hidden, follower_count, avg_rating, rating_count."""
    from organizers.models import Profile

    p = Profile.objects.create(
        name="Aggregate Test",
        slug="aggregate-test",
        hidden=False,
        follower_count=5,
        avg_rating=4.5,
        rating_count=10,
    )
    assert p.follower_count == 5
    assert p.avg_rating == 4.5
    assert p.rating_count == 10


@pytest.mark.django_db
def test_profile_manager_visible():
    """ProfileManager.visible() filters out hidden profiles."""
    from organizers.models import Profile

    Profile.objects.create(name="Visible", slug="visible-prof", hidden=False)
    Profile.objects.create(name="Hidden", slug="hidden-prof", hidden=True)
    visible = list(Profile.objects.visible())
    names = [p.name for p in visible]
    assert "Visible" in names
    assert "Hidden" not in names


@pytest.mark.django_db
def test_event_organizer_fk_targets_profile():
    """Event.organizer FK targets organizers.Profile (not Organizer)."""
    from django.utils import timezone

    from events.models import Event
    from organizers.models import Profile

    p = Profile.objects.create(name="Event Org", slug="event-org", status="approved")
    event = Event.objects.create(
        title="Test Event",
        slug="test-event",
        organizer=p,
        start=timezone.now(),
    )
    assert event.organizer == p
    # organizer_id no longer exists (FK removed); verify via EventOrganizer
    from events.models import EventOrganizer
    assert EventOrganizer.objects.filter(
        event=event, profile=p, is_primary=True
    ).exists()


@pytest.mark.django_db
def test_profile_reverse_events_queryset():
    """profile.events.all() returns events related to this profile."""
    from django.utils import timezone

    from events.models import Event
    from organizers.models import Profile

    p = Profile.objects.create(
        name="Reverse Org", slug="reverse-org", status="approved"
    )
    event = Event.objects.create(
        title="Reverse Event",
        slug="reverse-event",
        organizer=p,
        start=timezone.now(),
    )
    assert event in p.events.all()


@pytest.mark.django_db
def test_follow_model_works_with_profile():
    """Follow model works and its .profile FK points to Profile."""
    from organizers.models import Follow, Profile

    user = User.objects.create_user(
        username="followtest2",
        email="ft2@example.com",
        password="x",
    )
    p = Profile.objects.create(
        name="Follow Target", slug="follow-target", status="approved"
    )
    follow = Follow.objects.create(user=user, profile=p)
    assert follow.profile == p
