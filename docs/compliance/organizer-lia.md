# Legitimate Interests Assessment — Organizer Event Data

> **Sync note:** If this balancing changes, sync `templates/pages/privacy.html`: the "Organizer event publishing" row of the lawful-basis table, the LLM and Telegram processor entries, and the automated-processing section (§7).

**Legal basis:** Art. 6(1)(f) GDPR — Legitimate interest of the controller  
**Data category:** Organizer identity and public event listings  
**Controller:** Switch Berlin (operator details in Impressum)  
**Date:** 2026-04-22; revised 2026-09-29 for automated collection (sb-7wzb.2: organizer websites, automated collection, the Telegram API terms note, invite-only communities)  
**Review trigger:** Re-assess if 3 or more organizer objections per calendar quarter, or if processing purposes change materially.

---

## 1. Purpose

Switch Berlin lists queer and kink events sourced from announcements that organizers circulate themselves: organizer websites, public Telegram channels, groups and forum topics, Instagram accounts operated by or on behalf of organizers, and invite-only Telegram channels and groups that the operator's own account is a member of. The purpose is to make these announcements more discoverable to the Berlin queer/kink community via a structured, searchable platform.

**Collection is automated.** An operator-run collector reads the organizer websites' public event pages and, through the operator's own Telegram account, recent posts in the listed channels and groups (read only; it never posts, joins or reads member lists). A large language model structures each announcement into event fields. Events of organizers who have not claimed their Switch profile are listed without per-event human review; once an organizer claims their profile, their collected events wait as drafts for the organizer to approve. A human handles only exceptions (failed or uncertain extractions).

No additional personal data is collected about organizers beyond what they have already made public in their source channels. Processed data consists of: organizer name/pseudonym, event title, date, venue, and any promotional text or images included in the public announcement.

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
- **No automated profiling or scoring** of organizers occurs. The language model only extracts event fields (title, dates, venue, price, organizer name) from the announcement text.
- **No widening of a closed audience.** Events collected from invite-only sources are shown only to vouched members (see §2).
- **Minimal retention.** Organizer listings are hidden immediately upon a valid takedown request (see §4 below). Event records for past events are retained for community reference but can be de-listed on request.

### Conclusion

The balancing test is satisfied. The controller's legitimate interest and the community interest in event discovery outweigh the minimal privacy impact on organizers, given that: (a) events are already public, or, when collected from an invite-only community, shown only to vouched members; (b) organizers are acting in a semi-public, promotional capacity; (c) no special-category data is processed; and (d) an accessible, no-login opt-out path is available at all times.

---

## 4. Art. 21 Opt-Out Path

Organizers have the right to object to processing of their data under Art. 21 GDPR.

**How to exercise the right:** Submit a takedown request at `/takedown/` — no login is required. The form accepts the organizer name or Telegram channel URL and a reason.

**Outcome:** The organizer listing is hidden within **72 hours** of a valid request. Event ingestion from that source is halted immediately after the request is processed. Existing past-event records are de-listed from public views. The organizer may request full erasure under Art. 17 by selecting "Erasure request" in the form.

**No adverse consequence.** There is no penalty, fee, or service degradation for submitting a takedown request.

**Review trigger:** If 3 or more distinct organizers object per calendar quarter, the controller will re-assess whether legitimate interest remains the appropriate legal basis or whether a real opt-in mechanism is warranted.

---

## 5. Accepted risk — Telegram API terms

Telegram's API Terms of Service (section 1, https://core.telegram.org/api/terms) prohibit using data obtained from the Telegram platform "to train, fine-tune or otherwise engage in the development, enhancement or deployment of artificial intelligence". The collector passes Telegram post text to a language model that extracts event fields; no model is trained or fine-tuned on it. The clause reads as aimed at training data, but "deployment" is broad. The same exposure already exists through the forward-bot. The operator accepted this risk on 2026-09-28 at current scale (zero visitors); it is to be revisited at the legal gate (ADR-006, ADR-018 D6). This is a platform-terms risk, not a GDPR balancing factor. Not legal advice.

---

*Document maintained by the controller. Must be updated if: (a) new categories of organizer data are collected; (b) data is shared with third parties for new purposes; or (c) the review trigger is hit.*
