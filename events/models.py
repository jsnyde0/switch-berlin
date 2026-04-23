from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


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


class EventManager(models.Manager):
    def visible(self):
        return self.filter(hidden=False)


class Event(models.Model):
    objects = EventManager()

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200)  # unique per-organizer, see Meta
    description = models.TextField(blank=True)
    organizer = models.ForeignKey(
        "organizers.Organizer",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
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
            models.Index(fields=["organizer", "start"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["organizer", "slug"],
                name="event_slug_unique_per_organizer",
            ),
            models.UniqueConstraint(
                fields=["organizer", "start", "title"],
                name="event_dup_guard_org_start_title",
            ),
        ]

    def __str__(self):
        return self.title


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
