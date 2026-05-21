import logging
import uuid

import httpx
from allauth.account.adapter import DefaultAccountAdapter
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

logger = logging.getLogger(__name__)

_TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
_TURNSTILE_MAX_RETRIES = 2  # ADR-008 D4: 2 retries on transport blip


def validate_turnstile_token(token: str, secret_key: str) -> bool:
    """Validate a Cloudflare Turnstile token against the siteverify API.

    ADR-008 D4: transport errors (network blips) get up to 2 retries then raise.
    ADR-008 D3: 4xx/5xx from Turnstile → raise (never silently pass).

    Returns True if Cloudflare says success=true, False if success=false.
    Raises on any HTTP error or transport failure after retries exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(_TURNSTILE_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                _TURNSTILE_VERIFY_URL,
                data={"secret": secret_key, "response": token},
                timeout=5.0,
            )
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt < _TURNSTILE_MAX_RETRIES:
                logger.warning(
                    "Turnstile transport error (attempt %d/%d): %s",
                    attempt + 1,
                    _TURNSTILE_MAX_RETRIES + 1,
                    exc,
                )
                continue
            # Retries exhausted — fail loud (ADR-008 D4)
            raise RuntimeError(
                f"Turnstile siteverify unreachable after {_TURNSTILE_MAX_RETRIES + 1} "
                f"attempts: {exc}"
            ) from exc

        # ADR-008 D3: 4xx/5xx = data-integrity/infrastructure error → raise immediately
        if response.status_code >= 400:
            raise RuntimeError(
                f"Turnstile siteverify returned HTTP {response.status_code}; "
                "signup blocked (ADR-008 D3 fail loud)."
            )

        data = response.json()
        return bool(data.get("success", False))

    # Should not reach here
    raise RuntimeError("Turnstile validation failed unexpectedly") from last_exc


class NoSignupAdapter(DefaultAccountAdapter):
    """Invite-gated signup adapter — phase 0.4."""

    def is_open_for_signup(self, request):
        if not _get_flag_safe("INVITES_ENABLED", default=True):
            return False
        code = request.GET.get("code") or request.session.get("invite_code")
        if not code:
            return False
        from accounts.models import InviteCode

        try:
            invite = InviteCode.objects.get(code=code, redeemed_by__isnull=True)
        except InviteCode.DoesNotExist:
            return False
        if invite.expires_at and invite.expires_at <= timezone.now():
            return False
        request.session["invite_code"] = code
        return True

    def _create_owned_profile(self, user):
        """Create Profile(kind='person') + ProfileClaim(verified_method='auto_self').

        Per ADR-013 D3 (participant profiles via auto-created Profile on signup),
        ADR-008 D2 (adapter hook, not signal), ADR-008 D3 (fail loud).

        Named _create_owned_profile so kb-m69.5 can call it cleanly.
        Idempotent: if the user already has an auto_self ProfileClaim, no-op.
        """
        from organizers.models import Profile, ProfileClaim

        # Idempotency guard: if the user already has an auto_self claim, skip.
        if ProfileClaim.objects.filter(user=user, verified_method="auto_self").exists():
            return

        name = user.get_full_name() or user.email

        # Build a unique slug: slugify name + short uuid suffix to avoid collisions
        base_slug = slugify(name)[:190] or "user"
        slug = base_slug + "-" + str(uuid.uuid4())[:8]

        with transaction.atomic():
            profile = Profile.objects.create(
                kind="person",
                name=name,
                slug=slug,
            )
            ProfileClaim.objects.create(
                profile=profile,
                user=user,
                verified_method="auto_self",
                verified_at=timezone.now(),
                role="admin",
                verified_by_admin=None,
            )

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=commit)
        if commit:
            code = request.session.get("invite_code")
            if code:
                from accounts.models import InviteCode

                with transaction.atomic():
                    updated = InviteCode.objects.filter(
                        code=code, redeemed_by__isnull=True
                    ).update(redeemed_by=user, redeemed_at=timezone.now())
                    if updated == 0:
                        # Race: code already redeemed. Log and continue (lenient).
                        # Staff can reconcile. At 0.4 scale (5-15 users) acceptable.
                        logger.warning(
                            "Invite code %s already redeemed when saving user %s",
                            code,
                            user.pk,
                        )
                request.session.pop("invite_code", None)

            with transaction.atomic():
                self._create_owned_profile(user)

        return user


class OpenSignupAdapter(DefaultAccountAdapter):
    """Open signup adapter (kb-m69.5): Turnstile-gated, email-verified, auto-Profile.

    Per ADR-013 D2 (open signup path), ADR-014 D4 (Turnstile), ADR-008 D3 (fail loud).
    """

    def is_open_for_signup(self, request):
        """Open signup is always available (no invite code required)."""
        return True

    def get_signup_form_class(self):
        """Return the Turnstile-enabled signup form."""
        from accounts.forms import OpenSignupForm

        return OpenSignupForm

    def _create_owned_profile(self, user):
        """Identical to NoSignupAdapter._create_owned_profile — see docs there."""
        from organizers.models import Profile, ProfileClaim

        if ProfileClaim.objects.filter(user=user, verified_method="auto_self").exists():
            return

        name = user.get_full_name() or user.email
        base_slug = slugify(name)[:190] or "user"
        slug = base_slug + "-" + str(uuid.uuid4())[:8]

        with transaction.atomic():
            profile = Profile.objects.create(
                kind="person",
                name=name,
                slug=slug,
            )
            ProfileClaim.objects.create(
                profile=profile,
                user=user,
                verified_method="auto_self",
                verified_at=timezone.now(),
                role="admin",
                verified_by_admin=None,
            )

    def save_user(self, request, user, form, commit=True):
        """Create user + auto-Profile.

        Turnstile validation already ran in OpenSignupForm.clean_turnstile_token()
        before this is called. This only handles user persistence and Profile creation.
        """
        user = super().save_user(request, user, form, commit=commit)
        if commit:
            with transaction.atomic():
                self._create_owned_profile(user)
        return user


def _get_flag_safe(key: str, default: bool = False) -> bool:
    """Thin wrapper around get_flag that handles import gracefully."""
    from a_core.models import get_flag

    return get_flag(key, default=default)
