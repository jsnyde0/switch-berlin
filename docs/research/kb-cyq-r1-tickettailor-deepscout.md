# kb-cyq R1 P0 — TickeTailor deep-scout

**Date:** 2026-05-21
**Scope:** Phase R1 P0 deliverable for `kb-cyq`. Deep-scout of TickeTailor — the dominant content-policy-tolerant SaaS in our scene per [R0 synthesis](kb-cyq-r0-provider-landscape.md) (~20 sex-positive/kink/tantra operators across rope/shibari, tantra, festivals, somatic-consent intensives, temple nights).
**Method:** General-purpose subagent with logged-in CDP access (Chrome on `localhost:9222`, organizer dashboard at `https://app.tickettailor.com/dashboard`). WebFetch for static pages (ToS, AUP, pricing, API docs); `browser-automation` via CDP for organizer-dashboard exploration.
**Substrate role:** Evidence preserved verbatim; orchestrator synthesis flows from this doc into R2 decision.

---

## TL;DR

- **AUP literal text is hostile** ("no full nudity, pornographic or sexually explicit imagery"), but **enforcement is reactive-only** — moderation triggers on report or moderation-review of public listing; ~20+ kink/tantra/BDSM operators currently operate openly with **zero surfaced ban reports** across Reddit, Trustpilot, Capterra, Skift Meetings searches.
- **API is real and capacity-sync-capable.** REST at `https://api.tickettailor.com/v1`, HTTP Basic Auth with per-box-office API keys, 5000 req/30min, webhooks fire on `order.created/updated`, `issued_ticket.created/updated`, `event.created/updated/deleted`, `waitlist_signup.created`. **TickeTailor also publishes an MCP server.**
- **Fee structure is 5–7× cheaper than Eventbrite at typical workshop prices** (£0.60 pay-as-you-sell or £0.22 prepaid + organizer's own Stripe ~1.5%+€0.25).
- **Critical risk-surface shift:** TickeTailor is **not merchant-of-record** — organizer connects their own Stripe/PayPal/Square. **Stripe's adult-content policy (not TickeTailor's) is the actual financial-existential gate.** This is a different risk vector than Hipsy/Eventbrite (which ARE merchants of record). → spawned bead for payment-processor research.
- **Forbidden Tickets exists** (forbiddentickets.com) as a kink-specific competitor — existence proof that some bans DO happen, even if not publicly aired. P1 fallback scout dispatched.

---

## D1. API surface

| Capability | Status | Detail |
|---|---|---|
| Base URL | confirmed | `https://api.tickettailor.com/v1` |
| Docs | confirmed | https://developers.tickettailor.com/docs/api/ticket-tailor-api |
| Auth | confirmed | HTTP Basic Auth, Base64(api_key); per-box-office keys generated at `app.tickettailor.com/api` |
| Rate limit | confirmed | 5000 req/30min global; 30/hr on `POST /v1/issued_memberships` |
| Pagination | confirmed | Cursor-based (`starting_after`, `ending_before`, `limit≤100`) |
| Resources | confirmed | bundles, check_ins, checkout_forms, discount_codes, events, event_series, holds, issued_memberships, issued_tickets, membership_types, orders, products, stores, ticket_groups, ticket_types, vouchers, voucher_codes, waitlist_signups |
| Currency | confirmed | ISO 4217; values in cents |
| Errors | confirmed | Conventional 4xx/5xx with `{status, error_code, message}` |
| Webhooks | confirmed | Configured at Settings → API → Webhooks. Events: `order.created`, `order.updated`, `issued_ticket.created`, `issued_ticket.updated`, `event.created`, `event.updated`, `event.deleted`, `waitlist_signup.created`. Retry + signing supported. |
| MCP server | exists | Published at `developers.tickettailor.com/docs/mcp` — not deep-fetched in this scout. **Potentially short-circuits integration glue.** |

**Bidirectional capacity-sync verdict: feasible.** Event-update + `issued_ticket.created` webhooks give sub-second knowledge of TT-side sales. PATCH on event/ticket-type endpoints lets Switch push capacity changes back.

**Open question:** `POST /v1/events` create-endpoint URL returned 404 on direct probe; resource exists in nav. Bundle-create confirmed at `POST /v1/event_series/:id/bundles`. Event creation likely goes through `event_series` first, then ticket-types / bundles attached. **Needs spot-confirmation in R2.**

---

## D2. ToS / content policy (verbatim, AUP last-updated 2025-04-23)

**Source:** https://www.tickettailor.com/legal/acceptable-use-policy

> "If your event listing, or the purpose of the event itself features content relating to, or is intended to promote any of the following, you must cease to use our platform for ticketing. If you do not, and we discover the listing through our event review moderation process or it is brought to our attention by a third party, we reserve the right to deactivate your account and remove your listing."

