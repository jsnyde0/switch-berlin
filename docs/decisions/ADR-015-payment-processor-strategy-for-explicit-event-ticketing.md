# ADR-015: Payment-processor strategy for explicit-event ticketing

**Status:** Accepted 2026-05-21
**Parent:** [ADR-010 D1 — event-based product posture](ADR-010-event-based-product-posture.md) (ticketing-as-revenue-path); [ADR-011 D1 — personal-agent layer additive](ADR-011-personal-agent-layer-additive.md) (facilitator agent helps with org-side payment setup)
**Scope:** infrastructure binding on which payment processor underlies Switch's ticketing flows — both the V0/V1 tactical path (third-party ticketing via TickeTailor) and the long-term sister-platform path (per kb-2ve Phase A D1). Distinct from ADR-010 (product-posture / ticketing-as-revenue-path) and ADR-006 (legal-gate / GDPR-consent-basis) — this ADR is infra/ops, not product or legal.

## Context

`kb-cyq` R2 synthesis (2026-05-21) and `kb-0cj` R0 (payment-processor landscape) jointly surfaced that **payment-processor choice is a load-bearing decision distinct from ticket-platform choice**:

- **Most ticket platforms in our scene are NOT merchants of record.** TickeTailor (R2's chosen tactical platform) routes funds directly to the organizer's Stripe/PayPal/Square; TT is not in the funds path. Same shape for Squarespace-Commerce, DICE, Shotgun, Yogo (House of Play), and Eventbrite. **Stripe is the structural processor under the vast majority of our scene** — including TNT Berlin, Shibari Studio Berlin, Sensual Hearts Temple, Tantric Kink Munich, European Tantra Festival.
- **Stripe's January 2024 ToS update explicitly added "fetish services"** to the prohibited list, alongside escorts/pornography/sexual-massages. Termination-for-convenience confirmed in the SSA. **WishTender (dominatrix-tip platform) was cut off March 2024 with no notice** — the canonical EU/US-applies-globally precedent.
- **No mainstream-EU PSP is more friendly.** Adyen explicitly prohibits "fetish products" (strictest of the bunch). Mollie / Klarna / GoCardless all prohibit adult/sexual content. MoR absorbers (Paddle / FastSpring / LemonSqueezy) double-fail (adult bans + digital-products-only).
- **The only viable openly-adult EU-native EUR-SEPA processors** are Verotel and Segpay — at 5–10% fee + $500–1000/yr scheme-reg setup + 5–10% rolling reserve, subscription-content-shaped. They do not natively plug into TickeTailor (TT supports Stripe/PayPal/Square only) — adopting them means leaving TickeTailor for self-hosted or custom adult-friendly stacks.
- **The risk surface differs between V0/V1 tactical and long-term sister platform.** Per `kb-a2j` (Switch platform-level Stripe risk): V0/V1 in "Mode A coordination-layer" has Switch facilitate organizer-direct-Stripe accounts (Switch is not the Stripe ToS counterparty, organizer is); sister platform per `kb-2ve` Phase A is "Hipsy-shaped" → likely merchant of record → likely needs Stripe Connect (Mode B) or alternative-processor-as-MoR. Mode B engages platform-aggregator risk that Mode A does not.

Without canonical placement, future decisions on processor choice drift between three failure modes: (a) re-deriving the risk landscape per bead authoring round; (b) silently treating Stripe as inevitable when it is in fact the dominant default but not the only option; (c) ossifying the V0/V1 coordination-layer choice into a long-term constraint without re-validating it against sister-platform MoR posture.

This ADR canonicalizes **what the payment-processor decision surface looks like, what's currently chosen for V0/V1, and what's pending for the sister platform**.

## Decisions

### D1: V0/V1 tactical payment processor — organizer's own direct Stripe account in Mode A coordination-layer

**Firmness: FLEXIBLE** — `kb-cyq` R2 chose this path 2026-05-21 with concrete dogfooding-imminent intent (organizer-hub V1 implementation downstream). Mutation warrants: a surfaced Stripe ban on a Switch-onboarded organizer; a new openly-adult EU PSP that integrates with TickeTailor; a scene-wide migration trigger affecting >2 of the ~20 currently-Stripe-using scene operators. FLEXIBLE because direction can evolve with observed signal; the choice is not arbitrary but it is reversible.

Switch's V0/V1 tactical ticketing flow (via TickeTailor per `kb-cyq` R2 D1) uses **the organizer's own direct Stripe account** — not a Switch-owned Stripe Connect application. The Switch facilitator agent (per ADR-011 D1) helps the organizer set up and connect their Stripe account during onboarding (playbook in `kb-94h`), but Switch never holds the Stripe ToS counterparty relationship — that is organizer→Stripe direct. This is the **Mode A coordination-layer** architectural posture canonicalized in `kb-a2j`.

**Operationally:**

- **(a) Switch facilitator agent is a guide/automation layer**, not a payment intermediary. It surfaces onboarding guidance, generates cleaned event listings (per `kb-o0j` cleaning policy), and uses organizer-supplied Stripe API keys for capacity-sync read-back. It does NOT hold OAuth tokens for many organizers as a Stripe Connect platform application.
- **(b) Public messaging discipline.** Switch markets itself as event-coordination + community-trust infrastructure, NOT as a payment facilitator. The boundary defended in `kb-a2j`.
- **(c) Risk-inheritance, not risk-introduction.** Stripe's "fetish services" ToS prohibition is structurally present for all ~20 scene operators currently running Stripe. Switch building on this stack in Mode A inherits that risk symmetrically with the scene; it does not aggregate, amplify, or transform the risk into a new attack surface (per `kb-a2j` Mode A vs Mode B analysis).
- **(d) Cutover-readiness as deliverable.** Both AUP-layer (TickeTailor) and processor-layer (Stripe) enforcement are reactive with no notice (WishTender precedent). V0/V1 ships with cutover-readiness via `kb-y6w` (Stripe-ban runbook → Verotel/Segpay onboarding), `kb-6y6` (TT AUP §removal runbook → Hipsy/Eventbrite/self-hosted migration), `kb-d9s` (facilitator metadata-logging for cutover reproducibility), and `kb-bw0` (exploratory crypto fallback).

**Counter-argument acknowledgment (FLEXIBLE-path):** The alternative — **adopt Verotel or Segpay from V0/V1 day 1** — was considered. Counter: V0/V1 organizers do not yet exist; Stripe-direct-with-cutover-readiness has lower onboarding friction and matches what every comparable scene operator already runs. Verotel/Segpay's 5–10% fees + scheme-reg setup + subscription-shaped UX would impose audience-conversion friction and per-organizer onboarding cost without a corresponding risk-reduction (the underlying Visa/MC scheme rules are upstream of all of them, and `kb-0cj` R0 found no surfaced ban reports against Stripe-using scene operators despite the hostile ToS text). The loose formulation that survived: inherit the scene-default risk in Mode A; ship cutover-readiness as a deliverable.

**Rationale:**

- `external:` `kb-cyq` R2 D1 (2026-05-21) — user-ratified GO on TickeTailor + organizer-direct-Stripe; explicit ask for fallback documentation (Segpay/Verotel/Hipsy/Eventbrite/self-hosted)
- `external:` `kb-0cj` R0 (2026-05-21) — ~20 scene operators currently running Stripe without surfaced bans; no mainstream-EU alternative is more friendly
- `external:` adversarial review F2 (2026-05-21) — Mode A vs Mode B boundary clarified; V0/V1 explicitly chooses Mode A; `kb-a2j` carries the architectural detail
- `reasoned:` cutover-readiness as a deliverable hedges the reactive-enforcement risk without introducing day-1 friction that would suppress the V0/V1 organizer-hub from ever shipping (ADR-008 D2 — no speculative abstraction; build adult-friendly processor flows when the trigger fires, not before)
- `reasoned:` Mode A coordination-layer (per `kb-a2j`) keeps Switch out of Stripe's ISV/platform risk model, which is the relevant escape from "Switch-as-aggregator" attack surface

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Adopt Verotel or Segpay as the V0/V1 default processor | `external:` `kb-0cj` R0 — 5–10% fees + $500–1000/yr scheme-reg + rolling reserve + subscription-content-shaped UX; no V0/V1 organizer base yet exists to justify the day-1 friction. `reasoned:` Visa/MC scheme rules are upstream regardless of processor choice; the risk floor is invariant. |
| Switch-owned Stripe Connect platform aggregating organizer accounts | `external:` `kb-a2j` Mode B analysis — Stripe evaluates platforms holistically; a watchdog reporting "Switch is facilitating fetish events" routes through Stripe's platform-compliance team, and platforms have been terminated for restricted-business-facilitation regardless of individual merchant account states. Mode A coordination-layer is the explicit escape. |
| Skip ticketing entirely for V0/V1; defer until sister platform ships | `external:` `kb-cyq` R2 — sister platform is long-term core revenue infrastructure (kb-2ve Phase A D1); V0/V1 organizer-hub epic (`kb-dko`) cannot wait. `reasoned:` deferring also defers V0/V1 dogfooding signal that would inform sister-platform design. |
| Crypto-only payment rail (BTCPay / CoinGate / NOWPayments) | `external:` `kb-0cj` R0 D5 — tantra/workshop attendees are not crypto-native; audience-friction would crush conversion. `reasoned:` `kb-bw0` keeps crypto as exploratory V1.5 fallback rail, not primary. |

**What would invalidate this:**

- A Stripe ban on a Switch-onboarded organizer (operational signal). Triggers immediate `kb-y6w` cutover execution + post-mortem against this D1; if frequency >1/year per active organizer cohort, escalate to "Stripe-direct V0/V1 default is wrong" and re-evaluate Verotel/Segpay default-status.
- A new openly-adult EU PSP enters the market with native TickeTailor (or Eventbrite/Hipsy) integration — would weaken the "Verotel/Segpay only EU-native option but doesn't plug into TT" constraint and warrant re-evaluation.
- A scene-wide migration trigger affecting >2 of the ~20 currently-Stripe-using scene operators (e.g., Stripe revises ToS to explicitly enforce, or a coordinated watchdog campaign). Substantive observation; revisit whether Mode A coordination-layer is still risk-symmetric with the scene.
- `kb-a2j` Mode A vs Mode B boundary collapses (e.g., facilitator agent functionality drifts into platform-aggregator behavior). Substantive observation; this ADR's "coordination-layer" qualifier no longer applies and the risk re-shapes.

### D2: Long-term sister-platform payment processor — pending (currently captured-question)

**Firmness: FLEXIBLE** — decision not yet made; this entry captures the decision surface so future ADR evolution lands in place. Mutation warrants: `kb-hm0` (sister-platform processor strategy decision bead) converges; `kb-2ve` Phase B definition lands (sister-platform MoR posture, scale targets, EUR-only vs multi-currency); `kb-y6w` and `kb-6y6` cutover-readiness work produces empirical learnings on Stripe-ban frequency in V0/V1.

The long-term sister platform per `kb-2ve` Phase A D1 ("Hipsy-shaped" revenue home for explicit canonical events) is **likely merchant of record** by design — the platform takes ticket payments directly, not via organizer-passthrough. This is structurally distinct from V0/V1 tactical (D1 above) because:

- **Sister platform IS the MoR.** Stripe ToS counterparty relationship is platform→Stripe, not organizer→Stripe. Mode B platform-aggregator risk engages directly.
- **No "leave TT" cost.** Sister platform is greenfield; processor choice doesn't require migrating off another stack.
- **Long-term horizon compounds fee differences and lock-in.** A 5–10% Verotel/Segpay vs 1.5% Stripe fee gap is material at scale; once attendees know the payment UX, switching imposes friction.

The decision is **between two paths**:

- **Path A: Stripe day 1 + scheduled cutover.** Cheap (1.5% + €0.25), mass-market UX, deferred risk. Inherits the same Stripe ToS risk every scene operator already runs (per D1 logic). Requires a "scheduled cutover" trigger condition — what scale or signal flips sister platform to Path B? `kb-hm0` carries this design.
- **Path B: Adult-friendly processor day 1 (Verotel or Segpay as MoR).** Higher fees (5–10% + scheme-reg + rolling reserve), niche-fit UX (kink-aware checkout language), lower banking-surprise risk. Structurally resilient from launch.

Neither path is locked in this ADR; both remain valid pending `kb-hm0` synthesis. This D2 entry exists to canonicalize that the choice has a home, to document the invariants both paths inherit, and to prevent silent drift toward Path A by default just because Stripe is the V0/V1 choice.

**Invariants both paths inherit (regardless of direction):**

- Visa/MC scheme rules are upstream of every mainstream processor (no clean escape via processor choice alone)
- "Fetish services" hostile-text exists in Stripe ToS but enforcement is reactive (per `kb-0cj` R0)
- No mainstream-EU PSP is more friendly than Stripe (Adyen worse; Mollie / Klarna / GoCardless prohibit; MoR absorbers double-fail)
- Verotel + Segpay are the only EU-native EUR-SEPA openly-adult options
- Sister platform's web-UI surface follows the same cleaning-policy patterns as V0/V1's TickeTailor projection (per `kb-o0j`); the processor choice is orthogonal to cleaning-policy

**Rationale:**

- `external:` adversarial review F6 (2026-05-21) — payment-processor strategy is infra/ops, not product-posture; new ADR-015 canonicalizes the question separately from ADR-010
- `external:` `kb-cyq` R2 D3 (2026-05-21) — explicit spawn of `kb-hm0` for sister-platform processor decision; this D2 is the ADR side of that spawn
- `reasoned:` capturing the question as FLEXIBLE-pending prevents downstream silent commitments (e.g., kb-2ve Phase B implementation choosing Stripe-Connect by default without ADR-grounded warrant)

**Alternatives (for the D2 placement, not for the underlying choice):**

| Alternative | Why rejected |
|---|---|
| Fold D2 into D1 (one decision covering both V0/V1 and sister) | `reasoned:` different MoR models, different time horizons, different mutation triggers. Two decisions let D1 mutate independently of D2 (V0/V1 cutover learnings vs sister-platform launch posture). |
| Defer D2 until `kb-hm0` converges; don't write it in this ADR yet | `reasoned:` D2-as-captured-question prevents downstream drift. Without an ADR home, kb-2ve Phase B implementation might silently choose Stripe-Connect because Stripe was the V0/V1 default; FLEXIBLE-pending captures the choice surface so the eventual decision lands in place. |
| Write D2 in a separate ADR-016 dedicated to sister-platform processor | `reasoned:` payment-processor strategy is one decision surface; the V0/V1 and sister legs share invariants. Two-ADRs would duplicate the invariants section and force cross-citation. |

**What would invalidate this:**

- `kb-hm0` converges on a direction (Path A or Path B) — D2 mutates to FLEXIBLE-direction-set with the chosen path documented.
- `kb-2ve` Phase B definition lands and changes the sister-platform MoR posture (e.g., sister platform turns out to be agent-mediated coordination rather than direct-MoR). D2's framing reshapes accordingly.
- V0/V1 cutover-readiness empirical data (from `kb-y6w` runbook executions) shows Stripe-ban frequency higher than tolerable for an at-scale platform. Tilts Path B more strongly.
- New EU regulatory development (MiCA expansion, payment-services-directive update) changes the cost or feasibility of dedicated adult processors. Substantive observation; revisit both paths.

## Consequences

### Direct

- Future bead `--design` for ticketing-flow or payment-integration work must cite ADR-015 D1 (V0/V1) or D2 (sister) and identify which leg the work falls under.
- Switch facilitator agent design (per ADR-011) must respect Mode A coordination-layer boundary for V0/V1 work — no Stripe Connect aggregation, no platform-level OAuth across many organizers, no facilitator-mediated payment routing.
- Sister-platform implementation work (downstream of `kb-2ve` Phase B + `kb-dko` organizer-hub epic) must hold D2 open as a captured question until `kb-hm0` converges; default-to-Stripe-Connect without `kb-hm0` warrant is a violation of D2.
- Cutover-readiness beads (`kb-y6w`, `kb-6y6`, `kb-d9s`, `kb-bw0`) ship as V0/V1 deliverables — operationalizes D1's "cutover-readiness as deliverable" provision.
- Organizer Stripe-onboarding playbook (`kb-94h`) is V1 launch-readiness — operationalizes D1's "organizer-direct Stripe with facilitator-agent help" provision.

### Carried forward

- **ADR-010 D1(c) FLEXIBLE — ticketing as revenue path.** ADR-015 is the infra realization of ADR-010 D1(c)'s revenue path: which processor underlies the ticketing flow. ADR-010 stays at product-posture; ADR-015 carries the infra binding.
- **ADR-011 D1 FLEXIBLE — facilitator agent layer.** ADR-015 D1 explicitly names the facilitator agent as the integration vehicle for organizer-side Stripe setup (per ADR-011's agent-natural-feature framing). The agent's Mode A coordination-layer boundary is operationalized in `kb-a2j`.
- **ADR-008 D2 — no speculative abstraction.** ADR-015's D1 cutover-readiness scope is non-speculative: cutover beads target observed risk surfaces (Stripe ban, TT AUP §removal) with concrete migration targets, not generalized adversity-handling.

### Risk

- **Mode A vs Mode B drift.** If Switch facilitator agent functionality drifts toward aggregating payment behaviors (e.g., for multi-organizer cross-event upsell flows, or for centralized refund processing), it could cross into Mode B platform-aggregator territory and re-engage Stripe's platform risk model. Mitigation: `kb-a2j` carries the boundary; ADR-015 D1 invalidation predicate (boundary collapses) triggers re-evaluation.
- **Scheduled-cutover trigger for sister Path A is judgment-laden.** If sister platform adopts Stripe day 1 + scheduled cutover, the cutover trigger condition (scale? attention?) is non-trivial to define. Mitigation: `kb-hm0` synthesis must produce a concrete signal-shaped trigger, not a numeric threshold per ADR-008 D8.
- **Audience-conversion friction with Verotel/Segpay.** If Path B is chosen for sister platform, the higher checkout friction (kink-aware UX, subscription-shaped flows) may suppress attendee conversion in ways that mainstream Stripe wouldn't. Mitigation: `kb-hm0` includes audience-friction analysis before committing.
- **Dual-leg ADR evolution risk.** D1 and D2 evolve on different cadences (D1 on operational V0/V1 signal; D2 on sister-platform definition). Risk that one leg's mutation creates inconsistency with the other. Mitigation: every mutation revisits the invariants section to check cross-leg coherence.

## canonical_refs

- [ADR-006 D1, D2, D3](ADR-006-legal-gate-execution.md) — legal-gate framework; ADR-015 is infra-binding adjacent to but distinct from ADR-006's legal-binding. (Cited for adjacency; no direct constraint.)
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — no speculative abstraction; ADR-015's V0/V1 cutover-readiness scope is non-speculative (targets observed risk surfaces, not generalized adversity).
- [ADR-010 D1(c)](ADR-010-event-based-product-posture.md) — ticketing as revenue path (product-posture); ADR-015 is the infra realization of that posture.
- [ADR-011 D1](ADR-011-personal-agent-layer-additive.md) — personal-agent layer; ADR-015 D1 uses facilitator agent as integration vehicle for organizer-direct-Stripe setup.
- `kb-cyq` — research bead; R2 synthesis 2026-05-21 ratifies this ADR's D1 direction
- `kb-0cj` (closed 2026-05-21) — payment-processor R0 landscape; canonical evidence for both D1 and D2 invariants
- `kb-a2j` — Switch platform-level Stripe risk: confirms Mode A coordination-layer for D1; tracks Mode A vs Mode B boundary
- `kb-hm0` — sister-platform payment-processor strategy decision; D2's pending direction lands here
- `kb-y6w` — Stripe-ban cutover runbook (operationalizes D1 cutover-readiness)
- `kb-6y6` — TickeTailor AUP §removal cutover runbook (operationalizes D1 cutover-readiness)
- `kb-d9s` — Switch facilitator agent metadata-logging (operationalizes D1 cutover reproducibility)
- `kb-bw0` — crypto-fallback exploratory (operationalizes D1 V1.5 defense-in-depth)
- `kb-94h` — organizer Stripe-onboarding playbook (operationalizes D1 launch-readiness)
- `kb-2ve` (closed Phase A) — sister-platform vision; D2's MoR-posture-likely framing draws from kb-2ve Phase A D1 "Hipsy-shaped"
- `kb-dko` — organizer-hub epic; downstream consumer of D1
- `docs/research/kb-cyq-r0-provider-landscape.md` — ~80-organizer scene landscape; provider footprint evidence
- `docs/research/kb-cyq-r1-tickettailor-deepscout.md` — TickeTailor is not merchant-of-record finding
- `docs/research/kb-0cj-r0-payment-processor-landscape.md` — payment-processor landscape; Stripe ToS verbatim; WishTender precedent

## Open questions deferred

| Question | Resolution path |
|---|---|
| What's the cutover-trigger condition for sister-platform Path A (Stripe day 1 → scheduled cutover)? | Defer to `kb-hm0` synthesis. Must be signal-shaped per ADR-008 D8; candidate triggers include sustained Stripe ban frequency >threshold/year, regulatory shift (MiCA expansion, PSD3), or scene-wide migration event. |
| Does ADR-015 D1 Mode A coordination-layer constraint apply transitively to the sister platform's facilitator-agent integration? | Defer; cross-reference at sister-platform design time. Working assumption: sister platform is independent infrastructure with its own architectural choices (per `kb-2ve` Phase A); ADR-015 D1 binds Switch Berlin V0/V1 only. |
| Crypto-payment-rail viability for V1.5 fallback — when does `kb-bw0` exploratory work feed back to D1 invalidation? | Defer to `kb-bw0` R0 output; if a viable processor surfaces with audience-fit for our scene, D1 invalidation predicate gains a new entry "crypto-fallback now ships as primary alternate rail; cutover runbook updated." |
