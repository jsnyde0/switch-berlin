# Community Creation & Governance

**Source:** web research, 2026-05-27. Sources at the end. Answers the open question: *who/when/how are bubbles created, and should every event-organizer be a bubble?*

## Headline answer: no — make "bubble" a heavier, opt-in graduation

The evidence says don't conflate "runs an event" with "owns a gated community with a vetted roster." **Luma is the closest precedent and the strongest fit:** it cleanly separates **host** (runs events) → **subscriber** (follows, lightweight) → **member** (gated, vetted, opt-in). Forcing every casual organizer to carry membership governance, vetting, and succession they didn't ask for is the wrong default — and in a kink/safety context, *a vetted member roster you don't actively govern is worse than no roster*, because it implies a safety guarantee you aren't backing.

## 1. Who can create a community — the gate spectrum

- **Discord — zero gate** (free, instant, up to 100 servers/account). Bets on volume; *adds* structure later (a server becomes a discoverable "Community server" only on opt-in).
- **Reddit — soft fuzzy reputation gate** (~30 days old + ~50–200 karma + clean history; numbers deliberately unpublished + adaptive so spam farms can't tune). Anti-abuse, not quality.
- **Meetup — money is the gate** (paid organizer subscription required to create a group). Paywall self-selects committed organizers + funds the platform.
- **Mighty Networks / Circle.so — creator-economy paid SaaS** (monthly platform fee + transaction fees; you run a membership business). Money gate framed as "you're a business."
- **Geneva — free, casual, no monetization** (friends-who-know-each-other).
- **Luma — anyone, free, event-first**; the primitive is the *event/calendar*, not the *community*. Membership is an optional layer.

**Gate philosophies:** *no gate* (Discord/Luma/Geneva) bets on volume + opt-in graduation; *fuzzy reputation* (Reddit) targets abuse cheaply; *money* (Meetup/Mighty/Circle) self-selects commitment + funds platform; *vetting* (kink/sensitive, §5) targets safety.

## 2. "Organizer" vs "community-with-members" — the spectrum

| Weight | Example | Roster? | Vetted? |
|---|---|---|---|
| Just run an event | Luma host + attendees; Reddit | No real roster | No |
| Followers | Luma subscribers; Reddit subs | Soft list | No |
| Open membership | Meetup group; Discord server | Yes | No |
| Gated/paid membership | Luma Membership; Mighty/Circle paid tiers | Yes | Paywall |
| Vetted membership | kink collectives, Hacienda, CSPC | Yes | References/orientation |

**Luma's explicit layering is the model:** Host (lightest, run events forever with no community) → Subscriber (free follower, no commitment/gating) → Member (formal gated layer you must enable: tiers, member-only visibility, optional private-club hide-from-non-members). Removing membership leaves someone a subscriber. → *every organizer is a host; "community with vetted members" is a separate opt-in thing. Subscribers ≠ members by design.*

## 3. Governance once created (ownership, succession)

- **Discord — cautionary tale:** exactly **one owner**; ownership does **not** auto-pass to admins. If the owner abandons/deletes their account, the server enters **limbo** — runs on, but owner-only actions become impossible; recovery needs a Support petition with strict criteria. **Single-owner-with-no-succession is fragile.**
- **Circle/Mighty:** multiple admins but capped (cheaper plans ~3); the paying account is de facto owner.
- **Reddit:** creator becomes top mod; abandoned subs reclaimable via r/redditrequest.

**Takeaway:** design **multi-owner / co-steward + a defined succession path from the start.** Don't tie a bubble's existence to a single founder account.

## 4. Anti-sprawl, abandonment & quality

The bar for *existing* is low everywhere; the bar for *being discoverable / kept alive* is where quality is enforced.

- **Discord** — no creation limit; gates *visibility* (only opted-in Community servers meeting bars hit Discovery). Sprawl is fine if invisible.
- **Reddit** — actively fights abandonment: inactive-mod subs claimable; **subs that lose all mods get banned ("unmoderated")** and are unrecoverable. Stance: an unmoderated community is worse than none.
- **Meetup/Mighty/Circle** — the money gate is also the abandonment-detector (stop paying → lapse).
- **Luma** — event cadence is the signal; a dead calendar just stops showing events (no ghost-roster problem since the calendar, not membership, is the unit).

**Pattern:** separate "exists" from "listed." Gate discoverability, not creation; have a non-destructive abandonment path (re-home/archive, not Reddit's destructive ban).

## 5. Verticalized / sensitive-community vetting (most relevant)

Sensitive communities gate on **safety via accountable vouching**, not money or karma:

- **Hacienda** (vetted play community): application + **reference check** — they contact your named reference to confirm they know/trust/vouch for you. ~7-day approval. Closest existing analog to gating a bubble.
- **CSPC** (nonprofit): mandatory **in-person new-member orientation** before joining — vetting via consent education.
- **Real-world kink houses (the Kara/IKSK analog):** canonical **munch → vetting → invite**. Invite-only curated parties; references where the voucher is **co-accountable** (misbehave → both barred). Membership often **free** — "applications are purely for safety and community vetting," not revenue.
- **FetLife:** notably does **NOT** do heavy group vetting natively — real vetting happens off-platform; the friend-graph is the only soft gate. The dominant platform punts vetting to the community. A gap.
- **Feeld / Plura / HER:** vetting via *audience self-selection* (word-of-mouth, FLINTA-only norms) + paid tiers, not formal references.

**Key insight:** the voucher's **co-accountability** is the safety mechanism mainstream platforms lack and FetLife outsources. And the cultural norm is that **vetting is free** — paywalling a safety community contradicts the culture and excludes the people safety-vetting is meant to protect.

## Recommended shape (for the bubble model)

1. **Two-tier creation.** "Host an event" = open, instant, no roster. "Create a bubble" = opt-in, gated by vouching, carries a member roster + governance.
2. **Membership ≠ following.** Borrow Luma's subscriber-vs-member split: follow a bubble's events without being a vetted member.
3. **Multi-steward + succession by default.** Avoid Discord's single-owner limbo; bubbles should outlive their founder.
4. **Anti-sprawl via discovery, not creation.** Let bubbles exist quietly; gate *listing* on an activity/vetting bar. Non-destructive abandonment path.
5. **Vet on accountable references, free.** Keep money out of the safety gate — cultural norm *and* safety mechanism.

> Note: the repo already has `syndication/authz.py` + vouching work in flight, consistent with building toward accountable-vouching gating. (Verify current state before treating as load-bearing.)

## Sources

- Discord: [Create a server](https://support.discord.com/hc/en-us/articles/204849977) · [Transfer ownership](https://support.discord.com/hc/en-us/articles/216273938) · [Requesting a transfer](https://support.discord.com/hc/en-us/articles/26286635870359)
- Reddit: [Karma to create a subreddit (2026)](https://www.soar.sh/blog/karma-to-create-subreddit-2026) · [Take over an inactive community](https://support.reddithelp.com/hc/en-us/articles/360043478471) · [r/redditrequest](https://support.reddithelp.com/hc/en-us/articles/15484355484692)
- Meetup: [Organizer subscription prices](https://help.meetup.com/hc/en-us/articles/28677808413197)
- Circle/Mighty: [Circle vs Mighty Networks](https://www.group.app/blog/circle-vs-mighty-networks/)
- Luma: [Calendar Memberships](https://help.luma.com/p/calendar-memberships) · [Calendar Overview](https://help.luma.com/p/luma-calendar-overview)
- Vetted communities: [Hacienda FAQ](https://wearehacienda.com/faq/) · [CSPC Membership](https://thecspc.org/membership) · [Play Party Etiquette / vetting](https://msmorganthorne.com/play-party-etiquette-first-timers/) · [FetLife privacy](https://trypoise.app/kink-community/fetlife-privacy-settings)
