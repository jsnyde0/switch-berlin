# Scout brief: Hipsy organizer dashboard

**Scouted:** Hipsy (hipsy.nl) — Dutch-origin event-organizer platform, strong in yoga/conscious-community/tantra niche, multi-country (NL/BE/ES/FR).
**Focus:** Full surface of the authenticated organizer dashboard at `/app` plus public help-center.
**Date:** 2026-05-19.
**Account context:** Scouted as logged-in organizer "Scars and Roses" — real organizer with live event history (full visibility into participants, payouts, reviews).
**Raw sidecar:** `history/scout-features-hipsy-organizer-raw/` (30 feature records + 9 screenshots).

> **Single-platform scout.** No cross-vendor parity matrix; the table below stands in as a "features × underlying-job" inventory. Job clusters + open questions are the load-bearing output for `/brainstorm`.

---

## Feature inventory (with underlying jobs)

| Underlying job (organizer language) | Feature | Evidence | Tier |
| --- | --- | --- | --- |
| Run a flexible price ladder that rewards early commitment | Tiered ticket types with sequential availability ("Na Early bird") | ✓ UI | no-tiers |
| Let people pay what they can | Donation (pay-what-you-can) ticket type | ✓ docs | no-tiers |
| Give discounts privately without advertising them | Invisible tickets with secret-URL sharing | ✓ UI + UI-screenshot | no-tiers |
| Run promo / partner / press campaigns | Discount codes & value vouchers | ✓ UI | no-tiers |
| Cap how many seats / orders / per-person | Ticket capacity limits — event, order, per-user | ✓ UI | no-tiers |
| Run free events without ticketing infra | Registration via contact form (no tickets) | ✓ UI | no-tiers |
| Keep an event off public search | Private event mode (link-only) | ✓ docs | no-tiers |
| Iterate on the page before going live | Event draft / concept mode | ✓ UI | no-tiers |
| Turn off card payments for one event | Credit card acceptance toggle per event | ✓ UI | no-tiers |
| Get discovered by the right audience | Theme taxonomy — 6 categories, 80+ sub-themes (incl. Shibari, Tantra, Queer, Conscious Sexuality, Speelsheid) | ✓ UI | no-tiers |
| Filter audience by language/gender/age/country | Audience filters per event | ✓ UI | no-tiers |
| Operate across countries | Multi-country domains + geo-targeting (NL/BE/ES/FR) | ✓ UI | no-tiers |
| Know who's coming and check them in | Attendee list + check-in checkbox + mobile QR app | ✓ UI | no-tiers |
| Collect data needed for the event (dietary, custom Qs) | Custom registration form fields + up to 3 open questions | ✓ UI | no-tiers |
| Talk to ticket-holders before the event | Bulk email attendees from dashboard | ✓ UI | no-tiers |
| Send arrival info every time | Post-purchase info message + PDF attachment in confirmation email | ✓ UI | no-tiers |
| Build an owned mailing list, not just an event audience | Newsletter opt-in captured at checkout | ✓ docs | no-tiers |
| Be findable as an organizer, not just per-event | Public organizer profile + Follow button + follower count | ✓ marketing-page | no-tiers |
| Be reachable by interested attendees | Attendee-to-organizer direct message (Stuur bericht) | ✓ marketing-page | no-tiers |
| Look like a real brand | Organizer branding — logo, cover, color theme, photo gallery | ✓ UI | no-tiers |
| Embed selling into my own website | Customizable ticketshop iframe + brand-color controls | ✓ UI | no-tiers |
| Share organizing work with collaborators | Co-organizer access per event | ✓ UI | no-tiers |
| Run more than one organisation from one login | Multi-organisation account switching | ✓ UI | no-tiers |
| Measure marketing source attribution | UTM link generator + UTM stored per order + CSV export | ✓ UI | no-tiers |
| Run paid social ads with conversion data | Meta Pixel + Google Ads conversion pixels per event | ✓ UI | no-tiers |
| Wire it into my own stack | REST API + WordPress plugin + Zapier (new order / new event triggers) | ✓ docs | no-tiers |
| Get paid after the event | Post-event IBAN payout + downloadable credit invoice (eindafrekening) | ✓ UI | no-tiers |
| Earn trust from new attendees | Reviews — auto post-event invites + organizer reply + badge after 3 | ✓ UI | no-tiers |
| Know what content is allowed | Published event content policy (educational framing required for sexuality events; BDSM/sex-parties banned) | ✓ docs | n/a |
| Pay only when I sell | Freemium model — €0.80/ticket service fee + €0.35/order, no monthly fee | ✓ marketing-page | no-tiers |

