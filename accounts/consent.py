"""Art. 9(2)(a) GDPR attendance consent helpers.

revoke_art9_consent(user) is the single authoritative function for withdrawing
attendance consent. It must be called:

  1. From the /me withdrawal button endpoint.
  2. From the account-deletion path (pre_delete signal below).

Both call sites ensure that if a user's account is removed, their attendance
rows are also removed and consent is cleared — belt-and-suspenders erasure.
"""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.dispatch import receiver


def revoke_art9_consent(user):
    """Clear attendance consent AND hard-delete all Attendance rows. Idempotent.

    Args:
        user: A User instance. Safe to call when art9_consent_given_at is
              already None and no Attendance rows exist.
    """
    from events.models import Attendance

    with transaction.atomic():
        Attendance.objects.filter(user=user).delete()
        user.art9_consent_given_at = None
        user.save(update_fields=["art9_consent_given_at"])


# ---------------------------------------------------------------------------
# Belt + suspenders: also revoke on User deletion so orphaned rows never form.
# ---------------------------------------------------------------------------


def _connect_pre_delete_signal():
    """Register the pre_delete signal on User.

    Called from AccountsConfig.ready() so it runs once at app startup.
    Using a function avoids import-time side effects during migration.
    """
    from django.db.models.signals import pre_delete

    User = get_user_model()

    @receiver(pre_delete, sender=User, weak=False)
    def _revoke_on_user_delete(sender, instance, **kwargs):  # noqa: ARG001
        """Ensure attendance rows are deleted before the User row is removed."""
        from events.models import Attendance

        Attendance.objects.filter(user=instance).delete()
        # No need to clear art9_consent_given_at — the row is being deleted.
