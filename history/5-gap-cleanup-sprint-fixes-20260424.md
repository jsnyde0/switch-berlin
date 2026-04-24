# Fixes: 5-gap-cleanup-sprint
Date: 2026-04-24
Review passes: 1

## Critical

- **templates/events/list.html:28-35, templates/organizers/profile.html:65-82, events/views.py:35-38, organizers/views.py:22-34** — New "Lowest rated" / "Most reviewed" sort chips leak event-review signal before Bundle A `EVENT_REVIEWS_DISPLAYED` is flipped on, violating ADR-002 "Non-goals" and ADR-005 Bundle A's flag-gated contract. Fix: gate chip rendering behind `{% if EVENT_REVIEWS_DISPLAYED %}` in both templates; in both views, fall back to `date` when `sort in {lowest_rated, most_reviewed}` and the flag is off. Pass `EVENT_REVIEWS_DISPLAYED` to organizer profile context.

- **reviews/admin.py:70-84** — Bulk `resolve_approved` / `resolve_rejected` actions bypass `ModerationAction` audit-trail creation that `process_action` writes for single-flag resolves (load-bearing for DSA/GDPR per ADR-005 Bundle A). Fix: iterate queryset, create one `ModerationAction` per flag with `action="resolved"` inside `transaction.atomic()`, then save flag fields.

## Important

- **events/views.py:138-150** — Pagination `filter_query_string` excludes `sort`, so page 2+ loses the active sort. Fix: include `sort` in `filter_params` when non-default.

- **ingestion/bot.py:80** — `update.message.reply_text(...)` called without guard; inconsistent with defensive `update.message` null check on lines 73-77. Fix: wrap reply in `if update.message:`.

## Minor

- **events/views.py:35** — `_VALID_SORT_OPTIONS` defined inside request handler; module-level peer exists in organizers/views.py. Fix: hoist to module level.

## ADR Updates
- no ADR changes needed.

## Discarded

- **arch #3 (shared sort abstraction)** — premature; 2 callers do not justify extraction.
- **arch #4 (sort vs event_sort naming)** — intentional; both params coexist on organizer profile and chips preserve each other.
- **arch #5 (save() truncation fragile)** — belt+suspenders; bot pre-truncates at line 73. Low-risk.
- **arch #6 (schedule rename footgun)** — speculative operational concern.
- **arch #7 (JS loaded on change pages)** — script has early-return guard; harmless.
- **arch #8 (goButton fallback selector)** — working against Django's stable contract.
- **impl #5 (nulls_last on most_reviewed)** — `rating_count` has `default=0`, not nullable.
- **impl #6 (db_index on telegram_user_id)** — premature; low traffic at current scale.
