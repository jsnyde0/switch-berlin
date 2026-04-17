# ADR-001: Core product shape and technical stack

**Status:** Accepted (pending soft-launch)
**Date:** 2026-04-17
**Design:** [V0 design doc](../plans/2026-04-17-v0-design.md)
**Parent:** —
**Related:** `docs/project_brief.md` (partially superseded), `docs/hipsy_analysis.md` (precedent study)

## Context

Two prior repos (`event-gulper` — a Prefect/FastAPI/SQLAlchemy pipeline that shipped one working source; `just-show-up` — a Django 5 + HTMX + Tailwind scaffold with a parallel CrewAI/controlflow scraper) diverged in tech stack and died before shipping. A brainstorm in April 2026 converged on a sharper product wedge — curated queer/conscious-leaning kinky events in Berlin, with a two-tier trust model — and a merge-not-rebuild path forward.

ControlFlow was archived in August 2025. CrewAI and Instructor are redundant with pydantic-ai. Prefect and Celery are overkill for V0 scale. The `/events` page's combined filter + map + URL-sync + persisted-prefs UX sits at the edge of what HTMX handles cleanly. These realities shape the decisions below.

This ADR records the load-bearing decisions so future work doesn't re-litigate them. Open/deferred decisions live in the companion design doc's *Open Questions*.

## Decisions

### D1: Product framing — curated-trust, community-surfaced

**Firmness: FIRM**

The product is a curated guide to queer- and consciousness-leaning kinky events in Berlin, with a two-tier trust model: admin-gated organizer approval, community-gated event attention.

**Rationale:**

The Berlin kink scene is fragmented into many sub-bubbles. Newcomers don't know who to trust; locals miss adjacent scenes. A generic listings site is strictly worse than Telegram (Telegram already has the events). A values-filtered curator with a trusted community layer is a product Telegram can't be.

This framing also matches the user's stated preference to stay hands-off on event-level curation: admins gate organizers (bounded work), the community surfaces events (scales past one person's time).

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Curated-trust, community-surfaced (chosen)** | Differentiated from Telegram; niche-aligned; bounded editor workload | Requires building both trust layers at once |
| Generic Berlin kink listings aggregator | Simpler scope | Loses queer/conscious wedge; competes with Telegram on its own terms and loses |
| Manual editorial magazine (editor picks weekly) | Strong editorial voice | Burns out one person; doesn't scale past their time |
| Open marketplace (any organizer self-serves) | Fast cold-start | No trust layer; spam target; no editorial angle |
| Broad sex-positive (tantra, ecstatic dance included) | Larger addressable market | Dilutes niche; too close to Hipsy |

**What would invalidate this:**

If approved organizers won't submit (cold-start failure >4 weeks), OR if the queer/conscious filter proves too niche to reach ~200 WAU within 6 months, revisit scope.

---

### D2: Audience — Berlin insiders first, newcomers second

**Firmness: FIRM (12 months)**

Primary audience is Berliners already in some kink bubble who want to find events they'd otherwise miss. Secondary is curious outsiders/newcomers. Berlin-only for 12 months.

**Rationale:**

Niche is easier to penetrate than broad. Berlin has enough density to support a niche product. Hardcoding TZ, locale, and geo bounds simplifies every subsystem.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Berlin-only, insiders-first (chosen)** | Tight scope; hardcode TZ/locale; matches where users are | Limits growth ceiling before V1 |
| Multi-city from V0 | Larger TAM | Every subsystem needs abstraction; no local curator pipeline |
| Newcomers-first | Clearer onboarding story | Fights uphill — newcomers don't have the context to evaluate the product |

**What would invalidate this:**

Strong pull from adjacent cities (Hamburg, Amsterdam) with ≥3 volunteer curators offering to run those locales.

---

### D3: No manual event-level curation

**Firmness: FIRM**

Editor vets organizers; community signals (attend, interested, like, review) surface which events matter. Editor doesn't touch individual events beyond the admin-review step that approves the auto-extracted draft.

**Rationale:**

