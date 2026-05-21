import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserStatus(models.TextChoices):
    OPEN = "open", _("Open")
    VOUCHED = "vouched", _("Vouched")
    SUSPENDED_PENDING_INVESTIGATION = "suspended_pending_investigation", _(
        "Suspended — Pending Investigation"
    )
    BANNED = "banned", _("Banned")


class User(AbstractUser):
    status = models.CharField(
        max_length=40,
        choices=UserStatus.choices,
        default=UserStatus.OPEN,
        help_text=(
            "Trust tier: open (signup default), vouched (invite-verified), "
            "suspended_pending_investigation (reversible), banned (admin-final)."
        ),
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_users",
    )
    art9_consent_given_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Timestamp when the user gave Art. 9(2)(a) GDPR consent for "
            "storing attendance data (kink/queer event attendance may reveal "
            "sexual orientation). Null = no consent; attendance writes blocked."
        ),
    )
    # Cheap-foresight fields (ADR-003): ship now, activate logic in F1/F2/F4 beads.
    vouch_score = models.FloatField(
        default=0.0,
        help_text=(
            "Proportional trust score accumulated via vouching graph "
            "(F1 bead activates)."
        ),
    )
    personal_rating = models.FloatField(
        null=True,
        blank=True,
        help_text="Bayesian-averaged event-review rating (F2 bead activates).",
    )
    invite_codes_remaining = models.IntegerField(
        default=0,
        help_text=(
            "Admin-granted invite codes available to issue "
            "(F4 bead activates earning formula)."
        ),
    )

    class Meta(AbstractUser.Meta):
        verbose_name = _("user")
        verbose_name_plural = _("users")


def generate_code():
    return secrets.token_urlsafe(24)  # ~32 chars, 192 bits entropy


class InviteCode(models.Model):
    code = models.CharField(max_length=48, unique=True, default=generate_code)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invite_redeemed",
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return self.code[:12]
