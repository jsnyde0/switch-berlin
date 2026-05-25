# ADR-016: Outbound syndication architecture — canonical Event + Post, per-platform projections, agent + UI co-equal API clients

**Status:** Accepted 2026-05-25
**Parent:** [ADR-010 D1 — event-based product posture](ADR-010-event-based-product-posture.md) (real-world action drives the existence of both Event and Post); [ADR-011 D1 — personal-agent layer additive](ADR-011-personal-agent-layer-additive.md) (already names per-target syndication + promo-post drafting as agent-extended scope; this ADR canonicalizes the entity model and API contract within that framing)
**Scope:** data-model + API-surface architecture for how Switch produces outbound to external platforms — both event listings (FetLife / Ticket Tailor / Switch's own event page / Eventbrite-later / IG-as-listing-later) and promotion posts (Telegram / IG-later / FB-later). Distinct from ADR-010 (product-posture / why syndicate at all), ADR-011 (agent-vs-SaaS placement of the cleaning logic), ADR-012 (visibility tiers that constrain which projections are allowed), and ADR-015 (payment-processor binding for the ticketing leg).

## Context

`kb-dko` brainstorm (2026-05-22 → 2026-05-25) converged on the v0 shape of Switch's outbound syndication after eight platform-agent and event-platform scouts. Three load-bearing decisions surfaced that don't have a home in the existing ADR corpus:

- **Facilitators author Events first, then make multiple Posts about them over time.** The scout-observed FetLife event (kink-tantric festival in Belgium) already shows this pattern in the wild: a single canonical event listing, with a description that hand-pastes `"Tickets via Hipsy: https://hipsy.eu/event/..."` — i.e., the facilitator authored the event once, then created a manual cross-link to the ticketing leg. Real-world workflow runs Event-first → Posts-later, and Posts come in sequences (save-the-date → early bird → almost-sold-out → last-call). The current schema (per ADR-007 D2) models Event with organizer/facilitator through-tables but has no concept of Post.
- **Different platforms ingest different shapes.** Event-listing platforms (FetLife, Ticket Tailor, Eventbrite) take *structured event data* — datetime, location, capacity, ticket types, dress code, organizer, age restriction. Promotion platforms (Telegram channels, IG feed, FB feed) take *free-form posts* that reference the event. Forcing one entity type to cover both yields either (a) a bloated Event with platform-specific extras or (b) a bloated Post that re-encodes event facts. Both fail the kb-2ve Phase A D2 framing of "two distinct syndication flows."
- **Switch's web UI and a facilitator's personal agent need the same API.** The brainstorm landed on BYO-agent posture (no bundled agent at v0). The cleanest contract is Moltbook-style (https://www.moltbook.com/skill.md): HTTP REST + Bearer API key → short-lived identity token → service-side `verify-identity`. Web UI and agents are co-equal clients of the same primitives — no private fast-path. Per ADR-011 D2, the agent-extended scope is "agent-natural features the web UI may not match," but the API surface itself stays common.

The existing ADR corpus surrounds this territory without covering it. ADR-007 carries the Profile/Organizer/Facilitator/Event schema; ADR-010 names the purpose (real-world action); ADR-011 carries the agent-vs-SaaS placement of cleaning logic; ADR-012 binds visibility tiers; ADR-015 binds the ticketing/payment leg. kb-2ve Phase A D2 (closed parent brainstorm) named the two flows. kb-o0j (open) owns the per-platform cleaning-policy substrate. **None of them canonicalizes the entity structure** (Event vs Post; what a per-platform projection is) or **the API contract shape** (how agents and the UI consume the same surface). Without canonical placement, downstream beads drift into ad-hoc choices — couple Posts into Event by accident, conflate listing-vs-promotion projection shapes, or ossify a private UI fast-path that breaks BYO-agent parity later.

This ADR canonicalizes the entity model and the API contract; cleaning-policy detail stays in kb-o0j.

## Decisions

### D1: Canonical Event and Canonical Post are separate entities; Posts reference Events but never share fields

**Firmness: FLEXIBLE** — landed via kb-dko brainstorm 2026-05-25 with concrete dogfooding-imminent intent (v0 organizer-hub build downstream). Mutation warrants: facilitators in dogfooding never use multiple Posts per Event AND find the Event-vs-Post authoring friction outweighs the benefit; a real-world workflow surfaces where Post fields legitimately depend on Event-field values (suggesting hidden coupling); the cleaning-policy work in kb-o0j produces evidence that listing-and-promotion content can't be cleanly separated. FLEXIBLE because evidence is forward-looking; reversible if observed workflow contradicts.

**The canonical Event** carries the structured facts about what's happening: title, description (the Event's own description, authored once), datetime, end-datetime, timezone, recurrence pattern, location (in-person venue with address + city/region/country, or online with link, or hybrid), organizer + co-hosts (via ADR-007 D2 through-tables), capacity, age restriction, dress code, content warnings, category, tags, cover image + optional gallery + video, pricing model (free / paid / donation / sliding-scale), ticket type shapes (schema reserved per ADR-003 cheap foresight; ticketing behavior is the V0/V1 Ticket Tailor leg per ADR-015 D1), visibility (per ADR-012), external links the facilitator wants to point at. The Event doesn't change because of where it's being announced.

**The canonical Post** carries the communication artifact about an Event: a reference to the Event it's about (FK), a headline/hook, a body (its own body — not derived from event.description), key imagery, a call-to-action (typically pointing back to a listing or to Switch's own event page), and authoring metadata (voice/tone, intended-moment-in-lifecycle). One Event has many Posts over its lifecycle (save-the-date → early bird → almost-sold-out → last-call). Posts and Events never share fields; the Post body is post-canonical content, not a projection of event.description.

