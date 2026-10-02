# ADR-004: HTMX+Alpine as default for `/events` map surface, React island as tripwire escape hatch

**Status:** Accepted — spike graduated 2026-04-20; D4 applied (HTMX code is Phase 0.4 map surface) (revised 2026-10-02 — D1 fetch/filter split, D2 FIRM → FLEXIBLE, T1 dropped)
**Date:** 2026-04-20
**Design:** [Phase 0.4 HTMX map spike](../plans/2026-04-20-phase-0.4-htmx-map-spike-design.md)
**Parent:** [ADR-001 D5](ADR-001-core-product-and-stack.md), [ADR-002 D3](ADR-002-phased-rollout-and-legal-gate.md)
**Related:** [Phase 0.4 design](../plans/2026-04-17-phase-0.4-map-invite-design.md)

## Context

ADR-001 D5 committed to a single React island at `/events` via `django-vite`. ADR-002 D3 then softened that: the island decision was deferred to end of phase 0.3, to be made on evidence rather than speculation. Phase 0.3 shipped `/events` as HTMX + Alpine + Cotton components on 2026-04-19. This ADR records the outcome of that gate.

The decision had to balance four forces:

1. **Single mental model** is strictly better for a solo maintainer. Two runtimes (HTMX server-partial + React island) is a real tax even if each is small.
2. **The map surface is the only genuine complexity hotspot** in the 0.4–1.0 roadmap. Every other planned interaction (attend, follow, flag, reviews, invite signup, organizer self-edit, feature flags) is server-rendered forms or trivial toggles. No real-time, no offline, no messaging.
3. **HTMX+Alpine has a known ceiling for maps.** Research surfaced a working pattern — `hx-preserve` on a stable map container + map instance pinned in `Alpine.store('map', …)` + custom events for cross-panel selection — at a realistic cost of 80–150 LOC of glue. alpine-morph is buggy and should be avoided. deck.gl *reverse-controlled* mode is the one meaningful plugin that is genuinely harder in vanilla MapLibre than in `react-map-gl`; no such feature is on the 0.4–1.0 roadmap.
4. **Dogfooding for a week with 5 staff accounts is theater** at the current data density (~dozens of events, one organizer-peer, no invite cohort yet). Evidence will come from building, not browsing.

Two evaluation protocols were considered: a parallel bakeoff (HTMX spike vs React-island spike, same acceptance criteria, compare) and a default + tripwire escalation (build the boring default, define explicit stop conditions, spike the alternative only if tripped). The bakeoff guarantees fair comparison but costs ~5 solo-dev days and is contaminated by author bias (the second spike is always built with more context). The escalation pattern costs 3 days best case, 5 worst case, and produces most of Phase 0.4 as a side effect when the default holds.

## Decisions

### D1: HTMX + Alpine + vanilla MapLibre is the default path for `/events`

**Firmness: FLEXIBLE** — held by evidence from the spike; revisitable if tripwires fire.

Phase 0.4's map surface is built HTMX-first: vanilla MapLibre instance pinned via `hx-preserve`, the server bounding each fetch (visibility, dates, padded map area, whole-day date chunks served as rendered cards) while cheap filters show/hide those server-rendered cards in the browser (revised 2026-10-02, sb-x5xh.8), cross-panel selection bridged by custom DOM events against a single `Alpine.store('map', …)`. The React island scaffold (`frontend/src/events/EventsIsland.tsx`, `django-vite`, Vite config) stays in the repo as dormant code — wiring it in later is a local refactor; deleting the capability is wasteful (ADR-002 D3).

**Rationale:**

