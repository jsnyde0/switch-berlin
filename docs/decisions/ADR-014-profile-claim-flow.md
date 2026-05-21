# ADR-014: Profile claim flow — multi-claimant through-model, two-track verification, magic-link security envelope

**Status:** Accepted 2026-05-21
**Parent:** [ADR-007 D5 Profile claimable via User FK](ADR-007-profile-centric-schema.md) (evolved in place per ADR-011 D1)
**Scope:** how Profiles are claimed by Users — schema cardinality, verification routing, security envelope. Operationalizes the upstream curated-trust gate (ADR-001 D1) at the Profile-ownership boundary.

## Context

Switch Berlin (V0 pre-launch) hosts Profiles that are **admin-curated from public sources during Phase 0.5** — IKSK, Lavinia, etc. exist as Profile rows whether or not the named human or collective has signed up. Once the public-read flip (kb-9hw) ships, those humans will discover the platform hosts their pages and need a way to **claim** them and gain edit rights.

The claim flow has to honor three concrete realities surfaced during the kb-m69 brainstorm:

1. **Collectives have multiple co-organizers.** IKSK is fronted by ~3 humans. The current schema (`Profile.claimed_by = FK(User, null=True)` per ADR-007 D5) forces one of them to fictitiously "own" IKSK.
2. **Most facilitators don't operate domains.** Jana Felix Ruckert (`jana.felixruckert@gmx.de`) can't be verified via email-domain match — admin review must remain the universal fallback.
3. **Some organizers do.** IKSK runs `iksk.berlin`; a `lavinia@iksk.berlin` email is strong evidence of an IKSK claim. Domain-match is labor-saving when it applies.

The claim flow sits **upstream** of:
- The User trust model (ADR-013) — claimed-Profile users are typically the first admin-vouched cohort.
- Event editing surfaces (Phase 0.5+) — only claim-holders can edit their Profile's events.
- Telegram bot ApprovedSender flows — claim-holders become natural senders for their Profile's organizer Telegram channel.

This ADR canonicalizes the claim-flow primitives so those downstream surfaces have a stable substrate to bind against.

## Decisions

### D1 — Multi-claimant `ProfileClaim` through-model replaces single-FK ownership

**Decision:** Replace ADR-007 D5's `Profile.claimed_by = FK(User, null=True)` with a `ProfileClaim` through-model. A Profile has 0–N claims; each claim is one verified (User, Profile) pair.

```python
ProfileClaim(
    profile           = FK(Profile),
    user              = FK(User),
    verified_at       = DateTime,
    verified_method   = CharField,  # "email_domain" | "admin_review" | ...
    verified_by_admin = FK(User, null=True),  # NULL for email_domain auto-verify
    role              = CharField,  # V0: always "admin"; cheap foresight for "contributor" etc.
    created_at        = DateTime,
)
# unique_together = (profile, user)
```

Ergonomic accessors: `profile.claimants.all()`, `user.claimed_profiles.all()`, `profile.is_claimed` (= `claimants.exists()`).

**Firmness:** EXPLORATORY (overall — pending dogfooding); the through-model **shape** is the canonical schema replacement of D5 (FIRM evolution per ADR-011 D1, decision-property unchanged: "Profiles are claimable"). EXPLORATORY governs the `role` semantics, the `verified_method` enum vocabulary, and whether admin can revoke a claim.

**Rationale:**
- `reasoned:` Collectives like IKSK have multiple co-organizers. A single-FK shape forces a fiction (one human "owns" IKSK) that breaks down on day one. The through-model preserves the unified "Profile is claimable" semantic at the property level while flexing cardinality from 0..1 to 0..N.
- `external:` Crunchbase's "Manage My Company" flow (scout, kb-m69) uses a multi-employee verified-edit model — multiple verified employees can edit the same company page. Maps cleanly onto our co-organizer reality.
- `direct:` Person Profiles will typically have 1 claim (the human themselves); collective Profiles will typically have 1–N. The same shape serves both, matching ADR-007 D1's unified-Profile discipline.
- `reasoned:` `role` field is cheap foresight (ADR-003) — V0 collapses to `"admin"` for all claims; richer hierarchies (`"contributor"` with reduced edit rights, `"former"` for archived claims) accommodated by enum extension without schema migration.