**Workflow shape:** facilitator FIRST authors the Event (it exists in the world; gets listed; tickets become available). THEN, when they're ready to promote, they author one or more Posts (each tied to the Event by reference). The agent helps generate Post drafts from Event context, but the Post is its own authored artifact with its own body — not a rewrite of event.description.

**Rationale:**

- `external:` kb-dko brainstorm 2026-05-25 — user explicitly corrected the conflation: *"The event itself has a canonical description, why would it go borrow that from a post??? A facilitator FIRST tends to create the event. When that's all done, they make sure it's on all platforms it needs to be. THEN they will think of how to promote this."* The separation reflects observed facilitator workflow.
- `external:` kb-2ve Phase A D2 (closed 2026-05-20) — already framed two distinct syndication flows: event publishing AND event promotion posts. D1 here is the entity-level realization of that flow distinction.
- `external:` scout-observed FetLife event (kb-dko 2026-05-22) — in-the-wild evidence: facilitator authored event once + cross-linked to Hipsy ticketing in the description, separate from any subsequent promotion post.
- `reasoned:` calendar exports, search, ticketing all need Event without Post; coupling them forces "one event, one announcement" and loses campaign-sequence patterns that real facilitators use (save-the-date → early bird → last-call).
- `reasoned:` per ADR-003 cheap-foresight, structural separation now at zero cost preserves the multi-Post-per-Event campaign behavior for the post-v0 epic; coupling would force a migration.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Single Event entity with embedded promotional content (one body field used for both listings and promo posts) | `external:` kb-dko brainstorm 2026-05-25 user correction — collapses two distinct facilitator workflows (Event authoring vs Post composition) into one and forces "one event, one announcement." `reasoned:` loses the campaign-sequence pattern; downstream migration cost when multi-Post-per-Event behavior lands. |
| Post subsumes Event (Event facts live as fields on a Post) | `reasoned:` Event facts must stand alone — calendar exports, listing-platform ingestion, ticketing flows all need Event without Post present. `reasoned:` forces Event-fact duplication across multiple Posts referring to the same Event; consistency burden. |
| Event with an `announcements: List[Announcement]` inline collection (Posts as embedded sub-records) | `reasoned:` denormalizes Posts as a sub-resource of Events; obscures the Post-as-first-class-authoring-artifact framing the user emphasized. `reasoned:` complicates the API surface (Posts as nested under Events vs. as top-level resources facilitators and agents directly create/list/edit). |

**What would invalidate this:**

- Facilitators in dogfooding (Phase 0.5+) never use more than one Post per Event AND the Event-vs-Post authoring step adds friction without offsetting value. Operational signal across the first cohort of self-onboarded facilitators; if true across the cohort, collapse to a single entity.
- A real-world workflow surfaces where Post fields legitimately depend on Event-field values in ways that suggest hidden coupling (e.g., the post body always wants to interpolate event.title + event.datetime — suggesting the Post is actually a derived template, not a separate artifact). Substantive observation; revisit entity boundary.
- The kb-o0j cleaning-policy work concludes that listing-content and promotion-content cleaning are not separable (e.g., the same per-platform vocabulary substitutions apply identically to both shapes). Substantive observation; weakens the "two flows" framing.

