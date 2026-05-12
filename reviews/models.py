from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _


class Review(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    organizer = models.ForeignKey(
        "organizers.Profile",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    event = models.ForeignKey(
        "events.Event",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    body = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    hidden = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        constraints = [
            models.CheckConstraint(
                condition=Q(organizer__isnull=False) ^ Q(event__isnull=False),
                name="review_targets_exactly_one",
            ),
            models.UniqueConstraint(
                fields=["author", "organizer"],
                condition=models.Q(organizer__isnull=False),
                name="one_review_per_author_per_organizer",
            ),
            models.UniqueConstraint(
                fields=["author", "event"],
                condition=models.Q(event__isnull=False),
                name="one_review_per_author_per_event",
            ),
        ]

    def __str__(self):
        return f"Review by {self.author} (rating={self.rating})"


class Flag(models.Model):
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="flags_reported",
    )
    organizer = models.ForeignKey(
        "organizers.Profile", null=True, blank=True, on_delete=models.CASCADE,
        related_name="flags",
    )
    event = models.ForeignKey(
        "events.Event", null=True, blank=True, on_delete=models.CASCADE,
        related_name="flags",
    )
    review = models.ForeignKey(
        "reviews.Review", null=True, blank=True, on_delete=models.CASCADE,
        related_name="flags",
    )
    reason = models.CharField(
        max_length=30,
        choices=[
            ("illegal", "Illegal content — specify law"),
            ("spam", "Spam"), ("inaccurate", "Inaccurate"),
            ("harmful", "Harmful"), ("safety", "Safety concern"),
            ("other", "Other"),
        ],
    )
    body = models.TextField(blank=True)
    contact_email = models.EmailField(blank=True)
    law_reference = models.CharField(max_length=200, blank=True)
    good_faith_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="flags_resolved",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(organizer__isnull=False, event__isnull=True, review__isnull=True)
                    | Q(organizer__isnull=True, event__isnull=False, review__isnull=True)
                    | Q(organizer__isnull=True, event__isnull=True, review__isnull=False)
                ),
                name="flag_targets_exactly_one",
            ),
            models.UniqueConstraint(
                fields=["reporter", "event"],
                condition=models.Q(reporter__isnull=False, event__isnull=False),
                name="one_flag_per_reporter_per_event",
            ),
            models.UniqueConstraint(
                fields=["reporter", "organizer"],
                condition=models.Q(reporter__isnull=False, organizer__isnull=False),
                name="one_flag_per_reporter_per_organizer",
            ),
            models.UniqueConstraint(
                fields=["reporter", "review"],
                condition=models.Q(reporter__isnull=False, review__isnull=False),
                name="one_flag_per_reporter_per_review",
            ),
        ]
