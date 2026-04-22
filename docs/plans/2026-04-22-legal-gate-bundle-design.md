# Legal gate bundle — PUBLIC_READ_ENABLED flip prerequisites

**Date:** 2026-04-22
**Status:** Drafted; ready for beadification
**Parent roadmap:** [Bundle B ops in roadmap](2026-04-17-roadmap-0.1-to-1.0.md)
**Decisions:** [ADR-006 legal gate execution](../decisions/ADR-006-legal-gate-execution.md)
**Upstream ADRs:** [ADR-002 D2 legal gate](../decisions/ADR-002-phased-rollout-and-legal-gate.md), [ADR-003 F9 kill-switches](../decisions/ADR-003-cheap-foresight-patterns.md), [ADR-005 Bundle B ops](../decisions/ADR-005-bundle-post-0.5-execution.md)
**Supersedes in scope:** none — this is the concrete plan behind the "legal gate" banner in the roadmap.
**Audience:** maintainer (solo). Work produced here is internal-cohort-safe until env vars are filled and the flag is flipped.
**Risk killed:** shipping `PUBLIC_READ_ENABLED=True` with placeholder legal text (DDG §5, DSGVO, DSA, JuSchG non-compliance → Abmahnung, BfDI complaint, DSA takedown failure).

## Why a bundle, not one big PR

The 2026-04-22 legal review produced three classes of work:

1. **Structural/code** — parameterize copy, deploy check, attendance-consent schema + UX.
2. **Drafting** — English + German prose for Impressum, Privacy, Terms, Takedown form.
3. **Operator data** — name, address, contact email(s), phone/SLA — supplied by the operator at deploy time.

These have different cadences (code sprint → drafting review → ops). Bundling them as one PR forces the slowest step to block the fastest. Structuring this as its own mini-bundle inside Bundle B makes the sequence explicit and lets code ship without waiting on the operator's new public email.

## Scope

### In — structural (ships regardless of operator identity)

- **`a_core.legal` module** — new Python module exposing `legal_contact` dict (name, address, email, phone, dsa_email, responsible_name, responsible_address) built from `settings.LEGAL_CONTACT` which reads env vars. Template context processor makes it available in all templates.
- **Env-var schema** in `settings.py` + `.env.example`:
  - `IMPRESSUM_NAME` (required for public)
  - `IMPRESSUM_ADDRESS` (required for public)
  - `IMPRESSUM_EMAIL` (required for public)
  - `IMPRESSUM_PHONE` (optional — if empty, template renders "contact form" with stated SLA)
  - `RESPONSIBLE_PERSON_NAME` (optional, defaults to `IMPRESSUM_NAME`)
  - `RESPONSIBLE_PERSON_ADDRESS` (optional, defaults to `IMPRESSUM_ADDRESS`)
  - `DSA_CONTACT_EMAIL` (optional, defaults to `IMPRESSUM_EMAIL`)
- **Django system check** (`a_core/checks.py`) — `W006` warning if any required var is empty and `DEBUG=True`; `E006` error if empty and `PUBLIC_READ_ENABLED=True`. Registered via `apps.py` so `manage.py check --deploy` catches it before production start.
- **Attendance consent (Art. 9 D1)** —
  - `User.art9_consent_given_at: DateTimeField(null=True)` migration.
  - Pre-attend gate: `views.attend` and `views.interested` check `user.art9_consent_given_at is not None` before creating `Attendance`; otherwise return `_consent_required.html` partial with the consent modal.
  - Consent endpoint: `POST /accounts/art9-consent/` sets the timestamp.
  - Withdrawal on `/me`: "Withdraw attendance consent" button → clears timestamp AND deletes all `Attendance` rows for that user (hard delete; Art. 17 erasure). Idempotent.
  - Consent modal copy (EN + DE) explicitly names "sexual orientation" as a possible inference per Art. 9 plain-language requirement.
- **Takedown form upgrade (DSA Art. 16)** —
  - Reason dropdown adds "Illegal content (specify law)" option separate from ToS reasons.
  - Free-text "which law / why illegal" field, required when reason is "illegal".
  - Good-faith accuracy checkbox, required for submission.
  - Email required when reason is "illegal" (optional otherwise).
  - Short GDPR notice below form linking Privacy.
  - Warning: "Knowingly false reports may be rejected and escalated."
- **`docs/compliance/organizer-lia.md` (D2)** — one-page Legitimate Interests Assessment covering purpose / necessity / balancing / Art. 21 opt-out path for organizer data.
- **`Organizer.consent_method` vocabulary** — add `legitimate_interest` choice; data migration rewriting existing `telegram_forward_implied` rows to `legitimate_interest` with a note in `consent_notes`.

### In — drafting (English source; German translated via `.po`)

