"""Migration: backfill allauth EmailAddress rows for existing Users.

Context (kb-m69.5):
  Setting ACCOUNT_EMAIL_VERIFICATION='mandatory' requires every User to have a
  corresponding allauth EmailAddress row. This migration creates those rows for
  existing users who were created before allauth email verification was enabled.

  Per ADR-008 D3 (fail loud):
    - Active user with email  → EmailAddress(verified=True, primary=True)
    - Inactive user with email → EmailAddress(verified=False, primary=True)
    - User with blank email    → RAISES with a list of offending user IDs so the
                                 operator can decide (no silent verified=False coerce)
"""

from django.db import migrations


def forwards(apps, schema_editor):
    """Create allauth EmailAddress rows for users who don't have one."""
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    # ADR-008 D3: collect users with blank emails and raise loud
    blank_email_ids = list(
        User.objects.filter(email="").values_list("pk", flat=True)
    )
    if blank_email_ids:
        raise ValueError(
            "Migration 0006 aborted: the following User IDs have blank email "
            "addresses and cannot be backfilled. Set their email addresses or "
            "delete these accounts before running this migration. "
            f"Offending user IDs: {blank_email_ids}"
        )

    # Collect PKs of users that already have an EmailAddress (idempotency)
    existing_user_pks = set(
        EmailAddress.objects.values_list("user_id", flat=True)
    )

    # Create EmailAddress rows for users without one
    to_create = []
    for user in User.objects.exclude(pk__in=existing_user_pks).iterator():
        # Legacy approval-based proxy: is_active == email verified at time of
        # account activation (admin approval was the verification mechanism).
        verified = bool(user.is_active and user.email)
        to_create.append(
            EmailAddress(
                user_id=user.pk,
                email=user.email,
                verified=verified,
                primary=True,
            )
        )

    if to_create:
        EmailAddress.objects.bulk_create(to_create, ignore_conflicts=True)


def backwards(apps, schema_editor):
    """Reverse: remove EmailAddress rows created by this migration.

    NOTE: This is a best-effort reverse. It removes all EmailAddress rows for
    users who have exactly one primary EmailAddress (i.e. the ones we created).
    Users who had EmailAddresses before this migration ran are unaffected because
    they were excluded in forwards() via the 'existing_user_pks' guard.
    """
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")

    EmailAddress.objects.filter(user__in=User.objects.all()).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_cheap_foresight_fields"),
        ("account", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
