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
        "organizers.Organizer",
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

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        constraints = [
            models.CheckConstraint(
                condition=Q(organizer__isnull=False) ^ Q(event__isnull=False),
                name="review_targets_exactly_one",
            ),
        ]

    def __str__(self):
        return f"Review by {self.author} (rating={self.rating})"
