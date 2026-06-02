# Gates & Selective Integration

**Source:** web research + in-session synthesis, 2026-05-27. Sources at the end.

## The reframe this file is built on

"Trust" in a bubble + events product is not one thing. It decomposes into **independent gates**, and the products that handle communities well expose them as **separate toggles**. The two that matter most and are most often confused:

- **Membership gate** — *are you part of this bubble?* (the vouching question)
- **Attendance gate** — *for this specific event, can you get in?* (RSVP / ticket / approval)

These are different decisions. Someone can attend an open event of a bubble they're not a member of; a member can be auto-approved for member events. Switch already has the attendance gate (sign-up forms) and a visibility gate (ADR-012); the membership gate is the part that's currently global rather than per-bubble.

**The blunt finding:** existing event platforms share *visibility* well, *fake* door-access via invites/ticket-types, and almost never cleanly decouple *roster membership* from *door access* or support *cross-org vouching*. The model that treats "honor at the door" and "is a member" as truly orthogonal lives in the **membership-association / museum** world, not event-tech — which is exactly the white-space a per-gate-toggle design targets.

## Part A — The attendance-gate spectrum

From most open to most closed, the gate types that recur across platforms:

`open RSVP` → `RSVP + screening questions (visible to host, no gate)` → `request-to-attend + manual approve/reject` → `rules-based / members-only auto-gate` → `invite-only (no public request path)`

Where platforms sit:

- **Luma** — most granular. Per-event "Require Approval" → Pending queue → host approve/decline. Arbitrary **application questions** (incl. Terms/signature). Capacity + **waitlist**. Approval combines with payment (card held, captured on approval). **Invited guests bypass approval** (invite = pre-approval). Settable **per ticket type** — one event can have an open free tier + an approval-gated tier at once.
- **Posh** — cleanest **application-and-approval funnel**. Per-ticket-type "Require Approval" → Pending tab → approve/deny before purchase. Adds **social-vetting** (require LinkedIn/IG/Twitter) + optional password. Closest to a true curated/members-only experience.
- **Partiful** — lightweight, private-by-default (link-only). Gate is a single binary **"Guest Approval"** toggle. Separately: **"Allow Guests to Invite Mutuals"** (viral-spread control) and **guest-list visibility** (host can hide/anonymize) are their *own* independent toggles. No screening questions.
- **Meetup** — gating at two separate levels: **group join** questions vs **event RSVP** questions (answers org-only). Member-only achieved via **private groups**. Capacity → waitlist. Weakness: **cannot hide the attendee list**.
- **Eventbrite** — gates **upfront by access**, not post-hoc review: public → unlisted → private (link/password) → **invite-only**. No request→review funnel.

**Per-event host choice?** Luma and Posh are strongest (per-event *and* per-ticket-tier). Partiful is per-event but binary. Meetup mostly inherits from group privacy. Eventbrite is per-event but only on the access axis.

## Part B — Selective integration between separate communities

The "share some dimensions, keep others separate" pattern exists, but most event platforms only do part of it.

- **Meetup Pro networks** — shares branding, cross-group messaging, network-wide analytics, and a **Network Event Scheduler** (one event → many groups). **Keeps separate:** each group's roster (network membership ≠ sibling-group membership). Telling boundary: **private groups can't join a Pro network** (would leak member info to non-member admins). → shares events+branding+analytics, membership stays per-group.
- **Luma Calendars** — per-calendar **membership tiers** with own join questions + approval + member-only events/tickets. Membership strictly **per-calendar**. Cross-listing = **move/transfer an event** between calendars (or feature on city Explore), but an event lives on **one calendar at a time**; moving doesn't merge members. → separate rosters + wider surfacing, no reciprocal member-recognition.
- **Mighty Networks** — **Spaces** = gated sub-communities *within one network* (space-level event visible only to space members). Excellent intra-network scoping, but **no cross-*network* sharing** — the single network is the trust boundary.
- **Museums — NARM / ROAM (the archetype):** the purest "independent toggles per dimension" instance. You're a member of **one home institution**; your card is honored for **admission at every network institution** — but each keeps its **own roster** and you are *not* a member of the others. Two orthogonal dimensions made explicit:
  - **Door/access recognition** = shared (present card → free general admission).
  - **Membership/roster** = NOT shared (member only of home org).

  Further decomposed: shared admission **excludes** special exhibitions, ticketed events, parking — those stay separately gated. There's even a **"distance exclusion"** (no reciprocity within ~90 miles of home) — a *per-edge condition* on the toggle. And **NARM and ROAM don't honor each other** — federation is opt-in per institution. Strongest evidence that mature ecosystems model "honor at the door" and "are a member" as genuinely orthogonal switches.
