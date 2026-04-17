# Event Gulper — Project Brief (Draft)

## Goal
Launch a niche Berlin kink/sex-positive events finder with fresh, high-quality listings, solid search/filtering, and a review loop to keep quality high.

## Users
- Attendees: browse/search/filter events; view details; click out to tickets.
- Organizers: forward event posts (Telegram/bot); later self-serve.
- Internal curator: reviews parsed events, dedupes, publishes.

## Scope (MVP v1)
- Ingestion: Telegram forward-to-bot; Eventbrite scraper/API; Siegessäule scraper.
- Processing: store raw payloads; parse to normalized events; dedupe; human review; publish.
- Product: landing + search/filter with Hipsy-like card anatomy (date badge, image, title, organizer, city/venue, price/free/paid flag, tags/chips); event detail with cover image, time/place/map link, organizer mini-card, price range + external CTA, safety note, report/flag link.
- Organizer page (basic): logo/face, short bio, links, list of upcoming events, “verified” badge (manual).
- Admin/review: simple UI (Django admin is fine) to approve/edit parsed events; view raw vs parsed; mark duplicates.
- Infra: Postgres; Prefect for scheduled ETL; Django (+HTMX) for product UI/API. Skip Celery unless app-triggered async emerges.

## Non-Goals (v1)
- Ticketing/payments; organizer dashboards; mobile apps; ML recommendations; complex RBAC.

## Data Model (v1 proposal)
- Organizer: id, name, contact handles, source, status.
- Venue: id, name, address, geo, url.
- Event: id, title, description, organizer_id, venue_id, start/end, timezone, tags (M2M), price_min/max/currency, external_url, source, status (draft/review/published/rejected), raw_ref.
- Tag: id, slug, label, kind (theme/identity/format).
- EventImage: event_id, url/path, alt.
- Optional later: EventOccurrence for repeats.

## Ingestion Pipeline (Prefect)
- Sources: Telegram collector; Eventbrite (API if possible, else scrape Berlin + kink keywords); Siegessäule scrape.
- Flow: source → `raw_events` → parse/normalize → dedupe (title+date+venue fuzz + source ids) → `normalized_events` → mark for review.
- Review: status gating; human approval before publish.
- Contract: Prefect owns `raw_events` + `normalized_events`; product app reads published rows and can write edits via review UI.

## Product App (Django + HTMX)
- Search/list: filters (date range, tags, price free/paid, language, neighborhood/venue); sort by date/newest; card anatomy as above; organizer mini-card emphasis for trust.
- Event detail: title, time, venue map link, tags, price, external ticket URL, safety note, images, organizer mini-card, report/flag link.
- Submit event form: manual submissions to review queue.
- Admin/review: approve/edit parsed events; view raw vs parsed; mark duplicates.

## Roadmap (versions)
- V0 (internal): sources wired (Telegram bot + Eventbrite + Siegessäule) writing raw/normalized; dedupe; review UI; internal-only listings.
- V0.5: public landing/search/detail read-only; manual submit form to review queue; basic organizer pages; verified badge toggle (manual).
- V1: trust/safety polish (report link, safety note), better filters (date range, tags, free/paid, neighborhood), cover images on detail, basic SEO/og tags.
- V1.5 (social proof light): user accounts; save/bookmark events; follow organizers; lightweight reviews on organizers/events (form + moderation); public organizer profiles with bio/images/links; show badges/counts.
- V2 (quality/coverage): richer kink/accessibility taxonomy; improved parsing accuracy; stale/zero-new alerts; better dedupe/merge UI; geocoding and neighborhood facets.
- V3 (recommendations/agents): structured profiles/tags to feed LLM recs; on-site agent that can suggest events by vibe/time/location; chat prompt → curated list.
- V4 (ticketing/commerce, later): internal ticket types, checkout, QR codes, payouts. Deliberately deferred; focus on audience first.

## Telegram Bot (ingestion) — initial plan
- Mode: collector. Organizers forward posts to the bot/channel; store raw message (text/html/media refs), sender/channel id, timestamps.
- Parsing: start with heuristics (dates/times, price markers, location strings) and add LLM fallback; attach confidence scores; link to raw message id.
- Output: insert into `raw_events` with source metadata; normalized candidate with parsed fields; mark `status=needs_review` unless high-confidence and source is trusted/verified.
- Ownership: manual “verified organizer” flag can be set in admin; we can trust/auto-publish from verified sources later if desired.

## Open Decisions / Needs Discussion
1) Stack confirmation: Django + HTMX + DRF + Postgres + Prefect for ETL?
2) Tag taxonomy: kink types, audience, vibe, accessibility—what’s the initial set?
3) Geo granularity: borough vs neighborhood vs free-text? Geocoding now or later?
4) Language: store `language` field? multi-language content?
5) Parsing: regex/heuristics first with confidence vs immediate LLM fallback; budget constraints?
6) Dedupe rules: thresholds and precedence (earliest? highest confidence?).
7) Review policy: mandatory human approval for all sources or only low-confidence parses?
8) Branding/theme: initial UI direction (colors/type/voice).
9) Privacy/legal: terms/takedown; attribution to sources.
10) Hosting: where Postgres/Prefect/Django live (dev uses docker-compose).
11) Auth: simple admin only vs early organizer login?

## Risks & Mitigations
- Parser accuracy: start rule-based + confidence; human review; LLM fallback.
- Scraper fragility: per-source adapters; fixtures/tests; monitors/alerts.
- Data freshness: daily schedules; alert on zero new events.
- Content sensitivity: moderation tags + review step; clear guidelines.
- Legal/attribution: link to sources; honor takedowns.
