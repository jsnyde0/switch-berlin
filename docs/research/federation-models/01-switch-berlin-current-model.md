# Switch Berlin — Current Model (the monolith we start from)

**As of 2026-05-27.** Sourced from in-repo ADRs + bd memories via `/recall`.

## One-sentence version

Switch Berlin is a **single community with one trust layer**. You're either in or out of *Switch Berlin*, full stop. There is no notion today of separate trust domains you'd be vouched into independently.

## The trust machinery that exists

### User status
Every user has a status: `open`, `vouched`, `suspended`, or `banned` (ADR-013 D1). Vouching happens through a **vouch-graph** — existing trusted members vouch newcomers in — using **invite codes**, which admins hand out for now (V0 invite economy, ADR-013). The vouch graph carries *proportional consequences* with a one-hop cascade: if someone you vouched goes bad, it reflects on you.

### Two visibility systems — both community-wide
- **Profile identity visibility — 4 tiers** (ADR-009 D2): `public > vouched > friends > private`. Governs who can see a member's profile details.
- **Event visibility — 3 tiers** (ADR-012 D1): `public / semi_public / unlisted`, gated on whether the *viewer* is vouched. Read-side only — visibility does **not** gate outbound syndication (clarified 2026-05-26, ADR-016 D4/D5).

These two systems are **orthogonal** (different tier counts, different objects) and both currently scoped to the *whole* community, not to any sub-group.

### Enforcement
A **login-wall middleware** gates anonymous visitors — anonymous users get redirected (with a static-asset prefix exception so CSS/JS still loads).

### Identity & verification
Profiles are claimed via a `ProfileClaim` flow (ADR-014) with two-track verification: an email-domain fast-path plus an admin-review fallback, confirmed by a single-use magic link. `verified_method` is a canonical enum: `email_domain`, `admin_review`, `admin_legacy`, `auto_self`.

## How "houses / bubbles" are modeled today

They **aren't** — not as a first-class thing. A house like Kara or IKSK would today be a **collective Profile** (`Profile(kind=collective)`, ADR-007 D1) with co-organizers attached via `ProfileClaim` rows. That's effectively a *shared account that runs events*. It is **not** a separate trust domain, has no its-own-members concept, and no notion of "consent to share with another house."

## What's missing for the bubble model

- No first-class **bubble/house entity** with its own membership roster.
- No **per-bubble vouching** (today vouching is global to Switch Berlin).
- No **cross-bubble trust** rules ("vouched in Kara ≠ vouched in IKSK").
- No **consent-to-share** mechanism between bubbles.

This is exactly the open territory the rest of this research informs.

## Strategic-frame note (don't confuse the two federations)

The project already carries a **city-federated brand** frame (switch.berlin → switch.amsterdam → switch.lisbon). That is **brand replication per city**, a different axis from the **entity-level bubble federation** explored here. The bubble model is about independent houses *within* a scene choosing whether to interoperate — not about cloning the product to a new city.
