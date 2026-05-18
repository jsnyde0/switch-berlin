# Scout brief: community / social-network primitives for Switch Berlin

**Scouted:** Redlights · Diversia · FetLife · Upwork · Luma
**Focus:** authenticated experience — profiles, posts, messaging, groups, events, discovery, trust/verification, content moderation, monetization tiers; for Redlights + Upwork especially the provider-dashboard mechanics
**Date:** 2026-05-18 (retroactively amended 2026-05-18 — see footer)
**Method:** 1 docs-leaning pass (R1) + 1 authenticated re-scout pass (R2) for Diversia, FetLife, Upwork, Luma. Redlights stayed at R1 since the R1 scout was already authenticated. Final corpus 125 records (25/platform × 5 platforms, R2 superseding R1 where re-scouted); >70% `ui-screenshot` source_type. Raw records: `scout-features-switch-berlin-2026-05-18-raw/`.

---

## Parity matrix

Cells: `✓` direct UI/docs evidence · `~` inferred or partial-credibility · `✗` scout didn't see (NOT proven absent in product).

| Underlying job (user-language) | Feature shape | RL | Div | FL | Up | Lu |
| --- | --- | --- | --- | --- | --- | --- |
| "Be findable as the kink/role/orientation I actually am, not just via free-text bio" | Structured identity taxonomy with multi-select tags | ✓ services | ✓ gender×17, orientation, D/s roles, BDSM practices, social contexts | ✓ Gender×3, Orient×5, Role×5, Pronouns, ActivityLevel, LookingFor | ✓ skills tags | ~ bio + social links only |
| "Say what I'm into AND what I won't do" | Fetish/preference list with positive AND negative states | ✗ | ~ contact-intent selectors (positive only) | ✓ Into / Curious / Soft Limit / Hard Limit + giving/receiving sub-role | ✗ | ✗ |
| "Find people in my city/region open to what I'm open to" | Filtered member search with kink/identity criteria | ✓ rich filters (services, body, age, language) | ✓ but gated behind 'substantial profile' completeness | ✓ search by kinksters + Places hierarchy (no demographic filters by design) | ✓ rich client-side search of providers | ✗ (events, not people) |
| "Find events near me, this week, of the right vibe" | Geo + category event discovery | ✗ | ✓ calendar with country/region/type filters | ✓ Places + 50km radius + category + Friends-RSVPed filter | ✗ | ✓ Discover with auto-detected city + category + featured calendars |
| "Coordinate a gathering that matches my crowd" | Event creation with category/cost/RSVP/privacy | ✗ | ✓ visibility + dresscode + application-required + gender restrictions | ✓ category×5 + Public/FetLifers/Private + tagline/cost | ✗ | ✓ approval/capacity/waitlist/tickets/theme/blasts/check-in |
| "Cluster events under an identity (collective, host, calendar)" | Calendars / Groups / Networks as recurring containers | ✓ multi-platform listing across 3 sites | ✓ Networks (1400+) with Discussion/Documents/Events/Members tabs | ✓ Open vs Closed Groups with admin tools | ✗ | ✓ Personal + Team Calendars with subscribers, newsletters, paid memberships |
| "Send a message safely / control who can reach me" | Inbox with tiered privacy presets | ✓ anonymous mailbox (client → provider) | ✓ Spam settings + custom labels + storage quota (110kB free) | ✓ 4 named presets (Open/Kinky/Hardcore/Strict) + picture blur-by-default | ✓ compliance-enforced (no contact info pre-contract) | ✗ no member DM surface |
| "Trust this person is who they say they are" | Identity verification badge | ✓ Verified (photo with handheld sign or Skype cam-check) + Safe Sex auto-badge | ✗ no verification surface observed | ✓ ID or devil-horn photo → badge + higher limits | ✓ Identity Verification (35 Connects, 3yr validity) | ✗ no host verification badge |
| "Show I'm a quality member earned over time" | Tiered reputation/status | ~ Verified is binary, not tiered | ~ pervometer score (engagement, not reputation) | ✗ | ✓ Rising Talent → Top Rated → Top Rated Plus → Expert-Vetted with criteria | ✗ |
| "Signal interest without rejection cost" | Anonymous mutual-match | ✗ | ✓ "Seems nice/interesting" → Match | ✓ Crushing On (once/day, Supporter-gated send, free receive) | ✗ | ✗ |
| "See who's looking at my profile/listings" | Visitor log + analytics | ✓ stats: daily/monthly visitor counts, peak day, favorites, likes | ✓ visitor log (masked '?????' for free; VIP unlocks) | ✗ no analytics surface | ✓ My Stats: 12-mo earnings, JSS gauge, profile views/invites/impressions, proposal funnel | ✓ event-level Insights (views, top referrers, UTM, referral attribution) |
| "Boost my visibility temporarily / outbid the queue" | Promoted listing (auction or credit-based) | ✓ GOLD boost (2 credits = 6hr top placement); Planner auto-boost by time or page-position; banner ad slots | ✗ | ✗ (Supporter unlocks browsing, not boosting) | ✓ Boosted Proposals (auction for top-4 slots) + Boosted Profile (search auction) + Availability Badge (weekly Connects auction) | ~ Featured-curation submission (no payment, editorial) |
| "Pay for the platform / earn from the platform" | Monetization model — provider side | ✓ Credits ($-per-bundle) + SMS micro-pay (no subscription) | ✓ VIP single tier in 2/6/12-month bundles, ~€8–€32 | ✓ Supporter single tier, NON-recurring, €30/€60/€120/€240 lifetime | ✓ Connects $0.15/ea + Freelancer Plus $19.99/mo + 0–15% service fee per contract | ✓ Stripe ticketing 5% fee Free / 0% Plus ($59/mo per-CALENDAR) + paid calendar memberships |
| "Decide who can see my address/location/identity" | Granular visibility controls | ✓ geo-blocking by country list | ✓ network privacy, blocked-list | ✓ follower-approval, view-count opt-out, pic-blur, no demographic search by design | ✓ profile-on-break + earnings-hide (Plus) | ✓ event location hidden until guest approved; Public/Private/Member-Only visibility |
| "Report unsafe content / get the platform involved" | User reporting + admin review | ✓ listing review queue (manual approval pre-publish) | ✓ inline abuse-report links on every content type | ✓ tiered warnings (3-strike) + timeouts + bans across 10+ content types | ✓ Account Health dashboard + arbitration via Brief | ~ host-led RSVP approval; no surfaced T&S dashboard |
| "Keep a sub-community civil" | Group moderation tools | ✗ | ~ network owners + appointed moderators, mechanism not deeply observed | ✓ pre-moderation, timeout, member-removal, sticky threads | ✗ | ~ calendar admins approve submitted events |
| "Earn the right to be seen by gating new accounts" | Profile-completeness gates | ✗ (free open-listing model) | ✓ blocks advanced search + random-profile until photo+bio+sexuality data submitted | ~ implicit completeness signals only | ✓ 100% completeness unlocks Connects + Rising Talent eligibility | ✗ no completeness gate |
| "Build community knowledge together" | Community-authored reference | ✗ | ~ Library (stories/articles), Pervometer | ✓ Kinktionary wiki (1929 articles, 1107 contributors, peer-curated) | ✗ | ✗ |
| "Buy/sell kink-relevant goods" | Marketplace / classifieds | ~ rates and contact only | ✓ Bazaar (latex/leather/equipment/toys/party tickets, geo-filtered) | ✗ | ✓ (the whole platform IS this) | ✗ |
| "Discover trending content outside my social graph" | Algorithmic / curated content-feed tabs | ✗ | ~ "Everyone" feed view (global activity, not algorithmic) | ✓ /explore: Kinky & Popular · Fresh & Pervy · Stuff You Love · Friends & Following | ✗ (job feed, not content) | ✗ (event-focused) |
| "Sell pre-packaged offerings without waiting for an inbound request" | Productized service catalog | ~ listing IS the package, single-shape | ✗ | ✗ | ✓ Project Catalog — fixed scope/price/delivery, browsable as products | ~ paid calendar memberships are a package, not a service |

