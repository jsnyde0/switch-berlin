# ADR-008: Code posture — refactor hard, fail loud

**Status:** Accepted
**Date:** 2026-05-18
**Design:** —
**Parent:** [ADR-001](ADR-001-core-product-and-stack.md)
**Related:** [ADR-002](ADR-002-phased-rollout-and-legal-gate.md), [ADR-003](ADR-003-cheap-foresight-patterns.md)

## Context

V0 is pre-launch. No public users, no external integrations to preserve, no backward-compat surface to hold. The two prior repos (`event-gulper`, `just-show-up`) accumulated half-finished abstractions, optional fallbacks, and "just in case" code paths that made the merge harder than it should have been. This ADR records the code-quality posture that prevents the same accumulation from happening on `rebuild/v0` and through V0.

Two adjacent principles live elsewhere and are deliberately not duplicated here: [ADR-003](ADR-003-cheap-foresight-patterns.md) covers the *additive* side (zero-cost shape now so phase N+2 is additive); [ADR-002](ADR-002-phased-rollout-and-legal-gate.md) covers *when* invasive change is in scope. This ADR covers *how* code should be written and changed within those bounds.

The principles below were lifted and adapted from the mapular-platform repo (`CLAUDE.md` "MVP Mindset" + `ADR-001` "Fail-loud"), which encodes the same posture for a sibling pre-launch codebase.

## Decisions

### D1: Refactor hard, no backward compatibility

**Firmness: FIRM until V1 (public soft-launch)**

While V0 is pre-launch with no external users or integrations, refactor aggressively. Delete dead code on sight. No deprecation paths, no `_compat` shims, no renamed-but-kept duplicates, no migration helpers for code paths only the developer used.

**Rationale:**

Backward compatibility is a tax paid to users. There are no public users yet. Every shim is a future obstacle for no current benefit. The merge from `just-show-up` + `event-gulper` was harder than it should have been precisely because both repos had accumulated optional abstractions; the lesson is not to accumulate the next round.

**Concrete applications:**

- When renaming a field / model / view, edit every call site in one commit. Don't keep the old name around with a forwarding shim.
- When dropping a feature mid-build, delete the code. Don't comment it out, don't move it to `archive/`, don't gate it behind a flag.
- When a migration becomes painful, `migrate zero` + recreate is on the table **(pre-launch only)**.
- Database migrations may be squashed or dropped while no production data exists. Once V1 lands, the 2026-05-12 data loss incident (`docs/incident-2026-05-12-data-loss-restore-plan.md`) is the binding precedent and this no longer applies.

**What would invalidate this:**

V1 public soft-launch (per [ADR-002](ADR-002-phased-rollout-and-legal-gate.md)). Once real users have real accounts and bookmarkable URLs exist, backward compatibility re-enters scope and this decision flips to FLEXIBLE — at which point each breaking change is justified case-by-case rather than assumed.

---

### D2: No over-engineering, no speculative abstraction

**Firmness: FIRM**

Skip feature flags, migration paths, plugin systems, abstract base classes, and "just in case" generality. The simplest thing that works, one clear path, not multiple options. If two implementations diverge at the third call site, *then* extract — not before.

**Rationale:**

Premature abstraction is the most expensive form of over-engineering on a solo project: every layer of generality is a layer the author later has to maintain, navigate, and reverse-engineer. YAGNI is load-bearing at V0 density.

This sits in tension with [ADR-003](ADR-003-cheap-foresight-patterns.md) (cheap foresight), and the tension is intentional: cheap foresight is for *data shape and naming* where the cost is ≤1 hour and the optionality is real; D2 forbids speculative *behavioral* abstraction where the cost is open-ended and the optionality is hypothetical.

**Concrete applications:**

- No feature flags. If a feature isn't ready, don't merge it.
- No `Strategy` / `Provider` / `BaseAdapter` abstractions until there are 2+ real strategies/providers in the codebase.
- No optional kwargs that nothing currently passes.
- No defensive `try/except` around code that can't realistically fail (cf. D3).
- Code comments explaining *what* the code does are an abstraction tax — see global `CLAUDE.md` rules on commenting only when WHY is non-obvious.

**What would invalidate this:**

A second concrete consumer materializing (e.g., a second event-ingestion source genuinely diverging from Telegram). Extract from observed need, not anticipated need.

---

### D3: Fail loud on data integrity

**Firmness: FIRM** (clarified 2026-05-22 — write/migration-time silent defaults are silent fallbacks too; see "Write-time symmetry" below)

Missing or invalid data raises immediately. No silent fallbacks, no zero-fills, no defaults-that-mask-bugs, no `except Exception: pass` swallows. Errors render as visible neutral state in the UI, not interpolated values.

**Write-time symmetry (added 2026-05-22):** D3 covers silent defaults at *write* and *migration* time, not just at *read* time. If a write-time default would hide a data state that D3 would have raised on read, the default is a silent fallback and is banned. Two shapes surfaced in V0:

1. **Data migrations choosing a default for rows with no source signal.** A pessimistic default that hides previously-visible data is a labeling lie in the opposite direction — symmetric to the read-time case D3 names. See ADR-012 D4 for the operationalization in the visibility-tier migration surface; the same principle binds future migrations introducing any access-gating field.
2. **Compat properties over many-to-many through-tables returning `None` when the M2M has rows but no row matches the discriminator (`is_primary=True`, etc.).** That state is data corruption, not "no value." The property must raise; templates that render `obj.compat_prop.attr` must not silently fall through to empty-string via Django's variable-resolution swallow.

Both shapes look benign at the write site and explode at the read site — kb-cm5 (2026-05-22) hit both in one session (events.0013 migration backfill + `Event.organizer` compat property). The clarification preserves D3's intent: data integrity is checked where the lie is *introduced*, not only where it surfaces.

**Rationale:**

Silent fallbacks turn data-integrity bugs into UX bugs that look like product decisions. The fail-loud principle (adapted from mapular-platform ADR-001) makes the cost of a data bug a visible error during development and a logged exception in production — both of which are debuggable. The cost of a silent fallback is a confused user and a phantom bug report six weeks later.

**Concrete applications by surface:**

- **pydantic-ai extraction:** if the LLM returns malformed output, raise (`EventExtractionError`). Do not return a partially-populated `Event` with `title="Unknown"`.
- **Telegram ingestion pipeline:** malformed message → log with explicit reason, persist as `RawMessage` with a rejection reason. Do not synthesize fields to make extraction "succeed".
- **Django services / views:** missing required field → 4xx. No silent default values for fields the schema requires.
- **Django admin review:** if a draft event has missing required fields, the admin form shows the error, never auto-fills.
- **React island (`/events`):** missing or null API field → visible error state ("data unavailable"), never zero/empty rendering that looks like a valid result.
- **No `?? 0` or `or {}` on values where 0 / empty is semantically different from absent.**

**Known intentional soft-failures** (allow-list; anything not here is a bug):

- *TODO:* audit V0 codebase and enumerate. Until then, the allow-list is empty by default. Likely future entries: transient HTTP error retries (per D4), Telegram bot rate-limit backoff.

**What would invalidate this:**

Nothing at V0 scale. If at V1+ a specific surface accumulates enough user-facing noise from fail-loud behavior that the editor is overwhelmed, add that surface to the allow-list above with a stated reason — do not change the default for other surfaces.

---

### D4: Retry transient transport errors, then fail loud

**Firmness: FIRM**

Network-layer / transport errors (DNS blips, connection resets, transient timeouts) get up to **2 retries with linear backoff** before raising. Data-integrity errors (HTTP 4xx/5xx responses, parse errors, schema mismatches, missing fields) never retry.

**Retry list** (transport, infrastructure):

- Python: `httpx.ConnectError`, `httpx.ReadTimeout`, `httpx.WriteTimeout`, `httpx.RemoteProtocolError`
- Browser: `TypeError: Failed to fetch`, `TypeError: Load failed`, `NetworkError`, `AbortError`

**Fail-loud-immediately list** (data integrity):

- HTTP 4xx / 5xx responses (the server spoke; the answer is bad)
- JSON parse errors, pydantic validation errors
- Missing-required-field exceptions
- Django ORM `DoesNotExist` / `MultipleObjectsReturned`

**Rationale:**

D3 targets *data integrity*. Transient transport errors are *infrastructure hiccups*, not data integrity issues — a DNS blip on one scrape doesn't mean the source is bad, it means the pipe broke momentarily. A bounded retry-then-fail-loud preserves D3's surface: after retries are exhausted, the error surfaces exactly as if there had been no retry layer.

Lifted from mapular-platform ADR-001 D5 (2026-03-20), where a production `TypeError: Failed to fetch` on a shared mapbook crashed all data loading because the codebase had no transport-error recovery layer.

**Concrete applications:**

- **Scrape pipeline (`transforms/scrape.py`):** 2-retry linear backoff for the retry list. Parse / extraction errors after a successful fetch never retry.
- **React island fetches to `/api/events`:** 2-retry on network failure, then surface as "Connection failed — retry" rather than silently empty list.
- **Telegram bot outbound:** library-default retry is sufficient; do not stack a third layer of silent retries.

**What would invalidate this:**

A specific surface where 2 retries is empirically wrong (e.g., a webhook receiver that does not idempotency-key, where retrying causes duplicates). Document the exception inline at that surface and reduce to 0 retries — do not raise the global cap.

## Related

- [ADR-001](ADR-001-core-product-and-stack.md) — product shape & stack (D6 defines the code surface this posture applies to)
- [ADR-002](ADR-002-phased-rollout-and-legal-gate.md) — phased rollout (defines when V1 arrives, at which point D1 flips to FLEXIBLE)
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight (the additive complement to D1/D2: shape *data* now, don't abstract *behavior* now)
- `docs/incident-2026-05-12-data-loss-restore-plan.md` — binding precedent on the destructive-migration boundary referenced in D1
- Upstream reference: `mapular-platform/CLAUDE.md` "MVP Mindset" (lines 206-212) and `mapular-platform/docs/decisions/ADR-001-fail-loud-pattern.md` — source material adapted for kinky-bubbles' Django + pydantic-ai + React-island stack
