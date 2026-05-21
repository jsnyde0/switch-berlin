# Generated 2026-05-21 — extended with data migration backfill.
# ADR-012 D1 (visibility field), D2 (source-derived defaults), D3 (fail loud).

from django.db import migrations, models


# ADR-012 D2 mapping: RawMessage.source_type → visibility tier
# Defined inline so the migration is self-contained (historical-state safe).
_RAWMESSAGE_SOURCE_TO_TIER = {
    "telegram_bot_forward": "semi_public",   # private group forward
    "telegram_telethon": "public",           # public channel scrape
    "email_submission": "semi_public",
    "web_form": "semi_public",
}

# Tier ordering index: higher = more public
_TIER_RANK = {"semi_public": 0, "public": 1}


def backfill_visibility(apps, schema_editor):
    """
    Backfill Event.visibility per ADR-012 D2 source-derived mapping.

    Strategy (using raw SQL for historical-state safety):
    - Events linked to ≥1 ExtractionAttempt via RawMessage: map source_type →
      tier; max(public) wins across multiple sources.
    - Events with a direct raw_message FK but no ExtractionAttempt rows:
      map source_type → tier.
    - Events with no source linkage (manual / admin creation): semi_public.

    ADR-008 D3: unknown source_type raises — no silent fallback.
    """
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        # Step A: collect distinct (event_id, source_type) pairs from
        # ExtractionAttempt → RawMessage joins.
        cursor.execute(
            """
            SELECT ea.event_id, rm.source_type
            FROM ingestion_extractionattempt ea
            JOIN ingestion_rawmessage rm ON rm.id = ea.raw_message_id
            WHERE ea.event_id IS NOT NULL
            """
        )
        rows = cursor.fetchall()

    # Build event_id → set of source_types
    event_sources: dict[int, set[str]] = {}
    for event_id, source_type in rows:
        event_sources.setdefault(event_id, set()).add(source_type)

    # Also collect event_id → source_type from Event.raw_message FK directly
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT e.id, rm.source_type
            FROM events_event e
            JOIN ingestion_rawmessage rm ON rm.id = e.raw_message_id
            WHERE e.raw_message_id IS NOT NULL
            """
        )
        for event_id, source_type in cursor.fetchall():
            event_sources.setdefault(event_id, set()).add(source_type)

    # Compute per-event visibility tier
    public_ids: list[int] = []
    semi_ids: list[int] = []

    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM events_event")
        all_event_ids = [row[0] for row in cursor.fetchall()]

    for event_id in all_event_ids:
        sources = event_sources.get(event_id, set())
        if not sources:
            semi_ids.append(event_id)
            continue

        tier = "semi_public"  # pessimistic default
        for src in sources:
            if src not in _RAWMESSAGE_SOURCE_TO_TIER:
                raise ValueError(
                    f"Event {event_id}: unknown RawMessage.source_type {src!r}. "
                    "Add it to the backfill mapping in 0013_event_visibility.py "
                    "(ADR-008 D3 fail loud)."
                )
            src_tier = _RAWMESSAGE_SOURCE_TO_TIER[src]
            if _TIER_RANK[src_tier] > _TIER_RANK[tier]:
                tier = src_tier

        if tier == "public":
            public_ids.append(event_id)
        else:
            semi_ids.append(event_id)

    # Bulk update in batches (avoid huge IN() clauses)
    BATCH = 500
    with connection.cursor() as cursor:
        for i in range(0, len(public_ids), BATCH):
            ids = public_ids[i : i + BATCH]
            cursor.execute(
                "UPDATE events_event SET visibility = %s WHERE id = ANY(%s)",
                ["public", ids],
            )
        for i in range(0, len(semi_ids), BATCH):
            ids = semi_ids[i : i + BATCH]
            cursor.execute(
                "UPDATE events_event SET visibility = %s WHERE id = ANY(%s)",
                ["semi_public", ids],
            )


def reverse_backfill(apps, schema_editor):
    """No-op: field removal in reverse migration clears the data anyway."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("events", "0012_alter_eventimage_image"),
        ("ingestion", "0003_approvedsender_extractionattempt_and_more"),
    ]

    operations = [
        # Step 1: add the field with default='public' so the NOT NULL
        # constraint is satisfied immediately for all existing rows.
        migrations.AddField(
            model_name="event",
            name="visibility",
            field=models.CharField(
                choices=[
                    ("public", "Public"),
                    ("semi_public", "Semi-public"),
                    ("unlisted", "Unlisted"),
                ],
                default="public",
                help_text=(
                    "public: anyone, indexed. "
                    "semi_public: vouched users only, noindex. "
                    "unlisted: URL-keyed only, noindex."
                ),
                max_length=20,
            ),
        ),
        # Step 2: data migration — overwrite the temporary default with the
        # source-derived tier per ADR-012 D2.
        migrations.RunPython(backfill_visibility, reverse_code=reverse_backfill),
    ]
