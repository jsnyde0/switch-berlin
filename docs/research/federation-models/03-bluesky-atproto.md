# Bluesky / AT Protocol — Portable Identity & Composable Trust

**Source:** web research, 2026-05-27. Sources at the end. Read through the lens: *what's borrowable as a model, even if we never touch their protocol?*

## 1. Portable identity — your identity isn't owned by the place that hosts you

Jargon:
- **DID (Decentralized Identifier):** a permanent machine ID like `did:plc:1234abcd`. The *real* you, tied to a keypair, not a company. Never changes.
- **Handle:** the friendly name (`@amato.bsky.social`, or your own domain `@amato.com`). Just a pointer *to* your DID. Changes freely.
- **PDS (Personal Data Server):** the server hosting your data. You can move it.

**The trick:** people see/search by handle, but posts, social graph, and followers are anchored to the *immutable DID*, not the server. So you can switch hosts and keep everything. "Like keeping your phone number when you change carriers."

**Why it beats Mastodon's lock-in:** Mastodon fuses identity + storage + app into `@you@server`. Bluesky decouples all three — switch any one without losing the others.

**Map onto bubbles:** a member's identity should belong to *the member*, not to Kara or IKSK. Model **"person" as a first-class entity separate from "membership"**: one stable internal ID + a presentable handle; bubble memberships, vouches, and reputation *attach to* that identity rather than *being* it. Leaving a bubble, moving between bubbles, or belonging to several at once — you carry identity, verified history, and trust signals with you. The bubble is *a context you're a member of*, not the namespace that defines you. **You don't need DIDs or crypto to get this — just model person ≠ membership.**

## 2. Composable / stackable moderation — trust & safety as subscribable lenses (top pick)

Jargon:
- **Label:** a tag on a person/content — `spam`, `nsfw`, `trusted`, `bad-actor`. Inert by itself; just metadata.
- **Labeler:** an independent service that publishes labels. Anyone can run one. Doesn't host data or run an app — just *applies tags*.
- **Stackable / subscribable:** baseline moderation + *subscribe* to additional labelers on top. *Your* app decides what each label *does* — hide, blur, warn, ignore.

**The big idea — "moderation as a marketplace":** traditional platforms bake moderation into one opaque central authority. Bluesky *unbundles* it into a pluggable layer. Real examples in production: `@aegis.blue` (LGBTQIA+ community moderation), *News Detective* (fact-checkers). Who you subscribe to is **private**, and labelers work across *any* app on the network.

**Map onto bubbles — strongest fit in all the research:** each bubble already *is* a trust/safety lens. Model each bubble's vetting as a **labeler** publishing signals like `vouched-by-Kara`, `host-verified`, `flagged-do-not-admit`. Then:
- A member's baseline is their *home* bubble's lens.
- A member or bubble can *subscribe to* other bubbles' lenses they trust — a cross-bubble event inherits the safety signals of bubbles you've chosen to trust.
- Each subscriber decides the *effect*: one bubble hard-blocks anyone another flagged; another just shows a warning.

This is exactly the federated-trust problem: "we trust Kara's vetting, so we honor their vouches and bans" becomes a **subscription, not a hardcoded merge** — transparent and revocable (you see whose lens you trust; you can unsubscribe).

## 3. Algorithmic choice / custom feeds — let the community decide what surfaces

Jargon: a **feed generator** is a small service that filters/ranks the firehose of posts and returns a skeleton (list of IDs) the app fills in.

**Why it matters:** instead of one black-box "For You," Bluesky is a *marketplace of feeds*. You always know *why* you see something — it matched a feed *you chose*. Ranking is deliberately **separated from moderation**, so reduced reach is never ambiguously "filtered vs just not ranked."

**Map onto a multi-bubble events product:** feeds become **curated views over people and events** — "events at bubbles I belong to," "events at bubbles that vouch-overlap with mine," "newly-vouched members in my network," "public events within 50km my trusted bubbles co-host." Keeps the "why am I seeing this?" answer legible — which matters enormously in a consent-sensitive scene.

