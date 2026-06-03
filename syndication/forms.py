"""
Web forms for syndication Event and Post authoring (kb-a4u.3).

Co-equal seam (ADR-016 D3/D6): forms do NOT implement persistence directly.
They validate and clean data; the view calls syndication.services.create_event
/ create_post with the cleaned data — the same service functions the API handlers call.

ADR-016 D5: save-always — completeness gated at draft→ready, never at save.
No required fields beyond the minimal set that makes a draft meaningful.
ADR-008 D3: fail-loud on data integrity — no silent zero-fill.

Form precedents: organizers/forms.py, accounts/forms.py.
"""

import json

from django import forms
from django.utils.translation import gettext_lazy as _


class EventForm(forms.Form):
    """
    Event authoring form carrying ALL ADR-016 D1 fields.

    HTMX + Alpine per ADR-004.
    Renders as an HTML form whose POST calls the same service function
    as the Ninja API endpoint (co-equal, ADR-016 D3).

    ADR-016 D5: only title, slug, start are truly required for a minimal draft.
    All other fields are optional at save time; completeness is enforced at
    draft→ready, never here.

    v0 field set (kb-a4u acceptance criterion 1):
    title, description, start, end, venue (location FK), tags (M2M),
    dress_code, content_warnings, age_restriction, capacity,
    visibility, language, is_free, price_min_cents, price_max_cents,
    currency, sliding_scale, price_description, external_url, tickets_url,
    registration_required, registration_url, registration_email.

    Note: timezone is not authored per-event at v0 (TIME_ZONE=Europe/Berlin).
    """

    title = forms.CharField(
        max_length=300,
        label=_("Title"),
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    slug = forms.SlugField(
        max_length=200,
        label=_("URL slug"),
        help_text=_("Short, URL-friendly identifier. e.g. 'my-party-2026'"),
    )
    start = forms.DateTimeField(
        label=_("Start"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    end = forms.DateTimeField(
        required=False,
        label=_("End"),
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    description = forms.CharField(
        required=False,
        label=_("Description"),
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    venue = forms.IntegerField(
        required=False,
        label=_("Venue / Location"),
        help_text=_("Venue ID. Leave blank if venue is not yet known."),
        widget=forms.NumberInput(attrs={"placeholder": "Venue ID"}),
    )
    tags = forms.CharField(
        required=False,
        label=_("Tags"),
        help_text=_("Comma-separated tag slugs, e.g. 'fetish,bdsm,nudist'"),
        widget=forms.TextInput(attrs={"placeholder": "fetish, bdsm"}),
    )

    def clean_venue(self):
        """
        Resolve venue ID to a Venue instance.

        ADR-008 D3: fail-loud on invalid venue ID — no silent None fallback.
        Returns None if blank (venue is optional at draft time).
        """
        raw = self.cleaned_data.get("venue")
        if raw is None:
            return None
        from venues.models import Venue

        try:
            return Venue.objects.get(pk=raw)
        except Venue.DoesNotExist:
            raise forms.ValidationError(_("Venue with ID %(id)s does not exist.") % {"id": raw}) from None

    def clean_tags(self):
        """
        Parse tags from a comma-separated string to a list of Tag slugs.

        ADR-008 D3: unknown slugs are silently skipped (tags are optional; no
        hard failure on typo). Returns a list of Tag pk values.
        """
        from events.models import Tag

        raw = self.cleaned_data.get("tags", "").strip()
        if not raw:
            return []
        slugs = [s.strip() for s in raw.split(",") if s.strip()]
        return list(Tag.objects.filter(slug__in=slugs).values_list("pk", flat=True))

    dress_code = forms.CharField(
        required=False,
        max_length=300,
        label=_("Dress code"),
        help_text=_("e.g. 'Fetish attire required', 'Nude / minimal clothing'"),
    )
    content_warnings = forms.CharField(
        required=False,
        label=_("Content warnings"),
        help_text=_('JSON array of strings. e.g. ["nudity", "bdsm"]'),
        widget=forms.TextInput(attrs={"placeholder": '["nudity", "bdsm"]'}),
    )
    age_restriction = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=99,
        label=_("Age restriction"),
        help_text=_("Minimum age for attendees. Leave blank for no restriction."),
    )
    capacity = forms.IntegerField(
        required=False,
        min_value=1,
        label=_("Capacity"),
        help_text=_("Maximum number of attendees. Leave blank for no cap."),
    )
    visibility = forms.ChoiceField(
        choices=[
            ("public", _("Public — anyone, indexed")),
            ("semi_public", _("Semi-public — vouched users only, noindex")),
            ("unlisted", _("Unlisted — URL-only, noindex")),
        ],
        initial="public",
        required=False,
        label=_("Visibility"),
    )
    language = forms.ChoiceField(
        choices=[
            ("", _("— not specified —")),
            ("de", "Deutsch"),
            ("en", "English"),
            ("bilingual", "DE+EN"),
        ],
        required=False,
        label=_("Language"),
    )
    is_free = forms.BooleanField(
        required=False,
        label=_("Free event"),
    )
    price_min_cents = forms.IntegerField(
        required=False,
        min_value=0,
        label=_("Min price (cents)"),
        help_text=_("e.g. 2000 = 20.00€"),
    )
    price_max_cents = forms.IntegerField(
        required=False,
        min_value=0,
        label=_("Max price (cents)"),
    )
    currency = forms.CharField(
        required=False,
        max_length=3,
        initial="EUR",
        label=_("Currency"),
    )
    sliding_scale = forms.BooleanField(
        required=False,
        label=_("Sliding scale pricing"),
    )
    price_description = forms.CharField(
        required=False,
        label=_("Price description"),
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text=_('Free-form, e.g. "Supporter 25€ / Normal 20€ / Social 15€"'),
    )
    external_url = forms.URLField(
        required=False,
        label=_("External URL"),
        help_text=_("Organizer page or event page on another platform."),
    )
    tickets_url = forms.URLField(
        required=False,
        label=_("Tickets URL"),
        help_text=_("Direct link to buy tickets."),
    )
    registration_required = forms.BooleanField(
        required=False,
        label=_("Registration required"),
    )
    registration_url = forms.URLField(
        required=False,
        label=_("Registration URL"),
    )
    registration_email = forms.EmailField(
        required=False,
        label=_("Registration email"),
        help_text=_("Email address for registrations instead of a ticket link."),
    )

    # --- D1 fields completed in kb-a4u.19 ---

    CATEGORY_CHOICES = [
        ("", _("— not specified —")),
        ("play_party", _("Play Party")),
        ("workshop", _("Workshop")),
        ("munch", _("Munch")),
        ("performance", _("Performance")),
        ("social", _("Social")),
        ("festival", _("Festival")),
        ("other", _("Other")),
    ]
    category = forms.ChoiceField(
        choices=CATEGORY_CHOICES,
        required=False,
        label=_("Category"),
    )
    cover_image = forms.ImageField(
        required=False,
        label=_("Cover image"),
        help_text=_("JPG, PNG, or WebP. Max 5 MiB."),
    )

    def clean_content_warnings(self):
        """
        Parse content_warnings from a JSON-encoded string to a Python list.

        ADR-008 D3: fail loud on parse error — no silent empty-list fallback.
        """
        raw = self.cleaned_data.get("content_warnings", "").strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(
                _('Content warnings must be a valid JSON array, e.g. ["nudity", "bdsm"].')
            ) from exc
        if not isinstance(parsed, list):
            raise forms.ValidationError(_("Content warnings must be a JSON array."))
        return parsed


class PostForm(forms.Form):
    """
    Post authoring form for creating a promotional Post scoped to an Event.

    HTMX + Alpine per ADR-004.
    headline and body are the core fields (ADR-016 D1 for Post).
    Optional fields: cta, voice.
    """

    headline = forms.CharField(
        max_length=300,
        label=_("Headline / hook"),
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    body = forms.CharField(
        label=_("Post body"),
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text=_("The announcement text. Not derived from event description."),
    )
    cta = forms.CharField(
        required=False,
        max_length=500,
        label=_("Call to action"),
        help_text=_("URL or text to link readers to tickets/listing."),
    )
    voice = forms.CharField(
        required=False,
        max_length=100,
        label=_("Voice / tone"),
        help_text=_("e.g. 'playful', 'formal', 'urgent'"),
    )


class ContentVersionForm(forms.Form):
    """
    Minimal form for ContentVersion authoring (kb-wz8m.1 additive step).

    Only the core fields — name is required; editorial fields are optional
    (ADR-016 D5 save-always; completeness gated at draft→ready, never here).
    """

    name = forms.CharField(
        max_length=200,
        label=_("Version name"),
        help_text=_("e.g. 'canonical', 'hipsy-censored', 'campaign-v1'"),
    )
    headline = forms.CharField(
        required=False,
        max_length=300,
        label=_("Headline"),
    )
    body = forms.CharField(
        required=False,
        label=_("Body"),
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    imagery = forms.CharField(
        required=False,
        label=_("Imagery"),
        help_text=_('JSON array of image references/URLs, e.g. ["img1.jpg"]'),
        widget=forms.TextInput(attrs={"placeholder": '["img1.jpg"]'}),
    )
    cta = forms.CharField(
        required=False,
        max_length=500,
        label=_("Call to action"),
    )
    voice = forms.CharField(
        required=False,
        max_length=100,
        label=_("Voice / tone"),
        help_text=_("e.g. 'playful', 'formal'"),
    )


class PlatformConnectionForm(forms.Form):
    """
    Form for creating or editing a PlatformConnection.

    kinds is a MultipleChoiceField rendered as checkboxes — no raw JSON
    visible to the user. cleaned_data["kinds"] is already a plain Python
    list (["listing"] / ["promotion"] / ["listing","promotion"]).

    destination_id is required for non-switch platforms; for switch the
    view/form defaults it to "own-page" when blank (ADR-008 D3: fail loud
    for non-switch with empty destination, never silent zero-fill).
    """

    KINDS_CHOICES = [
        ("listing", _("Listing")),
        ("promotion", _("Promotion")),
    ]

    platform = forms.ChoiceField(
        choices=[
            ("switch", _("Switch (own event page)")),
            ("fetlife", _("FetLife")),
            ("tickettailor", _("Ticket Tailor")),
            ("telegram", _("Telegram channel")),
        ],
        label=_("Platform"),
    )
    destination_id = forms.CharField(
        max_length=300,
        required=False,
        label=_("Destination"),
        help_text=_("Platform-specific identifier: channel username, account ID, etc."),
    )
    kinds = forms.MultipleChoiceField(
        choices=KINDS_CHOICES,
        required=True,
        label=_("Kinds"),
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Select at least one kind this connection supports."),
    )
    enabled = forms.BooleanField(
        required=False,
        initial=True,
        label=_("Enabled"),
        help_text=_("Enable this connection for eager projection creation."),
    )

    def clean(self):
        """
        Cross-field validation:
        - For non-switch platforms, destination_id is required (fail loud).
        - For switch, default destination_id to 'own-page' if blank.
        """
        cleaned = super().clean()
        platform = cleaned.get("platform")
        destination_id = cleaned.get("destination_id", "").strip()

        if platform == "switch":
            if not destination_id:
                cleaned["destination_id"] = "own-page"
        else:
            if not destination_id:
                self.add_error(
                    "destination_id",
                    _("This field is required for the selected platform."),
                )
        return cleaned
