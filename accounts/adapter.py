import logging
import uuid

from allauth.account.adapter import DefaultAccountAdapter
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from a_core.models import get_flag

logger = logging.getLogger(__name__)


class NoSignupAdapter(DefaultAccountAdapter):
    """Invite-gated signup adapter — phase 0.4."""

    def is_open_for_signup(self, request):
        if not get_flag("INVITES_ENABLED", default=True):
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

    def _create_owned_profile(self, user):
        """
        Atomically create a Profile(kind='person') + ProfileClaim(verified_method='auto_self')
        for a new user.

        Per ADR-013 D3 (participant profiles via auto-created Profile on signup),
        ADR-008 D2 (adapter hook, not signal), ADR-008 D3 (fail loud — any DB failure
        propagates; caller must be in a transaction if rollback of user creation is desired).

        Named _create_owned_profile so kb-m69.5 can call it cleanly.

        Idempotent: if the user already has an auto_self ProfileClaim, the call is a no-op.
        """
        from organizers.models import Profile, ProfileClaim

        # Idempotency guard: if the user already has an auto_self claim, skip.
        if ProfileClaim.objects.filter(user=user, verified_method="auto_self").exists():
            return

        name = user.get_full_name() or user.email

        # Build a unique slug: slugify name + short uuid suffix to avoid collisions
        base_slug = slugify(name)[:190] or "user"
        slug = base_slug + "-" + str(uuid.uuid4())[:8]

        with transaction.atomic():
            profile = Profile.objects.create(
                kind="person",
                name=name,
                slug=slug,
            )
            ProfileClaim.objects.create(
                profile=profile,
                user=user,
                verified_method="auto_self",
                verified_at=timezone.now(),
                role="admin",
                verified_by_admin=None,
            )

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

            with transaction.atomic():
                self._create_owned_profile(user)

        return user