- **Impressum** (`templates/pages/impressum.html`):
  - Replace heading with "Angaben gemäß § 5 DDG" as primary, "Imprint" secondary.
  - All operator data reads from `legal_contact`.
  - §18 Abs. 2 MStV responsible-person block.
  - DSA Art. 11/12 contact point paragraph naming languages (DE, EN).
  - §36 VSBG consumer-arbitration statement.
  - Standard three-paragraph Haftung (Inhalte / Links / Urheberrecht).
- **Privacy** (`templates/pages/privacy.html`):
  - Controller block from `legal_contact`.
  - Per-purpose lawful basis table: account (Art. 6(1)(b)), attendance (Art. 9(2)(a) — D1), organizer publishing (Art. 6(1)(f) — D2 + link to LIA), flag reports (Art. 6(1)(c) DSA compliance), email delivery (Art. 6(1)(b) necessary for service).
  - Recipients / processors section: hosting (Hetzner/similar), email (SMTP provider name), LLM (OpenAI/Anthropic — SCC-based Art. 44ff transfer statement), Telegram (as ingestion channel), MapLibre tiles (OpenStreetMap Foundation).
  - Retention schedule per data category (attendance, ratings, flags, `RawMessage`, `EmailFailure`, accounts, session cookies).
  - Data subject rights: access, rectification, erasure, restriction, portability, objection (Art. 21 — explicit for organizers), **withdraw consent (Art. 7(3))**, complaint to BlnBDI (with address).
  - Automated-processing section (Art. 13(2)(f)) covering LLM extraction — no legally significant decisions about users.
  - TTDSG §25(2) age-gate cookie explanation, citing the correct subsection (Nr. 1 "strictly necessary for transmission" OR Nr. 2 "explicitly requested service" — needs agent-review to pick the defensible one).
  - Minimum-age clause (18+ referencing JuSchG).
  - "Last updated" date, driven by a template variable.
- **Terms** (`templates/pages/terms.html`):
  - DSA Art. 12 contact point line at top.
  - JuSchG age-restriction paragraph describing the age gate and content nature.
  - DSA Art. 14 content-moderation section: what actions (hide, remove, suspend, de-list), who decides (maintainer), review turnaround.
  - DSA Art. 20 appeal path: "reply to moderation notification email within 14 days."
  - User-generated content (ratings, flags) liability clause.
  - Governing law (German); jurisdiction (Berlin for non-consumers).
  - Severability + termination + "no paid product → Widerrufsrecht N/A" sentence.
  - "Last updated" date.
- **Takedown** (`templates/reviews/takedown.html`): form-level changes above; also cross-link to Terms and Privacy; plain-text `mailto:` fallback.
- **German `.po` entries** — regenerate with `makemessages`, translate all new strings. All operator-identity values stay language-neutral.

### Out — explicitly deferred

- Business-entity questions (UG/GbR/sole-trader implications on VAT, register entry). Env-var schema supports it; content additions deferred until the operator decides.
- Cookie banner. Confirmed not required if we stay session-cookie-only + JuSchG age gate cookie — both fall under TTDSG §25(2) exceptions. Re-evaluate if analytics/ads are ever added.
- Data Processing Agreements (DPAs) with each processor. Required paperwork but out of this code bundle; tracked separately as a Bundle B checklist bead.
- DPIA (Data Protection Impact Assessment) under Art. 35. Likely required given Art. 9 + potential large scale; tracked as separate bead, not blocking.
- In-app flag triage UI (deferred per phase 0.5 scope — email digest remains the triage surface).

## Data model deltas

### `User.art9_consent_given_at: DateTimeField(null=True, blank=True)` — **new**

Timestamp of attendance-consent acceptance. `null` = no consent; attendance writes blocked. Non-null = consent active; clearing it (withdrawal) also deletes all `Attendance` rows via a single function `revoke_art9_consent(user)` called from the `/me` withdrawal button AND from account deletion (belt + suspenders).

### `Organizer.consent_method: CharField` — **choices extended**

Add `("legitimate_interest", "Legitimate interest (Art. 6(1)(f))")`. Data migration backfills existing `telegram_forward_implied` rows → `legitimate_interest` and appends `"\nMigrated to Art. 6(1)(f) per ADR-006 on 2026-04-22."` to `consent_notes`.

### `Flag.reason` — **choices extended**

Add `("illegal", "Illegal content — specify law")` before existing reasons. Existing rows unaffected.

### `Flag.law_reference: CharField(max_length=200, blank=True)` — **new**

Free-text "which law" field populated when `reason == 'illegal'`. Shown in admin next to `details`.

### `Flag.good_faith_confirmed: BooleanField(default=False)` — **new**

Set True on submit when the Art. 16(2) checkbox is ticked. Required=True in the form; defaults False to keep existing rows working.

## Suggested bead structure (9 slices)

Target: each bead is ≤1 evening of solo work. Numbered for dependency order.