**Table-stakes floor (jobs most platforms address):** structured identity expression · filtered member-or-event discovery · inbox with privacy controls · user reporting + admin review · location/visibility controls. Anything that does not at least address these reads as parity-failure for a kink/community platform.

**Stark whitespace in the scouted set:** no platform combines kink-grade identity expression (FL/Div) with marketplace-grade provider monetization mechanics (RL/Up) with modern event discovery (Lu). Each platform owns 1–2 of those columns and ignores the rest. Two additional single-platform jobs surfaced on retroactive review: algorithmic content discovery (FL alone) and productized-offering selling (Up alone) — both are job-shaped axes the rest of the scouted set ignores entirely.

---

## Job clusters

### Job: "Be seen accurately for who I am, kink-first"

- **Diversia** — sexuality_identity.php: 17+ gender identities, intersex, gender expression (crossdressing/drag), D/s role tags, leather/appearance identities, BDSM practice tags, garment/material preferences, *preferred social contexts* (play parties, munches, cuddle puddles, swinging, cruising, sex clubs/saunas).
- **FetLife** — Gender×3, Orientation×5, Role×5, Pronouns×3, Activity level (7 options), Looking For (14 relationship/play options), NOT Looking For. Fetishes carry into/curious-about/soft-limit/hard-limit *plus* a giving/receiving/watching sub-role.
- **Redlights** — services taxonomy (~80 options) doubles as identity + as the source of the auto-assigned Safe Sex label.
- **Upwork** — skills tags, hourly rate, availability. Generic — no analog for the kink-axis.
- **Luma** — bio + social-links only. Identity is who-you-know (RSVPs), not who-you-are.
- **Shared shape:** structured multi-select tags > free text. Surfacing positive AND negative intent (NOT Looking For, Hard Limit) outperforms positive-only.
- **Shape variance:** Diversia treats identity as *what spaces I want to be in* (social contexts as first-class tags); FetLife treats identity as *what I do/want* (fetish + role); Redlights treats it as *services I offer*. Switch-Berlin's choice between these three axes is a positioning decision — they shape who recognizes themselves in the product.

