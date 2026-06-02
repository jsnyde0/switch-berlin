"""Forms for the reviews app."""

from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Flag


class TakedownForm(forms.ModelForm):
    """DSA Art. 16(2)-compliant takedown / flag submission form.

    Rules:
    - good_faith_confirmed is always required (checkbox).
    - contact_email and law_reference are required when reason == 'illegal'.
    - For all other reasons, neither field is required.
    """

    good_faith_confirmed = forms.BooleanField(
        required=True,
        label=_("I confirm the information above is accurate to the best of my knowledge (DSA Art. 16(2))."),
    )

    class Meta:
        model = Flag
        fields = [
            "reason",
            "body",
            "contact_email",
            "law_reference",
            "good_faith_confirmed",
        ]

    def clean(self):
        cleaned = super().clean()
        reason = cleaned.get("reason")
        if reason == "illegal":
            if not cleaned.get("contact_email"):
                self.add_error(
                    "contact_email",
                    _("Required for illegal-content reports (DSA Art. 16)."),
                )
            if not cleaned.get("law_reference"):
                self.add_error(
                    "law_reference",
                    _("Specify the law or legal provision violated (DSA Art. 16)."),
                )
        return cleaned
