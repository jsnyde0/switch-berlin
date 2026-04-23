"""Tests for DSA Art. 16(2) takedown form upgrade (bead kb-9kh.3).

TDD order:
  RED  — write tests, watch them fail
  GREEN — implement minimal code
  REFACTOR — clean up
"""

import pytest
from django.test import Client

from reviews.forms import TakedownForm
from reviews.models import Flag

# ---------------------------------------------------------------------------
# Form validation tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTakedownFormValidation:
    """Form-level validation for DSA Art. 16(2) fields."""

    def _form_data(self, **overrides):
        """Return minimal valid POST data for the takedown form."""
        data = {
            "reason": "spam",
            "body": "Some body text.",
            "contact_email": "",
            "law_reference": "",
            "good_faith_confirmed": True,
        }
        data.update(overrides)
        return data

    def test_form_rejects_without_good_faith_tick(self):
        """Submission without good_faith_confirmed must fail form validation."""
        data = self._form_data(good_faith_confirmed=False)
        form = TakedownForm(data=data)
        assert not form.is_valid()
        assert "good_faith_confirmed" in form.errors

    def test_illegal_reason_requires_email_and_law_reference(self):
        """reason='illegal' without contact_email AND law_reference must fail."""
        data = self._form_data(
            reason="illegal",
            contact_email="",
            law_reference="",
            good_faith_confirmed=True,
        )
        form = TakedownForm(data=data)
        assert not form.is_valid()
        assert "contact_email" in form.errors
        assert "law_reference" in form.errors

    def test_illegal_reason_requires_email(self):
        """reason='illegal' with law_reference but no email must fail on email."""
        data = self._form_data(
            reason="illegal",
            contact_email="",
            law_reference="GDPR Art. 17",
            good_faith_confirmed=True,
        )
        form = TakedownForm(data=data)
        assert not form.is_valid()
        assert "contact_email" in form.errors
        assert "law_reference" not in form.errors

    def test_illegal_reason_requires_law_reference(self):
        """reason='illegal' with email but no law_reference must fail."""
        data = self._form_data(
            reason="illegal",
            contact_email="reporter@example.com",
            law_reference="",
            good_faith_confirmed=True,
        )
        form = TakedownForm(data=data)
        assert not form.is_valid()
        assert "law_reference" in form.errors
        assert "contact_email" not in form.errors

    def test_other_reasons_dont_require_email_or_law_reference(self):
        """Non-illegal reasons must NOT require contact_email or law_reference."""
        for reason in ("spam", "inaccurate", "harmful", "safety", "other"):
            data = self._form_data(
                reason=reason,
                contact_email="",
                law_reference="",
                good_faith_confirmed=True,
            )
            form = TakedownForm(data=data)
            assert form.is_valid(), (
                f"Form should be valid for reason={reason!r}, errors: {form.errors}"
            )

    def test_illegal_reason_valid_with_all_required_fields(self):
        """reason='illegal' with all required fields passes validation."""
        data = self._form_data(
            reason="illegal",
            contact_email="reporter@example.com",
            law_reference="Network Enforcement Act (NetzDG) §1",
            good_faith_confirmed=True,
        )
        form = TakedownForm(data=data)
        assert form.is_valid(), f"Form should be valid, errors: {form.errors}"


# ---------------------------------------------------------------------------
# Model / save tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flag_saves_with_new_fields(approved_organizer):
    """Flag can be created with law_reference and good_faith_confirmed set."""
    flag = Flag.objects.create(
        organizer=approved_organizer,
        reason="illegal",
        body="Test body",
        contact_email="reporter@example.com",
        law_reference="GDPR Art. 17",
        good_faith_confirmed=True,
    )
    flag.refresh_from_db()
    assert flag.law_reference == "GDPR Art. 17"
    assert flag.good_faith_confirmed is True


@pytest.mark.django_db
def test_flag_defaults_for_new_fields(approved_organizer):
    """Existing-style Flag rows (without new fields) retain sane defaults."""
    flag = Flag.objects.create(
        organizer=approved_organizer,
        reason="spam",
        body="Spam content",
    )
    flag.refresh_from_db()
    assert flag.law_reference == ""
    assert flag.good_faith_confirmed is False


@pytest.mark.django_db
def test_illegal_reason_choice_exists():
    """Flag.reason choices include 'illegal' as the first choice."""
    choice_values = [v for v, _ in Flag._meta.get_field("reason").choices]
    assert "illegal" in choice_values
    assert choice_values.index("illegal") == 0


# ---------------------------------------------------------------------------
# Admin test
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_shows_law_reference(superuser, approved_organizer):
    """Flag admin change view includes law_reference in the displayed fields."""
    from django.contrib.admin.sites import AdminSite

    from reviews.admin import FlagAdmin

    flag = Flag.objects.create(
        organizer=approved_organizer,
        reason="illegal",
        body="Test",
        contact_email="x@example.com",
        law_reference="NetzDG §1",
        good_faith_confirmed=True,
    )

    # Verify law_reference appears in the admin change view
    FlagAdmin(Flag, AdminSite())  # ensure admin registers without error
    client = Client()
    client.force_login(superuser)
    response = client.get(f"/admin/reviews/flag/{flag.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "law_reference" in content


# ---------------------------------------------------------------------------
# Integration: view saves new fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_takedown_view_saves_law_reference_and_good_faith(
    client, published_event
):
    """POST to takedown view with illegal reason saves all new fields on Flag.

    We use raise_request_exception=False because the template rendering may
    fail in CI (missing Vite manifest) even though the DB write succeeds.
    We assert only on DB state, not on the response.
    """
    from django.test import Client as DjangoClient

    c = DjangoClient(raise_request_exception=False)
    url = f"http://testserver/events/{published_event.organizer.slug}/{published_event.slug}/"
    c.post(
        "/takedown/",
        {
            "event_url": url,
            "reason": "illegal",
            "body": "This is illegal.",
            "contact_email": "reporter@example.com",
            "law_reference": "NetzDG §1",
            "good_faith_confirmed": "on",
        },
    )
    flag = Flag.objects.filter(event=published_event).first()
    assert flag is not None
    assert flag.reason == "illegal"
    assert flag.law_reference == "NetzDG §1"
    assert flag.good_faith_confirmed is True