### Job: "Find others without the rejection cost of asking first"

- **Diversia** — Seems Nice/Interesting → mutual flag creates Match. Profile-completeness gates access to the search itself.
- **FetLife** — Crushing On: anonymous; one/day; mutual reveal. Free to receive, Supporter to send.
- **Upwork** — implicit version: client invites freelancer; freelancer accepts or ignores. No mutual-anonymity primitive.
- **Redlights** — favourites (one-sided wishlist), no mutuality.
- **Luma** — RSVP-shows-up-on-event-page; social proof via attendee lists, not anonymous mutual signaling.
- **Shared shape:** asymmetric like/flag becomes symmetric only on mutual confirmation. Reduces fear of asking.
- **Shape variance:** monetization — FetLife paywalls the send (scarcity-pricing), Diversia uses profile-completeness as the gate (quality-pricing). Different theories of what makes the signal valuable.

### Job: "Coordinate a gathering that has the right vibe"

- **Luma** — richest. Required-approval, capacity, waitlist (with auth-on-paid), group registration, token-gating, custom registration questions, themes, location hidden until approved, blasts via email/SMS/push, check-in app with Express mode + check-in-manager role (Plus), insights.
- **FetLife** — event with category, dress code, cost, type (in-person/virtual world/virtual local), 3-tier privacy (Public/FetLifers/Private), discovery by 50km + Friends-RSVPed filter.
- **Diversia** — dresscode, application-required toggle, gender restrictions (individual gender checkboxes), online-event toggle, multi-language descriptions, hide-participants-list option, post-event review tab.
- **Redlights** — N/A.
- **Upwork** — N/A.
- **Shared shape:** event-as-page (cover, hosts, time, place, attendees, RSVP), pre-approval gate, attendee messaging.
- **Shape variance:** Luma is the events-substrate champion BUT has zero kink-context primitives (no dress code field, no gender-restriction toggle, no application-questions for kink play, no host vetting badge); Diversia/FetLife have the kink-specific shape but lack Luma's modern attendee tooling (no SMS/push blasts, no QR check-in app, no waitlist authorization-and-charge). The synthesis question is whether kink-specific fields belong as a *layer over* a modern event substrate or *baked into* it.