**Alternatives:**
| Alternative | Why rejected |
|---|---|
| Keep single-FK `Profile.claimed_by` (ADR-007 D5 status quo) | `direct:` Cannot represent IKSK's actual co-organizer reality without out-of-band coordination. Surfaced during kb-m69 brainstorm. |
| Separate `Agency` entity (Upwork model) | `reasoned:` Adds an entity layer not yet needed; `Profile(kind=collective)` already plays this role. Cheap foresight: through-model + `role` field accommodates richer hierarchies later. |
| Pivot ApprovedSender to point at User instead of Profile | `reasoned:` Breaks the Phase 0.5 admin-curated workflow where ApprovedSender pre-exists for an unclaimed Profile. Telegram → Profile direction must remain. |
| `Profile.claimants = M2M(User)` plain M2M (no through) | `reasoned:` Loses the verification metadata (`verified_at`, `verified_method`, `verified_by_admin`) — these aren't auxiliary, they're load-bearing for the audit trail required by ADR-006 (legal gate) and the curated-trust model (ADR-001 D1). |

**Invalidation:**
- All facilitators turn out to operate as solo organizers (no co-managed collectives) → the through-model is over-engineering; could revert to FK. Empirically: IKSK alone disproves this.
- The `role` field never gets a second value beyond `"admin"` after 2 years of operation → cheap foresight didn't pay; could drop the field at the next clean-schema migration window (V1+).

### D2 — Web-first claim entry from the public Profile page, with two-track verification

