"""Migration: Replace User.is_approved (boolean) with User.status (enum).

Data migration:
  - is_approved=True  → status='vouched'
  - is_approved=False → status='open'   (default)

Per ADR-008 D1: is_approved is dropped outright — no compat shim.
Per ADR-013 D1: User.status carries the four-value trust tier.
"""

from django.db import migrations, models


def backfill_status_from_is_approved(apps, schema_editor):
    """Set status='vouched' for every row where is_approved=True.

    Rows with is_approved=False keep status='open' (the column default).
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_approved=True).update(status="vouched")


def reverse_status_to_is_approved(apps, schema_editor):
    """Restore is_approved from status for reversibility testing.

    status='vouched' → is_approved=True; all others → is_approved=False.
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(status="vouched").update(is_approved=True)
    User.objects.exclude(status="vouched").update(is_approved=False)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_add_art9_consent"),
    ]

    operations = [
        # 1. Add status with a temporary database-level default so the column
        #    is NOT NULL from the start (no NULL intermediary state).
        migrations.AddField(
            model_name="user",
            name="status",
            field=models.CharField(
                choices=[
                    ("open", "Open"),
                    ("vouched", "Vouched"),
                    (
                        "suspended_pending_investigation",
                        "Suspended — Pending Investigation",
                    ),
                    ("banned", "Banned"),
                ],
                default="open",
                help_text=(
                    "Trust tier: open (signup default), vouched (invite-verified), "
                    "suspended_pending_investigation (reversible), banned (admin-final)."
                ),
                max_length=40,
            ),
        ),
        # 2. Backfill: is_approved=True → status='vouched'.
        migrations.RunPython(
            backfill_status_from_is_approved,
            reverse_code=reverse_status_to_is_approved,
        ),
        # 3. Drop is_approved (ADR-008 D1 — no compat shim, no deprecation path).
        migrations.RemoveField(
            model_name="user",
            name="is_approved",
        ),
    ]