**Table-stakes observations:**
- Hipsy ships flat — **no feature gating by tier.** Every organizer gets every feature; the business model is purely transactional (per-ticket + per-order fees).
- The platform takes a **brand-with-followers stance**, not a pure-marketplace stance: public organizer profile, follow button, public follower count, and DM are all first-class. This is meaningfully different from Eventbrite's organizer-page-as-afterthought.
- Privacy/access controls run **at the per-ticket-type level** (invisible URL, donation, sequential availability) more than at the event level. The unit of "exclusivity" is the ticket, not the event.

---

## Job clusters

### Job: "Sell access on terms that match how the experience is priced"
- **Tiered + sequential tickets** — early bird auto-unlocks regular when sold out.
- **Donation ticket** — pay-what-you-can.
- **Invisible tickets with secret URL** — undisclosed discounts / member-only.
- **Discount codes & value vouchers** — promos.
- **Capacity limits** at event / order / per-user.
- **Per-event credit card toggle.**
- **Shared shape:** The pricing model itself is a *first-class field*, not an afterthought tagged on. Donation, sequential, hidden-URL aren't bolted on — they're peer ticket types.
- **Shape variance:** Hipsy has no **subscription**, **membership tier**, **patron**, or **recurring-donation** surface. Pricing-per-event is the only pricing primitive.

### Job: "Decide who can see this event and who can buy"
- **Private event** (link-only, hidden from search).
- **Draft / concept mode.**
- **Audience filters** — language, gender (all / men-only / women-only), age range, target countries.
- **Geo-targeting** by Hipsy country domain.
- **Invisible ticket URL** (re-classifies as access control as well as pricing).
- **Shared shape:** Access is a *gradient* (search-discoverable → link-only → invisible-tier-via-URL), not a binary public/private toggle.
- **Shape variance:** No **consent-tier / experience-level / vouched-only** gating. Gender audience is binary M/F/all — no NB-inclusive option, no role-aware filter (Top/bottom/etc), no kink-experience floor. The taxonomy enumerates "Conscious Sexuality / Shibari / Tantra / Queer / Speelsheid" in subthemes — but **the gating primitives don't match the taxonomy's social complexity.**

### Job: "Know who's coming and collect what I need from them"
- **Attendee list** with email, ticket type, order number.
- **On-site check-in** via dashboard checkbox or Hipsy Checkin mobile app (QR).
- **Custom registration form** — toggle 12 built-in fields + up to 3 freeform questions, each required or optional.
- **Newsletter opt-in** captured at checkout and exported via CSV.
- **Shared shape:** Data collection is *per-event*, not per-organizer profile. Custom questions are scoped to one event at a time.
- **Shape variance:** No **attendee profile** (the organizer sees orders, not people-over-time). No **labels / tags / cohorts** on attendees. No **repeat-attendee recognition** ("this person has been to your last 5 events"). No **across-events attendee history** in the dashboard.

### Job: "Communicate with people before and after"
- **Bulk email to attendees** from dashboard.
- **Post-purchase custom message + PDF attachment.**
- **Newsletter opt-in** at checkout (organizer owns the list via export).
- **Attendee-to-organizer DM** via public profile.
- **Reviews — auto post-event invite + organizer reply.**
- **Shared shape:** Comms are *batch broadcast + per-attendee response*, not threaded conversation.
- **Shape variance:** No **scheduled comms** (e.g. "send 24h before"). No **segmented messaging** (you can email "all attendees of event X", not "all attendees who've been to ≥3 of my events"). No **organizer push-notification surface**.

### Job: "Be findable as a brand, not just per event"
- **Public organizer profile page** with bio, logo, cover, photo gallery, upcoming/past events.
- **Follow button + follower count.**
- **Color theme + branded ticketshop.**
- **Reviews badge after 3 reviews.**
- **Multi-organisation account switching** (a person can run multiple organizer brands from one login).
- **Shared shape:** The organizer is a *first-class entity with social gravity*. Followers are real, follower count is public, DM is a button.
- **Shape variance:** No **organizer-to-organizer follow** (collab graph). No **attendee profiles** (followers are anonymous counts, not visible people). No **federated identity** — your follower count is locked to Hipsy.

