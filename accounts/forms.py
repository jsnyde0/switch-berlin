"""Account forms for kb-m69.5 open signup path + kb-m69.7 vouched signup path.

Per ADR-014 D4 (Turnstile on public-facing forms).
Per ADR-013 D2 (two signup paths: open + vouched).
Per ADR-008 D3 (fail loud on invalid invite — no silent fall-through to open path).
"""

from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class OpenSignupForm(SignupForm):
    """Allauth signup form extended with Turnstile + optional invite_code field.

    Turnstile token is validated server-side in clean_turnstile_token().
    The widget is a hidden input — the Cloudflare Turnstile JS widget fills it.

    If invite_code is provided and valid → vouched path (ADR-013 D2).
    If invite_code is provided and invalid → form-invalid, fail loud (ADR-008 D3).
    If invite_code is absent → open path (default).

    Per ADR-014 D4 (Turnstile on public-facing forms).
    Per ADR-008 D3 (fail loud — no silent fallback).
    """

    turnstile_token = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        label=_("Turnstile token"),
    )
    invite_code = forms.CharField(
        required=False,
        max_length=48,
        label=_("Invite code"),
        help_text=_(
            "Optional. If you have an invite code, enter it here to join as a vouched"
            " member."
        ),
    )

    def clean_turnstile_token(self):
        """Validate the Turnstile token against Cloudflare's siteverify API.

        Per ADR-008 D3: if the secret key is not configured → raise loudly (don't
        let signup through silently).
        """
        from accounts.adapter import validate_turnstile_token

        token = self.cleaned_data.get("turnstile_token", "")
        secret_key = getattr(settings, "TURNSTILE_SECRET_KEY", "")

        if not secret_key:
            # Misconfiguration: no secret key — fail loud (ADR-008 D3)
            raise forms.ValidationError(
                _(
                    "Signup is temporarily unavailable (server misconfiguration). "
                    "Please try again later."
                )
            )

        is_valid = validate_turnstile_token(token, secret_key)
        if not is_valid:
            raise forms.ValidationError(
                _("Human verification failed. Please complete the CAPTCHA.")
            )

        return token

    def clean_invite_code(self):
        """Validate the invite code if provided.

        Per ADR-008 D3: if an invite code is provided but invalid/already-used,
        raise a ValidationError — NO silent fall-through to open signup path.
        """
        code = self.cleaned_data.get("invite_code", "").strip()
        if not code:
            # No code supplied — open path (default)
            return code

        from accounts.models import InviteCode

        try:
            invite = InviteCode.objects.get(code=code)
        except InviteCode.DoesNotExist as exc:
            raise forms.ValidationError(
                _("This invite code is not valid. Please check and try again.")
            ) from exc

        if not invite.usable():
            raise forms.ValidationError(
                _("This invite code has already been used or has expired.")
            )

        return code