**Decision:** The claim entry point is a visible button on the **public Profile page** ("Manage this profile" when `Profile.is_claimed == False`; "Add me as a claimant" when claimed but the viewing User isn't already in `claimants`).

The flow runs two tracks based on email-domain evidence:

| Track | Triggered when | Outcome |
|---|---|---|
| **Email-domain fast-path** | Submitted email's domain matches `Profile.verified_domain` (admin-set per Profile, optional, opt-in) | Magic-link sent → on click, `ProfileClaim` row auto-created with `verified_method="email_domain"`, `verified_by_admin=NULL` |
| **Admin-review fallback** | No domain match OR `verified_domain` not set on Profile | Magic-link sent → on click, request enters `admin_review` queue with submitted email, free-text "why I'm claiming this" note, and User context. Admin manually creates `ProfileClaim` with `verified_method="admin_review"`, `verified_by_admin=<admin_user>` |

Both tracks pass through the magic-link confirmation step (proves the submitter controls the email). The fast-path differs only in the **post-confirmation routing** (auto-claim vs admin queue).

**Firmness:** EXPLORATORY (pending dogfooding the actual claim volume + admin labor load).

**Rationale:**
- `direct:` Per kb-m69 D1: many facilitators (e.g., Jana Felix Ruckert with a generic gmx.de email) won't have a matching domain. Admin-review must remain the **universal fallback**; the fast-path is opt-in per Profile and only operates when admin has explicitly set `verified_domain`.
- `external:` Crunchbase's "Manage My Company" flow (scout, kb-m69) uses email-domain match → instant verification with email-support fallback for mismatches. Their help article on the buried claim flow has –15 net helpfulness — **putting the claim button on the profile page itself** is the corrective lesson; web-first entry from the Profile surface is non-negotiable.
- `external:` GitHub's repo-claim and Eventbrite's organizer-claim flows both surface the claim entry on the public entity page itself (not a separate "claim center"), confirming the pattern.
- `reasoned:` Two-track verification preserves ADR-001 D1's curated-trust default (admin review) while adding a labor-saving fast-path. Admin retains control: fast-path only activates when admin opts a Profile into it by setting `verified_domain`.

**Alternatives:**
| Alternative | Why rejected |
|---|---|
| Bot-first claim (Telegram DM → admin keyboard) | `reasoned:` Couples identity to a third party; while Berlin scene is Telegram-native, web-first matches the broader user base (incoming facilitators discovering us via their public Profile URL share). Telegram link remains a separate primitive (ApprovedSender flow) downstream. |
| Always-admin-review (no fast-path) | `reasoned:` Admin labor scales linearly with claim rate; unnecessary friction for orgs with verifiable domains. Fast-path is opt-in so admin retains control. Invalidation predicate captures the reversal path: if fast-path abuse appears, retire it without affecting the admin-review default. |
| DNS-TXT verification (GitHub pattern) | `external:` GitHub scout (kb-m69) — DNS verification is org-only and impractical for individual facilitators who don't operate domains. Email-domain match achieves the same evidence threshold (proves control of an address on the domain) without the DNS-edit barrier. |
| Self-serve claim with no verification (just "I claim this") | `reasoned:` Violates ADR-001 D1's curated-trust posture. Anyone could claim IKSK by clicking a button. |

**Invalidation:**
- Admin labor turns out to be the bottleneck even for the few orgs with `verified_domain` set (e.g., domain-match still requires admin checks because the domain itself wasn't verifiable) → fast-path can be retired without affecting the admin-review default.
- A security incident shows the fast-path being abused (domain spoofing via SPF/DKIM gaps, expired-token replay, etc.) → fast-path retired; all claims route through admin-review until mitigation lands.
- Public Profile-page entry surface drives spam claims (>20% of submissions are obviously non-legitimate) → move entry behind a Cloudflare Turnstile challenge (ADR-013 references Turnstile as a sibling anti-abuse primitive) or require User authentication before showing the button.

### D3 — Magic-link security envelope: 1-day expiry, single-use, scoped to (email, profile, user) triple

**Decision:** The claim magic-link token has the following security properties:

- **Expiry:** 24 hours from issuance.
- **Single-use:** Token is invalidated on first successful click (regardless of whether the post-click step succeeds; replay attempts hit an invalidated-token error page).
- **Scope:** Token binds `(email, profile_id, user_id)` triple. A token issued for User A claiming Profile X with email `a@example.com` cannot be replayed by User B, against Profile Y, or with a different email.
- **Storage:** Token is stored hashed (not plaintext) per standard Django magic-link discipline.
- **Pre-issuance gate:** Cloudflare Turnstile challenge on the submit form (consistent with ADR-013-referenced anti-abuse primitives applied across signup/claim/contact forms).

**Firmness:** EXPLORATORY (the 24h expiry is a starting point; if abuse patterns or UX friction (legitimate users not clicking within 24h) emerge, tune the window).

**Rationale:**
- `external:` GitHub's repo-transfer magic-link uses a 1-day expiry — tight enough to limit replay risk while accommodating realistic user latency (check email next morning). Same threat model.
- `reasoned:` Single-use + (email, profile, user) scope prevents token-substitution attacks: an attacker who intercepts a token for User A's claim attempt cannot bind it to their own User account or redirect it to a different Profile.
- `reasoned:` Hashed storage prevents DB-leak compromise from yielding active tokens — standard Django security posture.
- `reasoned:` Turnstile pre-gate prevents automated form-submission floods (the leading abuse shape for any "submit your email" endpoint per scout/industry pattern).

**Alternatives:**
| Alternative | Why rejected |
|---|---|
| 7-day expiry (looser) | `reasoned:` Longer replay window for a security-load-bearing action (gaining edit rights on a public-facing Profile). 1 day is the industry-standard floor; tighter is overkill for non-financial actions. |
| 1-hour expiry (tighter) | `reasoned:` Legitimate users frequently check email asynchronously (next morning, after a meeting). 1-hour creates UX cliff with no security benefit at this attack value level. |
| Multi-use token (until expiry) | `reasoned:` Replay risk on shared/leaked email accounts. Single-use is cheap to implement and closes a clear attack class. |
| No Turnstile (rely on rate-limiting alone) | `reasoned:` Rate-limiting alone is leaky against distributed automated submission; Turnstile is the orthogonal mitigation already established for similar forms per kb-m69 D10. |

**Invalidation:**
- Click-through rate within 24h drops below 70% (significant fraction of legitimate users miss the window) → extend to 48–72h with corresponding security review.
- Token-substitution or replay-class abuse appears in audit logs → tighten scope (e.g., add IP-pinning, or require re-authentication immediately before claim activation).
- Turnstile false-positive rate proves to be a UX disaster (legitimate users blocked) → switch to a more permissive challenge or remove from the claim form (other forms' Turnstile usage governed by ADR-013).

## Consequences

### Direct schema impact (foundation for D1)

- ADR-007 D5 evolves in place per ADR-011 D1: `Profile.claimed_by = FK(User, null=True)` → `Profile.claimants = M2M(User, through="ProfileClaim")`.
- New model: `ProfileClaim(profile, user, verified_at, verified_method, verified_by_admin, role, created_at)`.
- New optional Profile field: `verified_domain = CharField(blank=True)` (admin-set, opt-in per Profile, enables D2 fast-path).
- Existing `Profile.claimed_by` rows (if any exist at migration time — V0 pre-launch may have zero) migrate to `ProfileClaim` rows with `verified_method="admin_legacy"`, `verified_by_admin=<migration_admin>`, `role="admin"`.

### Direct flow impact

- New view: claim entry form (public, Turnstile-gated) on `/p/{slug}/claim/`.
- New view: magic-link confirmation handler at `/accounts/claim-confirm/<token>/` (mirrors existing magic-link patterns in accounts/).
- New admin queue surface for `verified_method="admin_review"` track — surfaces pending claim requests with submitted email, free-text reason, viewing User.
- New email template for claim magic-link (separate from signup/login magic-link templates per ADR-008 D2 — no premature consolidation; extract from third diverging caller).

### Carried forward

- ADR-001 D1 curated-trust posture continues — fast-path is opt-in; admin retains universal fallback.
- ADR-006 D2 organizer LIA continues — claim moment becomes an explicit consent-capture point (organizer transitions from admin-curated-LIA basis to claim-confirmed Art. 6(1)(b) contract basis for editing actions). Migration of lawful basis at the moment of first claim is in scope for the implementation children.
- ADR-013 trust posture is consumed at the claim-completion edge: a User who successfully claims their first Profile likely transitions in admin discretion from `status='open'` to `status='vouched'`, though this is admin-mediated per ADR-013 D1, not auto-fired by claim completion.

### Risk

- Migration from `Profile.claimed_by` FK to `ProfileClaim` through-model is a touchpoint for organizers/, accounts/, and any view/template that read `profile.claimed_by`. Plan as an epic with shippable child beads.
- `verified_domain` collisions (two Profiles claiming `@iksk.berlin`) — admin-mediated by hand in V0; if frequent, add a uniqueness constraint or admin-review tie-breaker. Cheap foresight: don't constrain the schema preemptively.
- Magic-link delivery dependence on email infrastructure (already a dependency for signup; no new risk surface).

## canonical_refs

- [ADR-001 D1](ADR-001-core-product-and-stack.md) — FIRM curated-trust model; claim flow operationalizes the trust-gate at the Profile-ownership boundary.
- [ADR-003](ADR-003-cheap-foresight-patterns.md) — cheap foresight discipline; D1's `role` field and `verified_domain` opt-in field are cheap-foresight applications.
- [ADR-006 D2](ADR-006-legal-gate-execution.md) — FIRM organizer LIA basis; claim moment is the lawful-basis-migration trigger from LIA (Art. 6(1)(f)) to contract (Art. 6(1)(b)).
- [ADR-007 D5](ADR-007-profile-centric-schema.md) — FIRM (evolved in place per ADR-011 D1) — original single-FK `claimed_by` replaced by through-model; cardinality 0..1 → 0..N; decision-property "Profiles are claimable" unchanged.
- [ADR-008 D1](ADR-008-code-posture-refactor-hard-fail-loud.md) — D1 predicates (firmness, rationale, alternatives, invalidation, warrant tags); D2 no speculative behavioral abstraction (claim flow ships the simplest two-track form; richer roles deferred); D3 fail-loud on data integrity (no silent fallback on domain-match parse failure or magic-link token tampering).
- [ADR-011 D1](ADR-011-adrs-reflect-target-architecture.md) — FIRM in-place ADR evolution; routes the ADR-007 D5 evolution.
- [ADR-013 D1+D3](ADR-013-user-trust-model.md) — EXPLORATORY user trust posture; claim-completion is a downstream signal for `User.status` transitions; ADR-013-referenced Turnstile primitive applies at D3's pre-issuance gate.
- [bead kb-m69](https://github.com/jsnyde0/switch-berlin) — origin brainstorm (Identity and Trust Model). D1 (web-first claim with email-domain fast-path) and D2 (multi-claimant ProfileClaim through-model) canonicalized in this ADR.

## Post-write follow-ups (filed as separate beads per ADR-008 D4)

- ADR-007 D5 in-place evolution lands in the **same commit** as this file (the through-model is the substrate this ADR builds on; splitting would create a substrate-less ADR for the duration of the gap).
- `/decompose kb-m69` once all three trust-cluster ADRs (ADR-012, ADR-013, ADR-014) are in place — split into implementation children spanning schema migration, claim views, admin queue surface, and magic-link plumbing.
- Cross-link review: ADR-013 already references "forthcoming ADR" for User trust model (kb-f7n captures the ADR-012 forward-ref cleanup); no equivalent forward-ref cleanup is currently needed for ADR-014 because ADR-013 cites trust-model decisions, not claim-flow.