- **Association reciprocal agreements** — generalize the shape: two orgs negotiate à la carte *which* dimensions to share (cross-join discount, mutual newsletter, member-list exchange), and explicitly decline to federate when too similar.

## Synthesis — the distinct dimensions of sharing (treat each as an independent, per-edge, double-opt-in toggle)

1. **Event visibility / discovery** — can B's members *see* A's events? Most commonly shared; safest. (Luma feature/subscribe; Meetup Pro push; Mighty network-vs-space.)
2. **Event attendance / door access** — can a B member *attend* an A event without being an A member? **The dimension most platforms DON'T cleanly support — your differentiator.** (Museum reciprocal admission is the archetype.)
3. **Membership / roster recognition** — does B "know" A's members as members? Almost always kept **separate**. Reciprocity recognizes *status at the door* without merging *rosters*.
4. **Per-event approval gate** — open / questions / request-review / members-only / invite-only; per event and per ticket-tier (Luma, Posh). Independent of 1–3.
5. **Vouching / co-vouching** — can an A member's vouch carry weight in B's screening? No mainstream event platform does this natively. **Genuine white-space.**
6. **Branding / identity** — shared network branding vs each community keeping its own face. Separable.
7. **Sub-gate granularity within "access"** — even attendance decomposes: general admission ≠ special exhibition ≠ ticketed ≠ parking. Maps to "this community" vs "this event" vs "this *tier* of event."
8. **Edge conditions on a toggle** — a sharing toggle isn't just on/off; it can be conditional per relationship (museum 90-mile rule; agreements declined on overlap).

## Implications for the bubble model

- The "how do bubbles integrate" question is **not one switch** — it's a small matrix of independent toggles (visibility / door-access / roster / vouching / branding), each double-opt-in and revocable per pair of bubbles. This is exactly the user's intuition ("share events but not vouching").
- The **membership model can be lighter than it first seemed**, because the per-event attendance gate (already present as sign-up forms) carries a lot of the "who gets in" weight independently.
- The **most valuable, least-served** dimensions for this product are **door-access recognition decoupled from roster** (#2/#3) and **cross-bubble vouching** (#5) — neither is well-served by existing event-tech, and both are precisely the bubble-federation idea.

## Sources

- Luma: [Registration Process](https://help.luma.com/p/event-registration-process) · [Payment + Require Approval](https://help.luma.com/p/payment-require-approval) · [Guest List](https://help.luma.com/p/managing-your-guest-list) · [Calendar Memberships](https://help.luma.com/p/calendar-memberships) · [Featuring Events](https://help.luma.com/p/featuring-your-event-on-luma)
- Partiful: [Event Settings](https://help.partiful.com/hc/en-us/articles/28895223149979) · [Hide guest list](https://help.partiful.com/hc/en-us/articles/26503238663195)
- Meetup: [Profile/event questions](https://help.meetup.com/hc/en-us/articles/360022471332) · [Pro features](https://help.meetup.com/hc/en-us/articles/360002877711) · [Linking groups / private-group restriction](https://help.meetup.com/hc/en-us/articles/360002862372)
- Eventbrite: [Invite-only feature](https://www.eventbrite.com/blog/ds00-eventbrite-adds-an-invite-only-feature/) · [Privacy settings](https://www.eventbrite.com/help/en-us/articles/305873/)
- Posh: [Require Approval & manage requests](https://support.posh.vip/en/articles/10723709)
- Mighty Networks: [Spaces](https://www.mightynetworks.com/encyclopedia/spaces)
- Reciprocity: [NARM How It Works](https://narmassociation.org/how-it-works/) · [ROAM](https://www.wonderfulmuseums.com/museum/roam-museum-reciprocal/) · [Reciprocal Membership Agreements](https://associationsnow.com/2023/12/reciprocal-membership-agreements/)