Under the 0.4–1.0 roadmap, shipping a React island would add a second mental model for exactly one surface while every other feature is already server-rendered. Published case studies of full HTMX migrations (Contexte 21.5k→7.2k LOC, two-month timeline; Quantum Tricks admin 3,200→890 LOC, 847KB→14KB bundle) are dominated by the simplicity win, with no counter-case specifically about MapLibre forcing React. For the planned map scope (markers, clustering, privacy circles, drawer, list↔map highlight, URL sync), the plugin ecosystem is symmetric between vanilla and `react-map-gl`.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **HTMX+Alpine default, React island as tripwire (chosen)** | Single mental model; cheapest path to shipping Phase 0.4; evidence-driven | HTMX ceiling is real — if we hit it mid-phase, cost is the escape hatch |
| Commit to React island unconditionally (ADR-001 D5 as originally written) | Highest ceiling; familiar React+TS stack; best agent support | Pays complexity tax on a surface that probably doesn't need it |
| Parallel bakeoff (HTMX spike + React-island spike, compare) | Best-quality decision | ~5 solo-dev days burned; author bias contaminates the second build; 3 of those days replaced by actual progress under escalation |
| Cut the island permanently from the roadmap | Simplest possible stack; zero `django-vite` surface | Closes the door on deck.gl reverse-control / Cesium globe if we ever want them post-1.0 |

**What would invalidate this:**

Any D2 tripwire firing during the Phase 0.4 spike. Or, post-1.0, a feature requiring deck.gl reverse-controlled mode, heavy client-side constraint solving, real-time collaborative editing, or offline-first — none of which are on the current roadmap.

---

### D2: Tripwires — stop conditions that flip the decision to React island

**Firmness: FLEXIBLE** *(was FIRM until 2026-10-02 — the human ruled live in sb-x5xh.8 that a line count is a poor decision signal; T1 dropped, judgment trigger added)*

While building the map surface, if **any** of the following fires, stop the HTMX path and run the React-island spike (see D3):

| # | Tripwire | Measurement |
|---|---|---|
| T2 | Any single state-sync bug takes **>2 hours** to diagnose | Time each bug with a timer; one over-budget bug trips |
| T3 | `hx-preserve` + `Alpine.store` pattern **fails on browser back/forward navigation** (map state lost, stale markers, double-init) | Manual QA checklist |
| T4 | The glue needs to be duplicated in **≥3 unrelated templates** | Count on the diff |
| T5 | A scope item requires **`setTimeout`, manual DOM hand-syncing, or monkey-patching MapLibre internals** to work. Alpine-declarative show/hide (`x-show`) of server-rendered cards is not hand-syncing. | Self-review against the diff before claiming done |
| J | The approach becomes **unwieldy or performs poorly**, noticed while building | Judgment; name the symptom when raising it |

**T1 (300 LOC of glue) was dropped 2026-10-02 after it had already fired:** the events JS measured 334 LOC (`map.js` 283 + `store.js` 25 + `bridge.js` 26) when the human ruled it out. The drop is not cosmetic: line count is no longer a trigger.

**Rationale:**

The risk of an "HTMX default" decision is that it turns into "HTMX forever" through sunk cost. The objective tripwires T2–T5 each describe a specific failure mode (back/forward state loss, hand-syncing, glue duplication, long state bugs) and stay. Line count was the one tripwire measuring size rather than a failure: the surface grew by legitimate scope (filters, clustering, privacy circles) and crossed 300 without any of the failure modes showing.

**Counter-argument to the original FIRM rationale (2026-10-02):** the original held that softening tripwires defeats the design. That holds for the failure-mode tripwires, which stay. It does not hold for T1: a size proxy that fires on healthy growth teaches people to ignore tripwires, which is the sunk-cost path this decision exists to block. Adding judgment trigger J reintroduces the subjective gate rejected below; the human accepts that risk knowingly, with T2–T5 as the objective backstop.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Failure-mode tripwires + judgment trigger (chosen 2026-10-02)** | Fires on real failure, not size; reproducible for T2–T5 | J is easy to rationalize past — `reasoned:` mitigated by the objective T2–T5 |
| Objective tripwires incl. T1 300 LOC (chosen 2026-04-20) | Fully measurable | `direct:` T1 fired at 334 LOC on healthy growth with no failure mode present; human ruled 2026-10-02 (sb-x5xh.8) line count a poor signal |
| Subjective "felt tangled" gate only | Matches how people actually evaluate code | `reasoned:` too easy to rationalize past; relitigated every week |
| No tripwires, just ship whatever HTMX can do | Minimum ceremony | `reasoned:` unbounded hairball risk |