### Job: "Operate this as a small business"
- **Co-organizer access per event.**
- **Multi-organisation account.**
- **Per-event IBAN payout + downloadable credit invoice.**
- **VAT rate set per ticket type.**
- **CSV exports** of orders / participants / UTM data.
- **REST API + WordPress plugin + Zapier (new-order, new-event).**
- **Shared shape:** Hipsy treats the organizer as a small SaaS-tooled business — accounting outputs, multi-seat, integrations into the org's own stack.
- **Shape variance:** No **roles / permissions** (co-organizer is binary all-or-nothing access). No **employee / team / staff** distinction. No **financial dashboard across events** — invoices are per-event.

### Job: "Measure what worked and run paid acquisition"
- **UTM link generator + UTM tagged per order.**
- **Meta Pixel + Google Ads pixel per event.**
- **Reviews (post-event trust signal).**
- **Shared shape:** Hipsy is *attribution-aware* — UTM + pixel-by-event is more depth than most niche platforms ship.
- **Shape variance:** No **organizer-wide funnel analytics** ("how many people who follow me end up buying"). No **cohort/retention reporting** ("of attendees from event A, how many came to event B"). No **LTV reporting**. No **price-elasticity / sold-by-tier breakdown** beyond the raw orders CSV.

### Job: "Trust that this organizer and these attendees are safe to engage with"
- **Reviews** (post-event, with organizer reply).
- **Content policy** (banning categories of events).
- **Shared shape:** Trust is *one-way attendee→organizer* (reviews) and *one-way platform→content* (policy gatekeeping).
- **Shape variance:** No **attendee verification**. No **vouch / introduction graph**. No **organizer blocklist** (cannot say "don't sell to this user"). No **community guidelines surface to attendees during checkout** ("I agree to organizer's code of conduct"). No **reporting flow visible to organizers**.

---

## Open questions (white space)

Phrased as questions for `/brainstorm`, not features to build.

- **Cross-event attendee identity** — addressed by: none directly. Hipsy treats attendees as per-order, not per-person. **Open question:** Switch Berlin already has identity / 4-tier visibility (ADR-009). Does the organizer dashboard need to expose *attendee profiles* (subject to attendee privacy tier) — and if so, is that a feature that *requires* a different platform stance than Hipsy's "tickets, not people"? Why might Hipsy have refused this? (Privacy-by-design? GDPR conservatism? Maker-side complexity?)

