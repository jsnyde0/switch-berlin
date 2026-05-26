"""
Forms for the organizer profile-claim flow.

Per ADR-014 D2: collects email for claim verification; validates against
Profile.verified_domain for the email-domain fast-path branch.
Per ADR-014 D3: Turnstile pre-issuance gate on the submit form.
Per ADR-008 D3: fail loud on invalid Turnstile token.
"""

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class ClaimForm(forms.Form):
    """
    Claim entry form — collects the email address the user wants to verify
    their claim with, gated by Cloudflare Turnstile.

    Validation logic:
    - email must be a valid email address (basic Django EmailField validation).
    - turnstile_token is validated against Cloudflare siteverify (ADR-014 D3).
    - Domain matching against Profile.verified_domain is done in the view,
      not the form — the form is profile-agnostic.
    """

    email = forms.EmailField(
        label="Your email address",
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "placeholder": "you@example.com"}
        ),
        help_text="We'll send a verification link to this address.",
    )

    message = forms.CharField(
        label="Who are you? (optional but recommended)",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": (
                    "If your email domain doesn't match this profile, please "
                    "tell us who you are and how you're connected to this "
                    "organizer — e.g. 'I'm the organizer, contact me via "
                    "@handle on Telegram'."
                ),
            }
        ),
        help_text=(
            "Only shown to admins reviewing your claim. Leave blank if your "
            "email domain matches the profile's verified domain."
        ),
    )

    turnstile_token = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
        label=_("Turnstile token"),
    )

    def clean_turnstile_token(self):
        """Validate the Turnstile token against Cloudflare's siteverify API.

        Per ADR-008 D3: if the secret key is not configured → raise loudly.
        Per ADR-014 D3: Turnstile pre-issuance gate on the claim form.
        """
        from accounts.adapter import validate_turnstile_token

        token = self.cleaned_data.get("turnstile_token", "")

        if settings.DEBUG:
            # DEBUG-only bypass: the widget is suppressed in DEBUG (commit f1b84aa),
            # so there is no token to validate. Scoped to DEBUG=True — the Django
            # test runner forces DEBUG=False, and production runs DEBUG=False, so the
            # ADR-014 D3 Turnstile gate is unchanged everywhere it matters.
            return token

        secret_key = getattr(settings, "TURNSTILE_SECRET_KEY", "")

        if not secret_key:
            # Misconfiguration: no secret key — fail loud (ADR-008 D3)
            raise forms.ValidationError(
                _(
                    "Claim submission is temporarily unavailable"
                    " (server misconfiguration). Please try again later."
                )
            )

        is_valid = validate_turnstile_token(token, secret_key)
        if not is_valid:
            raise forms.ValidationError(
                _("Human verification failed. Please complete the CAPTCHA.")
            )

        return token