**What would invalidate this:**

A failure mode shows up that none of T2–T5 caught (for example a hairball no single bug or template count reveals), or J is invoked and argued away more than once while the code visibly degrades. Either way: restore an objective size or complexity measure that tracks failure rather than growth.

---

### D3: Escape hatch — map container is designed as a swappable surface

**Firmness: FIRM** — the whole point of the default + tripwire structure is to keep the swap cheap.

The HTMX path is built so that replacing the map container with a React island later is a **local refactor**, not a rewrite:

- The map lives in a single `<div id="map" hx-preserve="true">` with no HTMX children.
- All cross-panel state flows through one `Alpine.store('map', …)` — hovered event, filter bounds, zoom.
- All cross-component communication uses **custom DOM events on `window`** (`events:filter-changed`, `events:bounds-changed`, `events:hover-changed`) — not direct function calls, not shared closures.
- The map module exposes `init(container, store) → { destroy() }` and reads/writes the store only through published events.

To swap in a React island post-hoc: mount the island at the same `#map` element, subscribe it to the same window events, dispatch the same events back. The filter chips and list require zero changes.

**Rationale:**

ADR-001 D5 exists specifically to preserve the option of a React island at `/events`. Keeping `django-vite` wired but dormant costs nothing; designing the HTMX map with an escape hatch costs ~30 LOC of event-bus discipline. Together they mean the decision is reversible at any phase, at bounded cost.

**What would invalidate this:**

If the discipline itself becomes more than ~50 LOC or starts to contort the HTMX path (e.g., having to dispatch events for things HTMX would handle natively), reconsider — the escape hatch shouldn't be the main driver of the architecture.

---

### D4: Spike deliverable doubles as Phase 0.4 implementation when tripwires don't fire

**Firmness: FLEXIBLE**

If the HTMX spike completes without tripping T1–T5, its code graduates directly into Phase 0.4 — it is not thrown away and rewritten. The spike's acceptance criteria (see Phase 0.4 HTMX spike design doc) are a subset of Phase 0.4's scope; passing the spike means that subset is already shipped.

If a tripwire fires, the HTMX spike is **discarded**, the React-island spike runs against the same acceptance criteria, and its code graduates into Phase 0.4.

**Rationale:**

Solo-dev weekends are scarce. Treating the spike as throwaway only makes sense when the spike's quality bar is below shipping quality; in this case the tripwires *are* the quality bar, so passing them means shipping quality is already met. Conversely, if tripwires fire, the HTMX code is evidence of the failure mode — keeping it adds confusion.

**What would invalidate this:**

If mid-spike the scope drifts below shipping quality (skipped tests, no privacy enforcement, no CSRF), discard on completion regardless of tripwire outcome and rebuild clean.

## Consequences

**Easier:**
- Phase 0.4 starts immediately without a week of dogfooding that wouldn't produce signal anyway.
- The default is the simplest-stack path; shipping it is also shipping the mental-model win.
- Decision is reversible at bounded cost via D3.
- ADR-001 D5 is now concretely interpretable: "island preserved as optionality, not committed as implementation."
- ADR-002 D3 is resolved — the pending decision gate is closed.

**Harder:**
- Tripwire discipline requires actually measuring (T2 timer, T3 checklist) rather than vibing. Easy to skip.
- Event-bus discipline for D3's escape hatch adds ~30 LOC that wouldn't exist in a pure-HTMX-forever build.
- If tripwires fire mid-phase, Phase 0.4 slips by ~2 days for the React-island spike.

**Tradeoffs:**
- Accepts the risk of a late-stage discovery (e.g., at phase 0.6 signals or 1.0 bubble-bridging UI) that forces a retroactive island adoption. Mitigation: D3's escape hatch keeps the cost bounded; roadmap research shows no such forcing feature before 1.0.
- Accepts ~1000× training-data asymmetry between React and HTMX in LLM corpora. Mitigation: CLAUDE.md already constrains agents to hypermedia-first; the project's existing HTMX surface is reference material.