1. **`legal-contact` settings + context processor + deploy check** (no template changes yet). Ships env-var schema, `a_core.legal`, `a_core/checks.py`, context processor registration, `.env.example` update. Deploy check passes with placeholder values for current (internal) state; blocks public flip until filled. Tests: check error fires iff `PUBLIC_READ_ENABLED=True` and any required var is empty.
2. **Impressum rewrite + German translation** (kb-8qp). Uses `legal_contact` from bead 1. Drafts DE + EN. Regenerates `.po`. Agent-reviews final copy against DDG §5 checklist.
3. **Privacy rewrite + German translation** (kb-nyr). Depends on beads 1, 5 (consent field exists so policy can reference it accurately), 6 (LIA exists so policy can link it). Drafts DE + EN. Regenerates `.po`.
4. **Terms rewrite + German translation** (part of kb-7hg). Depends on bead 1. Drafts DE + EN. Regenerates `.po`.
5. **Attendance consent — schema + modal + endpoint + withdrawal** (D1). Adds `User.art9_consent_given_at` + migration, gate in `views.attend`/`views.interested`, consent endpoint, `_consent_required.html` partial, `/me` withdrawal button, `revoke_art9_consent()` helper called from account-deletion too. Tests: attend blocked without consent; attend works with consent; withdrawal deletes rows; idempotent withdrawal.
6. **Organizer LIA doc + consent_method migration** (D2). Writes `docs/compliance/organizer-lia.md`. Adds `legitimate_interest` choice. Data migration backfills existing rows. Tests: migration idempotent; admin shows new choice.
7. **Takedown form Art. 16(2) upgrade** (part of kb-7hg). Adds `Flag.law_reference`, `Flag.good_faith_confirmed`, `illegal` reason choice, form fields + required-when-illegal validation, GDPR notice, false-report warning, good-faith checkbox. Tests: form rejects submission without good-faith tick; illegal-reason requires email + law_reference; other reasons don't.
8. **Deploy-check hardening + `kb-804` close** — verify `manage.py check --deploy` on a CI job; add to pre-push or Django check registry. Close `kb-804`.
9. **Agent-review pass on final EN + DE drafts across all four docs** — second-opinion pass using the code-reviewer subagent with the full legal checklist; file any residual findings as follow-up beads. Close kb-8qp/kb-nyr/kb-7hg on clean pass.

## Readiness check / go-signal

`kb-9hw` (the flip bead) is the go-signal. It unblocks when:

- [ ] Beads 1–9 above closed.
- [ ] Operator has supplied `IMPRESSUM_*` env vars in production secrets manager.
- [ ] `manage.py check --deploy` on a production-like env returns 0.
- [ ] A smoke-test curl of `/impressum`, `/privacy`, `/terms`, `/takedown/` as anonymous user returns 200.
- [ ] `robots.txt` + OG-tag gating observed to follow `PUBLIC_READ_ENABLED` toggle on staging.
- [ ] Existing Bundle B beads `kb-lqw` (≥30 events) and `kb-vka` (q2 heartbeat 24h) closed.

## Rollback

If a post-flip legal issue surfaces (DPA inquiry, DSA notice, translation error found by a German-speaking user), the rollback is a single-flag flip: `PUBLIC_READ_ENABLED=False`. Robots.txt re-disallows; OG tags stop rendering; anonymous reads re-gate to login. Already-scraped social-cache previews persist 24–48h (per Bundle A §OG-meta-tags note) — panic-mode runbook in `docs/runbooks/panic-mode.md` covers cache-bust URLs.

No data migration is required for rollback. The attendance-consent checkbox + `/me` withdrawal stay live regardless of public flag state.

## Test plan

- **Unit:** each new form field, check, consent-gate function has tests in its own bead.
- **Template smoke:** new `tests/test_legal_pages.py` — anonymous GET on `/impressum`, `/privacy`, `/terms`, `/takedown/` returns 200 under both `PUBLIC_READ_ENABLED=True` and `=False` (already login-walled pages should be exempted from the anonymous wall for legal pages).
- **System check:** `tests/test_deploy_check.py` — parametrized across `{DEBUG, PUBLIC_READ_ENABLED}` and `{env complete, email missing, name missing, address missing}`; asserts `W006` vs `E006` levels.
- **Migration:** both data migrations (organizer consent_method backfill; attendance consent added) have roll-forward and roll-back tests.
- **i18n:** `django-admin compilemessages` passes; rendering with `LANGUAGE_CODE='de'` shows translated strings.

## Out-of-scope but tracked

- DPA paperwork with each processor (separate bead).
- DPIA under Art. 35 (separate bead; likely required).
- Business-entity decision impacting VAT/register entry (operator decision; env-var schema already extensible).
- BlnBDI proactive notification (only needed if a breach occurs; runbook link from Privacy policy).
