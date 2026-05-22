"""
Integration tests for Phase 0.5 — trust-cluster end-to-end (kb-m69.10).

Exercises the conjunction of 9 schema-and-behavior beads (kb-m69.1 through
kb-m69.9): signup paths, profile-claim flows, and the event-visibility access
matrix.

ADR refs:
- ADR-012 D3: viewer × event-tier access matrix (Flow G)
- ADR-013 D1: User.status driving access
- ADR-013 D2: two signup paths (open + vouched)
- ADR-014 D2+D3: claim flow + magic-link envelope

Flows A–H (8 end-to-end test functions + parametrized access matrix):
  A — Open signup (no invite): status='open', auto-Profile + auto-ProfileClaim created
  B — Vouched signup (valid invite): status='vouched', Vouch/InviteGrant/used-code
  C — Vouched signup with invalid/used invite: fail loud, no User created
  D — Email-domain fast-path claim: ProfileClaim(verified_method='email_domain')
  E — Magic-link claim (admin-review): ClaimIntent + MagicLinkToken → ProfileClaim
  F — Magic-link tampering: wrong user → 403, no ProfileClaim
  G — Access matrix: 3 tiers × 4 viewer states = 12 cells
  H — X-Robots-Tag header on semi_public/unlisted event detail pages
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from events.models import Event
from organizers.models import ClaimIntent, MagicLinkToken, Profile, ProfileClaim

User = get_user_model()

# ---------------------------------------------------------------------------
# Helpers & local fixtures
# ---------------------------------------------------------------------------

TURNSTILE_SETTINGS = dict(
    TURNSTILE_SITE_KEY="1x00000000000000000000AA",
    TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA",
    ACCOUNT_EMAIL_VERIFICATION="mandatory",
)


def _create_vouched_user(username, email):
    """Create a vouched user directly (bypassing signup flow)."""
    user = User.objects.create_user(username=username, email=email, password="Pass!123")
    user.status = "vouched"
    user.save()
    return user


@pytest.fixture
def grantor(db):
    """Staff user who owns the invite code."""
    return User.objects.create_user(
        username="grantor_trust",
        email="grantor_trust@example.com",
        password="Pass!123",
        is_staff=True,
        status="vouched",
    )


@pytest.fixture
def invite_code(db, grantor):
    from accounts.models import InviteCode

    return InviteCode.objects.create(created_by=grantor)


@pytest.fixture
def vouched_user(db):
    return _create_vouched_user("voucheduser", "vouched@example.com")


@pytest.fixture
def open_user(db):
    user = User.objects.create_user(
        username="openuser", email="open@example.com", password="Pass!123"
    )
    # status defaults to 'open'
    return user


@pytest.fixture
def profile_org(db):
    return Profile.objects.create(
        name="Trust Test Org",
        slug="trust-test-org",
        status="approved",
        kind="collective",
    )


@pytest.fixture
def public_event(db, profile_org):
    return Event.objects.create(
        title="Public Trust Event",
        slug="public-trust-event",
        organizer=profile_org,
        status="published",
        visibility="public",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def semi_public_event(db, profile_org):
    return Event.objects.create(
        title="Semi-Public Trust Event",
        slug="semi-public-trust-event",
        organizer=profile_org,
        status="published",
        visibility="semi_public",
        start=timezone.now() + timedelta(days=7),
    )


@pytest.fixture
def unlisted_event(db, profile_org):
    return Event.objects.create(
        title="Unlisted Trust Event",
        slug="unlisted-trust-event",
        organizer=profile_org,
        status="published",
        visibility="unlisted",
        start=timezone.now() + timedelta(days=7),
    )


# ---------------------------------------------------------------------------
# Flow A — Open signup, no invite
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_a_open_signup_creates_open_user_with_auto_profile():
    """
    Flow A: Anonymous user submits signup form with valid Turnstile + no invite.
    → User created with status='open', Profile(kind='person') auto-created,
      ProfileClaim(verified_method='auto_self') created,
      email-verification email queued.
    """
    from django.core import mail

    client = Client()
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "flow_a@example.com",
                "password1": "Str0ng!Pass456",
                "password2": "Str0ng!Pass456",
                "turnstile_token": "VALID",
            },
        )

    # Signup succeeds (redirect to email-confirmation page)
    assert response.status_code == 302

    user = User.objects.filter(email="flow_a@example.com").first()
    assert user is not None, "User was not created"
    assert user.status == "open", f"Expected status='open', got '{user.status}'"

    # Auto-Profile created (kind=person)
    claim = ProfileClaim.objects.filter(user=user, verified_method="auto_self").first()
    assert claim is not None, "auto_self ProfileClaim was not created"
    assert claim.profile.kind == "person", f"Expected kind='person', got '{claim.profile.kind}'"

    # Verification email sent
    assert len(mail.outbox) >= 1, "Expected email-verification email in outbox"


# ---------------------------------------------------------------------------
# Flow B — Vouched signup with valid invite
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_b_vouched_signup_with_valid_invite(grantor, invite_code):
    """
    Flow B: Anonymous user submits signup with valid InviteCode + valid Turnstile.
    → User created with status='vouched', Vouch row created, InviteGrant audit row
      created, InviteCode marked used.
    """
    from accounts.models import InviteGrant, Vouch

    client = Client()
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "flow_b@example.com",
                "password1": "Str0ng!Pass456",
                "password2": "Str0ng!Pass456",
                "turnstile_token": "VALID",
                "invite_code": invite_code.code,
            },
        )

    assert response.status_code == 302

    user = User.objects.filter(email="flow_b@example.com").first()
    assert user is not None, "User was not created"
    assert user.status == "vouched", f"Expected status='vouched', got '{user.status}'"

    # Vouch row
    assert Vouch.objects.filter(voucher=grantor, vouchee=user).exists(), "Vouch row missing"

    # InviteGrant audit row
    assert InviteGrant.objects.filter(recipient=user, invite_code=invite_code).exists(), (
        "InviteGrant audit row missing"
    )

    # InviteCode marked used
    invite_code.refresh_from_db()
    assert invite_code.used_at is not None, "InviteCode.used_at should be set"
    assert invite_code.used_by == user, "InviteCode.used_by should be the new user"


# ---------------------------------------------------------------------------
# Flow C — Vouched signup with invalid/used invite fails loud
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_c_vouched_signup_with_bad_code_fails_loud():
    """
    Flow C: signup with bad/used code → no User created, form-invalid,
    no silent fall-through to open path (ADR-008 D3).
    """
    client = Client()

    # C1: nonexistent code
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "flow_c1@example.com",
                "password1": "Str0ng!Pass456",
                "password2": "Str0ng!Pass456",
                "turnstile_token": "VALID",
                "invite_code": "DOES-NOT-EXIST-XYZ",
            },
        )

    # 200 = form re-rendered with error (NOT 302 redirect = success)
    assert response.status_code == 200, (
        f"Expected 200 (form-invalid), got {response.status_code}"
    )
    assert not User.objects.filter(email="flow_c1@example.com").exists(), (
        "User created despite invalid invite code (ADR-008 D3 violation)"
    )


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_c_vouched_signup_with_used_code_fails_loud(grantor):
    """
    Flow C: signup with already-used invite → fail loud, no User created.
    """
    from accounts.models import InviteCode

    existing = User.objects.create_user(
        username="prior_recipient", email="prior@example.com", password="x"
    )
    ic = InviteCode.objects.create(
        created_by=grantor,
        used_by=existing,
        used_at=timezone.now(),
    )

    client = Client()
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(
            "/accounts/signup/",
            {
                "email": "flow_c2@example.com",
                "password1": "Str0ng!Pass456",
                "password2": "Str0ng!Pass456",
                "turnstile_token": "VALID",
                "invite_code": ic.code,
            },
        )

    assert response.status_code == 200, (
        f"Expected 200 (form-invalid), got {response.status_code}"
    )
    assert not User.objects.filter(email="flow_c2@example.com").exists(), (
        "User created despite used invite code (ADR-008 D3 violation)"
    )


# ---------------------------------------------------------------------------
# Flow D — Email-domain fast-path claim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_d_email_domain_fastpath_claim(vouched_user):
    """
    Flow D: vouched user whose email matches Profile.verified_domain submits ClaimForm.
    → MagicLinkToken issued with intended_method='email_domain', redirect to check-email.
    Magic-link redemption then creates ProfileClaim(verified_method='email_domain').

    ADR-014 D2: Both tracks pass through magic-link confirmation. Fast-path
    differs only in post-confirmation routing (auto-claim vs admin queue).
    """
    from django.core import mail

    profile = Profile.objects.create(
        name="Domain Org",
        slug="domain-org",
        status="approved",
        kind="collective",
        verified_domain="example.com",
    )

    client = Client()
    client.force_login(vouched_user)

    url = reverse("organizer-claim-entry", kwargs={"slug": profile.slug})
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(url, {"email": vouched_user.email, "turnstile_token": "VALID"})

    # Should redirect to check-email page (NOT directly to profile)
    assert response.status_code == 302
    assert (
        "check" in response["Location"].lower()
        or "email" in response["Location"].lower()
    ), f"Expected check-email redirect on fast-path, got: {response['Location']}"

    # No ProfileClaim created at POST time (magic-link required)
    assert not ProfileClaim.objects.filter(profile=profile, user=vouched_user).exists(), (
        "ProfileClaim must NOT be created at POST time on fast-path (ADR-014 D2)"
    )

    # MagicLinkToken issued with intended_method='email_domain'
    token = MagicLinkToken.objects.filter(profile=profile, user_target=vouched_user).first()
    assert token is not None, "MagicLinkToken should be created on email-domain fast-path"
    assert token.intended_method == "email_domain", (
        f"Expected intended_method='email_domain', got '{token.intended_method}'"
    )

    # Magic-link email sent
    assert len(mail.outbox) >= 1, "Expected magic-link email in outbox on fast-path"

    # Redeem the magic link — creates ProfileClaim with verified_method='email_domain'
    redeem_url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    redeem_response = client.get(redeem_url)

    assert redeem_response.status_code == 302

    claim = ProfileClaim.objects.filter(profile=profile, user=vouched_user).first()
    assert claim is not None, "ProfileClaim was not created after fast-path magic-link redemption"
    assert claim.verified_method == "email_domain", (
        f"Expected verified_method='email_domain', got '{claim.verified_method}'"
    )


# ---------------------------------------------------------------------------
# Flow E — Magic-link claim (admin-review path)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(**TURNSTILE_SETTINGS)
def test_flow_e_magic_link_claim_admin_review_path(vouched_user):
    """
    Flow E: vouched user whose email does NOT match verified_domain submits ClaimForm.
    → ClaimIntent created, MagicLinkToken issued (intended_method='admin_review').
    Redemption stamps ClaimIntent.submitter_verified_at; no ProfileClaim yet
    (admin must approve first per ADR-014 D2).
    """
    from django.core import mail

    profile = Profile.objects.create(
        name="Review Org",
        slug="review-org",
        status="approved",
        kind="collective",
        verified_domain="different-domain.com",  # user's email is vouched@example.com
    )

    client = Client()
    client.force_login(vouched_user)

    # POST claim form — triggers admin-review path (email domain mismatch)
    url = reverse("organizer-claim-entry", kwargs={"slug": profile.slug})
    with patch("accounts.adapter.validate_turnstile_token", return_value=True):
        response = client.post(url, {"email": vouched_user.email, "turnstile_token": "VALID"})

    # Should redirect to check-email page
    assert response.status_code == 302

    # ClaimIntent created
    intent = ClaimIntent.objects.filter(user=vouched_user, profile=profile).first()
    assert intent is not None, "ClaimIntent was not created on admin-review path"

    # MagicLinkToken issued with intended_method='admin_review'
    token = MagicLinkToken.objects.filter(profile=profile, user_target=vouched_user).first()
    assert token is not None, "MagicLinkToken was not created on admin-review path"
    assert token.is_valid, "MagicLinkToken should be valid (not expired, not used)"
    assert token.intended_method == "admin_review", (
        f"Expected intended_method='admin_review', got '{token.intended_method}'"
    )

    # Magic-link email sent
    assert len(mail.outbox) >= 1, "Expected magic-link email in outbox"

    # Redeem the magic link
    redeem_url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    redeem_response = client.get(redeem_url)

    # Should redirect (to check-email page — admin must still approve)
    assert redeem_response.status_code == 302

    # ClaimIntent.submitter_verified_at stamped (email confirmed)
    intent.refresh_from_db()
    assert intent.submitter_verified_at is not None, (
        "ClaimIntent.submitter_verified_at should be stamped after magic-link redemption"
    )

    # No ProfileClaim created yet (admin approval required per ADR-014 D2)
    assert not ProfileClaim.objects.filter(profile=profile, user=vouched_user).exists(), (
        "ProfileClaim must NOT be created on admin-review path until admin approves (ADR-014 D2)"
    )

    # Token marked as used
    token.refresh_from_db()
    assert token.is_used, "MagicLinkToken should be marked used after redemption"


# ---------------------------------------------------------------------------
# Flow F — Magic-link tampering: wrong user → 403, no ProfileClaim
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flow_f_magic_link_tamper_wrong_user_fails_loud(vouched_user):
    """
    Flow F: magic-link redemption attempted by a different logged-in user.
    → 403 response (ADR-008 D3 fail loud), no ProfileClaim created.
    """
    profile = Profile.objects.create(
        name="Tamper Org",
        slug="tamper-org",
        status="approved",
        kind="collective",
    )

    # Token was issued for vouched_user
    token = MagicLinkToken.objects.create(
        email=vouched_user.email,
        profile=profile,
        user_target=vouched_user,
        expires_at=timezone.now() + timedelta(hours=24),
    )

    # Different user attempts to redeem
    attacker = _create_vouched_user("attacker_trust", "attacker_trust@example.com")
    client = Client()
    client.force_login(attacker)

    redeem_url = reverse("organizer-claim-redeem", kwargs={"token": str(token.token)})
    response = client.get(redeem_url)

    # Must fail loud — 403
    assert response.status_code == 403, (
        f"Expected 403 for wrong-user redemption (ADR-008 D3), got {response.status_code}"
    )

    # No ProfileClaim created
    assert not ProfileClaim.objects.filter(profile=profile).exists(), (
        "ProfileClaim should NOT be created on tampered redemption"
    )

    # Token still valid (not consumed by the attack)
    token.refresh_from_db()
    assert not token.is_used, "Token should not be marked used after failed redemption"


# ---------------------------------------------------------------------------
# Flow G — Access matrix: 3 tiers × 4 viewer states = 12 cells
# ---------------------------------------------------------------------------
#
# Matrix per ADR-012 D3 and events/managers.py:
#
#               | public | semi_public | unlisted
# --------------|--------|-------------|----------
# anon          |  200   |     404     |   404
# open          |  200   |     404     |   404
# vouched       |  200   |     200     |   200  (URL-keyed)
# staff         |  200   |     200     |   200
#
# "404" here: the queryset excludes those events from visible_to_url for that
# viewer — so event_detail raises Http404.


@pytest.mark.parametrize(
    "viewer_type,visibility,expected_status",
    [
        # Anonymous viewer
        ("anon", "public", 200),
        ("anon", "semi_public", 404),
        ("anon", "unlisted", 404),
        # open-status user
        ("open", "public", 200),
        ("open", "semi_public", 404),
        ("open", "unlisted", 404),
        # vouched user
        ("vouched", "public", 200),
        ("vouched", "semi_public", 200),
        ("vouched", "unlisted", 200),
        # staff user
        ("staff", "public", 200),
        ("staff", "semi_public", 200),
        ("staff", "unlisted", 200),
    ],
)
@pytest.mark.django_db
def test_flow_g_access_matrix(
    viewer_type,
    visibility,
    expected_status,
    profile_org,
    public_event,
    semi_public_event,
    unlisted_event,
):
    """
    Flow G: 12-cell access matrix (viewer × event-tier).
    Each cell asserts correct HTTP status per ADR-012 D3.
    """
    # Pick the right event fixture by visibility
    event_map = {
        "public": public_event,
        "semi_public": semi_public_event,
        "unlisted": unlisted_event,
    }
    event = event_map[visibility]

    # Build the correct viewer
    client = Client()
    if viewer_type == "anon":
        pass  # no login
    elif viewer_type == "open":
        open_user = User.objects.create_user(
            username=f"g_open_{visibility}",
            email=f"g_open_{visibility}@example.com",
            password="x",
        )
        # status defaults to 'open'
        client.force_login(open_user)
    elif viewer_type == "vouched":
        vouched = _create_vouched_user(
            f"g_vouched_{visibility}",
            f"g_vouched_{visibility}@example.com",
        )
        client.force_login(vouched)
    elif viewer_type == "staff":
        staff = User.objects.create_user(
            username=f"g_staff_{visibility}",
            email=f"g_staff_{visibility}@example.com",
            password="x",
            is_staff=True,
        )
        client.force_login(staff)

    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": event.organizer.slug,
            "event_slug": event.slug,
        },
    )
    response = client.get(url)

    assert response.status_code == expected_status, (
        f"Access matrix cell ({viewer_type} × {visibility}): "
        f"expected {expected_status}, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Flow H — X-Robots-Tag header on semi_public / unlisted event detail pages
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_flow_h_public_event_has_no_xrobots_header(vouched_user, public_event):
    """
    Flow H: GET on a public event → no X-Robots-Tag header (search engines may index).
    """
    client = Client()
    client.force_login(vouched_user)

    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": public_event.organizer.slug,
            "event_slug": public_event.slug,
        },
    )
    response = client.get(url)
    assert response.status_code == 200
    assert "X-Robots-Tag" not in response, (
        "Public event should NOT have X-Robots-Tag header"
    )


@pytest.mark.django_db
def test_flow_h_semi_public_event_has_noindex_header(vouched_user, semi_public_event):
    """
    Flow H: GET on a semi_public event → X-Robots-Tag: noindex, nofollow.
    """
    client = Client()
    client.force_login(vouched_user)

    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": semi_public_event.organizer.slug,
            "event_slug": semi_public_event.slug,
        },
    )
    response = client.get(url)
    assert response.status_code == 200
    assert "X-Robots-Tag" in response, "semi_public event must have X-Robots-Tag header"
    assert response["X-Robots-Tag"] == "noindex, nofollow", (
        f"Expected 'noindex, nofollow', got '{response['X-Robots-Tag']}'"
    )


@pytest.mark.django_db
def test_flow_h_unlisted_event_has_noindex_header(vouched_user, unlisted_event):
    """
    Flow H: GET on an unlisted event → X-Robots-Tag: noindex, nofollow.
    """
    client = Client()
    client.force_login(vouched_user)

    url = reverse(
        "event-detail",
        kwargs={
            "org_slug": unlisted_event.organizer.slug,
            "event_slug": unlisted_event.slug,
        },
    )
    response = client.get(url)
    assert response.status_code == 200
    assert "X-Robots-Tag" in response, "unlisted event must have X-Robots-Tag header"
    assert "noindex" in response["X-Robots-Tag"], (
        f"Expected 'noindex' in X-Robots-Tag, got '{response['X-Robots-Tag']}'"
    )
