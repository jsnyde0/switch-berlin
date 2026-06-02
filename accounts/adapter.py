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
                f"Turnstile siteverify unreachable after {_TURNSTILE_MAX_RETRIES + 1} attempts: {exc}"
            ) from exc

        # ADR-008 D3: 4xx/5xx = data-integrity/infrastructure error → raise immediately
        if response.status_code >= 400:
            raise RuntimeError(
                f"Turnstile siteverify returned HTTP {response.status_code}; signup blocked (ADR-008 D3 fail loud)."
            )

        data = response.json()
        return bool(data.get("success", False))

    # Should not reach here
    raise RuntimeError("Turnstile validation failed unexpectedly") from last_exc


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
        """Create Profile(kind='person') + ProfileClaim(verified_method='auto_self').

        Per ADR-013 D3 (participant profiles via auto-created Profile on signup),
        ADR-008 D2 (adapter hook, not signal), ADR-008 D3 (fail loud).

        Idempotent: if the user already has an auto_self ProfileClaim, no-op.
        """
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
                # auto_self ProfileClaim is already a verified ownership signal;
                # status='approved' makes the Profile visible to the owner
                # (organizer_profile view filters status='approved'). ADR-014 D1.
                status="approved",
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

        If invite code supplied, create Vouch + InviteGrant.

        Turnstile validation already ran in OpenSignupForm.clean_turnstile_token()
        and invite code validation ran in OpenSignupForm.clean_invite_code() before
        this is called.

        Per ADR-013 D2 (two signup paths: open + vouched).
        Per ADR-008 D3 (fail loud — invalid invite rejected at form layer already).
        All actions in a single atomic transaction to guarantee all-or-nothing.
        """
        invite_code_str = (form.cleaned_data or {}).get("invite_code", "").strip()

        user = super().save_user(request, user, form, commit=commit)
        if commit:
            with transaction.atomic():
                self._create_owned_profile(user)

                if invite_code_str:
                    from django.utils import timezone

                    from accounts.models import InviteCode, InviteGrant, Vouch

                    # Re-fetch inside the atomic block to lock for update
                    try:
                        invite = InviteCode.objects.select_for_update().get(code=invite_code_str)
                    except InviteCode.DoesNotExist as exc:
                        # Should not reach here — form already validated, but
                        # fail loud per ADR-008 D3 if somehow reached
                        raise RuntimeError(
                            f"Invite code {invite_code_str!r} not found at save time "
                            "(form validation passed but code gone). ADR-008 D3."
                        ) from exc

                    if not invite.usable():
                        # Race condition: another request used it between form clean
                        # and here. Fail loud — do not silently fall through.
                        raise RuntimeError(
                            f"Invite code {invite_code_str!r} was valid at form "
                            "validation but is no longer usable (race). ADR-008 D3."
                        )

                    now = timezone.now()

                    # Mark invite code as used
                    invite.used_by = user
                    invite.used_at = now
                    invite.save(update_fields=["used_by", "used_at"])

                    # Create Vouch: voucher = invite.created_by (grantor)
                    Vouch.objects.create(voucher=invite.created_by, vouchee=user)

                    # Create InviteGrant audit log
                    InviteGrant.objects.create(
                        grantor=invite.created_by,
                        recipient=user,
                        invite_code=invite,
                    )

                    # Set user status to vouched
                    user.status = "vouched"
                    user.save(update_fields=["status"])

        return user
