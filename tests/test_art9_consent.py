"""Art. 9(2)(a) attendance consent tests — bead kb-9kh.1.

TDD tests written BEFORE implementation. All tests must fail initially
(no art9_consent_given_at field, no consent module, no gates).
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def approved_user(db):
    """Approved user without Art. 9 consent."""
    user = User.objects.create_user(
        username="consent_user",
        email="consent@example.com",
        password="testpass123",
    )
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def approved_user_with_consent(approved_user):
    """Approved user WITH Art. 9 consent timestamp set."""
    approved_user.art9_consent_given_at = timezone.now()
    approved_user.save(update_fields=["art9_consent_given_at"])
    return approved_user


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_user_has_art9_consent_field(db):
    """User model must have art9_consent_given_at DateTimeField, null by default."""
    user = User.objects.create_user(
        username="schema_test",
        email="schema@example.com",
        password="x",
    )
    assert hasattr(user, "art9_consent_given_at")
    assert user.art9_consent_given_at is None


# ---------------------------------------------------------------------------
# Attend gate: blocked without consent
# ---------------------------------------------------------------------------


def test_attend_blocked_without_consent(client, approved_user, published_event):
    """POST attend without Art. 9 consent returns consent partial; no row created."""
    from events.models import Attendance

    client.force_login(approved_user)
    url = reverse(
        "event-attend",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    response = client.post(url, data={"status": "going"})

    # Should get a 200 with the consent partial, not an error
    assert response.status_code == 200
    content = response.content.decode().lower()
    # Consent partial must mention sexual orientation (EN or DE)
    assert "sexual orientation" in content or "sexuelle orientierung" in content

    # No Attendance row should have been created
    assert not Attendance.objects.filter(
        user=approved_user, event=published_event
    ).exists()


def test_attend_works_with_consent(client, approved_user_with_consent, published_event):
    """POST attend WITH Art. 9 consent creates Attendance row."""
    from events.models import Attendance

    client.force_login(approved_user_with_consent)
    url = reverse(
        "event-attend",
        kwargs={
            "org_slug": published_event.organizer.slug,
            "event_slug": published_event.slug,
        },
    )
    response = client.post(url, data={"status": "going"})

    assert response.status_code == 200
    assert Attendance.objects.filter(
        user=approved_user_with_consent, event=published_event, status="going"
    ).exists()


# ---------------------------------------------------------------------------
# Consent endpoint
# ---------------------------------------------------------------------------


def test_consent_endpoint_sets_timestamp(client, approved_user):
    """POST /accounts/art9-consent/ sets art9_consent_given_at on the user."""
    client.force_login(approved_user)
    assert approved_user.art9_consent_given_at is None

    response = client.post(reverse("art9-consent"), data={"next": "/"})

    approved_user.refresh_from_db()
    assert approved_user.art9_consent_given_at is not None
    # Returns HX-Redirect header (HTMX redirect) — status 200
    assert response.status_code == 200
    assert response.get("HX-Redirect") is not None


@pytest.mark.django_db
def test_consent_endpoint_requires_login(client):
    """POST /accounts/art9-consent/ redirects anonymous users to login."""
    response = client.post(reverse("art9-consent"), data={"next": "/"})
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]


# ---------------------------------------------------------------------------
# Revoke helper
# ---------------------------------------------------------------------------


def test_revoke_deletes_all_attendance_rows(
    db, approved_user_with_consent, published_event
):
    """revoke_art9_consent deletes all Attendance rows for the user."""
    from accounts.consent import revoke_art9_consent
    from events.models import Attendance

    # Create multiple attendance rows
    Attendance.objects.create(
        user=approved_user_with_consent, event=published_event, status="going"
    )

    revoke_art9_consent(approved_user_with_consent)

    approved_user_with_consent.refresh_from_db()
    assert approved_user_with_consent.art9_consent_given_at is None
    assert not Attendance.objects.filter(user=approved_user_with_consent).exists()


def test_revoke_is_idempotent(db, approved_user):
    """revoke_art9_consent called twice on a user with no rows does not error."""
    from accounts.consent import revoke_art9_consent

    # Should not raise even when already null and no rows
    revoke_art9_consent(approved_user)
    revoke_art9_consent(approved_user)

    approved_user.refresh_from_db()
    assert approved_user.art9_consent_given_at is None


# ---------------------------------------------------------------------------
# Withdrawal endpoint
# ---------------------------------------------------------------------------


def test_withdrawal_endpoint_revokes_and_redirects(
    client, approved_user_with_consent, published_event
):
    """POST /accounts/art9-consent/withdraw/ clears consent and attendance rows."""
    from events.models import Attendance

    Attendance.objects.create(
        user=approved_user_with_consent, event=published_event, status="going"
    )
    client.force_login(approved_user_with_consent)

    response = client.post(reverse("art9-consent-withdraw"))

    assert response.status_code == 302
    approved_user_with_consent.refresh_from_db()
    assert approved_user_with_consent.art9_consent_given_at is None
    assert not Attendance.objects.filter(user=approved_user_with_consent).exists()


# ---------------------------------------------------------------------------
# Open redirect protection
# ---------------------------------------------------------------------------


def test_consent_next_rejects_external_url(client, approved_user):
    """POST art9-consent with next=https://evil.com must redirect to '/' not evil."""
    client.force_login(approved_user)
    response = client.post(reverse("art9-consent"), data={"next": "https://evil.com"})
    assert response.status_code == 200
    assert response.get("HX-Redirect") == "/"


def test_consent_next_accepts_safe_internal_url(client, approved_user):
    """POST art9-consent with next=/events/ (safe internal URL) redirects there."""
    client.force_login(approved_user)
    response = client.post(reverse("art9-consent"), data={"next": "/events/"})
    assert response.status_code == 200
    assert response.get("HX-Redirect") == "/events/"


# ---------------------------------------------------------------------------
# Account deletion path (belt + suspenders)
# ---------------------------------------------------------------------------


def test_account_deletion_also_revokes(db, approved_user_with_consent, published_event):
    """Deleting a user clears attendance rows via pre_delete signal."""
    from events.models import Attendance

    Attendance.objects.create(
        user=approved_user_with_consent, event=published_event, status="going"
    )
    user_pk = approved_user_with_consent.pk

    approved_user_with_consent.delete()

    # After deletion all Attendance rows for this user must be gone
    assert not Attendance.objects.filter(user_id=user_pk).exists()
