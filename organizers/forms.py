"""
Forms for the organizer profile-claim flow.

Per ADR-014 D2: collects email for claim verification; validates against
Profile.verified_domain for the email-domain fast-path branch.
"""

from django import forms


class ClaimForm(forms.Form):
    """
    Claim entry form — collects the email address the user wants to verify
    their claim with.

    Validation logic:
    - email must be a valid email address (basic Django EmailField validation).
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
