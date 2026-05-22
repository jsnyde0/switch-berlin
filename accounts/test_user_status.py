"""Tests for kb-m69.1: User.status ENUM replacing is_approved.

Also covers cheap-foresight fields (ADR-003).
TDD: all tests were written before implementation.
"""

import pytest

# ---------------------------------------------------------------------------
# User.status field
# ---------------------------------------------------------------------------


def test_user_has_status_field():
    """User model must have a status field (not is_approved)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="status_test")
    assert hasattr(user, "status"), "User has no status attribute"
    assert not hasattr(User, "is_approved") or not any(
        f.name == "is_approved" for f in User._meta.get_fields()
    ), "is_approved should be gone from User model"


def test_user_status_default_is_open():
    """User.status must default to 'open'."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="status_default")
    assert user.status == "open", (
        f"status should default to 'open', got {user.status!r}"
    )


def test_user_status_choices_are_correct():
    """User.status choices must include all four trust tiers."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    field = User._meta.get_field("status")
    choice_values = [c[0] for c in field.choices]
    assert "open" in choice_values, f"'open' not in choices: {choice_values}"
    assert "vouched" in choice_values, f"'vouched' not in choices: {choice_values}"
    assert "suspended_pending_investigation" in choice_values, (
        f"'suspended_pending_investigation' not in choices: {choice_values}"
    )
    assert "banned" in choice_values, f"'banned' not in choices: {choice_values}"


def test_user_has_no_is_approved_field():
    """is_approved field must be gone (ADR-008 D1 — no compat shim)."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    field_names = [f.name for f in User._meta.get_fields()]
    assert "is_approved" not in field_names, (
        f"is_approved should have been dropped, but it's still in fields: {field_names}"
    )


# ---------------------------------------------------------------------------
# Cheap-foresight fields (ADR-003)
# ---------------------------------------------------------------------------


def test_user_has_vouch_score_field():
    """User.vouch_score (FloatField, default=0.0) must exist."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="vouch_test")
    assert hasattr(user, "vouch_score"), "User has no vouch_score attribute"
    assert user.vouch_score == 0.0, (
        f"vouch_score should default to 0.0, got {user.vouch_score!r}"
    )


def test_user_has_personal_rating_field():
    """User.personal_rating (FloatField, nullable) must exist."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="rating_test")
    assert hasattr(user, "personal_rating"), "User has no personal_rating attribute"
    assert user.personal_rating is None, (
        f"personal_rating should default to None, got {user.personal_rating!r}"
    )


def test_user_has_invite_codes_remaining_field():
    """User.invite_codes_remaining (IntegerField, default=0) must exist."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User(username="invite_test")
    assert hasattr(user, "invite_codes_remaining"), (
        "User has no invite_codes_remaining attribute"
    )
    assert user.invite_codes_remaining == 0, (
        "invite_codes_remaining should default to 0, "
        f"got {user.invite_codes_remaining!r}"
    )


# ---------------------------------------------------------------------------
# DB round-trip tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_user_status_persists_to_db():
    """User.status can be saved and retrieved from DB."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="status_db", email="status_db@example.com", password="x"
    )
    assert user.status == "open"

    user.status = "vouched"
    user.save()

    fetched = User.objects.get(pk=user.pk)
    assert fetched.status == "vouched"


@pytest.mark.django_db
def test_user_vouch_score_persists_to_db():
    """User.vouch_score can be set and retrieved."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="vouch_db", email="vouch_db@example.com", password="x"
    )
    user.vouch_score = 3.14
    user.save()

    fetched = User.objects.get(pk=user.pk)
    assert abs(fetched.vouch_score - 3.14) < 0.001


@pytest.mark.django_db
def test_user_personal_rating_nullable_in_db():
    """User.personal_rating is nullable; None round-trips correctly."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="rating_db", email="rating_db@example.com", password="x"
    )
    assert user.personal_rating is None

    fetched = User.objects.get(pk=user.pk)
    assert fetched.personal_rating is None


