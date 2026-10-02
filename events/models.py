from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from a_core.validators import validate_image_size
from events.managers import EventManager
from venues.address import validate_no_street_address

# Sentinel for "no value supplied" — distinguishes organizer=None from not set.
_UNSET = object()


class Tag(models.Model):
    slug = models.SlugField(unique=True)
    label = models.CharField(max_length=100)
    # F3 — include 'bubble' now; promote to own model later if needed
    kind = models.CharField(
        choices=[
            ("theme", "Theme"),
            ("format", "Format"),
            ("identity", "Identity"),
            ("bubble", "Bubble"),
        ]
    )
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["label"]
        verbose_name = _("tag")
        verbose_name_plural = _("tags")

    def __str__(self):
        return self.label


class EventOrganizer(models.Model):
    """
    Through-table connecting Event to Profile (ADR-007 D2).

    is_primary=True marks the 'hosting' organizer (at most one per event).
    A partial unique constraint enforces this at the DB level.
    """

    event = models.ForeignKey(
        "Event",
        on_delete=models.CASCADE,
        related_name="event_organizer_set",
    )
    profile = models.ForeignKey(
        "organizers.Profile",
        on_delete=models.PROTECT,
        related_name="event_organizer_set",
    )
    is_primary = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    # How the collector attributed this organizer (ADR-007 D9); blank = set by a person.
    attribution = models.CharField(
        max_length=10,
        blank=True,
        choices=[("explicit", _("named in the text")), ("publisher", _("the publishing source"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("event organizer")
        verbose_name_plural = _("event organizers")
        constraints = [
            # At most one is_primary=True row per event
            models.UniqueConstraint(
                condition=Q(is_primary=True),
                fields=["event"],
                name="event_organizer_one_primary_per_event",
            ),
        ]

    def __str__(self):
        role = "primary" if self.is_primary else "co-organizer"
        return f"{self.profile} — {self.event} ({role})"


class EventArtist(models.Model):
    """
    An artist credit on an event (ADR-007 D2): a display name, optionally
    linked to a Profile. Credited only — artists cannot edit the event
    (ADR-017 D1). Only the event's organizer managers or staff set the link.

    role is free text (Lead, DJ, Doula, …), kept but not displayed. The same
    profile can be an EventOrganizer AND an EventArtist of the same event.
    """

    event = models.ForeignKey(
        "Event",
        on_delete=models.CASCADE,
        related_name="artist_credits",
    )
    profile = models.ForeignKey(
        "organizers.Profile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="artist_credits",
    )
    name = models.CharField(max_length=200)
    role = models.CharField(max_length=100, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("event artist")
        verbose_name_plural = _("event artists")
        unique_together = (("event", "profile"),)

    def __str__(self):
        role_str = f" ({self.role})" if self.role else ""
        return f"{self.name} — {self.event}{role_str}"


class Event(models.Model):
    objects = EventManager()

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200)
    description = models.TextField(blank=True)
    organizers = models.ManyToManyField(
        "organizers.Profile",
        through="EventOrganizer",
        through_fields=("event", "profile"),
        related_name="events_organized",
        blank=True,
    )
    venue = models.ForeignKey(
        "venues.Venue",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
    )
    # Free text for anything that is not a real place ("Secret location, Mitte",
    # "Online (Zoom)"), shown where the venue would be. Never a street address:
    # addresses live on a Venue, where privacy_mode applies (sb-x5xh.2 ruling (b)).
    location_note = models.CharField(max_length=200, blank=True, validators=[validate_no_street_address])
    tags = models.ManyToManyField(Tag, blank=True, related_name="events")
    suggested_tags = models.JSONField(default=list, blank=True)

    # Time — no per-event timezone in 0.1 (TIME_ZONE=Europe/Berlin covers single-city).
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    # The source gave a date but no time: start holds that day at 00:00 and every
    # render says "time to be announced" instead (sb-7wzb.4; ADR-008 D3).
    start_time_unknown = models.BooleanField(default=False)

    # Price
    price_min_cents = models.IntegerField(null=True, blank=True)
    price_max_cents = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    is_free = models.BooleanField(default=False)
    sliding_scale = models.BooleanField(default=False)

    # Price (human-readable tiers, supplementing price_min/max_cents)
    price_description = models.TextField(
        blank=True,
        help_text=('Free-form price tiers, e.g. "Supporter 250€ / Normal 200€ / Social 150€"'),
    )

    # Language
    language = models.CharField(
        max_length=10,
        blank=True,
        choices=[
            ("de", "Deutsch"),
            ("en", "English"),
            ("bilingual", "DE+EN"),
        ],
        help_text="Primary language(s) of the event",
    )

    # Capacity
    capacity = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Max attendees; null = no cap / drop-in",
    )

    # Registration
    registration_required = models.BooleanField(
        default=False,
    )
    registration_url = models.URLField(
        blank=True,
        help_text="External registration page distinct from tickets_url",
    )

    # External
    external_url = models.URLField(blank=True)
    tickets_url = models.URLField(blank=True)
    # Registration by email (alternative to tickets_url)
    registration_email = models.EmailField(
        blank=True,
        help_text="If organizers take registration by email rather than ticket link",
    )

    # Lifecycle
    status = models.CharField(
        choices=[
            ("draft", "Draft"),
            ("review", "Needs review"),
            ("published", "Published"),
            ("cancelled", "Cancelled"),
            ("rejected", "Rejected"),
            ("archived", "Archived"),
        ],
        default="draft",
    )
    published_at = models.DateTimeField(null=True, blank=True)

    # Visibility tier (ADR-012 D1)
    visibility = models.CharField(
        max_length=20,
        choices=[
            ("public", "Public"),
            ("semi_public", "Semi-public"),
            ("unlisted", "Unlisted"),
        ],
        default="public",
        help_text=(
            "public: anyone, indexed. semi_public: vouched users only, noindex. unlisted: URL-keyed only, noindex."
        ),
    )

    # Aggregate / visibility fields (Phase 0.5)
    hidden = models.BooleanField(default=False)
    attendance_count = models.IntegerField(default=0)
    interested_count = models.IntegerField(default=0)
    rating_count = models.IntegerField(default=0)
    avg_rating = models.FloatField(null=True, blank=True)

    # --- Syndication extensions (sb-a4u.1, ADR-016 D1) ---

    # Event category (ADR-016 D1; v0 vocabulary — single CharField, no FK taxonomy).
    # blank=True per ADR-016 D5: save-always, completeness enforced at draft→ready.
    CATEGORY_CHOICES = [
        ("play_party", "Play Party"),
        ("workshop", "Workshop"),
        ("munch", "Munch"),
        ("performance", "Performance"),
        ("social", "Social"),
        ("festival", "Festival"),
        ("other", "Other"),
    ]
    category = models.CharField(
        max_length=50,
        choices=CATEGORY_CHOICES,
        blank=True,
        help_text="Event category (v0 vocabulary).",
    )

    # Content policy fields (listing-platform structured data)
    dress_code = models.CharField(
        max_length=300,
        blank=True,
        help_text="Dress code for the event (e.g., 'Fetish attire required').",
    )
    content_warnings = models.JSONField(
        default=list,
        blank=True,
        help_text="List of content warning strings (e.g., ['nudity', 'bdsm']).",
    )
    age_restriction = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Minimum age for attendees; null = no age restriction.",
    )

    # --- Recurrence reservation (ADR-016 Consequences, ADR-003 cheap foresight) ---
    # Data-shape only. Recurring-events behavioral epic ships later.

    recurrence_rule = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        help_text=(
            "RESERVED: iCal RRULE string for recurring events "
            "(e.g., 'FREQ=WEEKLY;BYDAY=SA'). null = one-time event. "
            "Behavior: recurring-events epic."
        ),
    )
    recurrence_parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurrence_instances",
        help_text=(
            "RESERVED: FK to the canonical recurring event this instance was generated from. "
            "null = original / standalone. Behavior: recurring-events epic."
        ),
    )

    # --- Ticket type taxonomy reservation (ADR-016 Consequences, ADR-003) ---
    ticket_types = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "RESERVED: full ticket type taxonomy "
            "(e.g., [{'name': 'Early Bird', 'price_cents': 1500, 'capacity': 20}]). "
            "Behavior: ticketing epic (ADR-015)."
        ),
    )

    # --- Buyer / attendee screening question reservations (ADR-016 Consequences) ---
    buyer_questions = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "RESERVED: screening questions asked at ticket purchase "
            "(e.g., [{'question': 'Have you attended before?', 'type': 'bool'}]). "
            "Behavior: RSVP+screening epic."
        ),
    )
    attendee_questions = models.JSONField(
        default=list,
        blank=True,
        help_text=("RESERVED: screening questions asked at event entry / check-in. Behavior: RSVP+screening epic."),
    )

    # Provenance (F7)
    raw_message = models.ForeignKey(
        "ingestion.RawMessage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="extracted_events",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start"]
        verbose_name = _("event")
        verbose_name_plural = _("events")
        indexes = [
            models.Index(fields=["status", "start"]),
        ]

    def __init__(self, *args, **kwargs):
        # Buffer organizer= kwarg so Event.objects.create(organizer=p, ...) works.
        # The value is flushed to EventOrganizer in save().
        _organizer = kwargs.pop("organizer", _UNSET)
        super().__init__(*args, **kwargs)
        if _organizer is not _UNSET:
            self._pending_organizer = _organizer

    def __str__(self):
        return self.title

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        # Remember the loaded start so save() can tell when a real time was written.
        instance._loaded_start = instance.__dict__.get("start")
        return instance

    def save(self, *args, **kwargs):
        # A date-only event whose start is edited (studio form, admin, API) now
        # has a real time: stop saying "time to be announced" (sb-7wzb.4 B1).
        loaded_start = getattr(self, "_loaded_start", None)
        if self.start_time_unknown and loaded_start is not None and self.start != loaded_start:
            self.start_time_unknown = False
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "start_time_unknown" not in update_fields:
                kwargs["update_fields"] = [*update_fields, "start_time_unknown"]
        super().save(*args, **kwargs)
        self._loaded_start = self.start
        pending = getattr(self, "_pending_organizer", _UNSET)
        if pending is not _UNSET:
            del self._pending_organizer
            if pending is None:
                # organizer=None: remove any existing primary EventOrganizer
                self.event_organizer_set.filter(is_primary=True).delete()
            else:
                eo, created = EventOrganizer.objects.get_or_create(
                    event=self,
                    is_primary=True,
                    defaults={"profile": pending, "order": 0},
                )
                if not created and eo.profile != pending:
                    eo.profile = pending
                    eo.save(update_fields=["profile"])

    @property
    def organizer(self):
        """
        Compat property: return the primary Profile for this event (or None).

        Preserves the FK semantics of the old Event.organizer field so that
        ~30 call sites (templates, views, admin, ingestion, tests) continue
        working without modification.
        """
        try:
            return self.event_organizer_set.get(is_primary=True).profile
        except EventOrganizer.DoesNotExist:
            return None

    @organizer.setter
    def organizer(self, value):
        """
        Compat setter: buffer the new organizer value.

        If the Event has already been saved (has a PK), apply immediately.
        Otherwise, buffer and apply after save() is called.
        """
        if self.pk is None:
            self._pending_organizer = value
        else:
            if value is None:
                self.event_organizer_set.filter(is_primary=True).delete()
            else:
                eo, created = EventOrganizer.objects.get_or_create(
                    event=self,
                    is_primary=True,
                    defaults={"profile": value, "order": 0},
                )
                if not created and eo.profile != value:
                    eo.profile = value
                    eo.save(update_fields=["profile"])

    @property
    def primary_organizer(self):
        """Alias for event.organizer (explicit form preferred in new code)."""
        return self.organizer

    @property
    def is_indexable(self) -> bool:
        """True iff robots may index this event (ADR-012 D4).

        Only public-tier events are search-engine indexable. semi_public and
        unlisted carry X-Robots-Tag: noindex (set by sb-m69.6 middleware) and
        are excluded from the sitemap.
        """
        return self.visibility == "public"


class Attendance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ("interested", "Interested"),
            ("going", "Going"),
            ("went", "Went"),
        ],
        default="interested",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "event")]

    def __str__(self):
        return f"{self.user} — {self.event} ({self.status})"


class EventImage(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(
        upload_to="events/",
        validators=[
            validate_image_size,
            FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"]),
        ],
    )
    alt = models.CharField(max_length=300, blank=True)
    is_cover = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("event image")
        verbose_name_plural = _("event images")

    def __str__(self):
        return f"Image for {self.event} ({self.order})"
