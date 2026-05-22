from django.contrib import admin
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import ClaimIntent, Profile, ProfileClaim


class ProfileClaimInline(admin.TabularInline):
    """
    Read-only inline for V0 — shows ProfileClaim rows on the Profile admin page.
    S9 (admin claim-queue) adds approve/reject/revoke actions in its own bead.
    """

    model = ProfileClaim
    extra = 0
    readonly_fields = [
        "user",
        "verified_at",
        "verified_method",
        "verified_by_admin",
        "role",
        "created_at",
        "rejected_at",
        "rejected_by_admin",
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "status", "verified_badge", "event_count"]
    list_filter = ["kind", "status", "verified_badge"]
    search_fields = ["name", "slug", "telegram_link"]
    readonly_fields = ["created_at", "updated_at", "approved_at"]
    inlines = [ProfileClaimInline]
    actions = [
        "mark_approved_explicit_opt_in",
        "mark_approved_telegram_forward_implied",
        "mark_approved_verified_public_source",
    ]

    def get_queryset(self, request):
        # events_organized is the M2M reverse from Event.organizers (kb-n0y)
        return (
            super()
            .get_queryset(request)
            .annotate(event_count=Count("events_organized", distinct=True))
        )

    def event_count(self, obj):
        return obj.event_count

    event_count.short_description = _("Events")
    event_count.admin_order_field = "event_count"

    @admin.action(description=_("Mark approved — explicit opt-in consent"))
    def mark_approved_explicit_opt_in(self, request, queryset):
        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="explicit_opt_in",
        )

    @admin.action(description=_("Mark approved — Telegram forward (implied consent)"))
    def mark_approved_telegram_forward_implied(self, request, queryset):
        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="telegram_forward_implied",
        )

    @admin.action(description=_("Mark approved — verified public source"))
    def mark_approved_verified_public_source(self, request, queryset):
        queryset.update(
            status="approved",
            approved_at=timezone.now(),
            approved_by=request.user,
            consent_recorded_at=timezone.now(),
            consent_method="verified_public_source",
        )


@admin.register(ClaimIntent)
class ClaimIntentAdmin(admin.ModelAdmin):
    """
    Admin surface for ClaimIntent rows (kb-m69.8 model).

    Shows pending intents (resolved_at IS NULL AND rejected_at IS NULL).
    Admin actions:
    - approve_claim: create ProfileClaim with verified_method='admin_review',
      set resolved_at
    - reject_claim: set rejected_at + rejected_by_admin + rejection_reason,
      no ProfileClaim

    Per ADR-014 D2 (admin-review track + soft-delete pattern).
    Per ADR-008 D3 (fail-loud on idempotency violation).
    """

    list_display = [
        "user",
        "user_email",
        "profile",
        "created_at",
        "message_preview",
        "is_pending",
    ]
    list_filter = ["resolved_at", "rejected_at"]
    search_fields = ["user__email", "user__username", "profile__name", "message"]
    readonly_fields = [
        "user",
        "profile",
        "created_at",
        "message",
        "submitter_verified_at",
        "resolved_at",
        "rejected_at",
        "rejected_by_admin",
        "rejection_reason",
    ]
    actions = ["approve_claim", "reject_claim"]

    def is_pending(self, obj):
        """Computed: True when resolved_at IS NULL AND rejected_at IS NULL."""
        return obj.resolved_at is None and obj.rejected_at is None

    is_pending.short_description = _("Pending")
    is_pending.boolean = True

    def user_email(self, obj):
        """Claimant's email — admin can mailto: from the list view (kb-j8u)."""
        return obj.user.email

    user_email.short_description = _("Email (contact)")

    def message_preview(self, obj):
        """First 80 chars of the claimant's message (kb-j8u)."""
        if not obj.message:
            return ""
        return obj.message if len(obj.message) <= 80 else obj.message[:77] + "…"

    message_preview.short_description = _("Message")

    @admin.action(description=_("Approve claim — create ProfileClaim (admin_review)"))
    def approve_claim(self, request, queryset):
        """
        Create a ProfileClaim with verified_method='admin_review', set resolved_at.

        Atomic. Per ADR-008 D3: fails loud if:
        - intent is already resolved (resolved_at IS NOT NULL)
        - user is already an active claimant of this profile
        """
        approved_count = 0
        skipped_count = 0

        for intent in queryset.select_related("user", "profile"):
            # Fail loud: already resolved
            if intent.resolved_at is not None:
                self.message_user(
                    request,
                    _(
                        f"Intent #{intent.pk} ({intent.user} → {intent.profile}) "
                        f"is already resolved — skipped."
                    ),
                    level="WARNING",
                )
                skipped_count += 1
                continue

            # Fail loud: user is already an active claimant of this profile
            already_active = intent.profile.profileclaim_set.filter(
                user=intent.user,
                rejected_at__isnull=True,
            ).exists()
            if already_active:
                self.message_user(
                    request,
                    _(
                        f"User {intent.user} is already an active claimant of "
                        f"{intent.profile} — skipped (ADR-008 D3)."
                    ),
                    level="WARNING",
                )
                skipped_count += 1
                continue

            # Atomic: create ProfileClaim + set resolved_at
            with transaction.atomic():
                ProfileClaim.objects.create(
                    profile=intent.profile,
                    user=intent.user,
                    verified_method="admin_review",
                    verified_by_admin=request.user.username,
                    role="admin",
                )
                ClaimIntent.objects.filter(pk=intent.pk).update(
                    resolved_at=timezone.now()
                )
            approved_count += 1

        if approved_count:
            self.message_user(
                request,
                _(f"Approved {approved_count} claim(s)."),
            )

    @admin.action(description=_("Reject claim — soft-delete, no ProfileClaim"))
    def reject_claim(self, request, queryset):
        """
        Set rejected_at + rejected_by_admin on the ClaimIntent.
        No ProfileClaim created.
        Per ADR-014 D2 soft-delete: row preserved for audit trail.
        """
        updated = queryset.update(
            rejected_at=timezone.now(),
            rejected_by_admin=request.user,
        )
        self.message_user(request, _(f"Rejected {updated} claim intent(s)."))


