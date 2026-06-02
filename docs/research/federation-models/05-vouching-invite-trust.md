# Vouching, Invite-Trees & Web-of-Trust

**Source:** web research, 2026-05-27. Sources at the end. Six systems, with what to steal for a vouched-in bubbles product serving a kink/alt scene.

## 1. Lobste.rs — the public invite tree

Invite-only tech-news site. Killer mechanic: the *entire invite tree is public* — every profile shows who invited them, up the whole chain. No shadow-banning; even the banned-IP list is public.

**Accountability mechanic:** policy says if you invite a bad actor, "the user that invited them may also be banned, going up the chain as needed." A whole sub-tree can in principle be removed.

**The load-bearing insight:** in practice Lobsters has *almost never* banned someone for an invitee's behavior — once or twice ever. **The deterrent isn't the punishment; it's the visibility.** Because everyone sees who vouched whom, careless inviting becomes socially legible — a member can quietly DM "can you coach the person you invited?" instead of mods reaching for blunt instruments.

**Nuance to copy:** Lobsters explicitly walks back "inviter liable forever." Refined framing: the public tree creates a *light* accountability chain — "does not mean every inviter is responsible for every bad comment forever, but it makes careless inviting visible." **Visibility, not perpetual liability** — that calibration is the steal.

## 2. Private trackers — invite-as-scarce-resource economy

Invite-only communities where membership is rationed and standing is continuously measured.

