import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserStatus(models.TextChoices):
    OPEN = "open", _("Open")
    VOUCHED = "vouched", _("Vouched")
    SUSPENDED_PENDING_INVESTIGATION = (
        "suspended_pending_investigation",
        _("Suspended — Pending Investigation"),
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
    """Single-use invite code owned by a grantor (vouched user or staff for
    admin-grants).

    Per ADR-013 D6 (V0 admin-grant invite economy).
    Per ADR-008 D3 (fail loud on invalid invite — usable() predicate).
    """

    code = models.CharField(max_length=48, unique=True, default=generate_code)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invites_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Single-use enforcement fields (kb-m69.7)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invite_used",
    )
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    def usable(self) -> bool:
        """Return True if this code can still be used to sign up.

        Per ADR-013 D6 (single-use enforcement).
        Per ADR-008 D3 (fail loud — callers must call usable() before redeeming).
        """
        from django.utils import timezone

        if self.used_at is not None:
            return False
        if self.expires_at is not None and self.expires_at <= timezone.now():
            return False
        return True

    def __str__(self):
        return self.code[:12]


class Vouch(models.Model):
    """Directed trust relationship: voucher vouches for vouchee.

    Per ADR-013 D3 (Vouch graph).
    Per ADR-003 (cheap-foresight cancelled_at — cancellation logic activates in F1
    bead).
    """

    voucher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vouches_given",
    )
    vouchee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vouches_received",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Cheap-foresight (ADR-003): cancellation logic activates in kb-a3a bead
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("voucher", "vouchee")]
        verbose_name = _("vouch")
        verbose_name_plural = _("vouches")

    def __str__(self):
        return f"{self.voucher} → {self.vouchee}"


class InviteGrant(models.Model):
    """Audit log: records each time an invite code was redeemed to create a vouched
    user.

    Per ADR-013 D4 (InviteGrant audit-log model).
    Per ADR-003 (cheap-foresight — grantor nullable for admin-grants).
    """

    # Nullable: admin-grants have no individual grantor (ADR-003)
    grantor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invite_grants_given",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="invite_grants_received",
    )
    invite_code = models.ForeignKey(
        InviteCode,
        on_delete=models.PROTECT,
        related_name="grants",
    )
    granted_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("invite grant")
        verbose_name_plural = _("invite grants")

    def __str__(self):
        return f"InviteGrant({self.recipient}, via {self.invite_code})"
