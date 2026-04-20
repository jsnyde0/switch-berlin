import logging

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class NoSignupAdapter(DefaultAccountAdapter):
    """Invite-gated signup adapter — phase 0.4."""

    def is_open_for_signup(self, request):
        if not getattr(settings, "INVITES_ENABLED", True):
            return False
        code = request.GET.get("code") or request.session.get("invite_code")
        if not code:
            return False
        from accounts.models import InviteCode

        try:
            invite = InviteCode.objects.get(code=code, redeemed_by__isnull=True)
        except InviteCode.DoesNotExist:
            return False
        if invite.expires_at and invite.expires_at <= timezone.now():
            return False
        request.session["invite_code"] = code
        return True

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=commit)
        if commit:
            code = request.session.get("invite_code")
            if code:
                from accounts.models import InviteCode

                with transaction.atomic():
                    updated = InviteCode.objects.filter(
                        code=code, redeemed_by__isnull=True
                    ).update(redeemed_by=user, redeemed_at=timezone.now())
                    if updated == 0:
                        # Race: code already redeemed. Log and continue (lenient).
                        # Staff can reconcile. At 0.4 scale (5-15 users) acceptable.
                        logger.warning(
                            "Invite code %s already redeemed when saving user %s",
                            code,
                            user.pk,
                        )
                request.session.pop("invite_code", None)
        return user