### Job: "Earn or pay for visibility on the platform"

- **Redlights** — pure transactional. Credits wallet, no subscription. GOLD boost (2 cred = 6hr top placement). Auto-renewal Planner with TIME triggers or POSITION triggers (boost when listing falls below page N). Banner inventory (slider €30/wk, category €32.5/wk, homepage €140/mo). SMS micro-payment as backup channel.
- **Upwork** — Connects ($0.15/ea) as currency for *bidding to apply* (variable per-job, e.g. 14 Connects shown in proposal flow with balance preview), boosting proposals, boosting profile, Availability Badge auction. *Plus* a subscription tier ($19.99/mo Freelancer Plus) for insights+Direct-Contracts-0%. *Plus* a 0–15% take-rate on contract earnings. Three monetization axes stacked.
- **Luma** — flat per-event 5% Stripe fee Free / 0% Luma Plus; Plus is calendar-level ($59/mo) not user-level. Calendar memberships (community paid subs) as a second monetization shape.
- **FetLife** — one tier, anti-subscription (explicitly non-recurring, "like Costco we sell in bulk"). Unlocks browsing volume (5000 K&P/day, all videos, all pictures, AMA send, feed-customization, 20 favorites, 1 crush/day). No boosts.
- **Diversia** — one VIP tier in 2/6/12-month bundles. Unlocks notification surface (email alerts, sound, calendar reminders), visitor log unmasking, picture/cover-image personalization, expanded messaging quota.
- **Shared shape:** every platform has at least one monetization axis; the kink platforms (FL, Div) lean *single subscription tier*, the marketplace platforms (RL, Up) lean *transactional currency*.
- **Shape variance:** FetLife and Redlights occupy opposite corners — FetLife refuses promotional surface entirely (no boosts, no ads visible to Supporters), Redlights is *built on* the boost economy. Diversia paywalls the *anxiety-reducing* features (alerts, who-visited). Upwork stacks all three axes simultaneously. Switch-Berlin picking one axis vs stacking is a load-bearing positioning call.

### Job: "Prove I'm safe to meet"

- **Redlights** — Verified badge (handheld-sign photo OR Skype cam-check) + Safe Sex auto-badge (derived from service tags).
- **FetLife** — optional ID-or-devil-horn-photo verification → badge + raised limits on messaging non-friends, friending, following.
- **Upwork** — Identity Verification badge (35 Connects, valid 3 years, required for some country-restricted work). Separate from reputation tiers.
- **Diversia** — none visible. Trust signal is profile-completeness + history.
- **Luma** — none visible. Trust signal is host's calendar follower count + past-event attendance ("0 Hosted, 14 Attended" on profile).
- **Shared shape:** photo-with-context OR ID upload → admin review → badge.
- **Shape variance:** FetLife's verification *unlocks behavior* (more DMs); Redlights' verification *signals trust to clients*; Upwork's verification *gates access to work*. Same primitive, three different downstream effects.

### Job: "Tier reputation publicly so newcomers and clients can read it"

Only Upwork does this richly: JSS (0–100% on a rolling 6/12/24-month window), Rising Talent → Top Rated (top 10%) → Top Rated Plus (top 3%) → Expert-Vetted (top 1%, invite-only). Each tier has *codified criteria* (numeric earnings, JSS thresholds, profile completeness, duration on platform, etc.) and *codified rewards* (Connects bonuses, badge visibility to specific client segments, faster payments). The other four platforms have *binary* signals (verified or not, Supporter or not) — no tiered reputation.

- **Shape question for Switch Berlin:** the kink platforms historically reject reputation tiers (they read as gamification of intimacy / status-jockeying). But the marketplace value of *"this provider has consistently delivered"* is the same job. Where is the line?

### Job: "Keep a sub-community civil at scale"

