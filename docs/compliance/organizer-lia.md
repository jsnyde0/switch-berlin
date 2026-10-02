# Legitimate Interests Assessment — Organizer Event Data

> **Sync note:** If this balancing changes, sync `templates/pages/privacy.html`: the "Organizer event publishing" row of the lawful-basis table (both paragraphs: organizer listings and artist credits, §3a), the LLM and Telegram processor entries, and the automated-processing section (§7).

**Legal basis:** Art. 6(1)(f) GDPR — Legitimate interest of the controller  
**Data category:** Organizer identity, public event listings, and the names of artists those listings credit (§3a)  
**Controller:** Switch Berlin (operator details in Impressum)  
**Date:** 2026-04-22; revised 2026-09-29 for automated collection (sb-7wzb.2: organizer websites, automated collection, the Telegram API terms note, invite-only communities); revised 2026-10-02 for event flyers (sb-7wzb.21, §3) and artist credits (sb-7wzb.17, §3a)  
**Review trigger:** Re-assess if 3 or more organizer objections per calendar quarter, or if processing purposes change materially.

---

## 1. Purpose

Switch Berlin lists queer and kink events sourced from announcements that organizers circulate themselves: organizer websites, public Telegram channels, groups and forum topics, Instagram accounts operated by or on behalf of organizers, and invite-only Telegram channels and groups that the operator's own account is a member of. The purpose is to make these announcements more discoverable to the Berlin queer/kink community via a structured, searchable platform.