### D2: Per-platform projections of two kinds — `listing` (from Event) and `promotion` (from Post); each projection is an editable, content-policy-filtered copy of its source

**Firmness: FLEXIBLE** — same kb-dko brainstorm convergence; same mutation warrants as D1. Reversible if the listing/promotion shape distinction collapses on observation.

A **projection** is a per-platform editable copy of either an Event (kind=listing) or a Post (kind=promotion), carrying:

- `platform_id` (e.g., `fetlife`, `tickettailor`, `switch-berlin-own`, `telegram-channel:<channel_id>`)
- `kind` ∈ {`listing`, `promotion`}
- `source_ref` (FK to Event for kind=listing, FK to Post for kind=promotion)
- `status` ∈ {`draft`, `ready`, `published`, `failed`} — tracks publication lifecycle
- `external_id?`, `external_url?`, `syndicated_at?` — populated after publication
- per-field overrides (every field of the source can be independently overridden on the projection; absent override means "use canonical value")
- platform-specific action elements (e.g., Telegram inline buttons, IG bio-link routing target, FetLife "interested" prompt copy) — these live on the projection, not on the canonical, because they're rendering choices specific to the platform

Each projection is generated initially from the canonical (Event for listing, Post for promotion) with content-policy filtering applied per platform (the filter rules live in kb-o0j cleaning-policy substrate, NOT in this ADR). Facilitator or agent edits the projection before flipping status to `ready` then `published`. When the canonical changes, projections do **not** auto-rewrite — they remain at their last-edited state until the facilitator or agent reviews and decides what to re-push.

**The agent's job becomes two-step:** (a) given a canonical Event, generate listing projections for each listing-platform target (event-structured shape + per-platform content-policy adaptation); (b) given a canonical Post + reference to its Event, generate promotion projections for each promotion-platform target (post-content shape + small set of inlined event facts + link back to a listing + per-platform content-policy adaptation).

