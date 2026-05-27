# ADR-016: Outbound syndication architecture — canonical Event + Post, per-platform projections, agent + UI co-equal API clients

**Status:** Accepted 2026-05-25 (D2 refined + D4/D5 added 2026-05-26 via C3/C5 authoring-UX brainstorm; D3 v0 concrete auth shape pinned 2026-05-27)
**Parent:** [ADR-010 D1 — event-based product posture](ADR-010-event-based-product-posture.md) (real-world action drives the existence of both Event and Post); [ADR-011 D1 — personal-agent layer additive](ADR-011-personal-agent-layer-additive.md) (already names per-target syndication + promo-post drafting as agent-extended scope; this ADR canonicalizes the entity model and API contract within that framing)
**Scope:** data-model + API-surface architecture for how Switch produces outbound to external platforms — both event listings (FetLife / Ticket Tailor / Switch's own event page / Eventbrite-later / IG-as-listing-later) and promotion posts (Telegram / IG-later / FB-later). Distinct from ADR-010 (product-posture / why syndicate at all), ADR-011 (agent-vs-SaaS placement of the cleaning logic), ADR-012 (visibility tiers — read-side rendering on switch.berlin; do NOT gate outbound syndication per the revised carried-forward note), and ADR-015 (payment-processor binding for the ticketing leg).

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

- `connection` (FK to a `PlatformConnection` destination — see D4; **supersedes** the `platform_id` string the as-built C1 schema shipped, refront via the kb-a4u.1 follow-up refactor bead)
- `kind` ∈ {`listing`, `promotion`}
- `source_ref` (FK to Event for kind=listing, FK to Post for kind=promotion)
- `status` ∈ {`draft`, `ready`, `published`, `failed`} — tracks publication lifecycle (see D5)
- `external_id?`, `external_url?`, `syndicated_at?` — populated after publication
- per-field overrides (`override_data` — every field of the source can be independently overridden on the projection; absent key means "use canonical value")
- `provenance` ∈ {`rule_template`, `agent_supplied`, `manual`} — how the *current* effective content was last produced; flips to `manual` the moment a human edits an override. Carries the generated-vs-edited signal the review board surfaces without any version machinery
- `generated_by?` (nullable agent identity) + `last_generated_at?` — ADR-003 reservation fields; empty for human-driven flows, populated when an agent supplies content. They are the columns a future `ProjectionRevision` history table would key on
- platform-specific action elements (e.g., Telegram inline buttons, IG bio-link routing target, FetLife "interested" prompt copy) — these live on the projection, not on the canonical, because they're rendering choices specific to the platform

**Effective content = live canonical (Event/Post fields) + `override_data`.** There is no stored `generated_body`/`override_body` two-field split: a listing's non-overridden fields track the Event automatically (no stale stored copy), and an override is a per-field delta. The template seed is one-time at projection creation, not a re-runnable regenerate. No version history at v0 — the additive path is a future append-only `ProjectionRevision` table keyed on `provenance` + `generated_by` + `last_generated_at`. (Dolt-style data versioning rejected for app data: its branch/merge superpower is unneeded for linear projection revisions; a plain Postgres revision table is the right tool when the agent-iteration loop makes history load-bearing.)

Each projection is generated initially from the canonical (Event for listing, Post for promotion) with content-policy filtering applied per platform (the filter rules live in kb-o0j cleaning-policy substrate, NOT in this ADR). Facilitator or agent edits the projection before flipping status to `ready` then `published`. When the canonical changes, non-overridden fields track it automatically; overridden fields remain at their last-edited state until the facilitator or agent reviews and decides what to re-push.

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

**v0 concrete shape (decided 2026-05-27 — narrows this FLEXIBLE decision in place per ADR-011 D1; converged in the C3/C5 + agent-credential design session).** The Moltbook three-leg pattern above is the target; v0 ships the subset that has a live consumer:

- **Issuance = one-time pairing-token redemption, not raw key paste.** `agents/register` mints a short-lived single-use *pairing token* (mirrors the `MagicLinkToken` envelope, organizers/models.py); the facilitator hands that token to their agent, which redeems it over the API for the long-lived Bearer key. The long-lived secret never transits the facilitator's clipboard — only the agent ever holds it (this is why pairing-token-redemption beats raw key-paste). Full agent-initiated browser device-flow (no paste at all) is deferred until non-technical-facilitator BYO friction surfaces — the operational signal this decision already names.
- **Legs 1–2 built; leg 3 (`verify-identity`) stubbed.** The long-lived-key → short-lived-identity-token exchange ships (real blast-radius reduction, cheap). `verify-identity` exists for a *third-party* service that receives a Switch-issued token and must ask Switch to validate it — the "Sign in with Switch" case (e.g. a future sister platform or partner aggregator), analogous to a service calling Google to verify a "Sign in with Google" token. v0 has no such consumer — the facilitator's own agent calls Switch directly and Switch verifies its own tokens — so `verify-identity` ships stubbed until an external consumer exists (ADR-008 D2).
- **Credential binds to the User, not a Profile.** One key = the registering facilitator's identity; authority resolves through that User's full `ProfileClaim` set (ADR-017 D1), exactly as the web UI's session does. No per-Profile keys.
- **Actor-marker is for provenance, not authority.** Web UI (session) and agent (Bearer) enter through different doors but resolve to the same User and the same `can_edit` — authority is identical by design (the agent is the user's delegate per ADR-017 D1). The request's auth method is recorded as an actor-marker on writes (→ the reserved `generated_by`/`provenance` projection fields) so the review surface can show "your agent drafted this; you edited it." Audit-only at v0; rate-limiting or per-action-confirmation by actor-type is deferred.

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

### D4: A projection targets a `PlatformConnection` (a specific destination), not a platform string; connections are eager-fanned into draft projections per enabled connection × supported kind

**Firmness: FLEXIBLE** — landed via the C3/C5 authoring-UX brainstorm 2026-05-26, dogfooding-imminent. Reversible if dogfooding shows organizers never run more than one destination per platform AND the connection indirection adds friction without value, or if eager creation produces draft clutter that organizers find noisier than an explicit "add a destination" gesture.

A **`PlatformConnection`** is a specific syndication destination owned by an organizer: one Telegram channel, one FetLife account, the Switch own-event-page, one Ticket Tailor account. It carries: organizer/Profile (per ADR-007 D2), `platform`, the destination identifier, per-destination credentials, an `enabled` flag, and the `kinds` it supports (Switch page → listing; Ticket Tailor → listing; Telegram → promotion; FetLife → **both**). A `PlatformProjection` FKs to a connection, **not** to a bare platform string.

This unifies two surfaces that would otherwise drift apart: the organizer's **"which platforms am I syndicating to" setting** and the **per-organizer adapter credential store** the adapter beads (kb-a4u.10–.16) needed anyway. They are the same model. An organizer may hold **multiple connections per platform** (three Telegram channels = three connection rows); "many channels later" is additive rows, zero reshape. Person/DM-level targeting *within* a destination is explicitly out of scope at v0 — v0 is destination/channel-level.

**Eager creation:** when an Event is authored, eager-create `draft` listing projections for each enabled connection that supports `listing`; when a Post is authored, eager-create `draft` promotion projections for each enabled connection that supports `promotion`. FetLife (both kinds) gets a listing row from the Event and promotion rows from Posts. **Per-event/post inclusion is expressed through status, not a separate toggle**: leaving a row in `draft` = "don't publish there this time." The status board is thereby honest-by-default — every possible destination is visible as a draft row, nothing is silently absent.

**Rationale:**

- `reasoned:` **the core of the model is non-speculative and needed now**: every credential-storing adapter (kb-a4u.10–.16) must put per-destination credentials *somewhere*, and the organizer's "which platforms am I syndicating to" setting (the `enabled` default) must live *somewhere* — a `platform_id` string has nowhere to put either. `PlatformConnection` is the home both already require at v0; it is not built ahead of a consumer. This is the ADR-008 D2-clearing argument: the model ships because v0 adapters demand it, not on foresight.
- `external:` C3/C5 brainstorm 2026-05-26 — the *multi-connection-per-platform* shaping on top is the only foresight increment, and it tracks stated present reality, not speculation: user named the multi-destination reality directly (*"on Telegram you can post this in many channels… config there of which channels it gets posted to"*) and corrected FetLife as both-kinds (*"it's like Facebook where you can post events but also create posts"*). Allowing N connection rows per platform is zero extra schema over the credential-home the adapters already force — ADR-003 cheap foresight on a known requirement.
- `reasoned:` eager creation makes the review board's "what's going where" complete by default (the visibility property worth stealing from a campaign-composer UI without building one), and gives an agent a stable set of draft rows to fill rather than requiring it to know the platform catalog to create rows.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| `platform_id` string on the projection (as-built C1) | `direct:` `syndication/models.py` shipped `platform_id = CharField` with `'telegram-channel:<id>'` encoding — the channel-in-a-string gesture shows destinations were anticipated but had nowhere structured to live. `reasoned:` no home for credentials / `enabled` / multiple channels; settings and adapter-creds would drift into separate ad-hoc stores. |
| Separate `Destination`/`Target` model distinct from a per-platform `Connection` | `reasoned:` over-modeled at v0 — one connection *is* one destination; "multiple Telegram channels" is multiple connection rows, no second model needed. Collapsing destination into connection is the simplest thing that supports the stated multi-channel requirement. |
| Lazy / on-demand projection creation (rows created only when a destination is chosen) | `reasoned:` the board only shows chosen channels, losing the honest-by-default "here's everywhere this could go" overview; and an agent must enumerate the platform catalog to create rows rather than filling a stable pre-existing set. `external:` user's "configurable per user… eager model" steer. |
| Per-event explicit platform toggle (separate from connection `enabled`) | `reasoned:` redundant with status — `draft` already expresses "not publishing here this time"; a second toggle is two mechanisms for one intent. |

**What would invalidate this:**

- Dogfooding organizers consistently run exactly one destination per platform AND report the connection FK / settings indirection as friction without offsetting value. Operational signal across the first cohort; collapse toward a thinner platform-enum if so.
- Eager draft rows prove to be clutter organizers actively dismiss rather than a useful overview (e.g., they want to opt *in* to destinations, not opt *out*). Operational signal; flip to lazy creation.
- Destination-level targeting proves too coarse — a real workflow needs per-person/segment targeting inside a channel at v0. Substantive observation; the connection shape doesn't preclude a sub-target later, but the v0 scope-out would be wrong.

### D5: Publish lifecycle is explicit and actor-attested — `draft → ready` is the completeness gate; `ready → published` is an explicit action; `mark-published` is a co-equal API verb

**Firmness: FLEXIBLE** — landed via the C3/C5 brainstorm 2026-05-26. Reversible if dogfooding shows the explicit publish step is friction organizers want automated away, or if the actor-attested model proves unreliable for no-API platforms.

The status enum `{draft, ready, published, failed}` (D2) carries these transition semantics:

- **`draft` doubles as work-in-progress.** Saving an incomplete Event/projection is always allowed; it sits in `draft`. The fail-loud "missing X" state (per ADR-008 D3 — no silent zero-fill) is therefore also the **save-and-resume affordance**: an organizer returning later sees clearly that the projection isn't ready and exactly what's blocking it.
- **`draft → ready` is the completeness gate.** This transition — an explicit approve action — is where required-input completeness is enforced. Completeness is gated *here*, never at save-time.
- **`ready → published` is an explicit publish action** (per-row, plus a batch "publish all ready"), **never auto-on-`ready`**. `ready` means "approved/staged"; `published` means "it's actually out there." Keeping the push deliberate (a) makes fail-loud a chosen act rather than a side-effect of approval, (b) gives an agent two clean composable verbs (`set-ready`, then `publish`) instead of one overloaded one, and (c) is the only model that works for no-API platforms.
- **`mark-published` is a first-class co-equal API verb** (per D3 — co-equal clients), not a UI-only button. The web "mark as posted" control and an agent's `switch projection publish <id>` hit the *same* verb. The distinction across platforms is **push-API-exists vs not**: push-API platforms (Telegram, Ticket Tailor) — the publish verb performs the push and auto-confirms `published`/`failed`; no-API platforms (FetLife) — the actor does the push out-of-band (human copy-paste, or agent browser-automation **with verification**) and then attests via `mark-published`. An agent is a *better* attestor than a human here because it can verify the post landed before attesting.

**Failed-push is governed by FIRM ADR-008 D3/D4** (not restated here): transport blips → up to 2 retries → `failed`; platform 4xx/5xx, content rejection, validation → no retry → immediate `failed`; `failed` is never silent — the row surfaces the platform's actual reason and offers a manual retry. Only push-API platforms can reach `failed` (a human is the transport for no-API platforms). **Content-policy pre-publish surfacing:** `clean_for_platform` (kb-o0j) flags terms a platform may reject; surface that as a pre-publish warning on the row rather than letting the push fail downstream. **Edit + re-publish of an already-`published` projection is deferred** (adapter-specific — some platforms support edit-in-place, some don't).

**Rationale:**

- `external:` C3/C5 brainstorm 2026-05-26 — user chose explicit publish (*"yes explicit"*) and reframed the no-API path as agent-attestable: *"keep in mind we'll probably want to enable our agent to do it for us. So the agent can then also verify, and use the cli… to mark as actually published."* Also surfaced the WIP insight: the incomplete-state display *"would allow users to save progress… and come back later… it's clear the event isn't 'ready' yet."*
- `reasoned:` actor-attested-via-a-shared-verb is the only model consistent with D3's co-equal principle — a UI-only "mark posted" button would be a private web fast-path, exactly what D3 forbids.
- `reasoned:` making `draft → ready` the single completeness gate (rather than gating at save) is what lets `draft` serve double duty as WIP without a separate "incomplete" state.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Auto-publish on `ready` (approval *is* publication) | `external:` user chose explicit. `reasoned:` makes the push a side-effect of approval (fail-loud becomes incidental, not deliberate); collapses the agent's two composable verbs into one; cannot express the no-API "staged, awaiting out-of-band post" state. |
| Human-only "mark as posted" UI button for no-API platforms | `reasoned:` a UI-only attest path is a private web fast-path — violates D3 co-equal. The attest must be a shared API verb so an agent can call it (and verify before attesting). |
| Gate completeness at save-time (can't save an incomplete Event) | `external:` user's save-and-resume framing. `reasoned:` blocks the partial-draft workflow; forces organizers to complete in one sitting; loses `draft`-as-WIP. |
| Auto-rewrite/auto-republish published projections when canonical changes | `reasoned:` adapter-specific and surprising (silent re-push of already-public content); deferred until the edit-in-place capability per adapter is known. |

**What would invalidate this:**

- Dogfooding organizers experience the explicit publish step as friction they'd rather have automated (e.g., "I always publish-all immediately after marking ready — why two steps?"). Operational signal; consider an opt-in auto-publish per connection.
- The actor-attested model proves unreliable for no-API platforms (agents mis-attest published when the post didn't actually land, or humans forget to attest and the board lies). Operational signal; layer verification requirements onto the attest verb.
- The `{draft, ready, published, failed}` enum proves too coarse (e.g., a load-bearing "agent-suggested, not yet human-reviewed" state emerges). Operational signal; refine the enum in place per the D2 note.

### D6: API framework = Django Ninja (in-process, Django-routed); django-bolt rejected because its separate server can't share Django's auth/service layer

**Firmness: FLEXIBLE** — user-confirmed at decomposition (2026-05-26); v0 tactical. Reversible if Ninja's in-process model can't cleanly share handler/auth with the HTMX views (D3 co-equal test can't go green without a private fast-path) or if perf needs exceed in-process Python.

The HTTP API surface (D3) is built with **Django Ninja**. Ninja handlers are ordinary in-process Django-routed callables, so the JSON API and the HTMX HTML views can sit over a **shared service/domain layer** and resolve to identical persistence + auth middleware. D3 mandates *co-equal clients of one API surface with no private fast-path*; the load-bearing mechanism that satisfies it is a **single shared auth + service layer** behind both the JSON and HTML entrypoints. A framework that runs its own server with its own auth necessarily implements that layer twice (or splits it), which reintroduces exactly the two-surface drift D3 forbids — that is the real reason django-bolt fails the test, not a literal "same callable" requirement. Ninja also auto-generates the OpenAPI/JSON-schema docs D3's consequences rely on as the interim agent contract (pre-`skill.md`). The app lives in a dedicated `syndication/` Django app (already created in C1).

**Rationale:**

- `reasoned:` co-equal (D3) requires the web UI and agents to hit the *same* logic behind one shared auth + service layer; an in-process framework lets HTML views and JSON handlers share that layer and the same Django auth middleware directly. A framework that runs its own server must re-implement auth on its side, splitting the layer D3 requires be single.
- `external:` django-bolt README — it runs a **separate Rust (Actix Web + PyO3) server** via `manage.py runbolt` with its own Rust-side auth; that separate-server-with-separate-auth shape is what splits the shared layer, so it cannot satisfy D3's no-private-fast-path constraint even though both could nominally expose the same API surface.
- `reasoned:` Ninja's auto-OpenAPI gives D3's interim agent contract nearly for free; DRF would need extra schema wiring; raw Django views would need hand-rolled typed schemas + docs.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| django-bolt (Rust Actix + PyO3) | `external:` django-bolt README — separate `runbolt` Rust server with Rust-side auth; `reasoned:` a separate server with its own auth splits the single shared auth/service layer D3 requires behind one API surface → reintroduces the two-surface drift D3 forbids. Its perf win (188k RPS) is irrelevant at v0 scale and is the explicit tripwire to revisit, not a v0 need. |
| Django REST Framework | `reasoned:` viable in-process and co-equal-compatible, but heavier (serializer/viewset ceremony) and needs extra wiring for OpenAPI; Ninja gives typed schemas + auto-docs with less boilerplate. Not wrong — just more for the same v0 outcome. |
| FastAPI (standalone ASGI) | `reasoned:` separate ASGI app, not Django-routed → loses native ORM/admin/middleware integration and the shared-handler property; reintroduces the two-surfaces drift D3 forbids. |
| Raw Django views + manual JSON | `reasoned:` no auto OpenAPI (D3's interim contract), hand-rolled request/response typing for every endpoint; more boilerplate and drift risk for a typed agent-facing API. |

**What would invalidate this:**

- The co-equal integration test (kb-a4u.9) can't be made green with Ninja without introducing a web-only fast-path — i.e., Ninja's request model and the HTMX view layer can't actually share handler/auth cleanly. Substantive observation at C2/C8; revisit framework.
- In-process Python throughput becomes load-bearing (the django-bolt tripwire fires under real traffic). Operational signal; revisit, having already isolated logic in a service layer so the swap is contained.

## Consequences

### Direct

- The v0 organizer-hub impl bead (spawned from kb-dko at close) must implement Event and Post as separate Django models with FK from Post to Event; not embed Post fields in Event.
- The v0 impl ships projection records for at minimum: FetLife listing, Ticket Tailor listing, Switch's own event page listing, Telegram channel promotion. Each projection carries the full schema in D2 (connection FK per D4, kind, source_ref, status, external_id?, external_url?, syndicated_at?, override_data, provenance, generated_by?, last_generated_at?).
- The as-built C1 schema (`syndication/models.py`, kb-a4u.1 closed 2026-05-26) predates D2's refinement + D4/D5: it shipped `platform_id` as a string and lacks `provenance` / `generated_by` / `last_generated_at` / `PlatformConnection`. The follow-up refactor bead **kb-a4u.18** (discovered-from kb-a4u.1) adds `PlatformConnection`, refronts the projection FK, AND adds the provenance + attribution fields — all three deltas in one schema refactor that blocks the authoring/generation/review beads and the credential-storing adapters. Pre-launch, squashable migration per ADR-008 D1.
- A `PlatformConnection` model (D4) lands in v0: organizer/Profile FK, platform, destination identifier, per-destination credentials, `enabled` flag, supported `kinds`. It is both the organizer's syndication-targets setting and the per-organizer adapter credential store the adapter beads consume.
- The authoring + review web UX (kb-a4u.3 / kb-a4u.5) is an Event-page-as-hub composition of independently-addressable HTMX-swappable fragments (event facts, posts, syndication board), domain-named so a later reorg (e.g. a Posts tab) is a route+nav change, not a re-plumb. The projection-review board is a panel on the Event page, not a separate destination. (UX/IA detail lives in those beads' `--design`, not this ADR.)
- The v0 impl exposes an HTTP API at the perimeter Web UI consumes — same endpoints, same auth, no private fast-path. `agents/register` and `verify-identity` endpoints land in v0.
- `switch-berlin/skill.md` is **not** a v0 deliverable; it gets extracted from dogfooding once the API has shaken out (Tier-2). Until then, the API itself is the contract; OpenAPI/JSON-schema docs at the API endpoints suffice.
- The Switch facilitator agent (planned in ADR-011 D1, dogfooded by the project owner first) interacts with Switch exclusively through this API contract — no direct DB access, no internal-only RPCs, no agent-special-casing in the codebase.
- Per ADR-003 cheap foresight, the schema reserves shape (not behavior) for: multi-Post-per-Event campaign sequencing, full ticket type taxonomy, buyer/attendee screening questions, recurrence pattern. These are reservation-only at v0 — the behavioral epics that consume them ship later (RSVP+screening epic, campaign-sequence epic, recurring-events epic).
- Per-platform content-policy filtering is owned by kb-o0j cleaning-policy substrate; D2 here only canonicalizes the **projection entity** that the cleaning rules operate on. ADR-016 does not encode policy rules.

### Carried forward

- **ADR-011 D1 FLEXIBLE — agent layer additive.** D3 here is the API contract realization of ADR-011 D1's "agent-extended scope" framing. ADR-011 stays at the layer-boundary level; ADR-016 D3 carries the wire-level contract.
- **ADR-010 D1 FLEXIBLE — real-world action over engagement.** D1 here separates Event (real-world action) from Post (communication about the action). The Post entity exists explicitly to drive real-world Events, not to optimize engagement-on-Posts as a metric.
- **ADR-012 FLEXIBLE — visibility tiers (REVISED 2026-05-26: visibility does NOT gate syndication).** `Event.visibility` governs how the event appears *on switch.berlin* (read-side `visible_to`, ADR-012) — it does **not** gate outbound syndication. A facilitator may syndicate their own event to any connected destination regardless of its Switch visibility tier; the platform does not restrict where a facilitator posts (ADR-010/011 facilitator-empowerment posture). This is safe because publish is always an explicit facilitator/agent action (D5) — nothing auto-publishes, so there is no auto-leak a tier-gate would need to prevent. Eager projection creation (D4) is therefore uniform across all visibility tiers. The prior assumption (unlisted → no projections; semi_public → matrix-compatible platforms only) is superseded. Switch's own-event-page listing remains governed by the normal read-side `visible_to` rendering, unchanged — that is not a syndication gate.
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
- [ADR-008 D2, D3, D4](ADR-008-code-posture-refactor-hard-fail-loud.md) — D2: no speculative abstraction (v0 projection plumbing covers exactly the four target platforms; abstraction shape emerges from the second platform within each kind; D4's connection-over-string and D5's lifecycle shape for stated requirements, not speculation). D3: fail-loud on data integrity — the "missing X" draft state (D5) is the visible-error realization, no silent zero-fill. D4 (retry): governs failed-push in D5 — transport→2 retries→failed, data/4xx/5xx→no retry.
- [ADR-010 D1](ADR-010-event-based-product-posture.md) — real-world action drives the existence of both Event (the action) and Post (announcement of the action); business model cannot monetize engagement-on-Posts.
- [ADR-011 D1, D2](ADR-011-personal-agent-layer-additive.md) — agent layer additive; agent-extended scope already names per-target syndication + promo-post drafting; ADR-016 D3 canonicalizes the API contract within that framing.
- [ADR-012](ADR-012-event-visibility-tiers.md) — visibility tiers govern read-side rendering on switch.berlin (`visible_to`); they do NOT gate outbound syndication (revised 2026-05-26 — facilitator controls outbound via explicit publish).
- [ADR-015 D1](ADR-015-payment-processor-strategy-for-explicit-event-ticketing.md) — V0/V1 ticketing rides on Ticket Tailor; ADR-016 D2's TT-listing projection inherits ADR-015's Mode A coordination-layer posture.
- `kb-2ve` (closed Phase A, 2026-05-20) — parent brainstorm that originally named the two syndication flows in D2 (event publishing AND event promotion posts).
- `kb-o0j` (open) — Switch facilitator cleaning policy; owns per-platform content-policy substrate that D2's projections invoke during generation. ADR-016 does not encode policy rules; kb-o0j does.
- `kb-dko` (closing at convergence of this brainstorm) — brainstorm bead that converged this ADR; closed via close-and-spawn into a v0 impl bead.
- `https://www.moltbook.com/skill.md` — external reference for the agent-platform contract pattern (Bearer API key → identity token → verify-identity endpoint).

## Open questions deferred

| Question | Resolution path |
|---|---|
| When does `switch-berlin/skill.md` get extracted from dogfooding? | Defer to post-v0; trigger is "dogfooding has surfaced enough friction patterns that a markdown spec for external agents adds more value than the API + OpenAPI docs alone." Likely Tier-2 deliverable in v0.5. |
| ~~What's the projection-publication trust model for manual-assisted platforms (FetLife)?~~ | **Resolved by D5 (2026-05-26):** actor-attested via a shared `mark-published` API verb. The actor (human copy-paste or agent browser-automation+verify) does the out-of-band push, then attests; an agent is a better attestor because it can verify. |
| ~~How do projection-edit-conflicts resolve when canonical changes after projection was edited?~~ | **Resolved by D2 refinement (2026-05-26):** non-overridden fields track the live canonical automatically (no stale stored copy); only overridden fields hold until reviewed. Edit + re-publish of an already-published projection remains deferred (adapter-specific). |
| Does the bundled-agent posture (deferred at v0) get a separate ADR when revisited, or does it land as an evolution of ADR-016 D3? | Defer; working assumption: in-place evolution of D3 (firmness shift + explicit bundled-agent decision), not a new ADR. Per ADR-011 D1 in-place mutation discipline. |
| What happens to `kb-o0j` cleaning-policy substrate if the listing-vs-promotion shape distinction collapses (D2 invalidation)? | Defer to that observation if it lands; kb-o0j's per-platform rules likely still apply but the "rules per kind" framing may collapse. |