User explicitly stated "I want to be as hands-off as possible." Community-driven surfacing scales past one person's time. Organizer gating is the trust layer; community signals are the attention layer. The two layers compose cleanly.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Community signals only (chosen)** | Scales; bounded editor workload; hands-off matches user preference | Requires user accounts V0 |
| Editor's-pick cards on homepage | Strong voice | Weekly curation burden; user vetoed |
| Weekly editor's note | Narrative connective tissue | Same burnout risk |
| Editor per-organizer curator notes | Nice-to-have voice | Drops in favor of "verified" as the signal |
| No community signals, pure chronological | Zero moderation load | Removes the feature that makes return visits valuable |

**What would invalidate this:**

If community signal noise floor is too high (approved-user base doesn't scale), revisit. Hide signals below thresholds as a first mitigation.

---

### D4: User accounts are V0-load-bearing

**Firmness: FIRM (given D3)**

User accounts (anonymous browse + approved-user interaction) ship in V0, not V1. Signup is invite-only at launch, admin-reviewed form after.

**Rationale:**

D3 makes community signals the primary event-surfacing mechanism. Without accounts, no signals. Approval gating prevents low-quality signals and brigading.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Invite-only + admin-approved accounts in V0 (chosen)** | Signal quality; anti-brigade; tight community | Cold-start friction |
| Email-verified-only | Lower friction | Weaker quality floor; no gate on community identity |
| No accounts, defer signals to V1 | Ship V0 faster | Contradicts D3 — would need editorial curation or pure chronological |

**What would invalidate this:**

If approval rate is a bottleneck, loosen to email-verified-only.

---

### D5: Single `/events` surface with filter + view modes; React island for interactivity

**Firmness: FIRM on island-vs-HTMX split; FLEXIBLE on default filter state**

No separate homepage. `/events` is both landing and primary surface. Filters (date, tags, organizer, price) + view modes (list, map). User preferences persist (session for anon, `User.prefs` for authenticated). Default: list, sorted by date, today → +14 days.

`/events` is implemented as a **React 19 + TypeScript island** (raw `maplibre-gl` + `nuqs` for URL-synced filter state) mounted in a Django template via `django-vite`. All other pages stay server-rendered Django + HTMX. Initial state passes via `{{ ... |json_script }}`; the island talks to `/api/events?…` with session cookies + CSRF header — no JWT, no CORS, no Inertia. Tailwind v4 + DaisyUI share a single `app.css` across Django templates and the React island.

**Rationale:**

One surface avoids maintaining multiple homepage variants; trivial to change default sort based on usage data.

Research in April 2026 confirmed that the filter + MapLibre + URL-sync + persisted-prefs combo sits at the edge of HTMX's sweet spot — solvable with Alpine + Idiomorph + `hx-preserve`, but the cumulative glue cost approaches the cost of a contained React island. `django-vite` is the canonical 2026 single-island integration pattern: mechanical, one-time setup (weekend + one Vite config), Node at build time only. Isolating React to this one page keeps the rest of the site simple.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Single `/events` + React island via django-vite (chosen)** | Rich client state where needed; Django admin intact; one deploy | Two frontend mental models |
| Distinct homepage + feed page | Classic structure | Duplicates templates and queries for no user benefit at V0 density |
| Organizer-directory-first landing | Foregrounds trust | Directories feel static; harder to drive return visits |
| Map-led landing | Visually appealing | At V0 event density, map looks empty |
| Pure HTMX + Alpine + Idiomorph everywhere | One mental model; one toolchain | Map-viewport + filter + URL-sync glue grows unbounded; known edge-of-sweet-spot |
| Full React SPA / Next.js | Modern UX throughout | Loses Django admin (load-bearing for D1 trust model); 2–3× slower to V0 |
| Inertia.js with Django adapter | SPA feel without API split | Forces every page through its pipeline; documented CSRF/409 quirks; overkill for one island |

**What would invalidate this:**

If the React island grows tendrils into other pages (filter state needed on organizer profiles, shared component boundaries expand), rethink the SPA boundary at V1. If HTMX+Alpine proves painful on non-island pages, evaluate Datastar.

**Map privacy:** AirBnB-style neighborhood circles for events with private venues (`privacy_mode=neighborhood_blur` or `private`).

---

### D6: Stack — Django 5 monolith; drop Celery/Prefect/SQLAlchemy/instructor/controlflow/CrewAI

**Firmness: FIRM on Django, Django-Q 2, pydantic-ai, Postgres+pgvector, django-vite. FLEXIBLE on PostGIS (lat/lng may suffice V0), map provider, hosting. EXPLORATORY on HTMX vs Datastar for non-island pages.**

Django 5 + HTMX + django-cotton + Tailwind v4 + DaisyUI + **Django-Q 2** + Postgres (pgvector) + pydantic-ai + python-telegram-bot + httpx/bs4/markdownify + Logfire + allauth — **plus one React 19 + TypeScript island on `/events`** via `django-vite` (see D5).

**Rationale:**

- **Django over FastAPI+SPA split**: admin is the review UX (load-bearing for D1); single deploy; allauth handles auth; `just-show-up` scaffold already has it.
- **Django-Q 2 over Celery**: drops Redis entirely; Postgres is already there; simpler ops; sufficient for V0 scale.
- **pydantic-ai over instructor**: instructor is a subset of pydantic-ai's functionality; no reason to carry both.
- **Drop controlflow**: archived August 2025.
- **Drop CrewAI**: third redundant agent framework.
- **Drop SQLAlchemy + asyncpg + FastAPI from event-gulper**: Django ORM is canonical, one DB access path.
- **Drop Prefect**: Django-Q covers scheduled-task use cases; Prefect server is an additional container not needed.
- **React island, not full SPA, not Inertia**: see D5.
- **DaisyUI inside the island too**: shadcn/ui collides with DaisyUI on CSS variables; one component library across both surfaces.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Django monolith + HTMX + one React island (chosen)** | Batteries-included; admin for free; bounded React surface | Two frontend mental models |
| Django + DRF API + Next.js frontend | Modern SPA throughout | Two apps, two deploys, CORS+auth handoff, build own admin (1–2 weeks lost) |
| Fullstack TS (SvelteKit / Next.js fullstack) | One language, modern UX | Rewrites the only salvageable Python code (scrape + pydantic-ai); build admin from scratch |
| Supabase + Next.js + Python worker | Auth/RLS/realtime free | Admin still to build; Supabase lock-in; Python worker still needed |

**What would invalidate this:**

- Django-Q scaling ceiling (unlikely at V0/V1 volume): migrate to Celery on Postgres broker.
- pydantic-ai replaced by something materially better: re-evaluate at V1.
- The `/events` island grows tendrils into other pages: rethink the SPA boundary.

---

### D7: Merge from `just-show-up` scaffold, port 3 files from `event-gulper`

**Firmness: FIRM**

New work happens on a `rebuild/v0` branch of **just-show-up** (renamed). Three files port over from `event-gulper`: `transforms/scrape.py`, `transforms/llm.py`, `sources/siegessaeule.py` (archival). Both old repos get deprecated; `event-gulper` gets deleted once rebuild is stable.

**Rationale:**

`just-show-up` has ~2 weeks of scaffold (CI, Docker, allauth, cotton, HTMX, Tailwind) not worth re-deriving. `event-gulper`'s non-trivial asset is the scrape+markdownify+LLM primitive — ~3 files stripped of Prefect decorators. Everything else in both repos is dead weight or duplication.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Merge from just-show-up, port 3 files (chosen)** | Keeps ~2 weeks of scaffold; keeps the one working pipeline | Requires disciplined purge of dead code |
| Rebuild from scratch | Zero baggage | Wastes 2 weeks of scaffold re-derivation |
| Keep both repos, compose via API | Preserves prior work | Doubles deploy complexity; two schemas; no clear API boundary justified |
| Start from event-gulper | Keeps pipeline native | Weaker frontend/UI scaffold; would build Tailwind/HTMX/auth from near-zero |

**What would invalidate this:**

Nothing short of discovering that `just-show-up`'s scaffold is materially broken or that the ported primitives don't survive the Prefect strip.

---

### D8: Data model — normalized schema from day 1

**Firmness: FIRM**

V0 ships the full normalized schema (Organizer, Venue, Tag M2M, Event with status enum, RawMessage, User+approval, Attendance, Review, Flag, Follow). No raw/normalized table split — `Event.status` handles the lifecycle (draft → review → published → rejected/cancelled).

**Rationale:**

Retrofitting normalization hurts; capturing it at ingest is cheap. The event-gulper schema's flat `EventDetailDB` with comma-joined tags and no organizer/venue entities is the first thing that'd have to change anyway. Doing it now avoids a V1 migration.

**Bubbles = Tags with `kind=bubble`**: cheap V0 representation; promote to first-class entity when the bridging UI ships.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Normalized schema day 1 (chosen)** | Aggregate queries trivial; no migration at V1 | Slightly more upfront modeling work |
| Flat single-table (event-gulper status quo) | Fastest to migrate today | Forces a painful V1 normalization; no organizer-aggregate queries |
| Raw + normalized table split | Clean separation of concerns | `Event.status` does the same work with one table |

**What would invalidate this:**

If the schema turns out to block fast iteration on unforeseen entities (e.g., `Series` for recurring events, `Ticket` for ticketing), add tables — the base normalization is sound regardless.

---

### D9: Ingestion — Telegram bot + URL enrichment + pydantic-ai + admin review

**Firmness: FIRM for V0. FLEXIBLE on adding Eventbrite/Siegessäule scrapers later.**

V0 ingestion is Telegram-only (bot forwards from approved organizers and from editor lurking in channels). URL enrichment uses httpx+markdownify. Extraction is pydantic-ai. All events land as `status=draft` and require admin approval before publishing.

**Rationale:**

Two-tier trust (D1) makes admin approval the gate, so the pipeline can be straightforward. URL enrichment is necessary because Telegram posts are teasers — real details live on linked pages.

**Deferrals** (explicit): OCR, roundup-post splitting, Fetlife/IG login-gated crawlers, Telethon user-session mode.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Telegram bot + URL enrichment + admin review (chosen)** | Aligns with D1 trust model; simple pipeline | Cold-start depends on organizer onboarding |
| Multi-source scrapers V0 (Eventbrite + Siegessäule + Telegram) | Faster cold-start content | Every source is a maintenance surface; most events already hit Telegram |
| Telethon user-session scraping | Broader Telegram access | ToS risk; no organizer consent recorded |
| No URL enrichment (Telegram text only) | Simpler | Events under-described; admin review becomes unreasonably heavy |

**What would invalidate this:**

If approved organizers don't materialize, Siegessäule/Eventbrite scraping returns as a cold-start mechanism (not the V0 default).

---

### D10: Legal compliance is critical path for public launch

**Firmness: FIRM**

Before any public URL goes live: JuSchG age gate on first load; DSA takedown flow; GDPR lawful-basis (consent) recorded per organizer + opt-out endpoint; Terms, Privacy, Imprint pages; Telegram bot consent text on first interaction.

**Rationale:**

Explicit/adult content in Germany has real regulatory obligations. Skipping these creates both legal risk and trust-destroying UX retrofits later.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Full legal checklist before public launch (chosen)** | Regulatory compliance; trust; no retrofit | Delays public launch |
| Invite-only / unlisted launch, defer legal | Ship private beta faster | Can't go public without doing this work anyway |
| Skip age gate, argue "mostly non-explicit" | Faster | Doesn't survive first flag in Germany |

**What would invalidate this:**

Nothing short of the site remaining invite-only/unlisted forever.

## Related

- [V0 design doc](../plans/2026-04-17-v0-design.md) — implementation details and open questions
- [`docs/project_brief.md`](../project_brief.md) — original brief, partially superseded (audience kept, firehose architecture deprecated)
- [`docs/hipsy_analysis.md`](../hipsy_analysis.md) — precedent study that informed the two-tier trust model