**Per ADR-008 D2** (no speculative abstraction), v0 ships projections for exactly the targets in scope (FetLife listing, Ticket Tailor listing, Switch's own event page listing, Telegram promotion). The second target *within each kind* is what drives the per-platform abstraction shape — until then, each platform's projection is written directly.

**Rationale:**

- `external:` kb-dko brainstorm 2026-05-22 — six platform scouts (FetLife, Hipsy, Eventbrite, Ticket Tailor, Telegram, Instagram) showed that event-listing platforms and promotion platforms ingest structurally different shapes; one projection type doesn't fit both.
- `external:` kb-o0j (open) — per-platform cleaning-policy substrate already assumes platform-specific projections exist; D2 here canonicalizes the projection entity that kb-o0j's cleaning rules operate on.
- `external:` kb-dko 2026-05-25 user correction — *"shouldn't the canonical have everything and other platforms just have a subset?"* — per-field overrides on projections satisfy this; canonical stays the source of truth, projections are filtered/edited copies.
- `reasoned:` content-policy adaptation per platform (Hipsy strips BDSM vocabulary; FetLife allows explicit; IG must rework imagery for Meta policy) requires a per-projection editable surface; trying to bake content-policy into the canonical Event/Post would mean the canonical is platform-aware, which couples concerns the user explicitly rejected.
- `reasoned:` per-projection status enum (`draft|ready|published|failed`) lets facilitator approve each projection independently — critical for the manual-assisted publication path on no-API platforms (FetLife in v0) where status=ready means "Switch has the text ready; facilitator needs to copy-paste."

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Single projection type with a `platform` discriminator only (no `kind` field) | `external:` kb-dko brainstorm 2026-05-25 — listing platforms ingest structured event-facts; promotion platforms ingest free-form post-content. The source entity (Event vs Post) and the field shape (structured vs free-form) differ fundamentally; a discriminator-only model would force projections to know about both source entities and rendering shapes. `reasoned:` `kind` carries semantic load (listing-or-promotion is the meaningful behavior split), platform-id is just routing detail. |
| Platform-specific extras as bolted-on fields on the canonical Event (e.g., `event.fetlife_dress_code`, `event.telegram_pinned_buttons`) | `external:` kb-dko brainstorm 2026-05-25 user correction — *"I don't like this idea of 'platform-specific extras'; shouldn't the canonical have everything and other platforms just have a subset?"* `reasoned:` forces the canonical Event to know about every platform Switch ever supports; violates separation of concerns (canonical = source of truth about the event; projection = platform-shaped render). |
| One projection per (Event-or-Post, platform), with an internal field signaling whether the source is Event or Post | `reasoned:` collapses listing-vs-promotion at the schema layer; loses the explicit `kind` that lets queries / agent code / UI filter "show me all listing projections that are stuck in `draft`" cleanly. `reasoned:` per-Post promotion projections need to inline event facts and link back to a listing projection; without `kind`, that cross-reference is implicit and fragile. |
| Project lazily at render time (no persistent projection records — generate fresh per publish) | `reasoned:` loses the per-projection edit history; loses the manual-assisted-publication status tracking; loses the ability for the facilitator to leave a FetLife listing projection in `ready` state for hours before copy-pasting. `reasoned:` agent generation is non-deterministic; persisting the projection lets facilitator review the exact text being published, not a re-generated approximation. |

**What would invalidate this:**

- All platforms in scope turn out to need both event-fact and post-content content equally (no clean listing/promotion split observed in dogfooding). Substantive observation across the first two targets within each kind; if true, collapse to a single projection type with discriminator-only routing.
- The status enum proves too coarse (e.g., dogfooding surfaces "needs facilitator review" or "agent-suggested but not yet reviewed" as load-bearing states). Operational signal; refine the enum in place — not a D2 invalidation per se.
- Per-field overrides prove unused or always-identical-to-canonical (i.e., projection-as-edit-layer adds friction without value). Operational signal; consider collapsing to "render canonical with platform-policy filter" without persistent override layer.

### D3: Switch's web UI and external personal agents are co-equal clients of the same HTTP API; Moltbook-pattern Bearer + identity-token auth; BYO-agent at v0

**Firmness: FLEXIBLE** — same kb-dko convergence. Mutation warrants: BYO-agent distribution friction blocks closest-circle facilitator adoption (signal: "we lost a closest-circle facilitator because BYO was too hard"); a sister-platform-style web-UI fast-path becomes load-bearing for performance or transactional integrity reasons; Moltbook-pattern auth proves insufficient for a real-world security concern that surfaces during dogfooding.

Switch exposes an HTTP API as the canonical surface for Event/Post/Projection operations. The Switch web UI and any facilitator's personal agent consume that surface as **co-equal clients** — there is no private UI fast-path. Auth follows the Moltbook pattern (https://www.moltbook.com/skill.md):

- A facilitator registers an agent via `agents/register` (browser-mediated one-time flow) → receives a Bearer API key (long-lived secret stored by the agent).
- For each request, the agent exchanges the API key for a short-lived **identity token** (~1h expiry, single-use scoped) via an exchange endpoint.
- External services calling Switch verify the identity token by hitting Switch's `verify-identity` endpoint with their own app key in the header.
- No SDK or per-language client is required; HTTP REST + Bearer works with any language.

**Per ADR-011 D2,** the web UI's affordances may not match the agent's affordances (agent-natural primitives may be exposed without web UI parity). But the API surface itself is common; the web UI is just one client among many.

**Per ADR-008 D2** (no speculative abstraction), v0 ships the smallest surface that supports the first projection set: canonical Event CRUD, canonical Post CRUD, projection generation for the four targets in v0 scope, projection status transitions, agent registration. The `switch-berlin/skill.md` agent-facing doc gets extracted from dogfooding (Tier-2 deliverable, not v0) — until then, the API itself is the contract.

**Bundled-agent posture is deferred.** Switch does NOT ship its own agent at v0. Facilitators bring their own (Claude Code / Cursor / nanoclaw / Paseo / whatever) and configure it against the API. The deferred-bundled-agent signal-to-revisit is "we lost a closest-circle facilitator because BYO was too hard" — operational signal, not a date.

**Rationale:**

- `external:` Moltbook scout (kb-dko 2026-05-22) — proven platform-agent contract pattern (Bearer + identity-token + verify-identity + agents/register); language-agnostic; no SDK required; agents are first-class participants alongside web clients.
- `external:` kb-dko brainstorm 2026-05-22 user framing — *"Switch is a platform with a uniform agent-callable API. The web UI and the facilitator's personal agent are co-equal clients of the same surface. Not 'Switch UI → push to platforms'; it's 'Switch is the platform-of-record + a programmable API; agents and UI are co-equal clients.'"*
- `external:` ADR-011 D1 — agent layer additive; the agent-extended scope already names per-target syndication + promo-post drafting as agent-natural features. D3 here gives the API contract shape that ADR-011 D1's framing assumes.
- `reasoned:` BYO-agent at v0 minimizes Switch's surface (we don't maintain an agent runtime in addition to the platform) and matches the dogfooding loop (user runs their own agent against the API, surfaces friction, friction informs `skill.md` extraction).
- `reasoned:` Moltbook-pattern auth's separation of long-lived API key from short-lived identity token reduces blast radius of token leakage — critical given facilitators will run agents on their own machines.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Bundled agent at v0 (Switch ships its own nanoclaw fork or equivalent) | `external:` kb-dko brainstorm 2026-05-22 user framing — *"initially it's probably waay too much to ship our own agent. We're probably better off building the skills/cli/... that any agent can use? And so, this way I can sort of just dogfood this myself with my own agent."* `reasoned:` shipping our own agent adds runtime maintenance, distribution, and security surface; defers `skill.md` extraction (which comes out of dogfooding friction); risks ossifying the API around the bundled agent's quirks before BYO patterns prove out. Deferred, not killed — revisit on distribution-friction signal. |
| Private web-UI fast-path with a separate agent-facing API surface | `external:` kb-dko brainstorm 2026-05-22 user framing — *"Web UI and the facilitator's personal agent are co-equal clients of the same surface. Not 'UI pushes, agent reads.'"* `reasoned:` two surfaces means two sources of truth for behavior; drift inevitable; agents quickly diverge from UI capabilities. `reasoned:` violates the Moltbook framing where agents are first-class participants. |
| SDK-per-language (Python SDK, JS SDK, etc.) instead of raw REST | `external:` Moltbook proves REST + Bearer is sufficient and language-agnostic. `reasoned:` SDKs impose per-language maintenance burden; raw REST works with any language including ones we don't anticipate (Pi-agent in Rust, Codex-flavored agents in Go, etc.). `reasoned:` we'd rather extract a `skill.md` (markdown spec for agents) from dogfooding than commit to N SDKs upfront. |
| OAuth instead of Bearer + identity-token | `reasoned:` OAuth's complexity (authorization code flow, refresh tokens, scope management) imposes web-app-shaped UX on what is a CLI/agent-shaped use case. `reasoned:` Moltbook's pattern (long-lived API key → short-lived identity token → verify endpoint) provides equivalent blast-radius reduction with simpler implementation. `external:` Moltbook docs explicitly document the design choice; we adopt it directly. |

