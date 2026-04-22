# Week-Off Runbook

Use this runbook when you will be away for >= 5 days with limited availability.

---

## Section 1: Pre-departure checklist

Before leaving, verify each item below. All boxes should be checked before you go offline.

- [ ] Last nightly run succeeded: check logfire for `finalize_attendance.done` and `recompute_aggregates.done` events from the last 24h
- [ ] django-q2 cluster is running: `docker ps` or process check shows `q-cluster` active
- [ ] No unresolved flags with high severity in admin: `/admin/reviews/flag/?resolved=False`
- [ ] No `EmailFailure` rows from the last 7 days: `/admin/a_core/emailfailure/`
- [ ] `INGESTION_PAUSED=False` (unless intentionally paused): `/admin/a_core/featureflag/`
- [ ] All feature flags are in intended state (review flag table in [panic-mode.md](panic-mode.md))
- [ ] Django-q2 `Schedule` entries exist for both nightly tasks:
  ```
  python manage.py shell -c 'from django_q.models import Schedule; print(list(Schedule.objects.values("name","next_run")))'
  ```

---

## Section 2: What auto-heals while you're away

### Safe to leave running unattended

These tasks are idempotent and self-correcting — a single missed run causes no data loss:

- **`finalize_attendance` (nightly 03:00 Europe/Berlin):** flips `going` -> `went` automatically. If it fails one night, it catches up on next run (idempotent).
- **`recompute_aggregates` (nightly):** recomputes all aggregate counts. If it fails one night, next run corrects it. Short-term display counts may be stale but no data loss.
- **`daily_flag_digest` (daily):** sends email digest. If SMTP fails, creates `EmailFailure` row. Non-critical; check on return.
- **Telegram bot:** continues ingesting if `INGESTION_PAUSED=False`. New events land as drafts and queue for admin review (no auto-publish). Safe to accumulate.

### Require manual intervention if they fail

These do NOT auto-recover and require a human decision:

- **Admin event review queue:** drafts do NOT auto-publish — maintainer must approve.
- **FeatureFlag changes:** must be manual.
- **Any DSA takedown received via email:** manual response required within 72h per DSA Art. 16.

---

## Section 3: On-return health check

Run these checks when you return from a week off.

### 1. Did nightly tasks run every day?

Logfire query to verify task history (adapt to logfire UI):

```sql
SELECT DATE(timestamp), name, updated_count
FROM logs
WHERE name IN ('finalize_attendance.done', 'recompute_aggregates.done')
  AND timestamp > NOW() - INTERVAL '8 days'
ORDER BY timestamp DESC
```

Expected: at least one row per task per day. Zero rows for a day = task did not run (check q-cluster was alive).

Note: both `finalize_attendance` and `recompute_aggregates` emit `duration_ms` alongside the count field — a healthy run shows non-null `duration_ms`.

### 2. Any email failures?

```python
# Django shell
from a_core.models import EmailFailure
print(EmailFailure.objects.filter(resolved=False).count())
```

Action: review and resolve if > 0.

### 3. Flag backlog?

```python
# Django shell
from reviews.models import Flag
print(Flag.objects.filter(resolved=False).count())
```

Action: triage via FlagAdmin moderation actions (step-6a).

### 4. Draft event backlog?

```python
# Django shell
from events.models import Event
print(Event.objects.filter(status='draft').count())
```

Action: review and approve/reject in admin.

---

## Section 4: Flags to flip before leaving (if going fully offline)

Optional hardening before a week off. These reduce noise accumulation while you are unreachable:

| Flag | Value to set | Reason |
|------|-------------|--------|
| `INGESTION_PAUSED` | `True` | Stops new drafts accumulating from Telegram bot |
| `FLAGS_ENABLED` | `False` | Prevents flag volume building up if you can't respond |

Restore on return: flip both flags back to their normal values, then wait 60s for the cache TTL to expire before verifying behaviour.

See [panic-mode.md](panic-mode.md) for the full flag table and emergency procedures.