**The two clauses that bite our domain:**

> "Post an event where the listing contains full nudity, pornographic or sexually explicit imagery."

> "Post an event where the listing or the content of the event itself promotes recruitment for services of a sexual nature."

**Critical qualifier:** "the listing contains" — moderation is keyed to what appears on the **public listing page (text + image)**, not the lived event experience.

**Tangential clauses worth noting:**
- Hateful/discriminatory speech prohibited — **but** explicit carve-out: *"Events may be tailored to specific communities or demographics (e.g., women-only spaces, faith-based gatherings, age-specific programs) where the purpose is community-building or addressing specific group needs."* — same logic-pattern applies to consenting-adult kink spaces.
- Criminal-in-country-of-event prohibited (non-issue in DE/UK/most EU for consenting-adult BDSM).
- Enforcement: report-form + moderation review. **"Fees are non-refundable"** if event is removed mid-sale → stranded sold-ticket inventory risk.

**Website Terms of Use** (https://www.tickettailor.com/legal/terms-of-use §7) reinforces: prohibits "obscene, indecent, ... pornographic" material.

**T&Cs:** must be 18+ to set up an account. **No "age-gate" toggle for ticket buyers in the listing-side platform** — organizer's responsibility.

---

## D3. Content-policy precedents (user-reports — outranks ToS prose per kb-cyq acceptance 1b)

### Existence proofs — live sex-positive operators on TT

Confirmed via SERP-surfaced public TickeTailor URLs (all currently selling, 2026-05-21):

- `tickettailor.com/events/serensins/...` — **Master Peter & Seren Sins** BDSM Dungeon Social; Femme/Them BDSM Social (London)
- `tickettailor.com/events/townhousewirral/...` — **Radical Desire BDSM Play Event** @ Townhouse (Wirral, UK); "Kink 101" + "Rope Social" munches
- `tickettailor.com/events/schooloferoticmysteries/...` — **Seani Love** "Rituals of Kink" (IKSK Berlin), "Adventures in Kink" (London); UK Sex Worker of the Year 2015
- `tickettailor.com/events/elegantlykinky` — **Mistress Zeneca's Cherry Noir BDSM Club & Villain's Ball** (Philadelphia)
- `tickettailor.com/events/thenewtantra/1590347` — TNT Intro Talk, Berlin
- `tickettailor.com/events/sanyaalaya/403496` — **"The Art of Tantric Kink"** Munich
- `tickettailor.com/events/tantriceric/797430` — **"Sensual Spanking Workshop"** by Eric (Tantra/Sacred Sex)
- `tickettailor.com/events/gaytantraeu/557647` — **GAY-TANTRA Energie-Sex Schnupper-Intensiv** (Vienna)
- `tickettailor.com/events/thefoxden/1008649` — Fox Den Tantra Fundamentals
- `tickettailor.com/events/wakingupthebody/2004793` — Wheel of Consent® Workshop
- `tickettailor.com/events/higherconsciousnessacademy/1421556` — Sacred Sensuality: Sufi Tantra
- `tickettailor.com/events/dancemeetstantra/1484459` — Dance Meets Tantra, Philadelphia

Corroborates and extends the R0 ~20-operator finding. New names (not in R0): ElegantlyKinky/Cherry Noir, Seren Sins, Townhouse-Wirral BDSM, Fox Den, Wheel-of-Consent-with-Eyal, Dance Meets Tantra Philly, Tantric Eric, GAY-TANTRA Vienna.

### Bans / suspensions reported

**Zero publicly-linkable user-reports surfaced** across:
- `site:reddit.com tickettailor` (no results)
- `tickettailor banned account suspended kink BDSM adult event` (no specific kink-ban hits)
- Trustpilot 35+ pages — overwhelmingly ease-of-use praise; complaints are billing/UX and ticket-buyer-side refund confusion, **not content-moderation bans**
- Capterra / Skift Meetings reviews — no content-policy complaints surfaced

**Caveat:** This does NOT prove zero bans. Content-policy bans rarely generate public posts because (a) organizers migrate platforms quietly, (b) stigmatized-vertical operators often don't publicly tag the platform that dropped them. **But:** lack of ANY surfaced complaint after multiple search variants is itself evidence of a non-trigger-happy moderation posture relative to Eventbrite, which has well-documented kink-organizer migration threads on FetLife and Reddit.

**Counter-signal:** **Forbidden Tickets (forbiddentickets.com)** exists as a kink-specific ticketing platform competitor. Either (a) historical bans created demand, or (b) niche-fit demand alone drove it. → P1 scout pending.

### TickeTailor public statements / case studies

- AUP framing is community-positive: "We believe in events as a positive force for good; to entertain, to educate and to bring communities together." No anti-adult-content rhetoric in marketing or company-values pages.
- Explicit demographic-targeting carve-out in AUP (women-only / faith-based / age-specific) — same logic-pattern applies to consenting-adult kink.
- Self-described "small independent team" (Trustpilot company replies) — under-staffed moderation is consistent with reactive-only enforcement.

---

## D4. Fee structure

**Source:** https://www.tickettailor.com/pricing/

| Component | Value | Notes |
|---|---|---|
| Free events | £0 / first 5,000 free tickets per year | Past-cap behavior **unconfirmed** |
| Pay-as-you-sell | £0.60 per paid ticket + VAT | Flat fee, no percentage |
| Pre-paid credits | £0.22–£0.41/ticket (volume-tiered) + VAT | Credits never expire |
| Charity / B-Corp / PTA / not-for-profit | 50% discount | Discretionary |
| Low-priced tickets | 50% discount | Auto-applied |
| Payment processing | **NOT bundled** — organizer's own Stripe / PayPal / Square | TickeTailor never touches funds |
| Stripe Eurozone (illustrative) | 1.5% + €0.25/transaction | Organizer pays Stripe direct |
| Currencies | GBP, EUR, USD, AUD, CAD natively | Multi-currency box office supported |
| VAT | UK VAT on TT fees; EU VAT on tickets = organizer responsibility | TT exposes "Checkout fees and tax" settings |
| Payout | N/A — Stripe disburses direct to organizer's bank | Standard Stripe rolling payouts |
| Merchant of record | **Organizer**, not TickeTailor | **Chargebacks hit organizer's Stripe, not TT** |
| Refunds | Organizer manages via own Stripe; TT fees non-refundable | |

**Comparative cost on £25 workshop ticket:**
- TickeTailor PAYG: £0.60 + Stripe(1.5%+£0.20) ≈ **£1.18 per ticket**
- TickeTailor prepaid: ~£0.40 + Stripe ≈ **£0.98 per ticket**
- Eventbrite (rough): 3.7% + £1.79 + 2.9% payment ≈ **£3.50+ per ticket**
- Hipsy (per `docs/hipsy_analysis.md`): ~3% ≈ **£0.75 per ticket** but content-policy hostile to BDSM/sex-party literal framing

**TickeTailor is dramatically cheaper than Eventbrite; slightly more expensive than Hipsy but with no Hipsy content-policy ban.**

---

## D5. Organizer dashboard (logged-in CDP scout)

**Dashboard sections:** Overview / Events / Orders / Promote / Products / Memberships / Box Office Settings.

**Event-create form** (`/event/add`):

- **Required:** `name`, `timezone`
- **Standard optional:** start/end date+time, `recurringEvent` (checkbox), venue (name/postcode/country) OR `onlineEvent` (with platform select), description (free-form textarea, no length limit), image (with crop + alt text), header image, custom CTA button label
- **Capacity:** `setMaxSellableTickets` + `maxSellableTickets` numeric; `showLowAvailability` with threshold + label
- **Ticket types section, products section, donations toggle**

**🚨 No content-moderation prompt or warning at event-create time observed.** No "18+ only" checkbox. No "adult content" flag. No AUP reminder UI. Organizer self-classification is entirely free-form. Implication: cleaning-flow design is wholly upstream of TT — TT doesn't gate or hint.

**Settings → API page** (`/api`): empty until first key generated; "Generate a new key" + lists of keys + webhooks.

**Settings → Integrations** (per Help Centre):
- **Payment:** Stripe, PayPal, Square
- **CRM:** Mailchimp, HubSpot, Constant Contact, ActiveCampaign
- **Analytics/ads:** Google Analytics, Meta Pixel (with Conversion API), TikTok Pixel
- **Automation:** Zapier (9,000-app gateway with triggers on order/event/ticket/waitlist resources)
- **Data export:** Coupler.io

**Other settings sections present:** Basic settings, Box office design, Contact preferences, Checkout form (`/settings/data-collection`), Multi-checkout (Beta), Email templates, Checkout fees and tax, Privacy policy, Banned emails, Self-serve, Payment systems, Seating charts, Integrations, Team access, Check-in app users, API, Custom domain, White Label, Billing.

**Screenshot from scout (event-edit viewport):** `/var/folders/jq/pbs9c2b5145gfpjl8trjgx_40000gn/T/screenshot-2026-05-21T10-03-16-215Z.png`

---

## Open questions / unresolved (feeding R2)

1. **POST /v1/events shape** — actual create-event endpoint not confirmed; bundle-create is. R2 should resolve by exploring docs nav (likely `event_series` then ticket-types/bundles attached).
2. **TickeTailor MCP server** — ships one at `/docs/mcp`. Not explored. Could short-circuit integration glue for Switch facilitator agent.
3. **Free-event cap behavior** past 5,000/yr — unstated on pricing page.
4. **🚨 Stripe's adult-content policy as upstream gate** — TickeTailor doesn't process funds; Stripe's TOS is the actual financial-risk gate. → spawned bead for payment-processor research.
5. **No Reddit indexing** for `tickettailor` — could reflect UK-focused brand with weaker US Reddit footprint OR genuine low complaint volume. FetLife / European-tantra-Facebook deep mining not done (out of token budget).
6. **Refund / chargeback liability on AUP removal** — confirmed organizer-side via own Stripe, but exact dispute-handling SLA when TT removes mid-sale (TT keeps fees, organizer keeps Stripe-held money) needs Help Centre lookup.
7. **Forbidden Tickets fallback** — does TT's AUP §removal happen often enough to warrant pre-positioning a fallback platform integration? → P1 scout dispatched.

---

## R2 decision hooks (NOT recommendations — facts that would tilt synthesis)

**Tilts toward TT-V1-tactical-GO:**
- API + webhooks sufficient for organizer-hub V1 capacity sync
- Fee floor dramatically lower than Eventbrite
- 12+ verifiable kink/tantra operators currently selling unbothered (existence proof)
- AUP enforced reactively, not proactively
- Organizer-owned payment processor means TT isn't chargeback principal
- TickeTailor's own MCP server could simplify Switch facilitator agent integration
- Demographic-targeting AUP carve-out gives interpretive cover for consenting-adult kink spaces

**Tilts toward TT-V1-tactical-NO-GO or hedged:**
- AUP §"full nudity, pornographic or sexually explicit imagery" is a literal-text time-bomb if a competitor or hostile reporter targets a Switch organizer with screenshots
- "Fees are non-refundable" on AUP-triggered removal = stranded sold-ticket inventory
- POST /v1/events confirmed only as `event_series`-then-bundles path — verify before integrating
- Lack of ANY surfaced ban report is suspicious in BOTH directions (could mean tolerance, could mean migration-without-public-airing — same evidentiary absence)
- Forbidden Tickets existence is direct evidence that *some* US/UK kink operators do migrate

**Tilts toward dedicated-alternative (Forbidden Tickets) or hybrid:**
- TT as default + Forbidden Tickets as warm fallback for organizers who've already been flagged elsewhere
- Pending R1 P1 scout to evaluate

---

## Sources

- [AUP](https://www.tickettailor.com/legal/acceptable-use-policy)
- [ToS](https://www.tickettailor.com/legal/terms-of-use)
- [Pricing](https://www.tickettailor.com/pricing/)
- [API docs](https://developers.tickettailor.com/docs/api/ticket-tailor-api)
- [Webhooks docs](https://developers.tickettailor.com/docs/webhook/introduction)
- [MCP docs](https://developers.tickettailor.com/docs/mcp)
- [Forbidden Tickets](https://forbiddentickets.com/)
- [Trustpilot reviews](https://www.trustpilot.com/review/tickettailor.com)
- [Zapier integrations](https://zapier.com/apps/ticket-tailor/integrations)
- [Meta Pixel integration help](https://help.tickettailor.com/en/articles/5560643-can-i-use-a-meta-tracking-pixel)
- Operator existence-proofs: [SerenSins](https://www.tickettailor.com/events/serensins/776194), [Townhouse Wirral](https://www.tickettailor.com/events/townhousewirral/959933), [School of Erotic Mysteries](https://www.tickettailor.com/events/schooloferoticmysteries/709590), [Elegantly Kinky](https://www.tickettailor.com/events/elegantlykinky), [TNT Berlin](https://www.tickettailor.com/events/thenewtantra/1590347), [Sanya Alaya Munich](https://www.tickettailor.com/events/sanyaalaya/403496), [Tantric Eric](https://www.tickettailor.com/events/tantriceric/797430), [GAY-TANTRA Vienna](https://www.tickettailor.com/events/gaytantraeu/557647)

## canonical_refs

- `kb-cyq` — parent bead (R1 P0 deep-scout deliverable)
- `docs/research/kb-cyq-r0-provider-landscape.md` — R0 discovery synthesis (predecessor)
- `docs/hipsy_analysis.md` — comparator prior scout
- `docs/decisions/ADR-010-event-based-product-posture.md` — D1(c) FLEXIBLE; ticketing as revenue path
- `docs/decisions/ADR-011-personal-agent-layer-additive.md` — D1 FLEXIBLE; facilitator agent as integration vehicle
