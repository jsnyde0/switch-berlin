# kb-cyq R0 — Provider-Frequency Landscape

**Scope:** Phase R0 discovery deliverable for `kb-cyq` (third-party ticket platform research for organizer-hub V1). Maps real organizers in the kink / sex-positive / conscious-sexuality / adjacent-embodied scene to the ticketing/payment providers they actually use, with evidence URLs. Discovery layer — does NOT make platform recommendations; that's Phase R1 deep-scouts and Phase R2 synthesis.

**Method:** Four parallel subagent scouts (2026-05-21), one per niche cluster (A: Berlin/EU explicit kink; B: tantra & conscious-sexuality coaches; C: sex-positive festivals & retreats; D: adjacent embodied/somatic with crossover signal). Each scout returned organizer → provider mappings with evidence URLs. This doc consolidates and synthesizes.

**Status:** R0 complete. R1 deep-scouts pending (P0: TickeTailor with logged-in CDP, Hipsy reuse).

---

## Provider tier summary

Frequency counts are across all clusters; "our scene" = the union of A + B + C + D.

| Tier | Provider | Footprint | Content-policy posture | Format affinity |
|---|---|---|---|---|
| **T1 dominant** | **TickeTailor** | B:13 + C:3 + D:2 + A:2 = **~20 orgs** | Openly explicit framing tolerated ("Tantric Kink", "Sex Club", "Sex Magic", "Sensual Hearts Temple", "Rope Jam") | In-person sex-positive education |
| **T2 specialist** | **Hipsy** | C:2-3 + A:1 — *already deep-scouted 2026-05-19* | Bans BDSM / sex-party literal-framing (per `docs/hipsy_analysis.md`) | NL/EU conscious community |
| **T2 specialist** | **Eventix** | A:2 (Subspace BXL, Iridescent) + C:1 (Wasteland) = 3 | Dutch event-industry default; tolerant in rope/fetish | NL/BE rope + AMS fetish |
| **T2 specialist** | **DICE + RA + Shotgun** | A:3 (Klub Verboten, Pornceptual, Torture Garden) | Mainstream techno providers; tolerant via dress-code/vetting flows | Fetish nightlife/club |
| **T3 conscious-coded** | **Eventbrite** | D:heavy (cuddle, ecstatic dance, men's circles, "Tantric Women's Circle"); softened-framing kink (Wet Playground "S*x-Positive" Barcelona); avoided by DE/AT explicit kink | Tolerates "conscious"/"tantric" framing; kinkier orgs route around | Adjacent/conscious community |
| **T3 digital** | **ThriveCart** | B:4 (Joanna Bauer Savage, Jannine MacKinnon, Feral Grace) | Digital cohorts / self-paced courses — not event ticketing per se | Course platform |
| **T3 UK niche** | **Dandelion** | B:3 (Sex Club, Bibi Gratzer, Rosa Maxwell) | UK-leaning, queer-friendly | Online workshops |
| **T4 self-hosted** | **WordPress + Events plugins** (Modern Events Calendar, Events Manager, The Events Calendar) | A:3 (Karada House, SM Kurse, Kinky Deviants Vienna) | Self-controlled — no platform policy | DE/AT education-focused |
| **T4 self-hosted** | **Squarespace / Wix native** | Mx Gili (B), Berlin Breathwork Days (D), Soul Impact (A — *corrected from Shopify*), FEAST (C), Knot Here (A); Umaversity → PlugAndPay | Self-controlled | Solo coaches / curated festivals |
| **T4 vetting-first** | **Telegram + custom + email** | Kink-Y, Xplore Berlin, Quälgeist app, Urban Joy / Joe Jung overlay, KuschelRaum | N/A — vetting *layer above* any provider | Application-gated explicit content |
| **T5 marketplace** | **BookRetreats / Retreat.guru / Tripaneer** | Global tantra retreats (cluster C aggregators) | Their own audience layer; not a provider for self-promoted events | Discovery + booking |
| **T5 specialist** | **Yogo** (DK fitness/activity SaaS, wraps Stripe) | A:1 (House of Play — *corrected from Stripe-direct*) | Single data point; unclear in our scene | Activity-class management |
| **T5 specialist** | **PlugAndPay** (NL checkout SaaS) | A:1 (Umaversity Amsterdam) | Single data point | NL checkout layer |
| **T5 specialist** | **Comers** (Swedish retreat-center booking) | C:1 (Ängsbacka Sexsibility Festival) | Single data point | Retreat centre stacks |
| **T5 specialist** | **HeadFirst Bristol (HDFST)** | C:1 (OURGASM Festival, Bristol) | UK indie-music ticketing | Regional UK |
| **T5 specialist** | **Zing Events** | C:1 (ISTA — International School of Temple Arts brand page) | Brand-aggregation across regional events | International training brands |
| **T5 specialist** | **Wix-native ticketing** | C:1 (FEAST AU) | Self-contained | Wix-built festival sites |
| **T5 specialist** | **JoyClub / Berliner.Party** | A:1 (Kinktastisch Berlin lists via both) | Kink-community-specific (DE) | DE kink community calendars |

---

## Cross-cluster load-bearing findings

### F1. TickeTailor is the de-facto content-policy-tolerant SaaS for sex-positive education

~20 data points across rope/shibari (Shibari Studio Berlin, Rope Jam London, Sanya Alaya "Tantric Kink" Munich), tantra (The New Tantra Berlin, Akaya World European Tantra Festival, Ibiza Tantra Festival, Coach Grethe, Higher Consciousness Academy, Amanda Biccum, Embodied Intimacy NL, London School of Tantra, Quintimacy Manchester, Somaki), somatic-consent (Liebeskunstnetzwerk Somatic Consent Practitioner Intensive), temple nights (Embodied Co-Loving Sensual Hearts Temple at Life Artists Creators Hub Berlin), festivals (Milk N Honey, Ibiza Tantra, European Tantra Festival).

**Hosts openly explicit framing without sanitization** — "Tantric Kink", "Sex Club", "Sex Magic", "Sensual Hearts Temple", "Sex & Sovereignty", "Tantric-Shibari" — a notable contrast to Hipsy (bans BDSM/sex-party literal framing) and Eventbrite (kinkier organizers route around).

**TickeTailor outranks Hipsy in *our* scene.** Hipsy is dominant in NL conscious-community ticketing but content-policy-restrictive; TickeTailor spans EU-wide explicit framing including Berlin (TNT, Shibari Studio, Sensual Hearts).

### F2. "Vetting layer above the provider" is a recurring design pattern

Multiple organizers across all four clusters decouple **consent-vetting** from **ticketing platform**, putting vetting upstream:

- **Telegram bots** — Urban Joy / Joe Jung (cuddle + ecstatic dance + shibari + tantra + men's circle, all gated via `t.me/JoeJung` before Eventbrite checkout); Kink-Y Berlin (Symbiotikka party); KuschelRaum routes via per-organizer email.
- **Application forms / invite-only signup** — The Intimate Revolution (own `tickets.theintimaterevolution.com` subdomain, application-gated); Mx Gili (Squarespace gated signup → invite → /signup-2026); Ananda Sarita / Xplore Berlin (email-only).
- **Member portals** — Klub Verboten (member layer on own site before DICE/RA checkout); Quälgeist e.V. (custom app + on-site calendar).

**Design implication for organizer-hub V1:** Switch facilitator agent can OWN vetting upstream of whichever third-party provider handles the cleaned ticket flow. This is consistent with kb-2ve Phase A authoring-hub framing — Switch as canonical authoring layer, with cleaned projections (and vetting filtration) sitting above per-platform checkout. Vetting is not a feature the third-party platform needs to provide.

### F3. Format dictates provider (clean rule)

| Format | Modal provider |
|---|---|
| Digital cohort / self-paced course | ThriveCart (low fees + course-platform integrations) |
| In-person workshop / retreat (sex-positive education) | TickeTailor |
| Multi-day sex-positive festival | Custom (gender quotas + app gating + accommodation/food bundling can't be SaaS'd) |
| Fetish nightlife / club | DICE / RA / Shotgun (dress-code/vetting layer leverages techno-scene flows) |
| Application-gated explicit (sex-positive parties, BDSM) | Telegram + custom |
| Conscious-coded adjacent (cuddle, ecstatic dance, AR, men's circles) | Eventbrite |
| Berlin solo educators | TickeTailor (if explicit), Eventbrite (if softened), WordPress plugin (if self-hosted) |

**For organizer-hub V1 tactical short-term:** **workshop/retreat format = TickeTailor**; **festival format = likely custom-build-required or accept-loss-of-features**; **party-format = TBD pending V1 scope on whether organizer-hub covers parties at all**.

### F4. Eventbrite tolerance ceiling

Eventbrite is **more tolerant than expected for "conscious"/"tantric" framing** — used openly for cuddle parties, "Tantric Women's Circle" (Berlin, May 2026), ecstatic-dance-with-cacao, men's circles, even ManKind Project. But: **avoided by DE/AT explicit kink organizers** (Karada House, SM Kurse, Kinky Deviants Vienna all on WordPress instead). The line is around explicit kink/BDSM vocabulary.

Notable boundary case: **Wet Playground (Barcelona) uses Eventbrite for "S*x-Positive Festival"** — with asterisk-censored title. Eventbrite *will* host that level of self-censoring.

**Open question for R1 (Eventbrite ToS-precedent scout):** What's the explicit content boundary? Is asterisk-censoring sufficient? Has Eventbrite ever banned an organizer in our scene? What recovery exists?

### F5. Self-hosted is durable but not a leverage path

DE/AT education-focused organizers (Karada House, SM Kurse, Kinky Deviants Vienna) prefer **WordPress + Events Calendar plugins** — full control, no platform-policy risk. Same pattern with Squarespace/Wix for solo coaches.

**Implication:** these organizers aren't seeking a third-party platform to outsource to — they're seeking *less* platform dependency. **Switch's V1 leverage path for them is probably not "we route you to a third-party"; it's "Switch projects cleaned tickets to your own self-hosted checkout via Stripe or your existing WordPress plugin."** This is a separate organizer-hub flow shape from the third-party-platform path — worth raising in kb-dko organizer-hub epic scoping.

### F6. Cluster A seed corrections

Three user-supplied seed providers turned out incorrect on direct inspection:

| Seed | User said | Cluster A scout found | Evidence |
|---|---|---|---|
| Soul Impact Berlin | Shopify (cartToken URL pattern) | **Squarespace** | `images.squarespace-cdn.com` on `/store`; no Shopify cart endpoints |
| Subspace BXL | Weeztix | **Eventix** | "Can't see booking?" → `eventix.shop/wxqwmqje` |
| House of Play | Stripe Checkout direct | **Yogo** (fitness/activity SaaS, DK; wraps Stripe) | Member portal at `hop.yogo.dk` |

**Implication:** the user's initial scan was reading payment infrastructure (Stripe) for ticketing platform (Yogo). Soul Impact may have shown a Shopify cart at the user's earlier observation moment and migrated since — worth a confirmation if Soul Impact comes up again as a deep-scout target.

### F7. Venue concentration: Life Artists Creators Hub (Milastr. 4 Berlin)

Cluster D and B independently surfaced this Berlin venue as hosting Mandy Baum (conscious cuddling + AR), Kuschelevents (cuddle), Christian Rippel ecstatic dance, Journey Within Tantra (women's circle), Embodied Co-Loving (Sensual Hearts Temple). Hub for sex-positive-adjacent embodied work. **Provider footprint here = Eventbrite + TickeTailor.** Any provider serving Milastr. 4 organizers serves a meaningful slice of Berlin's scene.

**Possible V1 launch-partner venue** for organizer-hub pilot.

### F8. Urban Joy / Joe Jung is a textbook V1 ICP

Single Berlin operator running:
- Ecstatic dance (Euphoria)
- Conscious cuddle (Cuddle Castle)
- Tantra (Temple Night)
- Shibari workshops
- Men's circle (Männerkraft Berlin)

All on **Eventbrite + Telegram-approval gating** (`t.me/JoeJung`). Crosses every cluster boundary at the single-operator level. **If we want a V1 pilot organizer who exercises the full cleaning + vetting + cross-platform flow, this is the canonical candidate.**

---

## Organizer directory (consolidated)

Aim of acceptance item (1a): 25-40 organizers. Delivered: **~80 organizers** across four clusters. Tables below preserve evidence URLs per organizer. (Pruned for the very-long-tail in Cluster D adjacent niches.)

### Cluster A — Berlin/EU explicit kink + BDSM + rope/shibari + sex-party

| Organizer | Website | Provider | Evidence |
|---|---|---|---|
| Soul Impact Berlin | soulimpactberlin.de | Squarespace Commerce (corrected from Shopify) | squarespace-cdn.com on /store |
| Karada House (Berlin) | karada-house.de | WordPress + The Events Calendar + WooCommerce (`/warenkorb/`, `/kasse/`) | `the-events-calendar` plugin folder; solidarity/regular/supporter tiers |
| SM Kurse (Studio LUX, Berlin) | smkurse.de | WordPress + Modern Events Calendar | `modern-events-calendar/assets/img/svg/` |
| Subspace BXL | subspace-bxl.be | **Eventix** (corrected from Weeztix) | `eventix.shop/wxqwmqje` |
| House of Play (Copenhagen) | houseofplay.dk | **Yogo** (corrected from Stripe-direct) | `hop.yogo.dk` member portal |
| Shibari Studio Berlin (Dan Carabas) | shibari-studio.com | **TickeTailor** | `tickettailor.com/events/shibaristudioberlin` |
| Iridescent (Amsterdam) | iridescentamsterdam.com | **Eventix** | `eventix.shop/xfcexrdq` and `shop.eventix.io/` |
| Umaversity (Amsterdam) | umaversity.com | **PlugAndPay** (NL) | `umaversity.plugandpay.nl/checkout/shibari-workshop-single-ticket` |
| Healing Movements (NL) | via hipsy.nl | **Hipsy** | hipsy.nl/event/2506-sensual-rope-play-shibari |
| Knot Here (Amsterdam) | knothere.nl | Squarespace; per-event provider TBD | squarespace-cdn |
| Kink-Y (Berlin) | kink-y.de | Custom site + Telegram bot for Symbiotikka party | "Registration only via telegram bot" |
| Kinktastisch (Berlin) | kinktastisch.com | Wix site; tickets via JoyClub + Berliner.Party | "Proudly created with Wix"; outbound to joyclub.de, berliner.party |
| Quälgeist Berlin e.V. | quaelgeist.sm | Custom Quälgeist app + on-site calendar | "Register via the calendar or Quälgeist app" |
| Klub Verboten (Berlin/London) | klubverboten.com | **DICE.fm** primary + Resident Advisor | dice.fm/promoters/klub-verboten-672q; ra.co/events/2351310 |
| Torture Garden Berlin | (via RA) | **Resident Advisor** + Eventbrite mailing-list link | ra.co/events/2220038 |
| Pornceptual (Berlin) | (via RA, Shotgun) | **Shotgun** + **Resident Advisor** + Rausgegangen | shotgun.live/en/events/porn-by-pornceptual; RA promoter 52590 |
| HEAT (Insomnia Berlin) | heat.berlin | Likely Eventbrite (sibling parties use it) — needs confirmation | sibling Unleashed.Berlin → eventbrite.com |
| Xplore Berlin | xplore-berlin.de | Email-only (jana.felixruckert@gmx.de) | "Please register with Jana via email" |
| René Desans (rope, BE) | renedesans.net/shibari | Custom contact form (Wix) | Form-only "Book Your Session" |
| Kinky Deviants (Vienna) | kinkydeviants.at | **WordPress + Events Manager** | Footer: "Powered by Events Manager" |
| Libertine Vienna | libertine.at | None — direct contact / walk-in | Listing-only |
| Rope Jam Studio (London) | (via TickeTailor) | **TickeTailor** | tickettailor.com/events/ropejam/2053109 |
| Casual_Rope (London) | (via Eventbrite) | **Eventbrite** | eventbrite.co.uk/o/casual-rope-89393785653 |

### Cluster B — Tantra / conscious-sexuality coaches

| Organizer | Website | Provider | Evidence |
|---|---|---|---|
| Joanna Bauer Savage / Wild Woman Reborn | wildwomanreborn.com | **ThriveCart + Eventbrite-DE (dual)** | joannabauersavage.thrivecart.com (digital); eventbrite.de (Berlin in-person) |
| School of Erotic Mysteries | (TT only) | **TickeTailor** | tickettailor.com/events/schooloferoticmysteries/2072412 |
| Haneen Khan | haneenkhan.com | **TickeTailor** | tickettailor.com/events/haneenkhan |
| Mx Gili | mxgili.com | **Squarespace Commerce + gated signup → invite** | Squarespace CDN; mxgili.com/events/sassy-sacred-2026 → /signup-2026 |
| Akaya World / European Tantra Festival | europeantantrafestival.com | **TickeTailor** | tickettailor.com/events/akayaworldllc/1693416 |
| Ibiza Tantra Festival | (TT) | **TickeTailor** | tickettailor.com/events/ibizatantrafestival/1977802 |
| Sanya Alaya (Art of Tantric Kink, Munich) | (TT) | **TickeTailor** | tickettailor.com/events/sanyaalaya/403496 |
| Amanda Biccum (Embodied Tantra, NL) | (TT) | **TickeTailor** | tickettailor.com/events/amandabiccum/1736826 |
| London School of Tantra (Eliza India & Fox Den) | (TT) | **TickeTailor** | tickettailor.com/events/thefoxden/1008649 |
| Rosa Maxwell (Rewriting Sex, London online) | (Dandelion) | **Dandelion** | dandelion.events/e/eqspa |
| The New Tantra (TNT, Berlin) | thenewtantra.com | **TickeTailor** | tickettailor.com/events/thenewtantra/1608464 |
| Higher Consciousness Academy (Sacred Sensuality / Sufi Tantra) | (TT) | **TickeTailor** | tickettailor.com/events/higherconsciousnessacademy/1421556 |
| Shibari Studio Berlin (Tantric-Shibari) | (TT) | **TickeTailor** | tickettailor.com/events/shibaristudioberlin/1515036 |
| Coach Grethe Fremo (Scotland/Norway) | coachgrethe.com | **TickeTailor** | tickettailor.com/events/coachgretheas/1993452 |
| Embodied Intimacy (NL retreat) | (TT) | **TickeTailor** | tickettailor.com/events/embodiedintimacy/221637 |
| Somaki (somatic sexologist) | (TT) | **TickeTailor** | tickettailor.com/events/somaki/877922 |
| Quintimacy (Manchester, queer-centred) | (TT) | **TickeTailor** | tickettailor.com/events/quintimacy/733438 |
| Sex Club (Berlin/London weekend retreats) | (Dandelion) | **Dandelion** | dandelion.events/e/a2tqs |
| Bibi Gratzer (Sacred Sexuality 6-week) | (Dandelion) | **Dandelion** | dandelion.events/e/o0ruy |
| Jannine MacKinnon (Sex Magick) | janninemackinnon.com | **ThriveCart** | janninemackinnon.thrivecart.com/l/ |
| Feral Grace (Sex & Sovereignty) | feralgrace.net | **ThriveCart** | feralgrace.thrivecart.com/sex--sovereignty/ |
| Moving Energy / This Land Sex Magic (Al Head, UK) | movingenergy.me.uk | None / email-only | myfaerieking@btinternet.com |
| Layla Martin (VITA) | laylamartin.com | Undetermined (suspected Kajabi or custom) | Not visible front-end |

### Cluster C — Sex-positive festivals + retreats + multi-day

| Organizer | Website | Provider | Evidence |
|---|---|---|---|
| Milk N Honey Festival | milknhoneyfestival.art | **TickeTailor** | tickettailor.com/events/milknhoneyfestival |
| Hipsy (via Lavinia / ManToManifestation) | hipsy.nl | **Hipsy** itself | hipsy.nl/event/183301-mantomanifestation-festival-2026 |
| European Tantra Festival 2026 (Kasteel de Berckt, NL) | akayaworld.com | **TickeTailor** | tickettailor.com/events/akayaworldllc/1693416 |
| ManToManifestation Festival (Amsterdam GBTQ+) | mantomanifestation.com | **Hipsy** | All 4 ticket tiers link to hipsy.nl |
| Conscious Play Fest (Berlin) | consciousplayfest.com | Custom Squarespace + integrated cart | /tickets-2026 internal cart |
| The Intimate Revolution (Berlin) | theintimaterevolution.com | Custom (`tickets.` subdomain, application-gated) | tickets.theintimaterevolution.com/apply |
| Xplore Berlin | xplore-berlin.de | Email-only | "Register with Jana via email" |
| Kāma Etna Festival (Sicily) | kamaetnafest.com | Custom WordPress (likely WooCommerce) | `/prodotto/` URL pattern |
| Baltic Tantra Festival (Latvia) | baltictantrafestival.com | Custom on-site cart (likely WooCommerce) | On-site cart "Get Tickets" |
| OURGASM Festival (Bristol UK) | ourgasmfestival.com | **HeadFirst Bristol (HDFST)** | hdfst.uk/e148469 |
| FEAST (Australia) | feastunlimited.com | **Wix native ticketing** | Wixstatic infrastructure |
| Sexsibility Festival / Ängsbacka (Sweden) | angsbacka.com | **Comers** (Swedish retreat-center booking) | iframeang.comers.se booking iframe |
| Wasteland (Amsterdam fetish) | wasteland.nl | **Weeztix + Eventix** (mixed across dates) | weeztix.shop/sw6d4rn3; eventix.shop/r2wjkzdv |
| Wet Playground "S*x-Positive Festival" (Barcelona) | kittyguide.online | **Eventbrite** + Shotgun + RA cross-listing | eventbrite.com/e/sx-positive-festival-i-tickets-1383681702219 |
| ISTA (International School of Temple Arts global trainings) | ista.life | **Zing Events** brand-aggregation | zing.events/brand/ista/ |

### Cluster D — Adjacent embodied/somatic (crossover-flagged subset)

Full table (24 organizers) in scout output; here are the **highest-crossover-signal** rows:

| Organizer | Niche | Provider | Crossover signal |
|---|---|---|---|
| Urban Joy / Joe Jung (Berlin) | ED + cuddle + tantra temple + shibari + men's circle | **Eventbrite + Telegram gatekeeping** | **STRONGEST** — single operator across all sub-niches |
| Cuddle Castle (Joe Jung) | Conscious cuddle | **Eventbrite + Telegram approval gate** | Same operator |
| Männerkraft Berlin (Joe Jung) | Men's circle | **Eventbrite + Telegram** | Same operator |
| Mandy Baum | Conscious cuddling + AR | **Eventbrite** | Same building as tantra temples (Milastr. 4) |
| Journey Within Tantra | Tantric women's circle | **Eventbrite** | At Life Artists Creators Hub |
| Embodied Co-Loving / Elina Zhang (Sensual Hearts Temple) | Temple/embodiment | **TickeTailor** | At Life Artists Creators Hub; "trauma-informed, intoxicants-free" |
| Liebeskunstnetzwerk (Somatic Consent Practitioner Intensive) | Consent-skills | **TickeTailor** | "Somatic embodiment of consent for touch" — exactly scene vocabulary |
| Kuschelevents.de (Christine) | Conscious cuddle | Direct site, early-bird tiers | At Life Artists Creators Hub |
| Christian Rippel / Sri Apollo | ED + Cacao | **Eventbrite** | At Life Artists Creators Hub |
| Berlin Breathwork Days (Yasmine Orth) | Breathwork | Squarespace direct | Trauma-informed; HU Berlin credibility |
| Ecstatic Dance Berlin (FMP1) | ED | Cash-at-door + IG/newsletter | None observed |
| Tanzfabrik Kreuzberg / K77 / Marameo | Contact improv | None (cash door) | None — CI scene structurally avoids ticketing |
| Authentic Berlin (Authentic Games, Ulli & Paweł) | AR | Meetup + cash/PayPal | None direct, but AR is foundational consent vocabulary used by scene |

---

## R1 deep-scout priorities

| Provider | Priority | Action | Login? |
|---|---|---|---|
| **TickeTailor** | **P0** | Full deep-scout — API surface (read + write, capacity sync), verbatim ToS on adult/sexual content, known precedents (bans/recovery from our-scene operators), fee structure, payment flow / merchant-of-record options, organizer dashboard | **Organizer account (user creates)** — deep-scout requires CDP with logged-in session for organizer-side visibility |
| **Hipsy** | P0 | **Reuse 2026-05-19 scout** (`docs/hipsy_analysis.md` + `history/scout-features-hipsy-2026-05-19.md`) + add user-reports/precedents lens on content-policy bans | Already done |
| **ThriveCart** | P1 | Deep-scout — digital-cohort path matters for V1 facilitator-coaching offerings; not event ticketing but parallel surface | Public docs may suffice; account if needed |
| **Eventix** | P1 | Deep-scout — NL/BE rope-scene coverage; Wasteland precedent | Organizer account helpful |
| **Eventbrite** | P2 | ToS-deep + precedent-mining only — focus on content-policy boundary (asterisk-censoring threshold, ban patterns) | No login needed |
| **DICE / RA / Shotgun** | P3 | Defer until V1 scope clarifies whether organizer-hub covers party-format | — |
| **Dandelion** | P3 | Defer — too niche | — |
| **WordPress Events plugins / Squarespace / Wix native** | P3 | Already understood — self-hosted, no leverage path | — |
| **BookRetreats / Retreat.guru** | P3 | Different shape (marketplace) — defer | — |

---

## Open questions feeding R1 / R2

- **TickeTailor:** Does the API support attendee-count read-back for bidirectional capacity sync with Switch's canonical event? What's the verbatim ToS on "adult content" / "sexual content" / "BDSM"? Any known precedents of bans against organizers in our scene? What's the fee structure for organizers compared to Hipsy/Eventbrite?
- **Vetting-decouple design:** Switch facilitator agent owns vetting layer upstream of TickeTailor. What does the cleaning flow look like when the explicit canonical event must project to a TickeTailor "Sensual Hearts Temple" cleaning — does TickeTailor require any specific framing, or are organizers already operating openly?
- **Festival format:** Multi-day festivals lean custom (Conscious Play Fest, Baltic Tantra, Kāma Etna). Does V1 organizer-hub punt on festival format entirely, or do we accept that festivals need a different path (custom-build / WordPress + WooCommerce / Squarespace)?
- **Self-hosted organizers (Karada, SM Kurse, Kinky Deviants):** Switch's leverage for them is NOT third-party routing — it's projecting cleaned tickets to their own self-hosted checkout. Is this a separate organizer-hub flow shape? Feeds `kb-dko` epic scoping.
- **Soul Impact Squarespace vs Shopify discrepancy:** Re-verify if Soul Impact is now confirmed Squarespace or has migrated since the user's earlier observation.

---

## canonical_refs

- `kb-cyq` — this bead
- `kb-6uj` — origin (R1 adversarial review surfacing this research need)
- `kb-2ve` (closed) — Phase A authoring-hub framing
- `kb-dko` — downstream organizer-hub epic
- `docs/decisions/ADR-010-event-based-product-posture.md` — D1(c) FLEXIBLE; ticketing as revenue path
- `docs/decisions/ADR-011-personal-agent-layer-additive.md` — D1 FLEXIBLE; facilitator agent as integration vehicle
- `docs/hipsy_analysis.md` — prior deep-scout (2026-05-19)
- `history/scout-features-hipsy-2026-05-19.md` — Hipsy scout evidence records
- `history/scout-features-switch-berlin-2026-05-18.md` — Lu.ma + Diversia + FetLife prior scouts
