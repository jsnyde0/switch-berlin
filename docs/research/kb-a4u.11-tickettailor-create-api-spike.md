# kb-a4u.11 — Ticket Tailor event-creation API spike

**Date:** 2026-05-26
**Bead:** kb-a4u.11 (research-only spike, Switch Berlin C11 adapter scope)
**Method:** WebFetch against `https://developers.tickettailor.com` REST reference pages, building on the prior kb-cyq deep-scout.

---

## Question

Does a public Ticket Tailor API endpoint exist for **event creation** (programmatic "POST /events"-style write), or is the API read-only? This decides whether the v0 C11 adapter can create events via API or must fall back to manual-assisted.

---

## What the prior deep-scout already established

`docs/research/kb-cyq-r1-tickettailor-deepscout.md` (D1) confirmed:

- REST base `https://api.tickettailor.com/v1`, HTTP Basic Auth with per-box-office API keys (Base64-encoded key), 5000 req/30min.
- `events` and `event_series` are both listed resources; webhooks fire on `event.created/updated/deleted`.
- **Left as the explicit open question:** a direct probe of `POST /v1/events` returned **404**. The scout hypothesized that event creation routes through `event_series` first (bundle-create was confirmed at `POST /v1/event_series/:id/bundles`), and flagged this for R2 spot-confirmation. That confirmation is the job of this spike.

---

## What I verified now

The 404 on `POST /v1/events` is expected: `events` is the **read** resource (GET list / GET retrieve only). **Writes go through `event_series`**, which exposes full CRUD. Confirmed from the live reference nav and endpoint pages:

| Operation | Method + Path | Evidence |
|---|---|---|
| List events (read) | `GET /v1/events`, `GET /v1/events/{id}` | [get-all-events](https://developers.tickettailor.com/docs/api/get-all-events) — "Returns a list of events"; no POST documented on this resource. |
| **Create event series** | **`POST /v1/event_series`** → **201 Created** | [create-event-series](https://developers.tickettailor.com/docs/api/create-event-series) — titled "Create an event series", documents POST with a 201 success response. |
| **Create event occurrence** | **`POST /v1/event_series/:event_series_id/events`** → **201 Created** | [create-event-series-event](https://developers.tickettailor.com/docs/api/create-event-series-event) — occurrence is associated to the series via the path id; returns 201. |
| Update / status / delete series | `update-event-series-by-id`, `change-event-series-status` (+ delete) | [get-all-event-series](https://developers.tickettailor.com/docs/api/get-all-event-series) nav lists full CRUD + occurrence create/update/delete + status change. |

**Auth:** same model as the rest of the API — HTTP Basic Auth, Base64(API key), per-box-office keys generated at `app.tickettailor.com/api` (confirmed in kb-cyq D1; the create pages sit under the same authenticated REST surface).

**Payload shape:** the reference pages render their request schema via client-side JS, so the static fetch did not expose the field list. The practical create-form field set is documented in kb-cyq D5 (logged-in dashboard scout of `/event/add`): **required** `name` + `timezone`; optional start/end date-time, recurring flag, venue (name/postcode/country) or online-event + platform, free-form description, image + alt text, header image, CTA label, capacity (`setMaxSellableTickets` / `maxSellableTickets`), low-availability threshold, ticket types, products, donations. The API event_series body is expected to mirror these. Exact JSON field names should be read off the live JS-rendered page (or via an authenticated probe) at adapter-build time — not a blocker for the scope verdict.

---

## Verdict

### (a) yes-public-endpoint

A public, documented API endpoint creates events programmatically:

- **`POST /v1/event_series`** (201) creates the event series, then
- **`POST /v1/event_series/:event_series_id/events`** (201) creates each event occurrence,
- under **HTTP Basic Auth** with a per-box-office API key.

The earlier `POST /v1/events` 404 was a red herring — `events` is read-only; the write path is the `event_series` resource. No support request or plan-tier gate is involved.

---

## What this means for the C11 adapter scope

The v0 C11 adapter can be a **fully programmatic create-path** (`POST /v1/event_series` → `POST /v1/event_series/:id/events` under Basic Auth) — no manual-assisted fallback needed for event creation; remaining build work is confirming the exact JSON body field names against the live JS-rendered reference (or an authenticated test call).

## canonical_refs

- `kb-a4u.11` — this spike's bead
- `docs/research/kb-cyq-r1-tickettailor-deepscout.md` — predecessor deep-scout (D1 API surface; D5 create-form fields)
- [Ticket Tailor API intro](https://developers.tickettailor.com/docs/api/ticket-tailor-api)
- [Create an event series](https://developers.tickettailor.com/docs/api/create-event-series)
- [Create an event occurrence](https://developers.tickettailor.com/docs/api/create-event-series-event)
- [Event series resource nav](https://developers.tickettailor.com/docs/api/get-all-event-series)
- `docs/decisions/ADR-010-event-based-product-posture.md` — ticketing as revenue/syndication path
