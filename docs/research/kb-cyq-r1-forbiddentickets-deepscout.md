# Forbidden Tickets R1 P1 scout — kb-cyq

## TL;DR
- **US-only, Bay Area-born kink/BDSM ticketing platform** operated by TicketGear Inc. (Oakland, CA) — purpose-built for the Leather/BDSM/kink/LGBTQ+/BIPOC community; no EU operator footprint found, zero overlap with our R0 organizers (TNT, Cherry Noir, Karada House, Sanya Alaya, School of Erotic Mysteries).
- **No public API, no webhooks, no Zapier, no iCal export, no documented multi-currency.** Only documented integration is "Bloom Community." Embeds available via code snippets. Capacity sync and external app integration would require email-to-team negotiation, not self-serve developer onboarding.
- **Pricing is competitive (1.75% + $0.75 service fee + 3.9% + $0.60 processing)** and the ToS/content policy is community-aligned in spirit — but the live ToS page returned no extractable verbatim text in our fetch, so the actual content-policy edges remain unverified. Payment processor not disclosed publicly; merchant-of-record unclear.

## D1. Platform overview

- **Legal entity:** TicketGear Inc. dba Forbidden Tickets, Oakland, California (mail@forbiddentickets.com, +1 510-435-8422). [Source: search-surfaced contact metadata]
- **Founding:** Year not stated. Origin story: "grew out of the local Bay Area BDSM community, spurred by the need for an independent ticketing platform where core values such as education, inclusion, and consent could be cultivated…" ([forbiddentickets.com/about](https://forbiddentickets.com/about))
- **Leadership:** Not named publicly. Described only as "The Forbidden Tickets team."
- **Target market:** Pure-kink + sex-positive-broader, biased toward **education + community** (munches, workshops, conferences, play parties) rather than large festivals. Explicit support for "Leather, BDSM, Kink, LGBTQ+, BIPOC, and QTPOC communities."
- **Positioning vs Eventbrite/TickeTailor:** Self-described as "friendly, home-brewed, community-based ticketing platform" with "customizable ticket types, fast payouts, minimal fees." Pricing page explicitly benchmarks against Eventbrite (2% + $0.79) and BrownPaperTickets (5% + $0.99). ([forbiddentickets.com/pricing](https://forbiddentickets.com/pricing))
- **Customer base (visible from /events):** ~100+ US producers — Wicked Grounds (SF/LA/Portland), Folsom Street Community Center, Folsom Street East, DFW Dungeon, Arizona Power Exchange, KinkyBlackHouse, AfterDark (SF Bay), Praxium, Trans Dad Productions, Queer Kinky Summer Camp.

## D2. API surface

| Capability | Status |
|---|---|
| Public REST/GraphQL API | **None found** — no `/api` page, no developer docs |
| Webhooks | **None documented** |
| Event create/update/read endpoints | **None documented** |
| Attendee read-back for capacity sync | **CSV export only** (manual) |
| iCal export | **Not mentioned** |
| Zapier | **Not mentioned** |
| Embed | **Yes** — "Code snippets for embedding attractive Forbidden Ticket links" ([/features](https://forbiddentickets.com/features)) |
| Other integrations | **Bloom Community** (only integration named) |
| QR check-in | **Yes** — built-in |
| CSV download | **Yes** — for "event tracking and organization" |

Sales-channel signal: features page invites organizers to "schedule a Zoom meeting to learn more" — suggests integration / capacity-sync would be a **bespoke email conversation**, not self-serve.

## D3. ToS / content policy (verbatim)

**Could not extract verbatim ToS text.** WebFetch on `/terms`, `/terms-and-conditions`, and `/legal/terms` all returned only the homepage mission boilerplate, not actual policy clauses. The ToS page either uses a non-standard URL, is JS-rendered, or returns the homepage on miss. Marketing-level statements only:

- Mission: *"bringing people together through informed, creative, and consensual play"* ([/about](https://forbiddentickets.com/about))
- Values: *"Forbidden Tickets believes in the power of Diversity and promotes shared values of Inclusivity and Respect."* ([/](https://forbiddentickets.com/))
- Supports: *"Leather, BDSM, Kink, LGBTQ+, BIPOC, and QTPOC communities"* — implicit allow-list, but not framed as content policy.

**Age verification, refund handling, chargeback policy, prohibited-content edges, sex-worker policy: all unverified.** R2 should either (a) re-fetch via `browser-automation` to render JS, or (b) email mail@forbiddentickets.com for the policy doc directly.

## D4. Fee structure + payment flow

| Item | Detail |
|---|---|
| Service fee | **1.75% + $0.75** per ticket ([/pricing](https://forbiddentickets.com/pricing)) |
| Processing fee | **3.9% + $0.60** per order |
| Free/registration-only tickets | **Complimentary** — no fee for either organizer or attendee |
| Subscription | None mentioned |
| Fee-bearer choice | **Yes** — organizer can choose who pays service vs processing fee ([/features](https://forbiddentickets.com/features)) |
| Payment processor | **Not disclosed publicly** — "works with several different credit card processors" |
| Merchant of record | **Not disclosed** |
| Currency | **USD-implied** — no EUR/GBP/SEPA mentioned anywhere |
| Payout schedule | **"Quick payout after events"** — exact cadence not stated |
| Split payouts | **Yes** — "Split payout options for event collaborators" |
| Cards accepted | Visa, Mastercard, Amex, Discover |

## D5. Operator footprint

- **Geography: US-only**, biased to SF Bay + secondary US metros (NYC, Chicago, Dallas, Portland, Phoenix, Boston, Seattle, Denver, Atlanta).
- **Zero EU events found** in `/events` listing covering May–Sep 2026. Targeted search for `forbiddentickets.com` + Berlin/Germany/Europe returned only US event examples ("SF: This is Your Brain on Kink", NYC "Midnight Masquerade", etc.).
- **Zero overlap with R0 organizers:** TNT, Cherry Noir BDSM, Karada House, Sanya Alaya, School of Erotic Mysteries — **none present** on Forbidden Tickets.
- **Distinct operator base:** Folsom Street Community Center ([/events/folsom-street-community-center](https://forbiddentickets.com/events)), Wicked Grounds ([example event](https://forbiddentickets.com/events/san-francisco-aids-foundation/2dabaa91ec)), AfterDark ([/events/afterdark](https://forbiddentickets.com/events/afterdark)), Mischief Matters ([/events/mischief-matters](https://forbiddentickets.com/events/mischief-matters)), Devyn Stone ([/events/devyn-stone](https://forbiddentickets.com/events/devyn-stone)).
- **Active, not stagnant** — events scheduled through Sep 2026, healthy producer onboarding pipeline.

## Open questions

1. Does Forbidden Tickets accept **EU-based organizers** at all? (No legal/jurisdictional info found.)
2. Is the payment processor **Stripe (with kink-tolerant arrangement) or an adult-specialist (CCBill/Segpay)?** This determines chargeback/account-freeze risk.
3. **Multi-currency / SEPA support** — totally undocumented; assume USD-only until contradicted.
4. **Actual ToS edges** — could not extract; needs JS-rendered fetch or direct email.
5. **API roadmap** — is integration negotiable for partners, or genuinely capped at "Bloom Community + CSV export"?

## R2 decision hooks

- **Tilts toward Forbidden-Tickets-as-V1-default:** none compelling for an EU-based organizer hub. The platform is US-only in producer base, lacks documented multi-currency, and has no API.
- **Tilts toward Forbidden-Tickets-as-warm-fallback only:** ToS/values-alignment is genuinely kink-native — if TickeTailor (or whoever V1 default ends up being) deplatforms a Bubbles operator, Forbidden Tickets is *plausibly* willing to onboard them, but the EU payment-flow question is unresolved. Useful as an **existence proof** that kink-tolerant ticketing exists, less useful as an operational fallback for EU operators.
- **Tilts toward skip-entirely:** US-only operator footprint + no API + undocumented EU payment support + bespoke-email onboarding model = high friction for an EU organizer-hub V1. If R0 organizers are EU-based (TNT/Karada/etc.), Forbidden Tickets is functionally out of reach without significant platform-side work.
