# Community-Membership Models — Discord, Slack, Reddit, Lemmy

**Source:** web research, 2026-05-27. Sources at the end.

## The big takeaway

**Discord, Slack, and Reddit all run a single global account system inside one platform, and layer per-community membership and roles on top.** None needs separate federated servers to give each community its own walls, roster, and trust rules. **Lemmy** is the one that *does* federate — and it's the cautionary contrast for why you probably don't want that at small scale. This file is the strongest evidence that the bubble model is an **authorization model, not an infrastructure model.**

## 1. Discord (servers / "guilds") — closest analog to bubbles

- **Membership:** one account, join many servers. The *only* default way in is an **invite link** — no public directory. Maps almost exactly to "vouched into a bubble": an insider hands you a link.
- **Roles & permissions are per-server:**
  - Permissions attach to **roles, not people** — trust scales without per-user fiddling.
  - Multiple roles → **union** of permissions.
  - Roles are **strictly per-server** — `@Moderator` in Kara House means nothing in IKSK. Same account, independent standing.
  - **Hierarchy:** you can only manage roles *below* your own, and only grant permissions you hold. Prevents privilege escalation for free.
  - **Cascade:** server-wide defaults → per-channel overrides (win) → per-user overrides. A bubble gets a private inner channel without inventing a new role.
- **Invites (= vouching, productized):** set **expiry** (30 min → Never), **max uses** (1, 5, … unlimited), **revoke** instantly. Who can mint *permanent* invites is itself permission-gated.

**Walk-through:** Kara member creates an invite "expires 1 day, max 1 use," sends it. You click, land as bare `@everyone`. A mod assigns `@Member`, unlocking member-only channels. The single-use link is now spent and dead — exactly "one vouch, one entry."

## 2. Slack Connect = "two bubbles consent to share a space"

Standard workspace membership = a single bubble. **Slack Connect** is the feature that matters: it lets **two separate organizations share one specific channel** while each keeps its own members, admins, and policies. Literally "two bubbles share a room without merging."

The consent handshake is **double opt-in**:
1. Org A invites Org B (A's admins may need to approve sending).
2. Org B accepts (B's admins can restrict who may accept / require approval).
3. Admin approval on **both** sides before the channel goes live.
4. After connection, **each side independently controls** what the other can do (e.g. "post & invite" vs "post only").

Two more transplantable ideas:
- **Per-partner auto-approve:** once Kara and IKSK trust each other, "auto-approve all future shared channels from this org" — so allied bubbles skip the repeated handshake.
- **Sharing is per-space, not all-or-nothing.** Org B sees only the shared channel, never the rest of A's workspace. **This is the crucial property: opt-in sharing is scoped to a resource, not the whole bubble.**

## 3. Reddit vs Lemmy — centralized vs federated

**Reddit (centralized)** — the cleanest illustration of the target pattern:
- One global account; "joining" a subreddit is just **subscribing** (feed customization, not a new identity).
- **Moderation is fully per-community** (each subreddit's mods + AutoModerator).
- Communities can **gate entry on global signals** — "need 50 karma, 30-day-old account." Global reputation feeds *local* trust decisions.
- Bans are two-tier: **subreddit ban** (local) vs admin **site-wide ban** (kills the account).
- → **Global identity + global reputation, but local membership, rules, and trust.**

**Lemmy (federated, ActivityPub)** — each community lives on an instance; instances sync over ActivityPub. Federation buys instance autonomy, leave-a-bad-host ability, distinct per-instance culture, public modlog. But at **small scale the costs bite:** thin activity in niche communities, flaky sync, steep newcomer learning curve (local-vs-all confusion), and **defederation risk** (a host you depend on can sever ties). Crucially: **federation's main payoff — escaping a bad central host — is something you already control as the platform operator.** You'd pay all the complexity for a benefit you don't need yet.

## The common pattern to steal (this IS the bubble model)

Every centralized one runs the **same three-layer model**:

1. **One global identity** — single account per person, reused everywhere.
2. **Per-community membership as a join record** — a row linking `user ↔ community` carrying that community's roles/standing. Joining adds a membership; it does **not** mint a new identity. Independently revocable per community.
3. **Per-community trust & roles, scoped locally** — roles/permissions/moderation live inside each community, mean nothing outside. A global signal (karma) can *optionally* feed local gating, but the *decision* is local.

…with a **sharing layer** on top: an explicit, double-opt-in, **per-space** edge between two communities (Slack Connect) — both admins consent, scoped to one shared resource, each side keeps independent control, revocable, optional "trusted partner → auto-approve."

**All of this is plain rows in one database:**
```
users
memberships   (user_id, bubble_id, role)
invites       (bubble_id, code, expires_at, max_uses, uses)
bubble_shares (bubble_a, bubble_b, scope, status)
```
No federation protocol, no separate servers. The "feels decentralized" experience is an **authorization model**, not an infrastructure model.

## What to steal / what to skip

**Steal:**
- **Invite-link joining with expiry + max-uses + revoke** (Discord) — vouching, productized. Single-use, time-boxed links = "vouched in by one member."
- **Per-community roles as named permission bundles, assigned to people, with a manage-hierarchy** (Discord) — union-of-permissions and "can't grant above yourself" are free correctness wins.
- **Per-resource permission overrides** for a private inner space without new role types (Discord).
- **Double opt-in, admin-approved, per-space sharing with independent controls** (Slack Connect) — bubble-to-bubble sharing done right.
- **Per-partner auto-approve** for allied bubbles (Slack Connect).
- **Global identity + optional global reputation feeding *local* trust gates, with local-vs-global ban tiers** (Reddit).

**Skip:**
- **Federation / ActivityPub / separate servers** (Lemmy) — sync fragility + defederation risk + onboarding friction, for a benefit you already hold as operator. Model sharing as a consented DB edge, not wire-protocol federation.
- **Open public directories / open-join** — bubbles are invite-gated by nature; borrow Reddit's *moderation* model, not its open-subscribe model.
- **Per-community separate logins/identities** — defeats the "one global identity" insight every platform deliberately preserves.

## Sources

- [Discord — Invites 101](https://support.discord.com/hc/en-us/articles/208866998-Invites-101) · [Roles and Permissions](https://support.discord.com/hc/en-us/articles/214836687-Discord-Roles-and-Permissions) · [Permissions FAQ](https://support.discord.com/hc/en-us/articles/206029707-Setting-Up-Permissions-FAQ)
- [Slack Connect overview](https://slack.com/help/articles/360035092414) · [Channel approval settings](https://slack.com/help/articles/115005912706) · [Managing Slack Connect (engineering)](https://slack.engineering/managing-slack-connect/) · [Multi-workspace channels](https://slack.com/help/articles/115004485887)
- [Reddit karma/moderation overview](https://www.techtimes.com/articles/315552/20260330/reddit-power-users-explained-karma-systems-moderation-growth-strategies.htm)
- [Lemmy Federation docs](https://join-lemmy.org/docs/contributors/05-federation.html) · [Understanding ActivityPub Part 2: Lemmy](https://seb.jambor.dev/posts/understanding-activitypub-part-2-lemmy/)
