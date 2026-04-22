# ADR-006: Legal gate execution — parameterize now, fill operator identity at deploy

**Status:** Accepted 2026-04-22
**Design:** [Legal gate bundle design](../plans/2026-04-22-legal-gate-bundle-design.md)
**Parent:** [ADR-002 D2 legal gate](ADR-002-phased-rollout-and-legal-gate.md), [ADR-005 Bundle B ops](ADR-005-bundle-post-0.5-execution.md)
**Scope:** all work needed to flip `PUBLIC_READ_ENABLED=True` under German/EU law (DDG §5, DSGVO/GDPR, DSA, JuSchG, TTDSG).

## Context

Phase 0.5 is code-complete but not public — the flip to `PUBLIC_READ_ENABLED=True` is gated on a legal-copy review. A structured review (2026-04-22) of `templates/pages/{impressum,privacy,terms}.html` and `templates/reviews/takedown.html` surfaced five P0 gaps (beads `kb-8qp`, `kb-nyr`, `kb-7hg`, `kb-804`, `kb-9hw`), of which two are not simple copy fixes but require a product decision:

1. **Attendance data on kink/queer events qualifies as GDPR Art. 9 "special category" data.** Clicking "attending" on a queer/kink event can reveal sexual orientation. Art. 6(1)(b) ("contract") is not a valid lawful basis for Art. 9; the current privacy policy uses it, which would fail a DPA audit.
2. **Organizer consent is recorded as implied (`method="telegram_forward_implied"`)** but the privacy policy describes it as "explicit consent at onboarding." Art. 7 GDPR requires a clear affirmative act for "consent"; forwarding a flyer to a bot is not. The claim as written is inaccurate and the basis as implemented is invalid.

A third decision concerns how to ship: the operator's identity (name, postal address, contact) is required content but is not a design question — it's data the operator supplies at deploy time.

## Decisions

### D1: Attendance uses explicit Art. 9(2)(a) consent, captured once per user

**Firmness: FIRM** — revisitable only if Berlin legal advice contradicts.

Users must tick an explicit consent checkbox before their first attendance/interested click is stored. The consent text names sexual orientation as a possible inference, names the specific processing, and can be withdrawn from `/me` at any time (withdrawal deletes all attendance rows). Until consent is given, attend/interested buttons render a modal that captures consent first.

**Rationale:** the alternative (drop per-user attendance, keep only aggregate counts) costs the `/me` page and personal history — features already built in Phase 0.4/Bundle A — for no legal gain the checkbox doesn't also deliver. A one-time consent is friction-light (shown once per user) and is the honest description of what the platform does.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Explicit checkbox + withdrawal (chosen)** | Keeps `/me` and signals; legally clean; user in control | One additional modal per user, one schema field, migration, withdrawal code path |
| Drop per-user attendance; aggregate only | Zero Art. 9 exposure; simpler privacy policy | Loses `/me`; loses "from organizers you follow" personalization; loses future review-authorship gate from Bundle A |
| Per-event consent | Maximally granular | UX hostile — every click becomes a two-step; abandonment spike likely |
| Tag-based consent (only for flagged-sensitive events) | Narrower consent scope | Requires classifying every event as sensitive/not; false-negatives = violations; all KB events are curated kink/queer-adjacent by editorial intent anyway |

**What would invalidate this:** if Berlin DPA (BlnBDI) guidance later treats invite-gated adult platforms as having built-in Art. 9(2)(e) "manifestly made public" status, the checkbox becomes unnecessary. Keep the field so withdrawal still works; stop gating new attends on it.

---

### D2: Organizer data processed under Art. 6(1)(f) legitimate interest, with documented LIA

**Firmness: FIRM** — revisitable only if an organizer objects with enough frequency to make opt-in friction cheaper.

Switch the organizer legal basis from "consent" to **legitimate interest (Art. 6(1)(f))**. Document a short balancing test (Legitimate Interests Assessment — LIA) in `docs/compliance/organizer-lia.md` covering: purpose (curated public listing of public events), necessity (no less-intrusive alternative since events are already public on Instagram/Telegram), balancing (organizers are semi-public figures; they can opt out via takedown endpoint at any time; no special-category data is processed about the organizer themselves). Update `Organizer.consent_method` vocabulary to include `legitimate_interest` and backfill existing `telegram_forward_implied` rows.