@admin.register(ProfileClaim)
class ProfileClaimAdmin(admin.ModelAdmin):
    """
    Top-level admin for ProfileClaim rows.

    Extends kb-m69.3's read-only ProfileClaimInline on Profile admin page
    with a revoke_claim admin action (this is a separate top-level admin).

    revoke_claim:
    - Sets rejected_at=now(), rejected_by_admin=admin_username on non-revoked claims.
    - Fails loud (warning) if claim is already revoked (ADR-008 D3).
    - Soft-delete: row preserved per ADR-014 D2.
    """

    list_display = ["user", "profile", "verified_method", "created_at", "is_revoked"]
    list_filter = ["rejected_at", "verified_method"]
    search_fields = ["profile__name", "user__email", "user__username"]
    readonly_fields = [
        "profile",
        "user",
        "verified_at",
        "verified_method",
        "verified_by_admin",
        "role",
        "created_at",
        "rejected_at",
        "rejected_by_admin",
        "revocation_reason",
    ]
    actions = ["revoke_claim"]

    def is_revoked(self, obj):
        """True if rejected_at is set (soft-deleted by admin revoke)."""
        return obj.rejected_at is not None

    is_revoked.short_description = _("Revoked")
    is_revoked.boolean = True

    @admin.action(description=_("Revoke claim — soft-delete (sets rejected_at)"))
    def revoke_claim(self, request, queryset):
        """
        Soft-revoke ProfileClaim rows by setting rejected_at + rejected_by_admin.

        Per ADR-008 D3: fails loud (warning) on already-revoked claims.
        Per ADR-014 D2: never hard-deletes — sets rejected_at only.
        """
        skipped_count = 0
        revoked_count = 0

        for claim in queryset.select_related("user", "profile"):
            # Fail loud: already revoked
            if claim.rejected_at is not None:
                self.message_user(
                    request,
                    _(
                        f"Claim #{claim.pk} ({claim.user} → {claim.profile}) "
                        f"is already revoked — skipped (ADR-008 D3)."
                    ),
                    level="WARNING",
                )
                skipped_count += 1
                continue

            ProfileClaim.objects.filter(pk=claim.pk).update(
                rejected_at=timezone.now(),
                rejected_by_admin=request.user.username,
            )
            revoked_count += 1

        if revoked_count:
            self.message_user(
                request,
                _(f"Revoked {revoked_count} claim(s)."),
            )