- **FetLife — by far the richest:** Group leaders configure pre-moderation (queue-all-posts), per-member pre-mod lists, timeouts (including for members who already left), stickies, member removal. Open vs Closed group choice. Plus platform-level: 3-strike warning system across virtually every content surface (profiles/pictures/videos/writings/statuses/comments/PMs/group posts/events/fetishes/AMAs).
- **Diversia** — inline abuse-report on each content type, manual admin review, sanctions (functionality withdrawn / account block).
- **Luma** — implicit via host approval queue per event; calendar admins approve submitted events.
- **Redlights** — listing-level review queue, no sub-community concept.
- **Upwork** — Account Health dashboard (Platform Access status × Account Standing gauge × enforcement history) + arbitration.
- **Shape variance:** FetLife is the only platform where *leaders are explicitly given Stalin-knobs* (timeouts, pre-mod lists). Diversia/Luma stop at admin escalation. Switch-Berlin needs to decide whether sub-community leaders get power or whether moderation stays platform-central.

### Job: "Understand if my work is paying off"

- **Upwork (richest provider analytics):** JSS gauge with "view insights" drilldown, profile views/invites/impressions time-series with Availability-Badge-on/off overlay, proposal funnel with organic-vs-boosted split, client relationship donut (>90d vs <90d).
- **Redlights:** daily/monthly visitor counts, peak-day-of-week, favorites count, likes count.
- **Luma:** per-event Insights (page views, top referrers, UTM tracking, referral attribution by guest).
- **FetLife:** view counts on posts (Jan 2025+); no profile/account-level analytics.
- **Diversia:** none beyond visitor log.
- **Shared shape:** "did people see it?" "did they act?"
- **Shape variance:** Upwork couples analytics directly to the auction surface (boost-spend → impressions → invites loop) — analytics IS the pitch for buying more Connects. Switch-Berlin's analytics design depends on whether there's a paid-promotion surface to feed.

### Job: "Discover trending or surfaced content without first building a follow-graph"

- **FetLife** — `/explore` surface offers four top-level feed tabs: *Kinky & Popular* (trending), *Fresh & Pervy* (newly uploaded), *Stuff You Love* (personalized via past loves/interests), *Friends & Following* (graph-based). Tabs apply across pictures, videos, writings simultaneously.
- **Diversia** — partial: feed "Mine vs Everyone" toggle gives global activity, but it's chronological, not algorithmic; no personalization layer.
- **Luma** — N/A as content; surfaced events feed serves a different job (events ≠ content).
- **Upwork** — N/A (jobs not content).
- **Redlights** — N/A.
- **Shared shape:** content-discovery primitive is *graph-independent*. New users get value before they've connected to anyone.
- **Shape variance:** FetLife is the only platform that ships four distinct curation axes (trending / new / personalized / graph) in one surface. Everyone else assumes the social graph is the discovery primitive — which excludes new users by design. For a Berlin scene where many users may be lurkers before they're posters, this matters.

### Job: "Sell what I do without waiting for someone to ask"

- **Upwork** — *Project Catalog*: fixed-price service packages (provider defines scope, price, delivery time; clients browse and buy directly). Distinct from the inbound-proposal-driven model — it's productizing the provider's offering, not bidding on a job.
- **Redlights** — adjacent shape only: a listing IS the productized offering, but only one shape (escort listing) and not browsable as a catalog of distinct packages from one provider.
- **Luma** — paid calendar memberships approximate this (host packages a recurring community as a subscription), but the unit is the community, not a service.
- **Diversia / FetLife** — none.
- **Shared shape:** the provider does the packaging work upfront; clients buy without negotiation.
- **Shape variance:** only Upwork ships the full pattern (multiple packages per provider, browsable catalog, fixed-price-no-bid). For Switch-Berlin's provider-side dashboard, the *productized-offering* axis is a separate design question from *listings* and from *subscriptions* — it's a third monetization shape neither of the kink platforms touches.

---

## Open questions (white space)

Phrased as questions — not as features to build.