- **Invite-as-scarce-resource:** you *earn* the ability to invite by ranking up through trust classes (new → Power User → VIP) via demonstrated contribution + tenure ("6 months in good standing, no active warnings"). Inviting is a *reward gated behind proven standing*, not a default.
- **Cascading accountability, harder than Lobsters:** "If the invitee gets in trouble for any reason, it reflects back upon the inviter… and if serious enough, both may be banned." Veterans warn newcomers against random personal invites *because* of shared liability.
- **Anti-circumvention:** **one account per lifetime** (can't burn-and-rejoin) + **buying/selling invites = near-certain ban** (keeps the invite from decoupling from trust).
- **"Ratio," translated:** standing is *continuous, not a one-time gate* — you keep access by keeping contributing.

## 3. PGP / Web of Trust — the cautionary tale

Decentralized peer-to-peer trust: you cryptographically sign (vouch for) keys you've verified; trust is **transitive** (trust Alice → Alice trusts Bob → some derived trust in Bob), with *trust levels* (full vs marginal).

**Why it's a failure — and the lesson:** not the crypto, the **usability**:
- **Don't make humans the trust engine.** Manual verify/sign/reason-about-chains/understand-"marginal-trust" was too much cognitive burden. Never escaped enthusiasts.
- The workflow never spoke the user's language; never explained what signing *meant*.
- Open unauthenticated infra invited abuse ("signature flooding," eventually disabled).
- **What won hides the trust decision** — TLS/HTTPS moved trust to the browser/OS vendor; messengers verify keys automatically.

**Takeaway:** transitive trust is powerful but **invisible plumbing should stay invisible.** If a member must consciously reason about a friend-of-a-friend chain, you've lost them. Compute trust paths behind the scenes; surface simple, legible outcomes.

## 4. Discourse trust levels — earned progression

Five automatic tiers by participation; each inherits the privileges below.
- **TL0 New** — heavily restricted (spam containment). "Not that we don't trust you, we just don't know each other yet."
- **TL1 Basic** — a little participation → normal functionality.
- **TL2 Member** — weeks of participation → **unlocks the ability to invite others.** Vouching power is a *mid-tier earned capability*.
- **TL3 Regular** — months, with quality gates (≤~5 confirmed flags, no suspensions in 6 months) → moderation-adjacent powers. **Trust decays if you misbehave.**
- **TL4 Leader** — hand-promoted; "almost moderators."

Key ideas: trust earned automatically through behavior; the right to vouch is itself earned; higher tiers carry losable quality requirements; thresholds configurable per community.

## 5. FetLife — the incumbent (what exists, concretely)

"Facebook for kink" — dominant kink social network. Profiles, groups, and **events/munches**.

**Identity & verification (the weak spot):**
- **Photo verification** — live selfie vs uploaded photo. Weak: "confirms your face but not your age," gameable.
- **Phone verification** — blocks bots/re-registration/underage, but brittle: one phone = one account forever, no resets → mistaken bans permanent, real users locked out.
- **Facial recognition** — newer, controversial; builds an "identity file" for ML. Privacy advocates flag it hard (breach/sale target; Facebook *retreated* from FR for these reasons).

**The genuinely good idea:** verification tied to **attending recognized munches/meetups** — trust rooted in showing up in person, mirroring the offline scene.

**What it does badly:** poor security/privacy track record (XSS CVE-2023-25309, historically weak encryption, centralized sensitive-data trove); leaky pseudonymity; widely-panned support; **no graduated trust model** (flat membership, no invite tree, no earned tiers).

**Lesson:** validates the *demand* + real-world-event-rooted verification, but its centralized-sensitive-data model and weak verification are exactly the failure modes to avoid. **Treat sensitive data as radioactive.**

## 6. Real-world kink-scene vouching norms (the ground truth)

The offline social protocol the product should *encode, not replace*. Standard progression: `attend munches → build trust → find people who'll vouch/sponsor you → access private parties / membership events.`

- **Munch = public, low-stakes entry + vetting.** A "munch" (Meeting Over Lunch) is a vanilla public gathering, no play. Function: "hosts want to see you can behave appropriately in a social setting before inviting you into their homes or dungeons."
- **Vouching = a named person stakes their reputation.** "If you behave inappropriately, both you and your friend can be asked not to return." Cascading accountability is the *cultural default* here, not a novel idea.
- **References** for riskier play — named members who've "seen them play, know their character." Etiquette: **ask permission before listing someone as a reference.**
- **Sponsorship is heavier.** The 15 Association requires **three** sponsors ("becoming a member means the club is vouching for you"), at least one on a governing committee.
- **Host's golden rule:** "feel comfortable vouching for every single person." No last-minute tag-alongs; anyone added must be pre-vouched. Safety over convenience.
- **Online presence as a signal** — groups often ask for your FetLife handle.

**Digital features that honor these norms:** model munch-attendance as the first trust step (check-in at a real event before private-event access); make vouching a named, reputation-staking act with the voucher visible; require consent-to-be-listed-as-reference; support multi-sponsor thresholds (per-bubble configurable); encode the host's veto; build a graduated path (attendee → vouched member → trusted-enough-to-vouch).

## What to steal / what to skip

**Steal:**
| Mechanic | From | Why |
|---|---|---|
| **Public/visible vouch chain** | Lobsters | Visibility (not punishment) disciplines careless vouching. Show who vouched whom *within a bubble*. |
| **"Light" accountability framing** | Lobsters | Voucher accountable for *careless* vouching, not liable forever. Calibrate explicitly or you'll scare off vouchers. |
| **Earn the right to vouch** | Discourse TL2 + trackers | Vouching is a mid-tier earned privilege gated behind a track record. |
| **Graduated trust progression** | Discourse TL0→TL4 | The literal "new → vouched → trusted-enough-to-vouch" model. Auto-progress on behavior; losable on misbehavior. |
| **Cascading accountability, dialed to taste** | Trackers + scene | Already matches scene norms. Implement as reputation impact / vouch-privilege suspension before sub-tree bans. |
| **Multi-sponsor thresholds, per-bubble configurable** | The 15 Association + Discourse | Bubbles set their own bar (1 voucher vs 3 + committee member). |
| **Real-world-event as root of trust** | FetLife munches + scene | Anchor verification in showing up in person — scene-authentic, hardest to fake. |
| **Consent-to-be-a-reference** | Scene norms | Never expose a voucher/reference without explicit opt-in — doubly critical here. |
| **Host/owner veto over any vouch** | Scene norms | Vouching proposes; the bubble owner disposes. Safety overrides automation. |

**Skip:**
| Anti-pattern | From | Why |
|---|---|---|
| **User-facing transitive-trust math** | PGP WoT | Compute paths invisibly; surface simple outcomes. Usability killed PGP, not crypto. |
| **One rigid global trust model** | PGP WoT | Let bubbles configure their own vouching rules. |
| **Hoarding biometric/identity files** | FetLife FR | A centralized sensitive-data trove is a breach magnet + community-harm vector. Minimize and decentralize. |
| **Weak verification dressed as real** | FetLife photo verify | No verification theater — false confidence is worse than none. |
| **Perpetual permanent liability** | over-reading Lobsters | Make vouchers liable forever and no one will vouch. "Visible, not eternal." |
| **Invites decoupled from trust** | Trackers' failure mode | Guard invite-buying/farming — one-account discipline + anti-commodification keeps vouches meaningful. |

**One-line synthesis:** Root trust in real-world presence (munch/event check-in); make vouching a *visible, consent-based, reputation-staking* act members *earn the right* to perform; let each bubble tune its own sponsor thresholds; keep cascading accountability *light and visible* rather than punitive; keep transitive-trust math invisible and sensitive identity data minimal.

## Sources

- [About | Lobsters](https://lobste.rs/about) · [Tree-style invite systems | Lobsters](https://lobste.rs/s/dw0hx5/tree_style_invite_systems_reduce_ai_slop)
- [Private tracker — Pulsed Media Wiki](https://wiki.pulsedmedia.com/wiki/Private_tracker) · [User Classes & Benefits — InviteHawk](https://www.invitehawk.com/topic/147817-private-trackers-user-classes-benefits/)
- [Why did the PGP Web of Trust fail?](https://medium.com/@bblfish/what-are-the-failings-of-pgp-web-of-trust-958e1f62e5b7) · [The Web of Trust is Dead](https://inversegravity.net/2019/web-of-trust-dead/) · [Web of trust — Wikipedia](https://en.wikipedia.org/wiki/Web_of_trust)
- [Understanding Discourse Trust Levels](https://blog.discourse.org/2018/06/understanding-discourse-trust-levels/) · [Trust Level Permissions Reference](https://meta.discourse.org/t/trust-level-permissions-reference/224824)
- [FetLife facial recognition critique](https://vocal.media/theSwamp/get-verified-and-explore-fet-life-s-new-facial-recognition-system) · [CVE-2023-25309 — The Cyber Express](https://thecyberexpress.com/fetlife-vulnerability-exposes-sensitive-data/)
- [The 15 Association — Membership](https://the15association.org/showsection.php?id=400) · [Play Party Etiquette — Ms Morgan Thorne](https://msmorganthorne.com/play-party-etiquette-first-timers/) · [What is a Munch? — Utah TNG](https://utahtng.org/2015/06/02/what-is-a-munch/)
