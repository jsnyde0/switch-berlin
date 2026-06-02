# Mastodon — The Federated Model

**Source:** web research, 2026-05-27. Sources listed at the end.

## The one-sentence version

Mastodon isn't one website. It's thousands of independent websites running the same software, all able to talk to each other through a shared "language" — exactly the way **email** works: your Gmail and your friend's Outlook are different companies' servers, but they exchange mail because they agree on a common protocol.

## 1. The core federation model

- **Fediverse** = "federated universe." The network of independently-run social platforms that can all talk to each other.
- **Instance / server** = one independent installation of the software, run by one person or group, with its own URL, rules, and accounts. There is no "Mastodon HQ" — your account lives on whichever instance you signed up to.
- **ActivityPub** = the shared "language" (a W3C standard) that lets instances exchange messages. When you post, your server mails standardized copies to the other servers where your followers live. It's an open standard, so non-Mastodon apps (Pixelfed for photos, PeerTube for video) speak it too.

**What "federated" means for you as a user:** sign up on *one* instance, but follow / reply / like / boost people on *other* instances as if it were one network. The seams are mostly invisible. One consequence: no server sees the whole network, so "trending" differs per instance.

## 2. Instance autonomy & interoperability

Each instance is run independently, but **by default interaction is automatic**. If you're on A and get pointed to someone on B, you follow them and the servers start exchanging posts. No admin has to approve a "friendship" first. Catch: your server only learns about content it has a reason to fetch — undiscovered remote users may be invisible until someone interacts. Discovery is a known weak spot.

## 3. Consent / blocking between instances (most relevant to bubbles)

Instances choose who they federate with. Two opposite philosophies:

- **Blocklist mode (default): "open unless blocked."** Talk to everyone except explicitly-blocked servers. Max connectivity, weaker safety.
- **Allowlist mode ("Limited Federation Mode"): "blocked unless allowed."** Talk to *nobody* except servers on a hand-picked allowlist. Max safety, weaker reach. (Empty allowlist = fully isolated.)

> **Allowlist mode is the closest existing analog to "bubbles/houses that vouch for members"** — a community that only federates with a hand-picked set of trusted peers. Your jotted idea ("Kara and IKSK each have their bubble, decide whether to join, and if not-joined you're vouched in one but not the other") is the allowlist model almost line for line.

**Defederation / domain blocking** = cutting off a whole server. Two severities:
- **Limit / Silence** (soft) — posts hidden unless you already follow; existing follows become follow-*requests*.
- **Suspend** (hard) — no content stored, **all existing follows between the two servers deleted**; un-suspending does *not* restore them. Defederation is not cleanly reversible.

If A and B haven't agreed to federate, users effectively can't see or interact across the gap. **Authorized Fetch / "Secure Mode"** makes blocks actually enforceable (off by default, costs resources). Admins share **community blocklists** (`#FediBlock`, curated lists) to scale moderation — but each is a *signal, not a command*.

## 4. Identity (the big weakness)

Identity is **tied to your instance**: `@username@instance.social`, email-shaped. The admin of that instance ultimately controls your account.

**Can you move?** Yes, with real caveats:
- ✅ **Followers transfer** automatically (irreversibly force-switched to your new handle).
- ⚠️ **Who you follow + blocks/mutes** don't move automatically — CSV export/import.
- ❌ **Your posts do NOT move** — they stay on the old server (or vanish if it dies).
- ⚠️ **Old server must be alive** to migrate. If your instance dies first, you're largely stranded.
- ⚠️ **30-day cooldown** between moves.

Bottom line: identity is *portable-ish*, not truly portable. **Lock-in — your handle and history hostage to one admin's server staying online and friendly — is the single biggest structural weakness.** Bluesky was built to fix this (see file 03).

## 5. Moderation

Always **local and per-instance.** No central committee. Each instance's volunteer admins set and enforce their own rules, only on their own server. A mod on A cannot touch a user on B — only the *local copy* of their content.

Per-account tools: **Limit/silence**, **Freeze** (reversible lock), **Suspend** (effective delete). For bad *servers*, admins **defederate** rather than chase individuals — "reach is a privilege." Honest tradeoff: real autonomy and self-protection, but **moderation quality varies wildly** and there's **no guaranteed network-wide enforcement**.

## 6. Monetization (the loudest warning)

There is **no native, built-in monetization** — no ads, no platform-level payments in the protocol.

- **The Mastodon nonprofit** lives on donations + Patreon + grants + merch (volatile: €545K in 2023, but donor base *fell ~23%*). In 2025 it added **paid managed hosting** + support contracts for predictable revenue.
- **Individual instances** survive on donations, hosting co-ops, occasional fees, or an org absorbing the cost.

Challenges: costs scale with size (hundreds of $/month in hosting; media storage grows); donation volatility; donor governance distortion; heavy ops burden.

> For an events/community product: **federation gives you no revenue mechanism for free.** Each "house" bears real, scaling infra cost with no native way to recoup it.

## 7. Pros & cons vs centralized (Twitter/Facebook)

**Pros:** no single owner / capture point; community self-governance; no ad-surveillance model; defederation as a real safety lever; some exit rights.

**Cons:** weak discoverability (no global index, confusing onboarding); network effects fight you (value split across instances); inconsistent moderation; cost/sustainability on volunteers; lock-in/fragility despite "portability"; fragmentation (defederation splits the network into islands).

Centralized platforms invert every one: great discovery, pooled network effects, deep pockets, consistent (if opaque) moderation — at the cost of one owner, ads/surveillance, and no exit.

## What to steal / what to skip

**Steal:**
- **Allowlist semantics** — the consent-to-share model between bubbles. (As a *model* inside one DB, not as servers.)
- **Defederation severities** — the limit-vs-suspend distinction is a useful vocabulary for "soft-hide vs hard-cut" between bubbles.
- **"Reach is a privilege"** framing for cross-bubble sharing.

**Skip:**
- **The actual servers + ActivityPub protocol** — wrong tool at single-city scale; brings the two killers below.
- **Server-bound identity** — the lock-in problem. (See Bluesky's DID fix, file 03.)
- **Donation-only sustainability** — no native money is a non-starter for a product that needs to monetize.

## Sources

- [Fediverse — Wikipedia](https://en.wikipedia.org/wiki/Fediverse) · [Mastodon — Wikipedia](https://en.wikipedia.org/wiki/Mastodon_(social_network)) · [Fediverse — Britannica](https://www.britannica.com/technology/fediverse)
- [Using allowlists / Limited Federation Mode — Fedi.Tips](https://fedi.tips/creating-an-isolated-server/) · [How to defederate — Fedi.Tips](https://fedi.tips/how-to-defederate-fediblock-a-server-on-mastodon/)
- [domain_blocks API — Mastodon docs](https://docs.joinmastodon.org/methods/admin/domain_blocks/) · [Moderation actions](https://docs.joinmastodon.org/admin/moderation/) · [Moving accounts](https://docs.joinmastodon.org/user/moving/)
- [The Story Behind Mastodon's Push For Donations — Dataconomy](https://dataconomy.com/2025/07/24/the-story-behind-mastodons-big-push-for-user-donations/) · [Mastodon Systemic Sustainability — Nick Johnson](https://medium.com/@lim_nick/mastodon-systemic-sustainability-afe172699cb2)
