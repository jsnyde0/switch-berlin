# kb-lqw — Seed real Berlin events (2026-04-23)

## Result

- 3 organizers created (IKSK Berlin, Kachenka, Karada House) — all `status=approved`, `consent_method=legitimate_interest`, `consent_recorded_at=now`.
- 23 events created, all `status=draft`, `venue=None`.
- Idempotent: second run reports 0/0 created.
- Wipe: `--wipe` deletes only the matching (organizer_slug, event_slug) rows in the seed set; no collateral damage.

## Command

Lives at `events/management/commands/seed_real_events.py`. Scraped data is hard-coded inside the file (URL → title / start / end / description / suggested_tags) so reruns do not re-scrape. Scraping was done with the `scrape-url` skill (Firecrawl, handles JS-rendered pages).

Run locally:

```bash
docker compose run --rm \
  -e IMPRESSUM_NAME="Jonatan Snyders" \
  -e IMPRESSUM_ADDRESS="Weisestr. 58, 12049 Berlin, Germany" \
  -e IMPRESSUM_EMAIL="kinkybubbles@protonmail.com" \
  -e DJANGO_SUPERUSER_USERNAME=admin \
  -e DJANGO_SUPERUSER_EMAIL=admin@example.com \
  -e DJANGO_SUPERUSER_PASSWORD=abc123 \
  app python manage.py seed_real_events
```

## Event distribution

| Organizer     | Events | Notes |
|---------------|--------|-------|
| IKSK Berlin   | 9      | Workshops, play parties, recurring drop-ins |
| Kachenka      | 1      | Orgasmic Dance Temple Night, May 29–31 2026 |
| Karada House  | 13     | SM Weekend (May 1–3) + online series + singles |

Total: 23 events from 3 organizers. All dates in 2026 (Apr–May). Timezone Europe/Berlin.

## Dates for events with no concrete date on source page

Three IKSK recurring/drop-in events had no parseable single date — placeholder dates chosen (flagged in description):

- **IKA ESKA Play Space (Kink & Bodywork)** — `2026-05-16` placeholder. Page describes recurring play party format.
- **Sexual Empowerement (Micha Stella)** — `2026-05-09 20:00` placeholder. Page lists time-of-day only, no date.
- **The Art of Kinky Kissing** — `2026-05-28` placeholder (every 2nd month, no concrete upcoming date).

Recurring series with stated cadence got a concrete inferred date (e.g. "Last Thursday of the month" → `2026-05-28` for The Art of Kissing; "Sundays, once a month" → `2026-05-31` for Shibari Life Drawing).

## Schema gaps / fields I wanted but didn't have

1. **No `price_description` / free-form price text.** Most real events advertise sliding scale like "Supporter 250€ / Normal 200€ / Social 150€", "High Income 35€ // Normal Income 30€ // Low Income 25€", or tier codes ("Frühbucher bis 31.03.2026 → 350€"). `price_min_cents` / `price_max_cents` + `is_free` + `sliding_scale` can encode the *range* but loses the tier labels, early-bird conditions, and discount codes. For 0.1 I left pricing unset (all null) rather than mangle it.
2. **No `language` field.** Events differentiate German-only / English-only / bilingual. Workshop language is material for participants — currently buried in description text.
3. **No `registration_url` / `registration_email` separate from `tickets_url`.** Many orgs take registration by email (`jana.felixruckert@gmx.de`, `shamanicblissinfo@gmail.com`) or a third-party page (himmelsschwestern.com). `tickets_url` doesn't fit email, and `external_url` is already the source page.
4. **No `recurrence` field.** "Every last Thursday of the month", "every 2nd month", "Sundays, once a month" — we just pick one instance. Phase 0.1 scope is fine, but noting the gap.
5. **No `facilitators` / `presenters` list.** Currently embedded in description. Useful for filter/search ("workshops by Joris Kern").
6. **No `capacity` / `registration_required` boolean.** Some events are drop-in, others require advance sign-up.
7. **No per-event date range flag for multi-day events.** I used `start` + `end` spanning multiple days (e.g. Silent Hunger: Fri 18:00 – Sun 18:00), but the UI likely won't know whether to display as "3-day workshop" vs. "really long single event".
8. **No `content_warnings` / `kink_intensity` field.** Kink events vary widely — "caning and flogging" vs. "life drawing" — and a consent-forward platform probably wants this explicit eventually.

## UX friction during seeding

- **Docker entrypoint.sh runs migrations + createsuperuser + collectstatic on every `run --rm`.** Adds ~5s overhead per invocation and fails loudly when `DJANGO_SUPERUSER_*` env vars are unset. Would be nicer to split these into a separate init script so `run --rm` invocations are lightweight.
- **`.env` is `.dockerignore`'d and `docker compose --env-file` only substitutes in compose YAML, not into container.** Had to pass `-e VAR=...` for six env vars on CLI. Could be fixed by adding `env_file: .env` to the `app` service in `docker-compose.yml`.
- **`a_core.E006` blocks all management commands** when `PUBLIC_READ_ENABLED=True` and legal vars are empty — a system check running before the command even dispatches. Fine for prod safety, painful for dev. Could be downgraded to a warning in DEBUG.

## Files

- New: `events/management/commands/seed_real_events.py`
- Log: `history/kb-lqw-seed-log-20260423.md` (this file)
- Scraped raw markdown (transient, in /tmp): `/tmp/iksk_batch1.md`, `/tmp/iksk_batch2.md`, `/tmp/kachenka.md`, `/tmp/karada_batch{1,2,3}.md`
