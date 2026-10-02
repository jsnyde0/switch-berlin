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
    - "I am credited on this event" (sb-7wzb.23) files an artist-credit removal request: the
      credited name and a contact email are required, the reason is fixed, no law is needed.
      The form only files the request; staff remove the credit.
    """

    credited = forms.BooleanField(required=False, label=_("I am credited on this event"))
    credited_name = forms.CharField(required=False, max_length=200, label=_("The name you are credited under"))

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
            "credited_name",
            "good_faith_confirmed",
        ]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("credited"):
            cleaned["reason"] = "artist_credit"
            for field in ("credited_name", "contact_email"):
                if not cleaned.get(field):
                    self.add_error(field, _("Required to remove a credit."))
            return cleaned
        cleaned["credited_name"] = ""
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