@pytest.mark.django_db
def test_user_invite_codes_remaining_persists_to_db():
    """User.invite_codes_remaining can be updated and retrieved."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(
        username="invite_db", email="invite_db@example.com", password="x"
    )
    assert user.invite_codes_remaining == 0

    user.invite_codes_remaining = 3
    user.save()

    fetched = User.objects.get(pk=user.pk)
    assert fetched.invite_codes_remaining == 3


# ---------------------------------------------------------------------------
# Decorator behaviour at each status value
# ---------------------------------------------------------------------------


def test_approved_required_permits_staff_user():
    """approved_required decorator passes staff users regardless of status."""
    from django.http import HttpResponse
    from django.test import RequestFactory

    from accounts.decorators import approved_required

    factory = RequestFactory()
    request = factory.get("/")
    request.user = type(
        "User",
        (),
        {"is_staff": True, "is_authenticated": True, "status": "open"},
    )()

    @approved_required
    def my_view(req):
        return HttpResponse("ok")

    response = my_view(request)
    assert response.status_code == 200


def test_approved_required_permits_vouched_user():
    """approved_required decorator passes users with status='vouched'."""
    from django.http import HttpResponse
    from django.test import RequestFactory

    from accounts.decorators import approved_required

    factory = RequestFactory()
    request = factory.get("/")
    request.user = type(
        "User",
        (),
        {"is_staff": False, "is_authenticated": True, "status": "vouched"},
    )()

    @approved_required
    def my_view(req):
        return HttpResponse("ok")

    response = my_view(request)
    assert response.status_code == 200


def test_approved_required_blocks_open_user():
    """approved_required decorator returns 403 for status='open' non-staff."""
    from django.test import RequestFactory

    from accounts.decorators import approved_required

    factory = RequestFactory()
    request = factory.get("/")
    request.user = type(
        "User",
        (),
        {"is_staff": False, "is_authenticated": True, "status": "open"},
    )()

    @approved_required
    def my_view(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    response = my_view(request)
    assert response.status_code == 403


def test_approved_required_blocks_suspended_user():
    """approved_required returns 403 for status='suspended_pending_investigation'."""
    from django.test import RequestFactory

    from accounts.decorators import approved_required

    factory = RequestFactory()
    request = factory.get("/")
    request.user = type(
        "User",
        (),
        {
            "is_staff": False,
            "is_authenticated": True,
            "status": "suspended_pending_investigation",
        },
    )()

    @approved_required
    def my_view(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    response = my_view(request)
    assert response.status_code == 403


def test_approved_required_blocks_banned_user():
    """approved_required decorator returns 403 for status='banned'."""
    from django.test import RequestFactory

    from accounts.decorators import approved_required

    factory = RequestFactory()
    request = factory.get("/")
    request.user = type(
        "User",
        (),
        {"is_staff": False, "is_authenticated": True, "status": "banned"},
    )()

    @approved_required
    def my_view(req):
        from django.http import HttpResponse

        return HttpResponse("ok")

    response = my_view(request)
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin list_filter by status
# ---------------------------------------------------------------------------


def test_admin_list_filter_includes_status():
    """CustomUserAdmin must include 'status' in list_filter (not is_approved)."""
    from accounts.admin import CustomUserAdmin

    assert "status" in CustomUserAdmin.list_filter, (
        f"'status' not in list_filter: {CustomUserAdmin.list_filter}"
    )
    assert "is_approved" not in CustomUserAdmin.list_filter, (
        "'is_approved' should have been removed from list_filter"
    )


def test_admin_list_display_includes_status():
    """CustomUserAdmin must include 'status' in list_display."""
    from accounts.admin import CustomUserAdmin

    assert "status" in CustomUserAdmin.list_display, (
        f"'status' not in list_display: {CustomUserAdmin.list_display}"
    )
    assert "is_approved" not in CustomUserAdmin.list_display, (
        "'is_approved' should have been removed from list_display"
    )