- **Membership / subscription / patron** — addressed by: none. Hipsy is pure per-event transactional. **Open question:** Organizers in our space (recurring play parties, monthly munches, on-going groups) clearly have membership-shaped revenue. Is the absence of subscription primitives on Hipsy a deliberate stance (avoid managing recurring billing), a maturity gap, or a graveyard (organizers tried it, it didn't fit)? What would change if Switch Berlin shipped subscription as a first-class peer of ticketing?

- **Waitlist / hold queue** — addressed by: none observed. Sold-out tickets just say "Uitverkocht." **Open question:** A waitlist is table-stakes on most modern ticketing platforms. Hipsy's absence is conspicuous. Is this because organizer-decided manual-allocation (via discount codes / invisible tickets) substitutes? Should Switch Berlin's "vouched-only" or "consent-prerequisite" gating use a waitlist-shaped UX even where there's no capacity issue?

- **Series / recurring events** — addressed by: none observed (only duplicate). **Open question:** For organizers running weekly classes / monthly parties, duplicating an event each time is meaningful friction. Hipsy's absence here is either pragmatic (each event is genuinely different) or a gap. What's the right primitive for Switch Berlin — series? recurring? membership-replaces-recurring?

- **Attendee segmentation + targeted communication** — addressed by: bulk-email-all only. **Open question:** "Email people who've been to ≥3 of my events" doesn't exist on Hipsy. Is that a deliberate stance (one-list-per-event simplicity wins) or an under-built area? For our space — where loyalty / regular-attendance is a core dynamic — should this be a first-class surface?

- **Consent-tier / experience-level audience gating** — addressed by: gender (binary), age, language, country — *not* role, experience, consent prerequisites. **Open question:** Hipsy enumerates "Shibari / Conscious Sexuality / Tantra / Queer / Speelsheid" in its 80+ sub-themes — yet has no consent-shaped gating primitive. **Is the white-space here a real opportunity or a regulatory minefield?** Switch Berlin's identity/social-graph work (ADR-007, ADR-009) creates substrate for it; what would the simplest viable consent-tier surface look like?

- **Organizer-to-organizer social graph** — addressed by: none. Co-organizers are per-event flat permissions; no follow / collab / referral primitives. **Open question:** In our community, organizers know each other and frequently collaborate / vouch / refer attendees across events. Should there be an organizer-graph primitive (peer follow, "trusted-by", co-host history) — or is that bloat that doesn't ship value?

- **Attendee-side moderation / safety surface** — addressed by: content policy (top-down) + reviews (after-the-fact). **Open question:** No organizer-side blocklist; no attendee report → organizer flow; no "person banned from this event" surface. For our space, where banning specific attendees is a real organizer need, is the simplest viable surface a per-organizer blocklist that lives orthogonal to identity, or something graph-tier-shaped?

- **Recurring-revenue / patron model** — covered by the membership question above but worth flagging separately. **Open question:** Diversia (prior scout) had a patron-shaped model; Hipsy doesn't. Where does Switch Berlin land — and how does that decision change every other surface (analytics, comms, attendee profile)?

- **Federated / portable organizer reputation** — addressed by: none. Reviews and follower count are Hipsy-locked. **Open question:** Switch Berlin's labelers deferral (kb-fx9 D6, deferred to V1+) is the right frame for this — but should the *organizer reputation primitives* (reviews, follower count) anticipate federation now even at zero cost? (ADR-003 cheap-foresight territory.)

---

## Evidence caveats

- **Pricing claims (`hipsy.nl/organize-your-event`)** are marketing-page; treat as approximate. The actual fee structure may have edge cases (per-method surcharges for non-iDEAL payment, refund handling) not captured in the headline numbers.
- **Reviews + follower count appearance on `hipsy.be/...`** is also marketing-surface — confirmed the buttons exist on the public profile; what shows behind them in the public flow was sampled at top-level only.
- **Hipsy Checkin mobile app:** referenced in docs; not exercised on-device.
- **`docs.hipsy.nl`** scanned at index level only — API rate limits, OAuth scopes, webhook signing, and Zapier action coverage (vs the documented triggers) were not exhausted.
- **Content policy** is the published one (2026-05-19). Hipsy could enforce more or less strictly than the text in practice; that requires live test which is out of scope for this scout.
- **No subscription / membership tier exists in the dashboard.** This is a positive absence (✓), but the inference is "we did not find one anywhere on the surface we walked" — not "Hipsy will never ship one." A Hipsy-Plus could be in beta, behind sales, etc.

---

## Brainstorm hand-off

The above is **evidence of opportunities and shared jobs**, not a feature list to build. Use the next step to validate:

- Paste this brief verbatim as initial context for the upcoming **vision brainstorm** (the one the work-stream table tags as gating kb-fx9 EXPLORATORY decisions). The Socratic loop will interrogate the open questions above — especially **cross-event attendee identity**, **membership vs ticketing**, and **consent-tier gating** — not consume the inventory.
- OR pick one job cluster (e.g. "consent-tier audience gating", "attendee segmentation + targeted communication") and re-invoke `/scout-features --focus "<that job>" --platforms <other platforms>` to triangulate.
- **Raw records sidecar:** `history/scout-features-hipsy-organizer-raw/` — 30 feature records + 9 screenshots + README. Read individual records when a brainstorm cluster needs the texture the brief compressed away.
- Do NOT route this brief into `/beadify` or `/decompose` directly — beads need `--design` + `--acceptance`, which this brief is not yet. The intended downstream is **vision brainstorm**, then ADR canonicalization for any FIRM decisions that emerge, then bead authoring.

### Switch-Berlin-specific takeaway (single sentence each)

- **Hipsy is not a platform Switch Berlin can ride** — its content policy explicitly bans the core use-case (BDSM, sex parties).
- **Hipsy IS a strong feature-pattern reference** — particularly for the *ticketing primitives* (sequential tiers, invisible-URL, donation), the *organizer-as-brand stance* (public profile, follow, DM, branded ticketshop), and the *attribution surfaces* (UTM, pixels, Zapier).
- **The most load-bearing white space for our space** is the gap between Hipsy's gender/age/country audience filters and the consent/experience/role gating our community actually needs — this is where ADR-007 + ADR-009 + kb-m69 substrate has a chance to be genuinely differentiating.
- **The second-most load-bearing gap** is membership vs ticketing — Hipsy is purely transactional, our space has clear membership-shaped revenue patterns (recurring groups, ongoing communities), and resolving this gates how attendee identity, comms, and analytics all get shaped.
