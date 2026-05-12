from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

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


class EventManager(models.Manager):
    def visible(self):
        return self.filter(hidden=False)


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
    tags = models.ManyToManyField(Tag, blank=True, related_name="events")
    suggested_tags = models.JSONField(default=list, blank=True)

    # Time — no per-event timezone in 0.1 (TIME_ZONE=Europe/Berlin covers single-city).
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)

    # Price
    price_min_cents = models.IntegerField(null=True, blank=True)
    price_max_cents = models.IntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")
    is_free = models.BooleanField(default=False)
    sliding_scale = models.BooleanField(default=False)

    # Price (human-readable tiers, supplementing price_min/max_cents)
    price_description = models.TextField(
        blank=True,
        help_text=(
            'Free-form price tiers, e.g. "Supporter 250€ / Normal 200€ / Social 150€"'
        ),
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

    # Aggregate / visibility fields (Phase 0.5)
    hidden = models.BooleanField(default=False)
    attendance_count = models.IntegerField(default=0)
    interested_count = models.IntegerField(default=0)
    rating_count = models.IntegerField(default=0)
    avg_rating = models.FloatField(null=True, blank=True)

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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
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
    image = models.ImageField(upload_to="events/")
    alt = models.CharField(max_length=300, blank=True)
    is_cover = models.BooleanField(default=False)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("event image")
        verbose_name_plural = _("event images")

    def __str__(self):
        return f"Image for {self.event} ({self.order})"
