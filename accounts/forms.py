"""Account forms for kb-m69.5 open signup path.

Per ADR-014 D4 (Turnstile on public-facing forms).
"""

from allauth.account.forms import SignupForm
from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class OpenSignupForm(SignupForm):
    """Allauth signup form extended with a Turnstile token field.

    Turnstile token is validated server-side in clean_turnstile_token().
    The widget is a hidden input — the Cloudflare Turnstile JS widget fills it.

    Per ADR-014 D4 (Turnstile on public-facing forms).
    Per ADR-008 D3 (fail loud — no silent fallback when token is missing/invalid).
    """

    turnstile_token = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        label=_("Turnstile token"),
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
