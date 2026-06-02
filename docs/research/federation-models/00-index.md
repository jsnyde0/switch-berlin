# Federation & Bubble-Trust Models — Research Index

**Status:** research / pre-decision (brainstorm in progress, 2026-05-27)
**Question driving this:** Switch Berlin is a monolith today (one community, one trust layer). We want to move toward a **"bubbles" model** — independent houses/collectives (e.g. Kara house, IKSK) that each have their own vouched members and events, and that can *opt in* to sharing with each other. This folder captures research into how comparable systems do it, so we can steal the good ideas and skip the bad ones.

## The core finding (read this first)

Federation bundles **two separable things**:

- **The mechanism** — actually-separate servers running software, talking over a protocol (Mastodon, ActivityPub). Expensive, ops-heavy, shines only at large scale. Brings no native monetization and creates identity lock-in.
- **The model** — bubble-scoped membership + vouching, with opt-in consent to share between bubbles. The genuinely valuable idea. **Buildable inside one platform / one database with zero federation machinery.**

**Decision so far:** we want the *model*, not the *mechanism* — at least until operating across cities at real scale. Everything here is read through that lens: "what's the borrowable *model*, even if we never run their infrastructure?"

## Contents

| # | File | What it covers |
|---|------|----------------|
| 01 | [Switch Berlin — current model](01-switch-berlin-current-model.md) | How membership, vouching, and visibility work today (the monolith we're starting from). |
| 02 | [Mastodon — federated model](02-mastodon.md) | The canonical "federated" system; allowlist mode maps almost exactly to the bubble idea. Mechanism vs model split. |
| 03 | [Bluesky / AT Protocol](03-bluesky-atproto.md) | Portable identity (DID), composable/stackable moderation, algorithmic choice. The fix for Mastodon's lock-in. |
| 04 | [Community-membership models](04-community-membership-models.md) | Discord, Slack Connect, Reddit/Lemmy — "one identity, many memberships, opt-in sharing" done *inside* a platform. |
| 05 | [Vouching, invite-trees & web-of-trust](05-vouching-invite-trust.md) | Lobste.rs invite tree, private-tracker invite economy, PGP web-of-trust, Discourse trust levels, FetLife, real kink-scene vouching norms. |
| 06 | [Gates & selective integration](06-gates-and-selective-integration.md) | The gates are orthogonal (visibility ≠ membership ≠ door-access ≠ vouching). Event-platform approval spectrum + the museum reciprocal-membership archetype + the 8 dimensions of sharing. |
| 07 | [Community creation & governance](07-community-creation-and-governance.md) | Who can create a community + the org-vs-bubble spectrum. Headline: don't make every organizer a bubble — make "bubble" a heavier opt-in graduation (Luma host→subscriber→member). |
| 08 | [Lived experience of gating](08-lived-experience-of-gating.md) | **Most design-shaping.** How gating fails in real kink/queer communities: over-gating reduces safety, "missing stair," whisper networks fail newcomers, attendee-list scraping, revocable cross-bubble trust. |

## What the research converges on (still exploratory — no decisions made)

Across all eight files, a consistent picture emerged:

1. **Build the model, not the mechanism.** Everyone who isn't Mastodon/Lemmy builds "bubbles" as rows in one database. Federation-the-infrastructure costs monetization, discoverability, and identity lock-in for benefits you don't need at single-city scale.
2. **"Trust" is not one gate — it's several orthogonal ones.** Visibility ≠ membership ≠ door-access (attendance) ≠ vouching ≠ roster-recognition. The per-event attendance gate (already present as sign-up forms) carries a lot of "who gets in" weight independently of membership. The museum reciprocal-membership model (NARM/ROAM) is the clearest real-world proof that "honor at the door" and "is a member" are separate switches.
3. **Bubble is a heavier, opt-in thing than organizer.** Don't make every event-host a gated community. A vetted roster you don't govern is *worse* than no roster (it implies a safety promise you aren't backing). Luma's host→subscriber→member layering is the precedent.
4. **Cross-bubble integration is a small matrix of independent, double-opt-in, revocable toggles** (visibility / door-access / roster / vouching / branding) — not one "join" switch. Honors the user's "share events but not vouching" intuition.
5. **Identity belongs to the person, not the bubble** (Bluesky's lesson, achievable without DIDs): model *person* separate from *membership* so people can belong to / move between bubbles carrying their history.
6. **Bubbles-as-subscribable-trust-lenses** (Bluesky labelers) is the standout idea for cross-bubble trust: "Kara subscribes to IKSK's vouches/bans," deciding for itself whether a flag means block or warn — transparent, revocable, no database merge.
7. **Safety-design hard lessons (file 08, load-bearing):** gate *behavior* not identity; over-gating *enables* abuse via unaccountable gatekeepers; formalize over whisper-networks (which fail newcomers); always offer a connection-free on-ramp; hide attendee/membership lists by default; stake vouching with cost + quota; make cross-bubble bans severity-tiered and never auto-federating; make alliances cleanly revocable.

**Likely ADR-worthy decisions if/when this firms up** (per the brainstorm ADR-routing gate — NOT yet authored): the gate taxonomy (tier enum on a domain object), the bubble-vs-organizer boundary (scope-boundary call), the per-bubble vouching default-policy, and the cross-bubble sharing/ban-propagation policy ("for all X do Y"). Flagged here so they don't strand in research text.

## Relevant existing decisions (ADRs)

These already constrain or touch the design surface (surfaced via `/scout-adrs`, 2026-05-27):

- **ADR-001 D1** (FIRM) — curated-trust posture; admin-gated organizer approval. Foundation for trust decisions; currently assumes a *single* community.
- **ADR-009 D1–D3** (FIRM) — `Connection` mutual-friendship graph; 4-tier Profile visibility (public > vouched > friends > private); friends-tier RSVP social proof.
- **ADR-012 D1–D3** (EXPLORATORY) — Event visibility tiers (public / semi_public / unlisted); read-side only (does NOT gate outbound syndication).
- **ADR-013 D1–D4** (EXPLORATORY) — User trust model: `User.status ∈ {open, vouched, suspended, banned}`; two signup paths; `Vouch` graph w/ proportional consequences + one-hop cascade; admin-grant invite economy.
- **ADR-014 D1–D3** (EXPLORATORY) — Profile claim flow; two-track verification (email-domain fast-path + admin review); magic-link.
- **ADR-007 D1, D2** (FIRM) — unified `Profile` model with `kind` discriminator; houses/collectives modeled today as `Profile(kind=collective)` + co-organizer claims, **not** as a first-class bubble entity.

**Gap:** no ADR governs per-bubble vouching, cross-bubble trust, or "bubbles consent to share." That's the open design territory this research feeds.

> Note: there is a *separate* "federation" already in the strategic frame — a **brand** federation (switch.berlin → switch.amsterdam → switch.lisbon), i.e. one product replicated per city. That is a different axis from the **entity-level** bubble federation researched here. Keep them distinct.