**Collection is automated.** An operator-run collector reads the organizer websites' public event pages and, through the operator's own Telegram account, recent posts in the listed channels and groups (read only; it never posts, joins or reads member lists). A large language model structures each announcement into event fields. Events of organizers who have not claimed their Switch profile are listed without per-event human review; once an organizer claims their profile, their collected events wait as drafts for the organizer to approve. A human handles only exceptions (failed or uncertain extractions). Every collected post is sent once, with the images attached to it (flyers, posters), to the language model, which returns the events the post announces. A post that announces none is deleted immediately (its text, its images, the message data and the sender's Telegram id), keeping only the message id so the same post is not checked twice. The one exception is an organizer's post about an event it does not announce (a call for helpers, a sold-out notice, a reminder, a recap): its text is kept with the message, its images are dropped, so the collector can tell it from an announcement and never turns it into an event (sb-7wzb.30). Of a post that does announce events, one reduced copy of its flyer is kept as each event's cover image (see Event flyers, §3); the original images are dropped once its events are extracted, and the text stays with them. This keeps ordinary chat by members of invite-only groups — people who are not organizers and whom this assessment does not cover — out of storage; it passes through the model once and is gone.

No additional personal data is collected about organizers beyond what they have already made public in their source channels. Processed data consists of: organizer name/pseudonym, event title, date, venue, the names of artists the announcement bills (see §3a), and any promotional text or images included in the public announcement.

---

## 2. Necessity

There is no less privacy-intrusive way to achieve the stated purpose while maintaining the quality of a curated, searchable event index:

- **Events from public sources are already public.** Organizers have voluntarily published these events on their websites, public Telegram channels and groups, and Instagram, which are accessible without login to any member of the public. For these sources Switch Berlin does not expose any data that was not already in public circulation.
- **Events from invite-only communities keep their audience.** Some organizers promote their events in invite-only Telegram channels and groups that the operator's account is a member of. These announcements are not public, so listing them publicly would widen their reach. Switch Berlin therefore lists them at the `semi_public` tier: visible only to members vouched into the Switch community, never to anonymous visitors or search engines. This mirrors the source's own audience (a closed community whose members the organizer is addressing) instead of exceeding it. The organizer may reclassify the event from the event-edit page after claiming their profile.
- **Automated collection is proportionate.** The collector structures announcements the organizers wrote in order to promote their events; it adds no data about organizers beyond what those announcements contain, and it does not profile or score anyone. Collecting by hand would process the same data with more delay and no less intrusion.
- **Showing organizer identity is proportionate.** A fully anonymised or aggregated listing (e.g., without organizer identity) would prevent users from making informed attendance decisions and would undermine the trust-based, community-serving nature of the platform.
- **Opt-in alternative is disproportionately burdensome.** Requiring explicit consent from every organizer before their already-public events appear in a curated listing would require us to contact each organizer, obtain a documented record of consent, and block listing on non-response — creating friction and data-management overhead not justified by any additional privacy protection, since the events are already publicly available.

---

## 3. Balancing Test

### Interests of the controller and community

The controller has a legitimate interest in operating a community-serving, curated event directory. The broader queer/kink community in Berlin has a legitimate interest in accessing event information in a structured, searchable, privacy-conscious platform.

### Reasonable expectations of organizers

Organizers who publish events on their websites, public Telegram channels and groups, or Instagram accounts do so with the expectation that those announcements will be seen and shared. Appearing in a community directory is consistent with, and a natural extension of, that expectation. Organizers who post in an invite-only community expect their announcement to reach that community's members; a listing restricted to vouched members of the Switch community (see §2) stays within that expectation. Organizers acting in a public capacity (promoting events to the general public or to community members) are treated differently from private individuals under GDPR recital 47.

### Privacy impact

- **No special-category data** (Art. 9 GDPR) is processed about the organizer themselves. The data relates to public events, not the organizer's private life.
- **No unexpected use.** Data is used solely for the purpose for which the organizer published it: promoting awareness of their event.
- **No automated profiling or scoring** of organizers occurs. The language model only extracts event fields (title, dates, venue, price, organizer name) from the announcement text and its attached images.
- **No widening of a closed audience.** Events collected from invite-only sources are shown only to vouched members (see §2).
- **Minimal retention.** Organizer listings are hidden immediately upon a valid takedown request (see §4 below). Event records for past events are retained for community reference but can be de-listed on request.

### Event flyers

We re-host a reduced copy of the flyer the organizer themselves published, credited to the organizer on their Switch profile, removed on request via the takedown route (§4). Same lawful basis as the event listing. The copy is web-size (long edge at most 1600 px, re-encoded); the original file is never stored. A flyer is shown to the same audience as the event it came from: a flyer collected from an invite-only source is shown only to vouched members (see §2). An event without a flyer has no image.

### Conclusion

The balancing test is satisfied. The controller's legitimate interest and the community interest in event discovery outweigh the minimal privacy impact on organizers, given that: (a) events are already public, or, when collected from an invite-only community, shown only to vouched members; (b) organizers are acting in a semi-public, promotional capacity; (c) no special-category data is processed; and (d) an accessible, no-login opt-out path is available at all times.

---

## 3a. Artist credits

Events may credit **artists** (people who teach, perform or play at an event) by name. An artist credit is the name as the organizer's announcement bills it, stored as text on the event. Switch never creates a profile from it; only the event's organizer managers or staff may link it to an existing profile. Names are kept from **all** sources the collector reads, public and invite-only, the same as the event they appear on. The announcement's promotional text and its flyer (§3) often carry the same names.

**Purpose.** Who teaches, performs or plays is core attendance information (§1: informed attendance decisions). An event listing without it is a worse listing.

**Necessity.** A credit repeats the organizer's own billing, as text, with no profile, no artist page and no linking across events unless a manager links a profile. That is the least intrusive form in which the information can be shown. For public sources the name is already in public circulation. For invite-only sources the name is not public, and a separate analysis on sb-7wzb.17 judged that showing it at all fails necessity there. This assessment answers that concern with the event's audience instead of with the name: a credit is never shown beyond the audience of the event that carries it (below).

**Balancing.** Artists differ from organizers in ways that weigh against them:

- They are private persons in a narrow public role. A scene name is still personal data.
- A credit at a kink event can indirectly reveal sex life or sexual orientation (Art. 9; the CJEU reads indirect revelation broadly, C-184/20). Art. 9(2)(e), data "manifestly made public", is weak here, because the organizer published the billing, not the artist (C-252/21 asks for the data subject's own deliberate choice).
- An artist billed for an event expects the billing to circulate with that event, to the audience the organizer addressed.

The safeguard is the event's **visibility tier** (ADR-012 D2), which a credit inherits without exception:

- A credit on a `public` event is shown wherever the event is: it repeats a billing that is already public.
- A credit on a non-public event (`semi_public`, `unlisted`) is shown only to that event's audience. Like everything else on the event, it never reaches search engines, sitemaps, structured data, link previews, feeds or anonymous visitors. Events collected from invite-only sources default to `semi_public` (§2), so their artist names stay inside a vouched audience that mirrors the source's own.

There is no separate name-specific limit (no exclusion of names from search or metadata on public events, and no time-based deletion of credits). The operator chose this on 2026-10-02 (ruling recorded on sb-7wzb.17): the protection is that the tier gates hold. They are therefore load-bearing for this assessment. Their audit across every exposure surface, with a test per surface, is sb-7wzb.26; until it closes, this balancing rests on gates that have not been audited end to end.

**Objection.** A credited artist can object under Art. 21 without a login. On `/takedown/` they tick "I am credited on this event" and give the event page, the name they are credited under and a contact email. The form only files a request: anyone can submit it, so it never deletes anything by itself. Staff run the admin action "remove credit and suppress" within **72 hours**: it deletes the matching credit and records the name, normalized, against every source channel that collected that event, in one transaction. The collector then skips that name from those sources, and on any event one of those sources announced, whichever source names it, so the credit is not re-created. Another source may still credit the name on an event none of those sources announced, and a new objection covers it. There is no adverse consequence for objecting.

**Conclusion.** With the tier gates holding and the objection route open, the balancing in §3 holds for artist credits: the names are shown only where the event itself may be seen, to an audience the organizer addressed, as the billing the organizer published. If the gates leak, this conclusion does not hold for credits from invite-only sources, and the leak is a data-protection incident, not a display bug.

---

## 4. Art. 21 Opt-Out Path

Organizers have the right to object to processing of their data under Art. 21 GDPR.

**How to exercise the right:** Submit a takedown request at `/takedown/` — no login is required. The form accepts the organizer name or Telegram channel URL and a reason.

**Outcome:** The organizer listing is hidden within **72 hours** of a valid request. Event ingestion from that source is halted immediately after the request is processed. Existing past-event records are de-listed from public views. The organizer may request full erasure under Art. 17 by selecting "Erasure request" in the form.

**Credited artists.** Artists credited on an event (§3a) exercise the same right through the same form (the "I am credited on this event" option). Outcome: the credit is removed within **72 hours** of a valid request and the name is suppressed for the sources that collected the event, so it is not re-created from them. The artist's event listing is unaffected: the organizer's event stays.

**No adverse consequence.** There is no penalty, fee, or service degradation for submitting a takedown request.

**Review trigger:** If 3 or more distinct organizers object per calendar quarter, the controller will re-assess whether legitimate interest remains the appropriate legal basis or whether a real opt-in mechanism is warranted.

---

## 5. Accepted risk — Telegram API terms

Telegram's API Terms of Service (section 1, https://core.telegram.org/api/terms) prohibit using data obtained from the Telegram platform "to train, fine-tune or otherwise engage in the development, enhancement or deployment of artificial intelligence". The collector passes Telegram post text to a language model that extracts event fields; no model is trained or fine-tuned on it. The clause reads as aimed at training data, but "deployment" is broad. The same exposure already exists through the forward-bot. The operator accepted this risk on 2026-09-28 at current scale (zero visitors); it is to be revisited at the legal gate (ADR-006, ADR-018 D6). This is a platform-terms risk, not a GDPR balancing factor. Not legal advice.

---

*Document maintained by the controller. Must be updated if: (a) new categories of organizer or artist data are collected, or a credit gains a surface beyond its event (artist pages, artist search, cross-event linking); (b) data is shared with third parties for new purposes; or (c) the review trigger is hit.*