1. **Kink-grade identity × event-grade primitives.** No scouted platform combines FetLife/Diversia-level identity taxonomy with Luma-level event tooling (waitlist authorization-and-charge, QR check-in app, blast composer, multi-channel notifications). **Open question:** is the gap a graveyard (kink-events were always orchestrated peer-to-peer or via Telegram — would Switch-Berlin be inventing demand?), or an opportunity (Berlin's scene has scale + Luma adjacent literacy)? Talking to 3–5 kink event hosts will resolve this faster than feature-spec'ing.

2. **Tiered reputation in a kink context.** Upwork's tiered-status system is rich (Rising Talent → Top Rated → Top Rated Plus → Expert-Vetted) but no kink platform attempts it. **Open question:** is the absence principled (status-signaling violates the egalitarian ethos of consent-positive spaces) or unexploited (vouching/karma/long-history signals would make first-time meetings safer)? If the latter, what's the kink-appropriate *unit* — events attended, references from verified hosts, longevity on platform?

3. **Boost auctions outside a marketplace.** Redlights/Upwork both run *auction-style* boost mechanics with credits. FetLife refuses them; Diversia ignores them. **Open question:** does a non-commercial kink platform have a *natural* primitive that *would* be valued enough to bid on (featured-on-event-page? top-of-search-for-an-interest? first-in-line-for-event-RSVP?), or does even *introducing* an auction primitive break the trust-currency the social platforms run on?

4. **Profile-completeness as a substitute for paid gates.** Diversia uses profile-completeness as the gate for advanced member search and random-profile discovery (no photo + bio + sexuality data → blocked). **Open question:** if the goal is high-quality matching/messaging, does profile-completeness gating outperform Supporter/Verified paywalling? It also encodes a quality signal the platform doesn't need to pay to manufacture.

5. **The verification primitive — what gets unlocked?** FetLife's verification raises messaging caps. Redlights' announces trustworthiness to clients. Upwork's gates work eligibility. All same primitive, three different downstream effects. **Open question:** in Switch-Berlin, what does verification *unlock* — visibility (search ranking), reach (DM/RSVP limits raised), access (private/RSVP-gated events), or eligibility (host an event, get the badge)? The answer shapes how much friction users will accept on the verification flow.

6. **The 'NOT Looking For' field.** FetLife is the only scouted platform with explicit *negative-intent* surfaces (NOT Looking For; Soft Limit; Hard Limit). Diversia's contact-intent selectors are positive-only. **Open question:** is negative intent a load-bearing trust primitive in this space (i.e. *seeing* a user's limits before interacting is itself a safety signal), or does it overwhelm new users / leak personal information? Worth a usability conversation, not a spec decision.

7. **Calendars / Networks / Groups — same primitive or different?** Luma's Calendars (subscriber-list + newsletters + paid memberships + event-submission queue) and Diversia's Networks (member-list + discussions + events + documents) and FetLife's Groups (Open/Closed + admin pre-mod) are *the same job* (cluster events + content under a recurring host identity) with different feature emphasis. **Open question:** would Switch-Berlin treat collective/host pages as primarily an *event-source* (Luma shape), a *forum* (FetLife/Diversia shape), or a *paid community* (Luma calendar memberships + FetLife Closed groups)? Picking one keeps the surface coherent; picking all three is a usability hazard.

8. **Non-recurring payment as positioning.** FetLife explicitly refuses recurring billing ("like Costco, we sell in bulk"). Diversia bundles in 2/6/12-month chunks. Both occupy the *anti-SaaS-feel* corner. Upwork and Luma are conventional SaaS. **Open question:** does the kink/community context demand non-recurring billing as a trust-signal? Or is FetLife's stance an artifact of their values and Switch-Berlin can ship conventional monthly recurring without harm?

9. **Content discovery for lurkers / pre-graph users.** FetLife is the only scouted platform that ships graph-independent content discovery (Kinky & Popular, Fresh & Pervy, Stuff You Love). Diversia's "Everyone" feed is chronological-only. **Open question:** is graph-independent discovery a load-bearing onboarding primitive for Switch-Berlin (Berlin has a lurker-heavy scene; first-time users need to *see* community texture before they connect), or does it leak content to under-vetted accounts and create T&S risk? The kink platforms' refusal might be principled, not lazy.