**What would invalidate this:**

- BYO-agent distribution friction blocks closest-circle facilitator adoption — operational signal, e.g., a facilitator says "I'd use this if you made it work without me configuring my own agent." If observed across more than one closest-circle facilitator, escalate bundled-agent posture from "deferred" to "in-scope for v0.5+."
- A sister-platform-style web-UI fast-path becomes load-bearing for transactional integrity or performance (e.g., a real-time RSVP flow that needs sub-50ms latency the public API can't deliver). Substantive observation; revisit "co-equal" framing.
- Moltbook-pattern auth proves insufficient for a real-world security concern (e.g., agent-side credential theft surfaces a need for per-action confirmation beyond identity-token verification). Substantive observation; layer additional auth without abandoning the base pattern.
- The `skill.md` extraction from dogfooding doesn't converge — facilitators' agents keep needing different primitive shapes — suggesting the API isn't co-equal in practice but is web-UI-shaped. Operational signal; reshape API primitives toward agent-naturalness.

## Consequences

### Direct

- The v0 organizer-hub impl bead (spawned from kb-dko at close) must implement Event and Post as separate Django models with FK from Post to Event; not embed Post fields in Event.
- The v0 impl ships projection records for at minimum: FetLife listing, Ticket Tailor listing, Switch's own event page listing, Telegram channel promotion. Each projection carries the full schema in D2 (platform_id, kind, source_ref, status, external_id?, external_url?, syndicated_at?, per-field overrides).
- The v0 impl exposes an HTTP API at the perimeter Web UI consumes — same endpoints, same auth, no private fast-path. `agents/register` and `verify-identity` endpoints land in v0.
- `switch-berlin/skill.md` is **not** a v0 deliverable; it gets extracted from dogfooding once the API has shaken out (Tier-2). Until then, the API itself is the contract; OpenAPI/JSON-schema docs at the API endpoints suffice.
- The Switch facilitator agent (planned in ADR-011 D1, dogfooded by the project owner first) interacts with Switch exclusively through this API contract — no direct DB access, no internal-only RPCs, no agent-special-casing in the codebase.
- Per ADR-003 cheap foresight, the schema reserves shape (not behavior) for: multi-Post-per-Event campaign sequencing, full ticket type taxonomy, buyer/attendee screening questions, recurrence pattern. These are reservation-only at v0 — the behavioral epics that consume them ship later (RSVP+screening epic, campaign-sequence epic, recurring-events epic).
- Per-platform content-policy filtering is owned by kb-o0j cleaning-policy substrate; D2 here only canonicalizes the **projection entity** that the cleaning rules operate on. ADR-016 does not encode policy rules.

### Carried forward

- **ADR-011 D1 FLEXIBLE — agent layer additive.** D3 here is the API contract realization of ADR-011 D1's "agent-extended scope" framing. ADR-011 stays at the layer-boundary level; ADR-016 D3 carries the wire-level contract.
- **ADR-010 D1 FLEXIBLE — real-world action over engagement.** D1 here separates Event (real-world action) from Post (communication about the action). The Post entity exists explicitly to drive real-world Events, not to optimize engagement-on-Posts as a metric.
- **ADR-012 FLEXIBLE — visibility tiers.** Projections inherit and respect Event.visibility: `unlisted` Events generate no external projections by default; `semi_public` Events generate projections only to platforms compatible with the viewer-tier access matrix (per ADR-012 D3); `public` Events project to all configured platforms. D2's projection generation logic honors ADR-012's matrix.
- **ADR-007 D2 FIRM — EventOrganizer/EventFacilitator through-tables.** Event's organizer + co-host modeling continues to use these through-tables; projections render organizer/co-host names per the canonical relationship.
- **ADR-008 D2 FIRM — no speculative abstraction.** v0 projection plumbing covers exactly the four target platforms in scope; the second target *within each kind* drives the per-platform adapter abstraction. No "ProjectionAdapter" base class or plugin registry until then.
- **ADR-003 — cheap foresight on data shape.** Schema reservations for multi-Post-per-Event, full ticket types, buyer/attendee questions, recurrence land in the v0 migration; behaviors ship in later epics.
- **ADR-015 D1 FLEXIBLE — V0/V1 ticketing on Ticket Tailor.** The Ticket Tailor listing projection in v0 scope inherits ADR-015's Mode A coordination-layer posture (organizer-direct Stripe, Switch is not in the payment funds path).

### Risk

- **Listing/promotion shape drift.** If empirical evidence shows listing and promotion projections converge in shape (e.g., promotion platforms start needing structured event fields equally; listing platforms start needing free-form post copy more than event description), D2's `kind` distinction loses meaning. Mitigation: explicit invalidation predicate; review at the second target within each kind.
- **Projection-as-edit-layer friction.** If facilitators never edit projection overrides (always accept canonical-as-projected), the per-field override mechanism is overhead without value. Mitigation: D2 invalidation predicate; observe dogfooding behavior in the first cohort.
- **BYO-agent distribution gap.** Closest-circle facilitators without agent fluency may be blocked from the BYO path; if the dogfooding cohort hits this, v0 doesn't ship signal on the wedge. Mitigation: dogfood-by-project-owner first (single facilitator with full agent fluency); broaden cohort once the BYO loop proves out; bundled-agent revisit on hit-signal.
- **Cleaning-policy substrate coupling.** D2's content-policy filtering depends on kb-o0j's cleaning-policy substrate. If kb-o0j evolves slowly or in a direction that doesn't fit projection-shape, projections can't be content-policy-clean. Mitigation: ADR-016 explicitly cross-refs kb-o0j; mid-implementation discoveries route there per ADR-008 D4.
- **API surface ossification before `skill.md` extraction.** If the v0 API surface gets used by external agents before `skill.md` (the agent-facing doc) shakes out, friction surfaces in production. Mitigation: dogfood-by-project-owner first; document API as JSON-schema/OpenAPI from day 1; treat `skill.md` extraction as a follow-up bead.
- **Mode-A boundary coupling with ADR-015 D1.** Projections to Ticket Tailor must not drift toward Mode B (Switch-aggregating-payments) per ADR-015 D1. Mitigation: ADR-015 D1 invalidation predicate already covers boundary collapse; ADR-016 D2's TT-listing projection only ships event metadata to TT, not payment routing.

## canonical_refs

- [ADR-001 D8](ADR-001-core-product-and-stack.md) — normalized schema from day 1; Event and Post will be Django models in the existing schema layer.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight on data shape; ticket_types, buyer_questions, attendee_questions, recurrence, multi-Post-per-Event campaign all reserve schema shape now, behavior later.
- [ADR-007 D2](ADR-007-profile-centric-schema.md) — EventOrganizer + EventFacilitator through-tables; Event uses these for organizer/co-hosts; projections render through-table names.
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction; v0 projection plumbing covers exactly the four target platforms; abstraction shape emerges from the second platform within each kind.
- [ADR-010 D1](ADR-010-event-based-product-posture.md) — real-world action drives the existence of both Event (the action) and Post (announcement of the action); business model cannot monetize engagement-on-Posts.
- [ADR-011 D1, D2](ADR-011-personal-agent-layer-additive.md) — agent layer additive; agent-extended scope already names per-target syndication + promo-post drafting; ADR-016 D3 canonicalizes the API contract within that framing.
- [ADR-012](ADR-012-event-visibility-tiers.md) — visibility tiers constrain projection generation; unlisted Events generate no external projections by default.
- [ADR-015 D1](ADR-015-payment-processor-strategy-for-explicit-event-ticketing.md) — V0/V1 ticketing rides on Ticket Tailor; ADR-016 D2's TT-listing projection inherits ADR-015's Mode A coordination-layer posture.
- `kb-2ve` (closed Phase A, 2026-05-20) — parent brainstorm that originally named the two syndication flows in D2 (event publishing AND event promotion posts).
- `kb-o0j` (open) — Switch facilitator cleaning policy; owns per-platform content-policy substrate that D2's projections invoke during generation. ADR-016 does not encode policy rules; kb-o0j does.
- `kb-dko` (closing at convergence of this brainstorm) — brainstorm bead that converged this ADR; closed via close-and-spawn into a v0 impl bead.
- `kb-94h` — organizer Stripe-onboarding playbook; complements ADR-015 D1 and the v0 listing projection to Ticket Tailor.
- `https://www.moltbook.com/skill.md` — external reference for the agent-platform contract pattern (Bearer API key → identity token → verify-identity endpoint).

## Open questions deferred

| Question | Resolution path |
|---|---|
| When does `switch-berlin/skill.md` get extracted from dogfooding? | Defer to post-v0; trigger is "dogfooding has surfaced enough friction patterns that a markdown spec for external agents adds more value than the API + OpenAPI docs alone." Likely Tier-2 deliverable in v0.5. |
| What's the projection-publication trust model for manual-assisted platforms (FetLife)? | Defer to v0 impl bead; working assumption: facilitator manually pastes; status=published is set by facilitator action in the web UI, not auto-detected. Could evolve to browser-automation later if FetLife ToS allows. |
| How do projection-edit-conflicts resolve when canonical changes after projection was edited? | Defer to dogfooding; working assumption: projections don't auto-rewrite; UI surfaces a "canonical has changed, review projection" affordance. |
| Does the bundled-agent posture (deferred at v0) get a separate ADR when revisited, or does it land as an evolution of ADR-016 D3? | Defer; working assumption: in-place evolution of D3 (firmness shift + explicit bundled-agent decision), not a new ADR. Per ADR-011 D1 in-place mutation discipline. |
| What happens to `kb-o0j` cleaning-policy substrate if the listing-vs-promotion shape distinction collapses (D2 invalidation)? | Defer to that observation if it lands; kb-o0j's per-platform rules likely still apply but the "rules per kind" framing may collapse. |
