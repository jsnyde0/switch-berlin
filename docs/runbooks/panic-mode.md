# Panic-Mode Runbook

Use this runbook when you need to quickly disable features or contain incidents via feature flags.
All flag flips are made in Django admin at `/admin/a_core/featureflag/`.

---

## Section 1: Flag Reference Table

| Flag | Default | Flip to for panic | Effect | Propagation lag |
|------|---------|-------------------|--------|-----------------|
| `LOGIN_WALL_ENABLED` | `True` | `True` (already on) | Forces login on all public pages | 60s cache TTL |
| `MAP_ENABLED` | `True` | `False` | Map feature hidden | 60s cache TTL |
| `INVITES_ENABLED` | `True` | `False` | New invite signups blocked | 60s cache TTL |
| `RATINGS_ENABLED` | `True` | `False` | Review form hidden; existing reviews preserved | 60s cache TTL |
| `FLAGS_ENABLED` | `True` | `False` | Flag/report buttons hidden; existing flags unaffected | 60s cache TTL |
| `PUBLIC_READ_ENABLED` | `True` | `False` | All pages return login wall; OG tags disappear from new requests | 60s cache TTL |
| `EVENT_REVIEWS_DISPLAYED` | `False` | `False` | Already off by default — no panic action needed | 60s cache TTL |
| `TRENDING_SORT_ENABLED` | `True` | `False` | Sort chip hidden; chronological only | 60s cache TTL |
| `INGESTION_PAUSED` | `False` | `True` | Telegram bot short-circuits; no new events ingested | 60s cache TTL |
| `threshold.organizer_ratings_display` | `3` | N/A | Numeric tuning knob — not a kill switch | 60s cache TTL |
| `threshold.event_ratings_display` | `3` | N/A | Numeric tuning knob — not a kill switch | 60s cache TTL |
| `threshold.auto_hide_flag` | `3` | N/A | Numeric tuning knob — not a kill switch | 60s cache TTL |
| `threshold.attendance_display` | `5` | N/A | Numeric tuning knob — not a kill switch | 60s cache TTL |
| `threshold.follower_display` | `5` | N/A | Numeric tuning knob — not a kill switch | 60s cache TTL |

> **Rate limits:** `RATELIMIT_ENABLE=False` env var disables ALL rate limits immediately (requires env reload / restart; no 60s lag).

---

## Section 2: Decision Tree — Incident Scenarios

**Scenario: spam surge**

- Signal: More than 20 unresolved flags in digest; unusual volume of flag/report submissions in short window
- Primary: flip `FLAGS_ENABLED=False` via Django admin at `/admin/a_core/featureflag/`
- Secondary: review `threshold.auto_hide_flag` numeric value — lower it to auto-hide content with fewer flags; check `Flag.objects.filter(resolved=False)` count in Django admin
- Verify: `Flag.objects.filter(resolved=False).count()` stops growing; flag/report buttons no longer visible to users

---

**Scenario: regulator complaint**

- Signal: Email or formal notice from a regulatory authority or legal contact about publicly accessible content
- Primary: flip `PUBLIC_READ_ENABLED=False` via Django admin at `/admin/a_core/featureflag/`
- Secondary: flip `LOGIN_WALL_ENABLED=True` to ensure login is enforced on all paths; review specific content flagged in the complaint
- Verify: anonymous `GET /events/` returns redirect to login (HTTP 302); no public OG previews served for new requests

---

**Scenario: bot noise / ingestion flood**

- Signal: Unusual volume of draft events appearing in admin; suspected automated or malicious submissions via Telegram ingestion
- Primary: flip `INGESTION_PAUSED=True` via Django admin at `/admin/a_core/featureflag/`
- Secondary: review `ApprovedSender` list in admin and remove or suspend suspect senders; audit queued draft events
- Verify: `_bot_enabled()` returns `False` (check via `manage.py shell`); no new events appear in admin draft queue

---

**Scenario: legal notice**

- Signal: DSA Art. 16 takedown notice or equivalent legal demand received for specific content
- Primary: use Django admin Flag detail + FlagAdmin moderation actions to set `hidden=True` on the target event or organizer; or directly set `event.hidden=True` / `organizer.suspended=True` in admin
- Secondary: log a `ModerationAction` record for the affected object; if the notice is systemic (multiple items or whole platform), flip `PUBLIC_READ_ENABLED=False`
- Verify: target object has `hidden=True` in DB; the content URL returns 404 or redirects; `ModerationAction` record created for audit trail

---

## Section 3: Full-Panic Combination (0.4 Posture)

The **0.4 posture** restores invite-only mode with no public read, no ratings, and no flags. Apply in this order:

1. `PUBLIC_READ_ENABLED = False`
2. `LOGIN_WALL_ENABLED = True`
3. `RATINGS_ENABLED = False`
4. `FLAGS_ENABLED = False`
5. `INGESTION_PAUSED = True` _(optional — stop new content ingestion)_

All steps are reversible within 60s + cache TTL by flipping each flag back to its default value.

---

## Section 4: Cache-TTL Lag Disclosure

All DB flags propagate within **60 seconds** (cache TTL in `get_flag` / `get_numeric`). There is no instant-flush mechanism without a deployment.

**After flipping a flag in admin, wait 60 seconds before verifying the effect in production requests.** Plan incident response windows accordingly — a flag flipped at T+0 will be fully effective by T+60s at the latest.

---

## Section 5: Social-Cache Cleanup URLs (OG Tag Rollback)

After flipping `PUBLIC_READ_ENABLED=False`, already-scraped social previews persist for 24–48 hours on most platforms. Use these tools to request a refresh:

- **Facebook / Meta Sharing Debugger:** https://developers.facebook.com/tools/debug/
  - Paste the URL, click "Scrape Again" to invalidate the cached preview.
- **Discord:** No self-serve invalidation tool; previews expire automatically in approximately 30 minutes.
- **Telegram:** No self-serve invalidation tool; previews expire automatically in approximately 1 hour.