10. **Productized offerings as a third monetization shape.** Upwork's Project Catalog (fixed-price packages browsable as products) is structurally distinct from listings (Redlights) and subscriptions (FetLife/Diversia). **Open question:** does Switch-Berlin's provider surface need a productized-offering axis (a host packages "a 4-hour munch for 12 people, all-in €X" as a buyable thing), or does the kink-event context already implicitly bundle scope/price/host into the event-creation flow itself, making a separate catalog redundant?

---

## Evidence caveats

- **Round 1 had partial auth on Diversia, FetLife, Upwork, Luma** → R1 records for those platforms leaned on docs/marketing-pages. R2 re-scouted with authenticated CDP session and the matrix above weighs R2 evidence over R1 wherever conflicts emerged (R2 corrected FetLife Supporter pricing to €30/€60/€120/€240, fetish states to 4 not 5, event privacy to exactly 3 options).
- **Redlights did not get an R2 re-scout** because R1 was already authenticated (dashboard URLs returned live UI). Stronger evidence than the others on first pass; no auth-gap risk.
- **The Upwork account observed is an inactive Basic profile** — earnings/JSS/proposals show zeros. The Stats UI shape is high-credibility; the *value distributions* in those widgets are not. Pricing flows for Connects bundles beyond unit price ($0.15/ea) were behind buttons not navigable without modifying state.
- **FetLife `/Jonj0/ama` page loaded with no composer** — AMA enable is a Supporter feature, not testable from this account. Record reflects the docs/pricing-page claim, not a UI walk.
- **No event-creation flow was published anywhere** — Luma's /create form was walked but not submitted; Diversia's event form was inspected but not submitted; FetLife's /events/new was inspected. Records capture the *form shape*, not server-side validation behavior.
- **No "intentional absence" claims.** Several `✗` cells in the matrix reflect "scout didn't see this primitive on this platform." FetLife's documented refusal of demographic filters is the one exception — that one ✗ is principled-absent per their own help docs.
- **Luma's host-side dashboard was not observable** (user has 0 hosted events on this account). Host insights, blast composer UI, check-in tools shape come from docs (Luma help center) not live UI.

---

## Brainstorm hand-off

This brief is **evidence of which jobs the comparable set addresses, and where shape varies** — it is NOT a feature list to build.

Recommended next moves:

- **Pick one job cluster and brainstorm against the open question for it.** The richest cluster for Switch Berlin is likely *"Coordinate a gathering that has the right vibe"* (open question #1) or *"Earn or pay for visibility"* (open question #3) — they sit at the intersection of the unaddressed white-space.
- **Talk to 3–5 prospective hosts/attendees in Berlin** before resolving open questions 1, 2, 3, and 6 — these are *user-research* questions, not design-from-scout questions.
- **Re-invoke `/scout-features --focus "<that job>"`** if a chosen cluster needs deeper evidence (e.g. focus on event-creation forms across Plura/Eventbrite/Partiful, or focus on verification across Tryst/SwingTowns/queer-dating apps).
- **Do NOT route this brief into `/beadify` or `/decompose` directly.** It is brainstorm fuel — there is no `--design` or `--acceptance` content here yet, and feature decisions need user-validation upstream of bead-scoping.

---

## Retroactive correction (2026-05-18)

This brief underwent a manual soldier-proof review on 2026-05-18. The review surfaced two missed job clusters that the original synthesis pass had silently dropped — both single-platform cases easy to miss without a coverage-rule discipline:

- **"Discover trending content outside my social graph"** — FetLife `/explore` (Kinky & Popular / Fresh & Pervy / Stuff You Love / Friends & Following tabs)
- **"Sell what I do without waiting for an inbound request"** — Upwork Project Catalog

Both have been folded back into the parity matrix (2 added rows), job clusters (2 added sections), and open questions (#9 and #10 added). Original record count corrected from "~130" to actual 125 (25 records × 5 platforms after R2-supersedes-R1 dedup). The skill (`~/.claude/skills/scout-features/SKILL.md`) has been updated with a coverage-rule forcing function in Lens C to structurally prevent this failure mode on future runs.