## 4. Reality check — what works vs what's aspirational

Per a Jan 2026 assessment, Bluesky's decentralization is *"more of a blueprint than a fully constructed reality."*

**Still centralized in practice (late 2025 / early 2026):**
- ~99.99% of users on Bluesky PBC's own infra and app.
- The **PLC directory** (the DID→keys/host address book) is still Bluesky-operated — a single point of failure for identity.
- **Keys are custodial** — most users log in with username/password and Bluesky holds their signing keys. "You own your identity" has an asterisk.
- Outages feel exactly like a centralized-platform outage.

**Genuinely working:** the portable-identity *architecture* + migration tools; **composable moderation and custom feeds work in production today** (the most proven parts); independent infra emerging (Blacksky relay); PLC planned to move to an independent Swiss association.

**Takeaway:** the parts worth stealing (moderation lenses, custom feeds, identity-separate-from-membership) are the parts that *actually work*. The aspirational part (true infra decentralization) is exactly what you already said you don't want.

## What to steal / what to skip

| Idea | Steal? | Why |
|---|---|---|
| **Identity ≠ membership** (person first-class; bubble is an attached context) | ✅ Steal | Members move between / belong to multiple bubbles without losing vouches, history, reputation. The conceptual fix for lock-in. |
| **Stable internal ID + changeable display handle** | ✅ Steal | Cheap now; handles change without breaking references. |
| **Bubbles-as-labelers / subscribable trust lenses** | ✅✅ **Top pick** | Directly models "each bubble vets its own, others opt in." Trust transparent, revocable, composable. |
| **Subscriber decides the *effect* of a label** (hide/warn/block) | ✅ Steal | One bubble's flag = hard block for one community, soft warning for another. |
| **Custom feeds over a shared people/events graph** | ✅ Steal | "Why am I seeing this?" stays legible — critical in this scene. |
| **Separating ranking from moderation** | ✅ Steal | Removes "filtered vs just not ranked" ambiguity. |
| **Actual AT Protocol / DIDs / PDS / federation infra** | ❌ Skip | Heavy, still centralized in practice, solves a planet-scale problem you don't have. |
| **Custodial-key / crypto identity machinery** | ❌ Skip | Even Bluesky made keys custodial for usability. |
| **"Decentralization" as a goal** | ❌ Skip | Aspirational even for Bluesky. Borrow patterns, not ideology. |

### The single most stealable idea

**Model each bubble as a subscribable trust/safety lens (a "labeler"), and make cross-bubble sharing a matter of opting into each other's lenses — not merging databases.** It maps one-to-one onto the actual problem: bubbles already vet, vouch, and ban; "may opt to share" is *precisely* a subscription between lenses. Federated trust without federated infrastructure — Kara can honor IKSK's vouches/bans by subscribing, decide for itself whether a flag means block or warn, see whose judgment it trusts, and revoke instantly. Transparent, consent-respecting, composable — and proven in production today.

## Sources

- [AT Protocol Identity guide](https://bluesky-jp.github.io/guides/identity) · [AT Protocol — Wikipedia](https://en.wikipedia.org/wiki/AT_Protocol) · [Usable Decentralized Social Media (arXiv)](https://arxiv.org/html/2402.03239v2)
- [Stackable Moderation](https://bsky.social/about/blog/03-12-2024-stackable-moderation) · [Composable Moderation](https://bsky.social/about/blog/4-13-2023-moderation) · [Moderation/Labelers docs](https://docs.bsky.app/docs/advanced-guides/moderation)
- [Custom Feeds](https://bsky.social/about/blog/7-27-2023-custom-feeds) · [Feed Generator docs](https://docs.bsky.app/docs/starter-templates/custom-feeds)
- [Rethinking Bluesky's Decentralization (Jan 2026)](https://plurality.leaflet.pub/3mfergx7i7c2b) · [How decentralized is Bluesky really?](https://dustycloud.org/blog/how-decentralized-is-bluesky/) · [Protocol Check-in Fall 2025](https://docs.bsky.app/blog/protocol-checkin-fall-2025)
