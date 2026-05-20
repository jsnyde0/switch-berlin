# Scout raw sidecar — Hipsy organizer dashboard

**Date:** 2026-05-19
**Scope:** Wide sweep of the authenticated organizer dashboard at `https://hipsy.nl/app` plus public help-center docs.
**Organizer account used:** Scars and Roses (user-supplied, real organizer with live event history at the time of the scout — provides authenticated visibility into participants, payouts, and settings).
**Brief:** `../scout-features-hipsy-2026-05-19.md`

## Files

- `hipsy-r1.json` — 30 feature records, schema per `~/.claude/agents/feature-scout.md`.
- `screenshots/` — 9 PNGs of distinctive surfaces:
  - `01-dashboard-overview.png` — top-level dashboard landing
  - `02-events-list.png` — organizer's events list view
  - `03-event-create-form.png` — event creation form fields
  - `04-attendee-management.png` — participants list + check-in
  - `05-ticket-management.png` — tiered ticketing UI with sequential availability
  - `06-event-settings.png` — per-event settings (visibility, registration mode, etc.)
  - `07-organisation-profile.png` — public organizer profile editor (branding, gallery)
  - `08-pricing-tarieven.png` — pricing/fees page
  - `09-tickets-invisible-discount.png` — invisible-ticket / secret-URL pricing pattern

## Rounds

R1 only. A second round was not run — the wide-sweep R1 covered all top-level dashboard sections plus public docs; nothing in R1 surfaced a surface that R2 would meaningfully deepen for the current brainstorm purpose. Re-invoke `/scout-features --focus "<job>"` if a specific cluster (e.g. attendee analytics, follower model) needs deeper coverage.

## Evidence mix

- **Authenticated UI screenshots:** load-bearing for most ticketing, attendee, settings, ticketshop, payout, reviews features. High-credibility.
- **Help-center docs (`hipsy.nl/help-center/...`):** load-bearing for donation tickets, private events, newsletter opt-in, content policy. High-credibility.
- **Marketing-page (`hipsy.nl/organize-your-event`, public `hipsy.be/...`):** used for pricing claims and the public follower-profile observation. Medium-credibility.
- **Inferred:** none. All records anchor on direct evidence.

## Known coverage gaps

- **Hipsy Checkin mobile app:** known to exist (referenced in docs) but not exercised on-device. Feature is recorded but not screenshotted.
- **Newsletter / mailing tools beyond per-event bulk-email:** not separately exposed in the dashboard navigation; if a standalone newsletter composer exists, it's behind a less-discoverable surface.
- **Hipsy Plus or premium tiers:** none observed. If a hidden enterprise/B2B tier exists, it is not surfaced on the public pricing page.
- **API rate limits / OAuth scopes:** not explored — `docs.hipsy.nl` was sampled at index level only.

## Hard exclusion to flag for Switch Berlin context

Hipsy's published [event-policy](https://hipsy.nl/help-center/page/beleidsrichtlijnen-voor-evenementen) explicitly prohibits **BDSM meetups, sex parties, erotic dance parties, and orgies**. Tantra and conscious-sexuality events are permitted only with educational framing and qualified facilitators, no explicit imagery. This makes Hipsy a non-substrate platform for the Switch Berlin core use-case — recorded here so the brainstorm reads Hipsy as a feature/UX inspiration source, not as a platform Switch Berlin could "just list on."
