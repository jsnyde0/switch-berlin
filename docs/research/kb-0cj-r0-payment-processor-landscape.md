# kb-0cj R0 — Payment processor landscape

**Scope:** Phase R0 broad survey of payment processors relevant to explicit / sex-positive / kink event ticketing in the EU. Surfaced from kb-cyq R1 (TickeTailor deep-scout) load-bearing finding: **TickeTailor is NOT merchant-of-record** — it routes to organizer's own Stripe / PayPal / Square account. Therefore the **payment processor's ToS, not the ticket platform's, is the financial-existential gate.** This is true regardless of which ticket SaaS sits above. R0 maps the landscape; does NOT recommend.

**Method:** WebFetch ToS pages (where reachable), WebSearch precedent mining (Reddit / 404 Media / sex-worker advocacy), checkout-flow inspection on R0 directory sample. 2026-05-21.

---

## TL;DR

- **Stripe is a hard ban for our scene's literal-framing operators.** ToS prohibits "fetish services" (added Jan 2024), pornography, and "sexually-related services" — language sweeps tantra workshops and kink education when triggered. Precedent pattern: silent onboarding → flag-on-volume (≈$50k+) → 1-7-day notice → payouts frozen + reserve held → no recovery. WishTender (dominatrix-tip platform) was cut off March 2024 with no notice; consistent w/ broader sex-worker-platform pattern.
- **Mollie, Adyen, Klarna, GoCardless all prohibit adult / sexual content too.** Adyen explicitly classes "fetish products" as **prohibited** (no waiver), "adult goods" as restricted (waiver possible). Klarna prohibits "live web cam, pornographic products". Mollie rejects "digital sexual or pornographic content".
- **No mainstream EU PSP openly accepts explicit content.** The EU-vs-US posture is largely the same; the Visa/Mastercard scheme rules and acquiring-bank pressure cascade equally on both sides.
- **MoR absorbers (Paddle, FastSpring, LemonSqueezy) all ban adult content explicitly** AND are digital-product-focused — not viable for event ticketing regardless.
- **Dedicated adult processors (CCBill, Segpay, Verotel, Epoch, RocketGate) openly accept** but: 5-10% fees (vs Stripe ~2.9%), $500-$1000/year scheme registration, 5-10% rolling reserve for 6 months, high-risk KYC. Built for subscription content, not event ticketing — integration mismatch likely.
- **Most of our scene actually runs on Stripe today** (via TickeTailor's organizer-connect flow, ~20 orgs). The financial-existential risk is **already present and unmitigated** in the current state; this is not a hypothetical Switch-introduces-risk problem.
- **Crypto (BTCPay, NOWPayments) is the only zero-policy-risk fiat-adjacent rail**, but Coinbase Commerce exits EU 2026-03-31 (MiCA fallout). Audience-friction is real — attendees of tantra workshops are not crypto-native.
- **Peer-platform validation (D7):** OnlyFans / Fansly / JustForFans / FanCentro / ManyVids all run on **CCBill / Segpay / Epoch / Centrobill** — confirming D2's "subscription-content-shaped" claim. The OnlyFans-Stripe arrangement is a bespoke high-risk carve-out, not a reusable pattern. No peer creator-subscription platform has solved the policy-gate problem; they've routed around it via specialist acquirers.

---

## D1. Stripe — ToS verbatim + precedents

### ToS / restricted-business policy

Source: `stripe.com/legal/restricted-businesses` (German render — English routes return 404 to WebFetch but content is the same per cross-references and per the Jan-2024 update widely cited):

> "Adult services such as prostitution, escorts, pay-per-view, sexual massages, **fetish services**, mail-order brides and adult live-chat features"

> "Pornography and other mature audience content (including literature, imagery and other media) designed for the purpose of sexual gratification"

> "**All artificial-intelligence generated content** that meets the above criteria" (added 2024)

**Note on "fetish services":** This phrase was added in the Jan 2024 ToS update per 404 Media reporting. Pre-2024 the ban covered "escort / live-chat / massage" — the 2024 update explicitly added fetish, which is the closest term to BDSM / rope / shibari education in our scene. The ambiguity — does "fetish service" reach a rope-tying class, a tantra retreat, a "sensual hearts temple" — is the operational risk surface. Stripe interprets at its discretion.

Stripe Services Agreement (`stripe.com/legal/ssa`) gives Stripe **termination-for-convenience**:

> "Stripe may terminate this Agreement or close User's Stripe Account at any time. Stripe will notify User in accordance with Law."

No floor on notice period. Reserve terms reference "Reserve Notice" in dashboard — no public % schedule, but industry reports cite 5-30% rolling reserves on high-risk-flagged accounts.

### User-reported precedents

- **WishTender shutdown (2024-03)** — Stripe terminated dominatrix tipping platform with no advance notice. 404 Media: "Stripe Cuts Off Platform Used by Dominatrixes". The Jan-2024 ToS update (adding "fetish services") triggered platform-wide enforcement waves.  
  Source: https://www.404media.co/stripe-cuts-off-platform-used-by-dominatrixes-wishtender/
- **Volume-triggered enforcement pattern** (multiple secondary sources, signaturepayments.com / corepay.net / paycompass.com): silent onboarding works for sub-$50k/yr volumes; flag triggers near $50k+ → 24-72 hr notice → frozen payouts + reserve hold → no productive appeal.
- **Survivors Against SESTA list (2018)** — sex-worker-rights group documented 100+ financial platforms (incl. Stripe, Square, PayPal) discriminating against sex workers / adult-adjacent operators. Source: https://survivorsagainstsesta.org/platforms-discriminate-against-sex-workers/
- **Reddit / sex-worker-forum precedent on direct kink-workshop bans is THIN** — likely because the operators silently operate-until-banned (no public posting to avoid triggering review), or migrate to Hipsy/TickeTailor as soon as they exit cottage scale. The absence of a flood of public ban-stories does NOT mean no risk; it means the population is small and the operators self-suppress reporting.

### Recovery path

Effectively none. Stripe ToS retains "for any or no reason" termination; appeals route through generic support; account-level appeals rarely succeed for adult-flagged decisions per multiple PaymentCloud / Charge.stripe.com / paycompass reports. **Funds-held duration** during termination: up to 90-180 days. For an organizer who lives ticket-cycle to ticket-cycle, a single freeze = catastrophic.

### EU vs US posture difference

**Materially the same.** Stripe-EU uses different acquiring banks (e.g., Citibank Europe in IE) than Stripe-US (Wells Fargo, PNC), but the Visa/Mastercard scheme rules — which forbid adult-coded MCC categories without explicit "high-risk" registration — apply equally. Stripe's restricted-businesses list is global. The 404 Media WishTender story applied globally despite a non-US-only enforcement framing.

One nuance: PSD2 / SCA in the EU adds 3DS friction but doesn't broaden adult acceptance. The EU's GDPR/PSD2 framework gives organizers slightly stronger termination-notice rights de jure, but de facto the freeze-first-explain-later pattern still applies.

---

## D2. Dedicated adult processors

| Processor | HQ | Adult acceptance | Fees (typical, no public rate card) | EU/EUR/SEPA | Integration | Event-tix fit |
|---|---|---|---|---|---|---|
| **CCBill** | US (Phoenix) + EU offices | Explicit — "All-inclusive content, entertainment and toy sales" listed as core vertical | Quote-based, ~10-15% + scheme reg | Yes (no SEPA-native confirmed; multi-currency) | API + hosted cart + shopping-cart plugins | Subscription-content-shaped; event-tix unusual |
| **Segpay** | US + EU-licensed (UK FCA #584599, CBI #635753) | Explicit — "adult and dating merchants globally" | 5-10% + $950 Visa-reg + $500 MC-reg + 5% rolling reserve 6mo | **Yes — EUR + SEPA + PSD2-compliant** | Hosted + API + recurring-billing | Subscription-shaped; event-tix unusual |
| **Verotel** | NL (Amsterdam) — EMI status | Explicit — homepage: **"Adult? No problem!"** | "Competitive rates"; published rate card on site (rare in space) | **Yes — EU/EUR native, escrow under EU regulation** | VerotelRUM hosted + FlexPay API | Subscription-shaped; could be event-tix-able |
| **Epoch** | Guernsey (Epoch EU Ltd) | Explicit adult vertical, 20+ yr track record | Per-merchant quote; $1000/yr MC-reg for EU merchants | EU-licensed, multi-currency | MoR model — Epoch is the merchant of record | Subscription-shaped; MoR shields organizer from acquirer pressure |
| **RocketGate** | US | Adult gateway (not full MoR; routes to acquirer) | Per-merchant; less public info | Likely no SEPA-native | Gateway-only — needs separate merchant account | Subscription-shaped; not event-tix-shaped |

**Key tension:** these processors are *content-subscription* shaped (cam sites, OnlyFans-class platforms, dating). None publish event-ticketing case studies. **Integration mismatch is real** — an organizer wanting "sell 30 workshop tickets for €60 each" through CCBill would be a square-peg fit, and the scheme-reg fees alone (~$1500/yr) eat margin on low-volume events.

**Verotel + Segpay are the most plausible EU candidates** if our-scene operators ever need a true Stripe replacement: both EU-EUR-licensed, both openly accept fetish/adult, both EMI/FCA-regulated.

Sources: https://segpay.com/solutions/eu-merchants/ ; https://www.verotel.com/ ; https://www.ccbill.com/ ; https://merchantmachine.co.uk/epoch/

---

## D3. EU PSPs

| PSP | Adult / fetish posture | Source / verbatim |
|---|---|---|
| **Mollie** | **Prohibited** — "Any digital sexual or pornographic content, for example erotic or pornographic imagery and videos"; "Adult dating sites or mail-order brides" | help.mollie.com/.../115000939369 (per Mollie support docs) |
| **Adyen** | **Fetish products = PROHIBITED (no waiver).** Adult goods (excl. fetish) = restricted (waiver possible). Sexual content = prohibited. "Sexually oriented massage parlors, saunas, escort agencies or any sexually-related services" = prohibited. Casual dating = restricted (merchant) / prohibited (platform) | adyen.com/legal/list-restricted-prohibited (verbatim above) |
| **GoCardless** | Direct-debit-focused; restricted-activities list less explicit publicly, but as a UK-FCA regulated PSP subject to same scheme rules — adult is effectively prohibited. Direct-debit also a poor fit for sub-€100 event-tix (consumer DD friction). | gocardless.com/legal/restrictions/ |
| **Klarna** | **Prohibited:** "prostitution-related services, escort agencies, adult massage services... adult, sexual or pornographic products and services, including live web cam." Also imposes line-item-data redaction even for legitimate merchants ("never send line item data that could reveal details about someone's sex life"). | docs.klarna.com/.../prohibited-and-restricted-businesses |

**Headline finding:** Adyen is the strictest of the bunch — fetish is hard-prohibited, no waiver path. **No mainstream EU PSP openly accepts our-scene literal framing.** They're all downstream of the same Visa/Mastercard scheme rules.

This means the workshop / retreat / sex-positive-festival organizer's choice is: (a) Stripe + softened framing + ban risk, (b) dedicated adult processor + high fees + integration friction, (c) self-host + cash/SEPA-direct, or (d) crypto fallback.

Sources: verbatim Adyen list from adyen.com/legal/list-restricted-prohibited ; Klarna verbatim from docs.klarna.com ; Mollie summary from official help-center indexed snippets.

---

## D4. MoR absorbers — DEAD-END for event ticketing

| MoR | Adult posture | Event-tix fit |
|---|---|---|
| **Paddle** | "adult and other age-restricted content and services, including sexually-oriented or pornographic products or services, **any material of a lewd and lascivious nature**, dating services/applications, or any other products/services intended for this industry" — prohibited. **Also explicitly excludes physical/in-person services, consulting, coaching, IT services.** | **Hard NO** — Paddle is SaaS-only by AUP. Event-tix isn't even within scope before the adult-content layer. |
| **LemonSqueezy** | "sexually-oriented or pornographic content" prohibited. Digital goods only. | **NO** — digital goods only. |
| **FastSpring** | "Adult content, pornography and sex-related merchandising are prohibited on all FastSpring sites. **This includes sites that may infer sexual content or link to adult content elsewhere.**" — broadest exclusion of the three. | **NO** — digital goods focus + broad adult exclusion. |

**Conclusion:** MoR absorber path is unavailable on two independent axes (product-type mismatch AND adult-content ban). Cross this option off the matrix.

Sources: paddle.com/help/start/intro-to-paddle/what-am-i-not-allowed-to-sell-on-paddle ; docs.lemonsqueezy.com/help/getting-started/prohibited-products ; FastSpring legal pages via TOS Tracker.

---

## D5. Crypto fallback

| Provider | Fee | KYC for organizer | Audience friction | EU posture |
|---|---|---|---|---|
| **BTCPay Server** (self-hosted, OSS) | **0%** (server costs only) | None — operator-controlled | High — Bitcoin-native attendees only; no auto-EUR settlement | MiCA exempt (self-hosted infrastructure); operator owns compliance |
| **NOWPayments** | 0.5% single-coin / 1% with conversion; 350+ coins | Light KYC | Moderate — wide coin support eases UX | MiCA posture unclear; verify before scaling per industry note |
| **Coinbase Commerce** | 1% | Yes | Moderate | **EXIT EU 2026-03-31** — no longer viable post-MiCA |
| **CoinGate** (added for reference) | 1% flat, EUR settlement | Yes | Lower — fiat-settles in EUR | **MiCA-licensed**, PI-licensed in EU |

**Audience-friction reality check:** A "Tantric Kink" workshop in Munich charging €120/ticket — what fraction of attendees would pay in BTC? Realistically <5% in 2026. Crypto is a **fallback rail** (for when Stripe shuts off mid-cycle), not a primary rail.

**BTCPay's lack of fiat-settlement** is a hard blocker for organizers who need to pay venues / facilitators / catering in EUR — they'd hold BTC volatility risk between sale and settlement. CoinGate's EUR-settlement + MiCA license positions it better as a primary-or-fallback for organizers willing to take 1%.

Sources: docs.btcpayserver.org ; nowpayments.io/pricing ; coingate.com/blog ; industry MiCA-deadline reporting.

---

## D6. Operator-actually-uses map

**Critical structural observation:** TickeTailor (~20 orgs in R0 directory) is NOT a payment processor — per `help.tickettailor.com/.../which-payment-providers-do-you-support`, TT routes to organizer's connected **Stripe, PayPal, or Square** account. "Ticket funds never touch Ticket Tailor's bank account. Your ticket money is sent to your online payment processing account (e.g. your Stripe account) directly after a ticket is purchased."

This means: **every TickeTailor org in our scene is, by default and almost certainly, running on Stripe.** TickeTailor recommends Stripe in its onboarding flow.

| Org | R0 ticket platform | Underlying payment processor | Evidence |
|---|---|---|---|
| Shibari Studio Berlin | TickeTailor | **Stripe** (almost certain — TT default) | TT's own docs: Stripe is default connect path |
| Rope Jam (London) | TickeTailor | **Stripe** (TT default) | TT docs |
| TNT (The New Tantra, Berlin) | TickeTailor | **Stripe** (TT default) | TT docs |
| Akaya World / European Tantra Festival | TickeTailor | **Stripe** (TT default) | TT docs |
| Sanya Alaya (Tantric Kink, Munich) | TickeTailor | **Stripe** (TT default) | TT docs |
| Amanda Biccum (Embodied Tantra, NL) | TickeTailor | **Stripe** (TT default) | TT docs |
| Coach Grethe (Scotland/Norway) | TickeTailor | **Stripe** (TT default) | TT docs |
| London School of Tantra (Fox Den) | TickeTailor | **Stripe** (TT default) | TT docs |
| Embodied Intimacy (NL) | TickeTailor | **Stripe** (TT default) | TT docs |
| Higher Consciousness Academy | TickeTailor | **Stripe** (TT default) | TT docs |
| Sensual Hearts Temple (Embodied Co-Loving) | TickeTailor | **Stripe** (TT default) | TT docs |
| Liebeskunstnetzwerk (Somatic Consent Intensive) | TickeTailor | **Stripe** (TT default) | TT docs |
| Milk N Honey Festival | TickeTailor | **Stripe** (TT default) | TT docs |
| Ibiza Tantra Festival | TickeTailor | **Stripe** (TT default) | TT docs |
| School of Erotic Mysteries | TickeTailor | **Stripe** (TT default) | TT docs |
| Haneen Khan | TickeTailor | **Stripe** (TT default) | TT docs |
| Karada House (Berlin) | WordPress + WooCommerce + The Events Calendar | **Likely Stripe via WooCommerce-Gateway-Stripe** OR **Mollie via WooCommerce-Mollie** (DE-EU common); could also be PayPal | `/kasse/` returned 403 on direct fetch; needs CDP inspection — note Mollie's adult-content ban applies, so if Mollie is actually used, Karada House is at the same kind of risk |
| SM Kurse (Berlin) | WordPress + Modern Events Calendar | **Likely Stripe or PayPal/SEPA via WC**, possibly Mollie | Site closed-cart on inspection (`/store` returned no payment indicators) |
| Kinky Deviants (Vienna) | WordPress + Events Manager | **Unknown** — no payment-method indicators visible on public site | Likely Stripe or PayPal AT-direct |
| Soul Impact Berlin | Squarespace Commerce | **Stripe** (Squarespace Commerce default; also offers PayPal) | Squarespace Commerce ships with Stripe as default |
| Knot Here (Amsterdam) | Squarespace | **Stripe** + likely **iDEAL** via Squarespace Commerce NL routing | Squarespace default |
| House of Play (CPH) | Yogo (DK SaaS) | **Stripe** (Yogo wraps Stripe per R0 finding) | R0 doc F6: "Yogo wraps Stripe" |
| Umaversity (Amsterdam) | PlugAndPay | **Likely Mollie or Stripe via PlugAndPay** | URL redirect from checkout to josarah.com suggests org-direct flow; PlugAndPay supports both |
| Healing Movements (NL) | Hipsy | **Mollie** (Hipsy uses Mollie per prior scout) | docs/hipsy_analysis.md |
| ManToManifestation Festival | Hipsy | **Mollie** | Same |
| Iridescent Amsterdam | Eventix | **Adyen** (Eventix is built on Adyen) — or **Mollie**; needs confirmation | Eventix docs reference Adyen + Mollie |
| Subspace BXL | Eventix | **Adyen** or **Mollie** | Same |
| Wasteland (Amsterdam fetish) | Weeztix + Eventix | **Adyen** / **Mollie** | Same |
| Klub Verboten | DICE.fm | **Stripe** (DICE built on Stripe) | DICE's public engineering posts |
| Pornceptual | Shotgun | **Stripe** (Shotgun built on Stripe — confirmed in Shotgun's public engineering blog) | Industry-known |
| Wet Playground (Barcelona "S*x-Positive") | Eventbrite | **Stripe + Eventbrite Payments** (Eventbrite uses both PayPal and a Stripe-backed Eventbrite Payments) | Eventbrite docs |
| Urban Joy / Joe Jung | Eventbrite | **Stripe + Eventbrite Payments** | Same |
| Mandy Baum, Journey Within Tantra, Christian Rippel | Eventbrite | **Stripe + Eventbrite Payments** | Same |

**Synthesis:** **Stripe is the structural payment processor underneath the vast majority of our scene** — directly (TT, Squarespace, DICE, Shotgun, Yogo) or indirectly (Eventbrite Payments). The next-most-common is **Mollie** (Hipsy + likely WordPress-WooCommerce + Eventix). **Adyen** is a strong candidate underneath Eventix / Wasteland but unconfirmed. **None of the processors actually underneath our scene's checkouts openly accept adult/fetish/sexual content** — every one of them is one ToS-enforcement cycle away from an account freeze.

The risk surface is not "Switch introduces processor risk by routing." The risk surface is "this entire scene runs on a stack that has been one policy memo away from collapsing for years." Switch's stance on this is downstream of acknowledging this is the operating reality.

---

## D7. Cross-reference: peer creator-subscription platforms

**Lens shift from D6.** D6 mapped our-scene **event-ticketing organizers** (workshops, retreats, festivals). This section is the **peer-platform** view: what processor stack do OnlyFans, Fansly, and the OnlyFans-alternatives ecosystem actually run on? Two motivations: (a) D2's claim that CCBill / Segpay / Verotel / Epoch are subscription-content-shaped is empirically validated here, and (b) the OnlyFans-Stripe arrangement is a notable carve-out anomaly worth naming.

| Platform | Primary processor / acquirer | Alt rails | Notes |
|---|---|---|---|
| **OnlyFans** | Multi-stack: Stripe (special carve-out, third-party-reported, not officially confirmed) + **CCBill**; acquired via Merrick Bank / Harris Bank | None — cards only; rejects PayPal / crypto | Stripe-on-OnlyFans is anomalous: likely a bespoke high-risk contract with mandatory consent + ID verification layers, not standard Stripe-Connect onboarding |
| **Fansly** | **CCBill + Epoch** (billed under "Select Media LLC") | PayPal, Paxum (processor-routed) | Standard adult-stack |
| **Fanvue** | Not publicly disclosed (high-risk acquirer) | SEPA / IBAN / Wise / crypto for **creator payouts** | UK-based; processor opaque on customer-facing side |
| **JustForFans** | **CCBill** | Crypto via Coinpayments + Qvapay | Standard adult-stack |
| **ManyVids** | **Segpay + Epoch** (inferred from secondary sources, not directly confirmed) | Crypto, Paxum (historical) | |
| **LoyalFans** | Not publicly disclosed | ACH / wire / SEPA / Paxum payouts | |
| **FanCentro** | **Centrobill** (sister / in-house processor) | Crypto + Paxum payouts | At-scale platforms build their own processor — pattern worth noting |
| **AdmireMe.VIP** | Not disclosed (UK-based; Segpay / Verotel likely, inferred) | — | |
| **AVN Stars** | **Defunct for monetization since 2022-01-01** — banking discrimination | N/A | Cautionary: a platform with content + payment stack still got cut |

**Visa / Mastercard scheme-rule context (globally validates D1 + D3):** the same Oct-2021 Visa / MC adult-merchant rule packages that constrain Stripe / Mollie / Adyen *also* constrain whoever acquires for these subscription platforms. Visa's program folded into **VIRP** (Visa Integrity Risk Program, May 2023) — written consent verification, ID validation, pre-publication review, takedown SLAs. Mastercard's parallel package is **AN 5196**. Combined with the **MATCH list** (terminated-merchant database that follows a business across acquirers), this is why specialist processors with pre-built compliance tooling are the only viable boarders for adult MCCs — across both event-ticketing and creator-subscription verticals.

**Synthesis against D2's "integration mismatch" claim:** peer-platform data **confirms** D2. Every CCBill / Segpay / Epoch deployment in the wild is subscription-content-shaped (recurring billing, sub-merchant content rails, age / consent verification primitives). For event-ticketing (one-off €60-€120 purchases, no recurring, no content-hosted) the integration mismatch is structural. **Verotel + Segpay remain the most plausible EU candidates** for a hypothetical event-tix deployment (per D2), but the absence of any peer event-platform actually running on them is itself evidence that the shape-mismatch is real.

**OnlyFans-Stripe anomaly — do not generalize.** OnlyFans reportedly runs partial Stripe coverage despite the Jan-2024 ToS update banning "fetish services." Two plausible readings: (a) bespoke pre-2024 grandfathered high-risk contract with mandatory consent / ID layers — not a precedent any new merchant could replicate; (b) the Stripe relationship is overstated by third-party reporters and OnlyFans is actually fully on CCBill + similar, with Stripe only handling tangential rails (creator payouts, agency billing). Either way: **the OnlyFans-Stripe story is not a counter-example to "Stripe is a hard ban for our scene's literal-framing operators" in D1.** It is sui generis.

**Why this matters for Switch (V1+):** if Switch ever moves from event-ticketing-passthrough toward any creator-monetization rail (subscriptions, tips, content unlocks), the relevant processor set shifts from "Stripe-with-mitigations" (D1) to "specialist adult acquirer" (D2). The creator-subs vertical is where Verotel / Segpay become primary candidates rather than fallbacks. This is downstream of an ADR-010 D1(d)-class scope decision.

**Sources for D7:** [Corepay — OnlyFans alternatives](https://corepay.net/articles/alternatives-to-onlyfans-payment-processor/) ; [PaymentCloud — OF processor guide](https://paymentcloudinc.com/blog/onlyfans-payment-processor-guide/) ; [Segpay — VIRP brief](https://segpay.com/blog/visa-integrity-risk-program-high-risk-merchants/) ; [Input Mag — AVN Stars shutdown](https://www.inputmag.com/culture/avn-stars-end-monetization-sex-work-banking-discrimination) ; [Fanvue Help — payouts](https://help.fanvue.com/en/articles/9508853-payout-methods-available-on-fanvue) ; [BonerGhosts — LoyalFans](https://bonerghosts.com/2025/03/19/loyalfans-payments/) ; [PayConsults — Epoch / Segpay](https://www.payconsults.com/post/epoch-segpay-is-this-the-end-of-the-list-of-payment-providers-for-adult-merchants) ; [FanSpicy — Fansly descriptor](https://fanspicy.com/insights/how-does-fansly-appear-on-bank-statement/).

**Staleness flags:** OnlyFans / Stripe is third-party-asserted, not authoritatively confirmed. ManyVids / LoyalFans / Fanvue / AdmireMe processor identities are opaque — confirming would require billing-descriptor checks on live transactions. Acquirer relationships shift post-2021 Visa policy changes; treat platform-to-processor mappings as "as-of late-2024 / 2025" snapshots, not durable facts.

---

## Open questions / unresolved

- **Adyen vs Mollie underneath Eventix / Weeztix:** which is it? Affects Wasteland, Subspace BXL, Iridescent risk surface. Worth one CDP-checkout inspection per Eventix event.
- **WordPress organizers (Karada House, SM Kurse, Kinky Deviants):** what specific WooCommerce-payment-gateway plugin? If Mollie, risk is the same as TT-on-Stripe. If a German Sparkasse-direct or SEPA-direct, risk is much lower (banks generally less twitchy than card-network PSPs on adult content — but ban-on-disclosure still possible).
- **Verotel as Stripe-replacement viability:** does Verotel actually support a workshop-tickets shape (one-off purchases, low ticket count, no subscription)? Worth a 30-min sales call in R1 — they openly publish rates which is unusual in the high-risk space.
- **Stripe enforcement-volume threshold:** the "$50k flag" figure is widely cited in secondary sources but never officially confirmed. Is it actually $50k of *annual* gross? *Monthly*? Per-event? Affects which of our-scene organizers are above/below the line.
- **EU-vs-US Stripe enforcement asymmetry:** a deeper precedent dive specifically on **EU-Stripe accounts** terminated for adult-adjacent reasons (vs the WishTender US case) would be high-value. Sex-worker advocacy groups (e.g., ESWA in Europe) likely have records.
- **Hipsy's payment processor + their content-policy stack:** Hipsy uses Mollie (per prior scout) AND has its own content policy (bans BDSM/sex-party literal framing). Is Hipsy's content policy *because* Mollie's is, or independent? Affects whether moving to a more permissive ticket platform (TT) but keeping Mollie underneath actually helps.

---

## R1 deep-scout priorities (proposed)

| Priority | Processor | Rationale |
|---|---|---|
| **P0** | **Stripe** — full ToS + EU-precedent deep-dive | Underlies majority of scene; Jan-2024 "fetish services" addition is highest-leverage operational risk. Need: actual EU-organizer ban precedents (search ESWA, sifted.eu, fetlife public discussions, hacker news ToS-update threads), volume-threshold empirics, recovery-path interviews if possible. |
| **P1** | **Mollie** — secondary scene processor + Hipsy's stack | Second-largest exposure. Verbatim prohibited list, EU-org ban precedents, posture toward "wellness" / "tantra" / "education" framing of adult-adjacent. |
| **P1** | **Verotel** — only EU-native openly-adult processor with public rates | If Stripe-replacement question ever arises, Verotel is the realistic answer. Need: actual fee schedule, event-tix integration shape, ticket-platform compatibility (does any of TT/Eventix/Eventbrite support Verotel?), KYC depth. |
| **P2** | **Segpay** — EU-licensed adult processor, but US-rooted | Backup option to Verotel. Mainly worth confirming the FCA/CBI license claims and the fee structure for one-off tickets vs subscription content. |
| **P2** | **CoinGate** — MiCA-licensed crypto, EUR settlement | As a true Stripe-failover rail, CoinGate beats BTCPay (fiat-settled) and beats NOWPayments (MiCA-licensed). Worth one-day deep-scout on integration shape, organizer onboarding, and which ticket platforms support it. |
| **Skip in R1** | **Adyen, Klarna, GoCardless, Paddle, FastSpring, LemonSqueezy** | All clear policy bans; no leverage path; further depth not load-bearing for V0/V1. |
| **Skip in R1** | **CCBill, Epoch, RocketGate** | Subscription-content-shaped, not event-tix-shaped. Confirmed dead-end on integration mismatch. |

---

## canonical_refs

- `kb-0cj` — this bead
- `kb-cyq` — parent (R0 directory + R1 TickeTailor scout)
- `kb-cyq` R1 finding: TickeTailor is not MoR — this entire R0 is downstream of that
- `docs/research/kb-cyq-r0-provider-landscape.md` — directory source for D6
- `docs/research/kb-cyq-r1-tickettailor-deepscout.md` — origin of the not-MoR finding
- `docs/decisions/ADR-010-event-based-product-posture.md` — D1(c) ticketing as revenue path
- `docs/decisions/ADR-011-personal-agent-layer-additive.md` — facilitator-agent as integration vehicle
- `docs/hipsy_analysis.md` — Hipsy uses Mollie; Mollie's adult-content ban therefore reaches Hipsy's organizers
