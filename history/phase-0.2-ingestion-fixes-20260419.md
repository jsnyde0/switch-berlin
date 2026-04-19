# Fixes: phase-0.2-ingestion
Date: 2026-04-19
Review passes: 1

## Critical

- **ingestion/bot.py:63-88** — Non-text handler fires before allowlist check. Any unapproved Telegram user sending an image/sticker creates a `RawMessage` row with `extraction_status='skipped'`. Fix: move allowlist check (step 5) above non-text check (step 4). Add test for unapproved-sender-non-text path.

- **templates/admin/events/event/change_form.html:16** — `{{ extracted_draft_json }}` rendered with Django auto-escaping, which HTML-encodes `<`, `>`, `&`, `"` inside JSON strings. `JSON.parse()` in `event_draft.js` will throw on any event description containing these characters. Fix: in `events/admin.py` `change_view`, pass the raw dict (not pre-serialized JSON). In template, use `{{ extracted_draft|json_script:"extracted-draft-data" }}`. Update `event_draft.js` to read from `document.getElementById('extracted-draft-data').textContent`.

## Important

- **ingestion/tasks.py** — `SourceFailure` model exists but is never written to. Design doc go/no-go criterion: "Zero extraction failures silently lost (every failure visible as a `SourceFailure`)." Fix: create `SourceFailure` rows in `process_raw_message` when enrichment or extraction fails, alongside the existing `extraction_error` field.

- **events/admin.py:106-115** — Bulk `publish_events` action uses `queryset.update()` which bypasses `save_model` GDPR consent capture. Organizers whose first event is bulk-published will have no `consent_recorded_at`. Fix: extract consent logic into shared helper, call from both `save_model` and `publish_events`. Add test for bulk publish consent.

- **ingestion/tasks.py:27** — `RawMessage.objects.get(id=raw_message_id)` has no `DoesNotExist` handler. If the row was deleted between enqueue and execution, the task fails with an unhandled exception. Fix: wrap in `try/except RawMessage.DoesNotExist`, log warning, return cleanly.

- **ingestion/extraction.py:100-105** — Tag matching issues one `Tag.objects.filter(slug__iexact=tag_str).first()` query per tag (N+1). Fix: fetch all known tag slugs in a single query and match in Python.

## Minor

- **ingestion/bot.py:39-43** — German consent text has missing umlauts (`bestatigst` → `bestätigst`, `fur` → `für`). Legal text should be accurate.

- **ingestion/management/commands/run_bot.py:8-13** — No validation of `TELEGRAM_BOT_TOKEN` before starting bot. Empty token (the default) causes an opaque error. Fix: add `if not token: raise CommandError("TELEGRAM_BOT_TOKEN is not set")`.

## ADR Updates

- No ADR changes needed. The ADR-003 F9 deviation (env var instead of DB flag) is documented in the code as intentional and deferred to a future bead.

## Discarded

- **ADR-003 F9 feature flag** — Intentional documented deviation; bead explicitly deferred DB-backed flags. Not a fix for this round.
- **Circular import ingestion↔events** — Mitigated by deferred imports (standard Django pattern). No action needed.
- **Character-count truncation in enrichment** — Negligible at V0 scale. `len(str)` vs `len(str.encode())` difference is minimal for Berlin-locale text.
- **logfire missing `is_allowlisted` field** — Minor logging field omission. Not worth a fix.
- **Slug UniqueConstraint with NULL organizer** — Mitigated by UUID suffix in pipeline code. Low risk at V0 volume.
- **SSRF in URL enrichment** — Initially discarded (closed beta, low attack surface). Subsequently addressed: private/reserved IP blocking via DNS resolution check added to `enrichment.py` before each fetch.
