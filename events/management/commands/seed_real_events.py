"""Seed real Berlin kink/queer events as draft Events (bead kb-lqw).

Creates 3 approved Organizers (IKSK Berlin, Kachenka, Karada House) and 32
draft Events with titles, descriptions, start datetimes, and suggested_tags
scraped from public organizer websites on 2026-04-23 and refreshed
2026-05-07 (9 additional IKSK specials covering May–Sep 2026).

Consent: ``legitimate_interest`` per docs/compliance/organizer-lia.md.

Usage::

    docker compose run --rm app python manage.py seed_real_events
    docker compose run --rm app python manage.py seed_real_events --wipe

Idempotent: uses get_or_create keyed on ``(organizer, slug)``. ``--wipe`` only
removes rows matching the seeded organizer+slug set, leaving other data intact.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from events.models import Event
from organizers.models import Organizer

BERLIN_TZ = zoneinfo.ZoneInfo("Europe/Berlin")


def dt(year: int, month: int, day: int, hour: int = 19, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=BERLIN_TZ)


# ---------------------------------------------------------------------------
# Organizers
# ---------------------------------------------------------------------------

ORGANIZERS = [
    {
        "slug": "iksk-berlin",
        "name": "IKSK Berlin",
        "website": "https://www.iksk-berlin.de",
        "description": (
            "IKSK — Institut für Körperforschung und sexuelle Kultur. "
            "Berlin institute hosting workshops, play parties and discussions "
            "on conscious kink, BDSM, tantra and sex-positive culture at "
            "Holzmarkt 25."
        ),
    },
    {
        "slug": "kachenka",
        "name": "Kachenka",
        "website": "https://www.kachenka.org",
        "description": (
            "Kachenka hosts embodied, ecstatic, sex-positive gatherings in "
            "Berlin — orgasmic dance temples, tantric ritual nights and "
            "community play spaces."
        ),
    },
    {
        "slug": "karada-house",
        "name": "Karada House",
        "website": "https://karada-house.de",
        "description": (
            "Karada House is a Berlin space for rope, kink, embodiment and "
            "community education — workshops, series, and SM weekends led by "
            "queer- and trauma-informed facilitators."
        ),
    },
]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------
# Keyed on external_url; scraped from public organizer sites on 2026-04-23.
# Dates are timezone-aware Europe/Berlin. Where the source page lists no
# concrete date (recurring drop-ins, monthly series), a plausible near-future
# date is picked and flagged in notes.

EVENTS: list[dict] = [
    # --- IKSK Berlin ---------------------------------------------------------
    {
        "organizer_slug": "iksk-berlin",
        "slug": "tantra-trifft-bdsm-mai-2026",
        "external_url": "https://www.iksk-berlin.de/amira",
        "title": "TANTRA trifft BDSM — Wo Schatten, da auch Licht",
        "start": dt(2026, 5, 23, 19, 0),
        "end": dt(2026, 5, 25, 16, 0),
        "description": (
            "Workshop in deutscher Sprache mit Ariane (schamanische "
            "Tantra-Domina) und Christina (Heilpraktikerin & "
            "Sexualtherapeutin). Ein sinnlich-spielerischer Wochenend-"
            "Workshop der Himmelsschwestern: Tantra-Achtsamkeit trifft "
            "Conscious Kink. 23.–25. Mai 2026, IKSK Holzmarkt 25. "
            "Frühbucher 350€ / regulär 390€."
        ),
        "suggested_tags": ["tantra", "bdsm", "workshop", "weekend", "german"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "desire-andy-buru-mai-2026",
        "external_url": "https://www.iksk-berlin.de/desire-andy",
        "title": "Desire — with Andy Buru",
        "start": dt(2026, 5, 1, 19, 0),
        "end": dt(2026, 5, 3, 18, 0),
        "description": (
            "Three-day workshop in English with Andy Buru exploring desire "
            "beyond duality: no dom/sub pairings, instead trios, quads, solo "
            "and group rituals. Borrowing from theatre — mask work, "
            "character, ritualized scenes. Fri 19-22 / Sat 10-13, 15-18, "
            "19-21 / Sun 10-13, 15-18. Sliding scale 160–240€."
        ),
        "suggested_tags": ["bdsm", "workshop", "weekend", "ritual", "english"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "ika-eska-kink-bodywork",
        "external_url": (
            "https://www.iksk-berlin.de/playparty/ika-eska-felicitas-bodywork"
        ),
        "title": "IKA ESKA Play Party — Kink & Bodywork (hosted by Ale Felicitas)",
        # Recurring; no concrete date on page — plausible near-future placeholder.
        "start": dt(2026, 5, 16, 12, 0),
        "end": dt(2026, 5, 17, 0, 0),
        "description": (
            "Workshop + play party at IKSK's floating pyramid above "
            "Holzmarkt. Workshop explores kink through bodywork — face/head "
            "massage, hair pulling, soft breath play, D/s dynamics. Play "
            "party: strict dress code, switches/role players/queer people "
            "and feminists especially welcome. Workshop 12:00–18:00 (45–85€), "
            "Play Party 19:00–24:00 (sliding 20–40€)."
        ),
        "suggested_tags": [
            "bdsm",
            "bodywork",
            "play-party",
            "workshop",
            "queer",
        ],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "sexual-empowerement-micha-stella",
        "external_url": "https://www.iksk-berlin.de/sexual-empowerement",
        "title": "Sexual Empowerement — with Micha Stella",
        # Recurring evening drop-in; no concrete date on page — placeholder.
        "start": dt(2026, 5, 9, 20, 0),
        "end": dt(2026, 5, 9, 23, 30),
        "description": (
            "Evening workshop with Micha Stella. Creative tools, playful "
            "techniques, witch craft, radical empathy, critical thinking "
            "and non-binary perspectives for collective sexual empowerment "
            "and freedom. Open to every gender, orientation, origin, "
            "experience and age (18+). Sliding scale 35–75€."
        ),
        "suggested_tags": ["empowerment", "workshop", "queer", "consent"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "shibari-life-drawing",
        "external_url": "https://www.iksk-berlin.de/shibari-life-drawing",
        "title": "Shibari Life Drawing — hosted by Asimira",
        # Last Sunday of the month recurring — use last Sun of May 2026.
        "start": dt(2026, 5, 31, 19, 0),
        "end": dt(2026, 5, 31, 22, 0),
        "description": (
            "An evening of artistic exploration and slow shibari "
            "performances. Life drawing paired with shibari; poses held "
            "1–15 minutes. All skill levels welcome — bring your own drawing "
            "supplies. Sundays, once a month. Sliding scale 15/20/25€."
        ),
        "suggested_tags": ["shibari", "rope", "art", "life-drawing", "monthly"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "silent-hunger-the-feeding-mai-2026",
        "external_url": "https://www.iksk-berlin.de/silent-hunger-lavinia",
        "title": "Silent Hunger: The Feeding — with Lavinia",
        "start": dt(2026, 5, 15, 18, 0),
        "end": dt(2026, 5, 17, 18, 0),
        "description": (
            "Weekend experimental workshop (in English) with Lavinia, "
            "exploring the act of feeding and being fed as a site of "
            "control, shame, satisfaction and fulfillment. Fri Appetite, "
            "Sat Hunger + The Feast (play space 20–24), Sun Siesta. Sober, "
            "trauma-aware, consent-based. Sliding scale 150/200/250€."
        ),
        "suggested_tags": ["bdsm", "workshop", "weekend", "power-exchange"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "speed-fucking-beate-mai-2026",
        "external_url": "https://www.iksk-berlin.de/speed-fucking-beata",
        "title": "Speed Fucking — with Beate",
        "start": dt(2026, 5, 20, 20, 0),
        "end": dt(2026, 5, 20, 23, 30),
        "description": (
            "Wednesday evening drop-in with Beate (Deutsch & English). "
            "Sliding scale 20–80€. 20:00 to max 23:30 at IKSK Holzmarkt 25."
        ),
        "suggested_tags": ["sex-positive", "play-party", "drop-in"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "the-art-of-kinky-kissing-mai-2026",
        "external_url": "https://www.iksk-berlin.de/the-art-of-kinky-kissing",
        "title": "The Art of Kinky Kissing — with Joris Kern",
        # Every 2nd month — plausible near-future.
        "start": dt(2026, 5, 28, 19, 0),
        "end": dt(2026, 5, 28, 22, 30),
        "description": (
            "Part II of Joris Kern's kissing series — kissing in BDSM: "
            "threat vs. comfort, anchor vs. denial, biting and breath play. "
            "Requires prior attendance of 'The Art of Kissing I'. Drop-in, "
            "no registration. Every second month. Sliding scale 25/30/35€."
        ),
        "suggested_tags": ["bdsm", "kissing", "workshop", "drop-in"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "the-art-of-kissing-mai-2026",
        "external_url": "https://www.iksk-berlin.de/the-art-of-kissing",
        "title": "The Art of Kissing — with Joris Kern",
        # Last Thursday of each month — last Thursday of May 2026 is May 28.
        "start": dt(2026, 5, 28, 19, 0),
        "end": dt(2026, 5, 28, 22, 0),
        "description": (
            "Monthly drop-in workshop with Joris Kern. Explore kissing as "
            "communication: desire, shyness, surrender. Open to all genders "
            "and experience levels. Last Thursday of the month. Sliding "
            "scale 25/30/35€. No registration, just drop in."
        ),
        "suggested_tags": ["kissing", "workshop", "drop-in", "monthly"],
    },
    # --- IKSK Berlin: 2026-05-07 refresh batch -------------------------------
    {
        "organizer_slug": "iksk-berlin",
        "slug": "venus-unbound-mary-magdalene-mai-2026",
        "external_url": (
            "https://www.iksk-berlin.de/venus-unbound-2-anna-valeska-pohl"
        ),
        "title": "Venus Unbound — Ritual II: Mary Magdalene & The Lover",
        "start": dt(2026, 5, 23, 11, 0),
        "end": dt(2026, 5, 23, 16, 0),
        "description": (
            "A lab for archetypes, desire and radical self-authorship with "
            "Anna Valeska Pohl (English). Working with Mary Magdalene and "
            "The Lover archetypes through writing, embodiment and ritual — "
            "questions of devotion, desire, shame, voice and the politics "
            "of love. Drawing on Audre Lorde and bell hooks. Sliding scale "
            "30/50/70€."
        ),
        "suggested_tags": ["ritual", "workshop", "feminism", "english"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "visceral-touch-dandelion-mai-2026",
        "external_url": "https://www.iksk-berlin.de/visceral-touch",
        "title": "Visceral Touch — with Alexandre Dandelion",
        "start": dt(2026, 5, 17, 18, 30),
        "end": dt(2026, 5, 17, 22, 30),
        "description": (
            "Drop-in workshop in English & français with Alexandre "
            "Dandelion (physiotherapist + Taoist/tantric massage). "
            "Exploration of sensing, attunement and depth through touch, "
            "breath, movement and sound — inspired by Mantak Chia's Chi "
            "Nei Tsang abdominal massage and tantric bodywork. Solo or "
            "partnered. Sliding scale 15/30/50€."
        ),
        "suggested_tags": ["bodywork", "tantra", "drop-in", "workshop"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "getting-good-at-being-bad-felix-mai-2026",
        "external_url": "https://www.iksk-berlin.de/getting-good-at-being-bad",
        "title": "Getting Good at Being Bad — The Art of Impact Play (Felix Ruckert)",
        "start": dt(2026, 5, 30, 15, 0),
        "end": dt(2026, 5, 30, 22, 0),
        "description": (
            "Bilingual (DE/EN) impact-play workshop + ritual + open play "
            "with Felix Ruckert. Floggers, whips, canes — empowerment, "
            "anger as valve, trance, presence. Practical learning of "
            "physical communication and consent. Final ritual + open play "
            "21:00. Drop-in or registration. Normal 60€ / Social & "
            "Members 30€."
        ),
        "suggested_tags": ["bdsm", "impact", "workshop", "play-party"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "juliette-dragon-intensive-jun-2026",
        "external_url": "https://www.iksk-berlin.de/juliette-dragon-intensive",
        "title": "Juliette Dragon Intensive — Neo Burlesque & Cabaret on High Heels",
        "start": dt(2026, 6, 4, 12, 0),
        "end": dt(2026, 6, 7, 23, 30),
        "description": (
            "Four-day intensive (English with French accent) with Juliette "
            "Dragon — Le Cabaret des Filles de Joie. Neo burlesque, "
            "striptease and cabaret on high heels: studying retro pin-up "
            "and femme fatale archetypes, reclaiming codes of seduction "
            "with humour and feminist critique. Sun Jun 7: rehearsal + "
            "evening performance & play party (also open to non-WS, 20€). "
            "All four days: 160/200/240€. Single day: 50/60/70€. "
            "Registration: jana.felixruckert@gmx.de."
        ),
        "suggested_tags": [
            "burlesque",
            "performance",
            "workshop",
            "intensive",
            "play-party",
        ],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "turning-men-into-furniture-jun-2026",
        "external_url": (
            "https://www.iksk-berlin.de/men-as-furniture-beataf9d4ba79"
        ),
        "title": "Turning Men Into Furniture — with Beata & Becky",
        "start": dt(2026, 6, 17, 20, 0),
        "end": dt(2026, 6, 17, 23, 30),
        "description": (
            "English-language objectification workshop + house party with "
            "Beata & Becky (luhmen d'arc). Men+ become chairs, lamps, "
            "rugs, sofas; flintas use the furniture under negotiated care "
            "tags. Trained in somatics, performative arts, BDSM and queer "
            "theory. Drop-in. Sliding scale 30–80€."
        ),
        "suggested_tags": ["bdsm", "objectification", "play-party", "queer"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "silly-play-joris-jun-2026",
        "external_url": "https://www.iksk-berlin.de/silly-play",
        "title": "Playful Sexy Mischief — with Joris Kern",
        "start": dt(2026, 6, 27, 11, 0),
        "end": dt(2026, 6, 28, 17, 0),
        "description": (
            "Two-day workshop with Joris Kern (consent author, "
            "konsenskultur.net) reclaiming playfulness, absurdity and "
            "silliness in sex and BDSM. Games with varying degrees of "
            "nudity, sensuality and roleplay. Single cis men only welcome "
            "if willing to do exercises with other men. Sliding scale "
            "130–150€. Registration: jana.felixruckert@gmx.de."
        ),
        "suggested_tags": ["consent", "workshop", "play", "weekend"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "self-deconstruction-fakeera-jul-2026",
        "external_url": "https://www.iksk-berlin.de/self-deconstruction-fakeera",
        "title": "Self Deconstruction — with Fakeera",
        "start": dt(2026, 7, 3, 18, 0),
        "end": dt(2026, 7, 5, 18, 0),
        "description": (
            "Three-day workshop in English with Fakeera (intuitive guide, "
            "20+ years working with the emotional body). Inner inquiry "
            "through parts work, shamanic psychodrama and movement "
            "metaphors — meeting the inner critic, child, envious self, "
            "loving self with awareness. Tiers: Social 150€ / Basic 200€ "
            "/ Supporter 250€. Registration: jana.felixruckert@gmx.de."
        ),
        "suggested_tags": ["workshop", "weekend", "embodiment", "english"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "tease-and-torment-ena-roxu-sep-2026",
        "external_url": "https://www.iksk-berlin.de/ena-roxu",
        "title": "Tease & Torment — Erotic Tension in Ropes (Roxu & Ena Dahl)",
        "start": dt(2026, 9, 13, 11, 0),
        "end": dt(2026, 9, 14, 18, 0),
        "description": (
            "Weekend rope intensive (English) with Roxu and Ena Dahl. "
            "Saturday 'Charm Me. Furiously.': seductive floorwork, tease "
            "and denial, building anticipation. Sunday 'Torment Me. In "
            "Detail.': spicy partials and predicaments where pleasure and "
            "torment intertwine. Intermediate level — riggers need single/"
            "double column ties + safe uplines (Sat) and solid TK + semi-"
            "suspension knowledge (Sun). 150€/pair (one day) — 300€/pair "
            "(two days). Members 25% off. Registration: "
            "jana.felixruckert@gmx.de."
        ),
        "suggested_tags": ["shibari", "rope", "workshop", "weekend", "intermediate"],
    },
    {
        "organizer_slug": "iksk-berlin",
        "slug": "pain-processing-jay-sep-2026",
        "external_url": "https://www.iksk-berlin.de/pain-processing",
        "title": "Pain Processing Exploration — with Jay",
        "start": dt(2026, 9, 25, 18, 0),
        "end": dt(2026, 9, 27, 20, 0),
        "description": (
            "Three-day workshop in English with Jay (conscious kink + "
            "embodiment facilitator, molecular biology background, "
            "ritualsofsurrender.com). Neuroscience of pain meets ecstatic "
            "trance through deep surrender — pain as information, energy "
            "to move and transform. Topics include neurobiology, safety "
            "and red flags, pain in D/S, breathing techniques, energy "
            "discharges and full-body orgasms. Open to BDSM-experienced "
            "and newcomers; designed for switching. Tiers: Social & "
            "Members 150€ / Normal 200€ / Support 250€. Registration: "
            "jana.felixruckert@gmx.de."
        ),
        "suggested_tags": ["bdsm", "pain-play", "workshop", "weekend", "english"],
    },
    # --- Kachenka ------------------------------------------------------------
    {
        "organizer_slug": "kachenka",
        "slug": "orgasmic-dance-temple-night-mai-2026",
        "external_url": (
            "https://www.kachenka.org/events/"
            "orgasmicdancetemplenight-pnsnz-r5ee3-y5p67-carp4-geez5-4tzzb-"
            "9hfdt-dwyfx-ke3cp-jj47f-fnenl-ja5kw-bpmtk-mejyh-jp9zp-csexj-5zwm7"
        ),
        "title": "Orgasmic Dance Temple Night",
        "start": dt(2026, 5, 29, 18, 0),
        "end": dt(2026, 5, 31, 23, 45),
        "description": (
            "Ecstatic, embodied, sex-positive temple night by Kachenka. "
            "Dance, breath, ritual. Berlin."
        ),
        "suggested_tags": ["ecstatic-dance", "temple", "ritual", "sex-positive"],
    },
    # --- Karada House --------------------------------------------------------
    {
        "organizer_slug": "karada-house",
        "slug": "delving-into-dominance-archetypes",
        "external_url": (
            "https://karada-house.de/events/delving-into-dominance-archetypes/"
        ),
        "title": "Delving Into Dominance — Archetypes & Inspiration (Part 4)",
        "start": dt(2026, 5, 5, 19, 0),
        "end": dt(2026, 5, 5, 22, 0),
        "description": (
            "Part 4 of Caritia's 4-part online series. Shaping characters "
            "and expressions of your dominant self — archetypes, inspiration "
            "and nuance for your leadership style."
        ),
        "suggested_tags": ["bdsm", "dominance", "online", "series"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "delving-into-dominance-series-2",
        "external_url": (
            "https://karada-house.de/events/delving-into-dominance-series-2/"
        ),
        "title": "Delving Into Dominance — 4-Part Series (2026)",
        "start": dt(2026, 4, 14, 19, 0),
        "end": dt(2026, 5, 5, 22, 0),
        "description": (
            "Full 4-part online series with Caritia: Map of Me (Apr 14), "
            "Boundaries & Negotiation (Apr 21), Styles of Leadership "
            "(Apr 28), Archetypes & Inspiration (May 5). Intersectional, "
            "trauma-aware lens on dominance and leadership."
        ),
        "suggested_tags": ["bdsm", "dominance", "online", "series"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "delving-into-dominance-styles",
        "external_url": (
            "https://karada-house.de/events/delving-into-dominance-styles/"
        ),
        "title": "Delving Into Dominance — Styles of Leadership (Part 3)",
        "start": dt(2026, 4, 28, 19, 0),
        "end": dt(2026, 4, 28, 22, 0),
        "description": (
            "Part 3 of the series. Discover and explore how you want to "
            "dominate and/or lead in play or erotic contexts. Identify "
            "personal areas of interest and leadership styles."
        ),
        "suggested_tags": ["bdsm", "dominance", "online", "series"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "first-aid-for-kink-rope",
        "external_url": "https://karada-house.de/events/first-aid-for-kink-rope/",
        "title": "First Aid for Kink & Rope",
        "start": dt(2026, 4, 26, 19, 0),
        "end": dt(2026, 4, 26, 22, 0),
        "description": (
            "Practical first aid training tailored for kink and rope "
            "practitioners at Karada House."
        ),
        "suggested_tags": ["rope", "bdsm", "safety", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "how-to-plan-an-orgy",
        "external_url": "https://karada-house.de/events/how-to-plan-an-orgy/",
        "title": "How to Plan an Orgy",
        "start": dt(2026, 4, 24, 19, 0),
        "end": dt(2026, 4, 24, 22, 0),
        "description": (
            "Practical workshop on designing and hosting consensual group "
            "sex gatherings — invites, venue, consent frameworks, "
            "aftercare."
        ),
        "suggested_tags": ["play-party", "sex-positive", "workshop", "consent"],
    },
    # --- Karada SM Weekend (May 1-3, 2026) ----------------------------------
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-caning-and-flogging",
        "external_url": (
            "https://karada-house.de/events/sm-weekend-caning-and-flogging/"
        ),
        "title": "SM Weekend: Caning and Flogging",
        "start": dt(2026, 5, 3, 12, 0),
        "end": dt(2026, 5, 3, 14, 0),
        "description": (
            "Part of Karada House's SM Weekend. Hands-on workshop on caning "
            "and flogging — technique, safety, intensity."
        ),
        "suggested_tags": ["bdsm", "impact", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-face-slapping-biting-scratching",
        "external_url": (
            "https://karada-house.de/events/"
            "sm-weekend-face-slapping-biting-scratching/"
        ),
        "title": "SM Weekend: Face Slapping, Biting & Scratching",
        "start": dt(2026, 5, 2, 15, 30),
        "end": dt(2026, 5, 2, 17, 30),
        "description": (
            "SM Weekend session on primal-adjacent sensation play: face "
            "slapping, biting, scratching. Consent, calibration and "
            "intensity."
        ),
        "suggested_tags": ["bdsm", "primal", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-genital-nipple-torment",
        "external_url": (
            "https://karada-house.de/events/sm-weekend-genital-nipple-torment/"
        ),
        "title": "SM Weekend: Genital & Nipple Torment",
        "start": dt(2026, 5, 2, 12, 0),
        "end": dt(2026, 5, 2, 14, 0),
        "description": (
            "SM Weekend session on CBT/nipple torment — anatomy, safety, "
            "tools and play."
        ),
        "suggested_tags": ["bdsm", "sm-weekend", "sensation", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-pain-processing-theory",
        "external_url": (
            "https://karada-house.de/events/sm-weekend-pain-processing-theory/"
        ),
        "title": "SM Weekend: Pain Processing & Theory",
        "start": dt(2026, 5, 1, 11, 0),
        "end": dt(2026, 5, 1, 13, 0),
        "description": (
            "SM Weekend theory session on how pain is processed, framed, "
            "and transformed in consensual sadomasochistic play."
        ),
        "suggested_tags": ["bdsm", "theory", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-painful-rope",
        "external_url": "https://karada-house.de/events/sm-weekend-painful-rope/",
        "title": "SM Weekend: Painful Rope",
        "start": dt(2026, 5, 3, 18, 0),
        "end": dt(2026, 5, 3, 20, 0),
        "description": (
            "SM Weekend session bridging rope bondage and sadomasochistic "
            "intensity — predicament ties, pain as texture."
        ),
        "suggested_tags": ["rope", "shibari", "bdsm", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-spanking",
        "external_url": "https://karada-house.de/events/sm-weekend-spanking/",
        "title": "SM Weekend: Spanking",
        "start": dt(2026, 5, 1, 14, 0),
        "end": dt(2026, 5, 1, 16, 0),
        "description": (
            "SM Weekend hands-on spanking workshop — OTK, warm-up, hand "
            "and implement technique."
        ),
        "suggested_tags": ["bdsm", "impact", "spanking", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-thuddy-impact-kicking-punching",
        "external_url": (
            "https://karada-house.de/events/"
            "sm-weekend-thuddy-impact-kicking-punching/"
        ),
        "title": "SM Weekend: Thuddy Impact — Kicking & Punching",
        "start": dt(2026, 5, 2, 18, 0),
        "end": dt(2026, 5, 2, 20, 0),
        "description": (
            "SM Weekend session on thuddy impact — safe kicking and "
            "punching, target areas, intensity calibration."
        ),
        "suggested_tags": ["bdsm", "impact", "primal", "sm-weekend", "workshop"],
    },
    {
        "organizer_slug": "karada-house",
        "slug": "sm-weekend-wax-play",
        "external_url": "https://karada-house.de/events/sm-weekend-wax-play/",
        "title": "SM Weekend: Wax Play",
        "start": dt(2026, 5, 3, 15, 30),
        "end": dt(2026, 5, 3, 17, 30),
        "description": (
            "SM Weekend wax play workshop — candle types, temperature, "
            "aftercare, cleanup."
        ),
        "suggested_tags": ["bdsm", "sensation", "wax", "sm-weekend", "workshop"],
    },
]


class Command(BaseCommand):
    help = "Seed real Berlin kink/queer Events as drafts (bead kb-lqw)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wipe",
            action="store_true",
            default=False,
            help=(
                "Delete previously seeded events and organizers matching the "
                "seed set before re-seeding."
            ),
        )

    def handle(self, *args, **options):
        wipe = options["wipe"]
        verbosity = options["verbosity"]

        org_slugs = {o["slug"] for o in ORGANIZERS}
        event_keys = {(e["organizer_slug"], e["slug"]) for e in EVENTS}

        if wipe:
            if verbosity >= 1:
                self.stdout.write("Wiping previously seeded events + organizers…")
            for org_slug, ev_slug in event_keys:
                Event.objects.filter(
                    organizer__slug=org_slug, slug=ev_slug
                ).delete()
            Organizer.objects.filter(slug__in=org_slugs).delete()

        now = timezone.now()
        consent_notes = (
            "Public website — LIA per docs/compliance/organizer-lia.md, "
            "scraped 2026-04-23"
        )

        orgs_created = 0
        orgs_by_slug: dict[str, Organizer] = {}
        for od in ORGANIZERS:
            org, created = Organizer.objects.get_or_create(
                slug=od["slug"],
                defaults={
                    "name": od["name"],
                    "website": od["website"],
                    "description": od["description"],
                    "status": "approved",
                    "approved_at": now,
                    "consent_method": "legitimate_interest",
                    "consent_recorded_at": now,
                    "consent_notes": consent_notes,
                },
            )
            orgs_by_slug[od["slug"]] = org
            if created:
                orgs_created += 1

        events_created = 0
        for ev in EVENTS:
            org = orgs_by_slug[ev["organizer_slug"]]
            obj, created = Event.objects.get_or_create(
                organizer=org,
                slug=ev["slug"],
                defaults={
                    "title": ev["title"],
                    "description": ev["description"],
                    "start": ev["start"],
                    "end": ev.get("end"),
                    "external_url": ev["external_url"],
                    "suggested_tags": ev["suggested_tags"],
                    "status": "draft",
                    "venue": None,
                },
            )
            if created:
                events_created += 1
                if verbosity >= 2:
                    self.stdout.write(
                        f"  + {org.slug}/{obj.slug}  ({obj.start.isoformat()})"
                    )

        if verbosity >= 1:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Seeded {orgs_created} new organizers "
                    f"({len(ORGANIZERS)} total in seed set) and "
                    f"{events_created} new events "
                    f"({len(EVENTS)} total in seed set)."
                )
            )
