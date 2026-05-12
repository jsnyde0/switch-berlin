# Data migration for bead kb-9kh.2 (Organizer LIA + consent_method migration)
# Backfills existing telegram_forward_implied rows to legitimate_interest per ADR-006.
#
# Forward:  consent_method "telegram_forward_implied" → "legitimate_interest"
#           + append note to consent_notes (idempotent: only appends if note absent)
# Reverse:  consent_method "legitimate_interest" → "telegram_forward_implied"
#           (note is left in place on reverse — no attempt to remove it)

from django.db import migrations

_ADR_NOTE = "\nMigrated to Art. 6(1)(f) per ADR-006 on 2026-04-22."


def backfill_consent_method(apps, schema_editor):
    # Try Profile first (post-rename), fall back to Organizer (pre-rename)
    try:
        Model = apps.get_model("organizers", "Profile")
    except LookupError:
        Model = apps.get_model("organizers", "Organizer")
    for org in Model.objects.filter(consent_method="telegram_forward_implied"):
        org.consent_method = "legitimate_interest"
        existing_notes = org.consent_notes or ""
        # Idempotency guard: don't double-append if already contains the note
        if _ADR_NOTE.strip() not in existing_notes:
            org.consent_notes = existing_notes + _ADR_NOTE
        org.save(update_fields=["consent_method", "consent_notes"])


def reverse_backfill(apps, schema_editor):
    # Try Profile first (post-rename), fall back to Organizer (pre-rename)
    try:
        Model = apps.get_model("organizers", "Profile")
    except LookupError:
        Model = apps.get_model("organizers", "Organizer")
    for org in Model.objects.filter(consent_method="legitimate_interest"):
        org.consent_method = "telegram_forward_implied"
        org.save(update_fields=["consent_method"])


class Migration(migrations.Migration):

    dependencies = [
        ("organizers", "0005_add_legitimate_interest_choice"),
    ]

    operations = [
        migrations.RunPython(backfill_consent_method, reverse_backfill),
    ]