**Rationale:** organizer events are already public content (Telegram channels, Instagram) — the honest legal basis is legitimate interest in curating public information, not "consent we didn't really get." Switching is a copy-and-vocab change, not a UX change; the opt-out path via `/takedown/` already satisfies the "right to object" (Art. 21).

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Legitimate interest + LIA (chosen)** | Honest basis; no organizer friction; aligns with how events reach us (forwarded public flyers) | Requires writing + maintaining LIA doc; Art. 21 objection path must work (it does via `/takedown/`) |
| Real opt-in: organizer replies "YES" before first publish | Unambiguous Art. 7 consent | High friction; likely loses organizers who forward and expect silence; blocks publishing on no-reply |
| Keep "implied consent" wording | No work | Legally invalid (Art. 7 requires affirmative act); abmahnfähig; dishonest documentation |

**What would invalidate this:** three or more organizers objecting per quarter to how their events are represented; at that volume, shifting to real opt-in becomes cheaper than fighting takedowns.

---

### D3: Ship structural legal changes now; operator identity fills via env vars at deploy

**Firmness: FLEXIBLE**

All legal-document placeholders (`[MAINTAINER NAME]`, `[CONTACT EMAIL]`, etc.) are replaced by template variables read from Django settings, which in turn read from env vars:

- `IMPRESSUM_NAME`, `IMPRESSUM_ADDRESS`, `IMPRESSUM_EMAIL`
- `IMPRESSUM_PHONE` (optional second channel)
- `RESPONSIBLE_PERSON_NAME`, `RESPONSIBLE_PERSON_ADDRESS` (§18 MStV; defaults to `IMPRESSUM_*` if unset)
- `DSA_CONTACT_EMAIL` (defaults to `IMPRESSUM_EMAIL` if unset)

A Django system check (run on `manage.py check --deploy`) fails if any *required* var is empty while `PUBLIC_READ_ENABLED=True`. Internal cohort (current state) runs fine with placeholders populated by the maintainer's personal values for review only; public flip is blocked by the check until env is filled.

**Rationale:** the operator wants a separate public-facing email before launch (current personal Gmail is fine internally). Parameterizing means the code change lands now; the operator fills env values when the public email is ready. The system check is the tripwire that prevents a shipped-with-placeholders disaster.

**Alternatives considered:**

| Approach | Pros | Cons |
|---|---|---|
| **Parameterize + deploy check (chosen)** | Code work unblocked; operator identity not on critical path; impossible to ship with empty values | One new settings module for legal contact data; one Django check |
| Hardcode current personal values; rotate at launch | Simplest | Requires a code change at launch moment (fragile); personal email leaks into git history |
| Wait for operator to choose public email, then draft | Cleanest single PR | Blocks all legal-gate work on a non-code decision |

**What would invalidate this:** if the operator ultimately decides to incorporate (UG/GbR/etc.) before launch, a broader rewrite of the impressum becomes necessary — the env-var skeleton still works but adds fields (register number, court, VAT ID, etc.).

## Consequences

**Easier:**
- Legal-gate work can be executed in one code sprint without waiting on the operator's email decision or business-entity question.
- The `PUBLIC_READ_ENABLED` flip stays a single flag — the deploy check prevents unsafe flips automatically.
- Bundle B becomes cleaner: five P0 beads collapse to "review the draft copy → fill env vars → run `manage.py check --deploy` → flip flag."

**Harder:**
- Two new developer-visible conventions: `IMPRESSUM_*` env-var namespace and `legal_contact` settings module/template context processor.
- Organizer-LIA document must be kept current if processing purposes change (writing it once is ~1 hour; maintenance is per-feature).
- Attendance-consent checkbox is a real UX surface — adds one bead with schema change, migration, modal, withdrawal flow, and tests.

**Tradeoffs:**
- Explicit attendance consent adds friction for users who don't read modals. Acceptable: the platform's editorial positioning ("curated queer/kinky events") already signals the content nature; the modal confirms what users already know about the platform.
- Legitimate interest for organizers accepts some regulatory risk vs. real opt-in. Mitigated by accessible takedown path and documented LIA.
