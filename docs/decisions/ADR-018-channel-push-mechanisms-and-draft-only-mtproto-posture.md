# ADR-018: Syndication channel push mechanisms and the draft-only MTProto posture

**Status:** Accepted 2026-06-11
**Parent:** [ADR-016 — outbound syndication architecture](ADR-016-outbound-syndication-architecture-event-post-projections.md) (the data model + publish lifecycle this ADR gives a *transport mechanism* to — ADR-016 owns what a projection IS and its state machine; this ADR owns how a projection physically reaches the destination platform); [ADR-011 D1 — personal-agent layer](ADR-011-personal-agent-layer-additive.md) (agent-extended scope may be agent-only — the saveDraft tier is such a capability); [ADR-017 D1 — agent is the user's delegate](ADR-017-authorization-edit-publish-policy.md) (the agent acts with the user's authority — here, on the user's own Telegram account)
**Scope:** arch — how an outbound projection is *physically delivered* to a destination platform, and the ToS-risk posture of acting on a user's own messaging account. Distinct from ADR-016 (the canonical data model, projection lifecycle, and publish state machine) and from ADR-017 (who is *authorized* to publish). This ADR governs *transport + risk*, not model, lifecycle, or authz.

## Context

ADR-016 models projections and a publish lifecycle but leaves the *delivery mechanism* per platform as an adapter detail. The first real channel (Telegram) forced the question, because the actual job-to-be-done is **fan-out**: a facilitator authors an event once and distributes it to their own channel **plus** the many community groups and forum-topics they participate in — most of which are **private** (no public username).

A live spike (kb-mztq, 2026-06-11) validated the mechanics against a real facilitator account and verified Telegram's behavior against `core.telegram.org` docs. Findings that shape this ADR:

- A **Bot API** bot can only post where the bot itself is admin/member — it cannot reach the private community groups a facilitator is merely a member of.
- A **deep-link** (`tg://resolve?domain=…&text=…`) can pre-fill a draft, but only addresses **public** (username-bearing) destinations.
- **MTProto `saveDraft`** (acting as the user's own account) places a server-side draft — text + link-preview card — that **syncs to all the user's devices without sending anything and without notifying anyone**. It reaches *any* dialog the user can post in, private or public, including forum groups. Validated live: private member-supergroups, own broadcast channels, and forum groups all received synced drafts the human could then send. **Correction (kb-ru55.6 dogfood, 2026-06-12):** within a forum, the draft is placed **forum-level** (`reply_to=None`) and is visible in whatever topic composer the human opens — **per-topic *pinning* via `top_msg_id` is stored correctly server-side (`ForumTopic.draft` populates) but Telegram Desktop does NOT render a topic-pinned draft**, so it is invisible to the user. The earlier spike conflated forum-level visibility with topic-pinning. Net: forum *reach* is real and visible; per-topic *pinning* is not a working delivery guarantee today (see D1 note + deferred kb-ru55.9).
- The real target filter is **"can the user post here"** — not chat type. Broadcast channels the user only subscribes to are dead ends.
- Telegram's documented permanent-ban enforcement for "flooding/spamming" is keyed to **sent messages and recipient reports**; a draft produces neither. Logging in via an unofficial MTProto client does put the account "under observation" (documented baseline).

This ADR canonicalizes the resulting tiered delivery strategy and the FIRM safety firewall so the adapters, the cockpit, and the agent/CLI don't each reinvent it.

## Decisions

### D1: Tiered push mechanism, selected per destination by type + "can the user post here"

**Firmness: FLEXIBLE** — converged from the kb-mztq spike; expected to gain tiers as new platforms onboard. Reversible per-tier as platform capabilities change.

A projection is delivered by the mechanism that fits its destination:

- **Own / admin channels** → **Bot API auto-post** (the Switch bot, added as admin, posts directly; no human send).
- **Groups / supergroups / forum groups the user can post in (INCLUDING private, no-username)** → **MTProto `saveDraft` as the user's own account**: the agent places a synced native draft (text + link-preview card); the **human reviews and sends** on their official client. This is the only mechanism that reaches private communities. **Forum-topic caveat (kb-ru55.6, 2026-06-12):** the draft is placed **forum-level** (`reply_to=None`), NOT pinned to a specific topic — a `top_msg_id`-pinned draft is stored server-side but **Telegram Desktop does not render it** (invisible to the user). The forum-level draft is visible in whatever topic composer the human opens; the **intended topic is conveyed via the distribute result** for the human to route. True per-topic pinning is deferred (kb-ru55.9).
- **Public destinations** → *also* offer a zero-auth **deep-link** (`tg://resolve?domain=…&text=…`) open-with-draft convenience (no MTProto session required).
- **Broadcast channels the user only subscribes to** → **not targets** (the user cannot post; excluded from the destination set).

**Rationale:**

- `direct:` spike kb-mztq + dogfood kb-ru55.6 — no single mechanism spans the set: the bot can't reach private member-groups, deep-links can't address private (no username), and `saveDraft` is the only path into private communities (verified live across private supergroups, own channel, and forum groups — forum drafts placed forum-level, not topic-pinned; see D1 caveat).
- `reasoned:` ADR-008 D2 (concrete-not-speculative) is *satisfied* by per-tier divergence here — the divergence is real and observed, not anticipated; a unified "channel push" abstraction would have to special-case all three anyway.
- `direct:` the dogfooding facilitator's real inventory was ~17 private member-supergroups vs ~7 public groups — the private-only `saveDraft` tier carries the majority of the value, not an edge case.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Bot API for all channels | `direct:` (kb-mztq) a bot cannot post into groups/channels it isn't admin/member of — it cannot reach the private communities that are the bulk of real fan-out targets. |
| Deep-links only (no MTProto) | `direct:` deep-links resolve **public usernames only**; the majority of the facilitator's real destinations are private/no-username, so this covers a minority. |
| One uniform "channel push" mechanism | `reasoned:` no mechanism covers own-channel (bot) + private groups (saveDraft) + zero-auth public (deep-link) at once; forcing one would special-case all three. ADR-008 D2 favors the concrete per-tier shape when divergence is already real. |

**What would invalidate this:**

- Telegram (or a new platform) ships an official multi-target broadcast/forward API that reaches a user's communities natively — the `saveDraft` tier could be subsumed by it.
- A platform onboards whose destinations fit none of the three tiers — add a tier rather than bending an existing one.
- A draft representation is found that Telegram Desktop renders **pinned to a specific forum topic** (kb-ru55.9) — the forum-topic tier would upgrade from forum-level to true per-topic placement. (The official apps support per-topic drafts, so some representation renders; ours — `InputReplyToMessage(reply_to_msg_id=topic_id, top_msg_id=topic_id)` — does not.)

### D2: The automated MTProto client only ever DRAFTS — never sends (the ToS firewall)

**Firmness: FIRM** — this is the load-bearing safety constraint that makes the entire MTProto tier defensible; reversal requires argument, not iteration.

The automated client (Telethon, logged into the user's own account) calls **only** `saveDraft`. It **never** sends a message. Every actual send is the **human's manual action on their official Telegram client**. Programmatic sending as the user (tier-3 auto-send) is **DEFERRED** behind explicit per-user opt-in plus recorded risk acceptance, and is out of scope here.

**Counter-argument (required for FIRM):** The natural pull is auto-send — a true one-click "post to all my communities" is more valuable than a human send-pass. But the value of *reaching* private communities is already fully captured by draft-placement; the only thing auto-send adds is removing the human's Send tap. That marginal convenience moves the system from "the automated client emits no outbound message" (outside Telegram's documented spam-ban surface) to "the automated client mass-sends as the user" (squarely the flooding pattern Telegram says is "banned forever"). The failure mode — permanent loss of the user's personal account — is severe and irreversible, so the human-send tap is worth making FIRM rather than leaving to convenience. This is not a recipe leak: it forecloses a real, tempting behavior (auto-send-by-default) on a safety basis, not an ossified judgment.

**Rationale:**

- `external:` `core.telegram.org/api/obtaining_api_id` + `/api/terms` — flood/spam permanent-ban enforcement is described against *sent/broadcast messages and recipient reports*; drafts create neither.
- `reasoned:` keeping the *send* on the human's official client means the only outbound messages Telegram sees are human-initiated, human-paced, and native — the automation is invisible to spam enforcement.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Auto-send as the user (tier-3) by default | `external:` mass-sending the same content across many chats is exactly the "flooding/spamming → banned forever" pattern (core.telegram.org); risks the user's personal account. Deferred behind explicit opt-in, never default. |
| Leave send-vs-draft to orchestrator/implementer judgment per case | `reasoned:` the firewall is load-bearing safety with an irreversible failure mode; leaving it to per-case judgment invites an implementer wiring auto-send "just for the own-channel" or "just for convenience" and eroding the guarantee. FIRM keeps it a single explicit boundary. |

**What would invalidate this:**

- Telegram publishes an official safe-harbor (e.g. a sanctioned rate or endpoint) for automated sending on a user's behalf — the firewall could relax to that boundary (still opt-in).
- A destination class genuinely requires send-not-draft and has no draft affordance — revisit for that class only, behind opt-in.

### D3: Accept the unofficial-client "under observation" baseline for the draft-only tier

**Firmness: FLEXIBLE** — a risk-acceptance posture; revisit if Telegram's enforcement behavior changes.

Logging into a user's account via an unofficial MTProto client (Telethon) places that account "under observation" per Telegram's docs — an **unavoidable baseline** of any MTProto approach, independent of what the client does. We **accept** this baseline for the draft-only tier because (a) reaching private communities + topics is otherwise impossible, and (b) the spam-ban *surface* is avoided entirely by never sending (D2). The session is the **user's own account, held locally by the agent** — it is **not a bot acting for a personal account**; the "userbot" label is misleading and should be avoided in product copy (it is *the user, automated, draft-only*).

**Rationale:**

- `external:` `core.telegram.org/api/obtaining_api_id` — unofficial-client logins are "automatically put under observation"; this is stated as a monitoring baseline, not a ban trigger absent spam.
- `reasoned:` per ADR-008 D3 (fail-loud, no silent fallback on integrity), the risk is surfaced honestly to the user rather than hidden; consent is informed.

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Refuse MTProto entirely (bot-only) | `direct:` (kb-mztq) forecloses the entire private-community fan-out — the core value of the product for Telegram. |
| Treat MTProto as risk-free / hide the baseline | `external:` the docs explicitly state unofficial-client accounts are monitored; pretending otherwise violates ADR-008 D3's honesty posture and mis-informs the user's consent. |

**What would invalidate this:**

- Telegram begins banning accounts for **draft-setting or unofficial-client login alone** (not just sending) — the entire MTProto tier's risk calculus flips and the saveDraft tier would have to be reconsidered.

### D4: The `saveDraft` tier is agent-side (a local client with the user's session), not server-side

**Firmness: FLEXIBLE** — placement decision; revisit if a server-side session-custody model with acceptable security emerges. (Elaborated 2026-06-11 with the execution split, capability ladder, and sync seam below.)

The `saveDraft` capability runs in the **agent/CLI on the user's own machine**, holding the user's MTProto session locally. The web UI orchestrates the cockpit (destination list, coverage tracking) but **structurally cannot** place drafts — only a client with the user's session can. The platform stays dual-surface (ADR-016 D3 co-equal API), but this specific capability is **agent-only** per ADR-011 D1 (agent-extended scope may be agent-only).

**Execution split, capability ladder, and sync seam (the orchestration model):** the split between web and agent is *by tier, not by surface* — the web is the full orchestration cockpit (author, destination picker, trigger distribute, coverage), and it **directly executes the two tiers that need no session**: Bot API auto-post to own/admin channels and public deep-link prefills. Only the session-required tier (D1's private groups + forum topics via `saveDraft`) is handed to the user's local agent for execution. This yields a **capability ladder, not a wall**: a facilitator who connects nothing still reaches their own channel (bot) and public groups (deep-link) from the browser alone; connecting a local agent *unlocks* private-community + forum-topic reach. The agent syncs **only destination metadata** (ids, titles, types, topic ids, postability) up to the platform so the web picker can render the inventory — **never message content** in that direction. A server-held session that would make the private hop web-executable is **deferred behind explicit per-user opt-in + recorded risk acceptance** (it would concentrate every facilitator's full personal-account session on the platform — the breach surface D4 exists to avoid); it is not a V0 default.

**Rationale:**

- `reasoned:` only a client authenticated with the user's MTProto session can call `saveDraft`; a browser cannot. The capability is therefore inherently client-side.
- `reasoned:` keeping the session **on the user's machine** avoids the platform custodying users' personal Telegram sessions — a large security/liability surface — and aligns with ADR-011 D1 (the agent layer is where account-bound, agent-natural capabilities live).

**Alternatives:**

| Alternative | Why rejected |
|---|---|
| Server-side MTProto (platform holds users' sessions) | `reasoned:` the platform would custody every facilitator's full personal-account session — a severe security/liability concentration. The local-agent model keeps each session on its owner's machine. |
| Drive `saveDraft` from the web UI | `reasoned:` structurally impossible — a browser has no MTProto session; only a local client with the user's credentials can place the draft. |

**What would invalidate this:**

- A server-side session-custody model emerges with acceptable security/consent properties (e.g. user-held keys, scoped delegation) — D4 would revisit whether the capability can move server-side without concentrating personal-account risk.

## canonical_refs

- [ADR-016 — outbound syndication architecture](ADR-016-outbound-syndication-architecture-event-post-projections.md) — D3 (co-equal API), D4 (projection→PlatformConnection destination), D5 (publish lifecycle); the data model + lifecycle this ADR transports.
- [ADR-011 D1](ADR-011-personal-agent-layer-additive.md) — agent-extended scope may be agent-only (D4 relies on this).
- [ADR-017 D1](ADR-017-authorization-edit-publish-policy.md) — agent is the user's delegate (the agent acts on the user's own account).
- [ADR-008 D2](ADR-008-code-posture-refactor-hard-fail-loud.md) — concrete-not-speculative (D1's per-tier divergence is observed, not anticipated).
- [ADR-008 D3](ADR-008-code-posture-refactor-hard-fail-loud.md) — fail-loud / honest surfacing (D3 risk disclosure).
- Spike bead **kb-mztq** — the live validation (saveDraft into private member-supergroups, own broadcast channels, and forum topics; deep-link prefill; the "can you post" filter).
- `core.telegram.org/api/obtaining_api_id`, `/api/drafts`, `/api/links`, `/api/terms` — external spec for saveDraft semantics, draft sync, deep-link prefill, and flood/spam enforcement.
