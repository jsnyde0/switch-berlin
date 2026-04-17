# Hipsy.nl Research Findings & Feature Inventory

**Purpose:** This document captures a deep-dive analysis of [hipsy.nl](https://hipsy.nl) to inform the design and requirements of Event Gulper. It inventories features, data models, and UX patterns observed during research.

## 1. Core Platform Structure
Hipsy operates as a two-sided marketplace for "conscious" events (ecstatic dance, yoga, retreats).
*   **Domains:** Operates on multiple regional domains (`.nl`, `.be`) sharing a similar structure/backend.
*   **User Types:**
    *   **Attendees:** Browse, follow, save, book.
    *   **Organizers:** Create profiles, manage events, build community.

## 2. Feature Inventory

### 2.1 Organizer Profiles
Hipsy appears to support tiers of organizer profiles, ranging from basic to enhanced.

**Common Features:**
*   **Identity:** Name, Profile Picture/Logo.
*   **Stats:** Follower count, "Review Score" (e.g., "158 reviews").
*   **Actions:** "Volgen" (Follow), "Stuur bericht" (Send Message).
*   **Event Lists:** Tabs for "Aankomend" (Upcoming) and "Afgelopen" (Past) events.
*   **Reviews:** Aggregated reviews linked to the profile.

**Enhanced Profile Features (Observed on `/eris-grace`, `/djheidi`):**
*   **Cover Banner:** Large, high-quality header image.
*   **Rich Bio:** Extended "About" section with formatted text, links, and potentially embedded media.
*   **Integrated Reviews:** Reviews displayed prominently on the profile page itself (or via anchor link `#reviews`).
*   **Custom URL:** Clean slug-based URLs (e.g., `hipsy.nl/eris-grace`).

### 2.2 Event Discovery (The Feed)
*   **List View:**
    *   Vertical feed of event cards.
    *   **Card Content:** Date badge, Title, Organizer Name, Location (City), Price/Price Range, Thumbnail Image.
*   **Filtering:**
    *   Date range.
    *   Location/Distance.
    *   Categories/Tags (implied).

### 2.3 Event Detail Page
**Header & Key Info:**
*   **Visuals:** Large cover image.
*   **Meta:** Title, Date, Time, Location (Address + "View on map").
*   **Organizer Card:** Small sidebar/header section linking to the organizer.

**Interaction & Engagement:**
*   **Contact:** "Neem contact op met de organisator" (Contact organizer).
*   **Social:** "Opslaan" (Save/Bookmark), "Delen" (Share), "Rapporteer" (Report).
*   **Follow:** Button to follow the organizer directly from the event page.

**Ticketing & Monetization:**
*   **Ticket Types:** Multiple tiers supported (e.g., "Early Bird", "Regular", "Low Income").
*   **Status:** "Uitverkocht" (Sold out) indicators.
*   **Booking:** "Boek nu" (Book now) button (likely internal checkout or deep integration).

**Content:**
*   **Description:** Rich text area for event details.
*   **Location:** Map integration.

### 2.4 Reviews & Reputation
*   **Organizer-Centric:** Reviews seem primarily attached to the *Organizer*, not just the specific event instance.
*   **Visibility:** Review counts are highly visible on event cards and detail pages ("Social Proof").
*   **Structure:** Star rating + text comment.

### 2.5 User Account & Management
**Account Dashboard:**
*   **Tickets/Orders:** List of purchased tickets with download links (PDF/QR). No native resale/refund UI observed.
*   **Saved Events:** List of bookmarked events.
*   **Preferences:**
    *   **Newsletter:** Granular frequency control (Weekly, Bi-monthly, Monthly, News-only, Never).
    *   **Interests:** Extensive tag selection (e.g., "Tantra", "Yoga") to tailor recommendations.
    *   **Reviews:** Opt-in toggle for review requests.
*   **Profile Settings:** Basic fields (Name, Email, Photo, Password). No public bio for attendees.

**Navigation:**
*   Sidebar menu: Orders, Account Details, Preferences, Saved Events.
*   "Following" functionality seems to exist (button on profiles) but no dedicated `/account/following` page was found (returned 404). It might be hidden or under a different URL.

## 3. Data Model Inferences

Based on the UI, the backend likely supports:

**User (Attendee):**
*   `first_name`, `last_name`, `email`, `password_hash`
*   `profile_photo_url`
*   `newsletter_preference` (enum)
*   `ask_for_reviews` (boolean)
*   `interests` (Many-to-Many with Tags)

**Organizer:**
*   `slug` (unique identifier for URL)

*   `is_premium` / `tier` (flag for enhanced profile features)
*   `banner_image`, `profile_image`
*   `bio_html`
*   `follower_count`
*   `review_aggregate_score`
*   `review_count`

**Event:**
*   `organizer_id` (Foreign Key)
*   `location_data` (Lat/Long for map, Address string)
*   `ticket_config` (One-to-Many relationship with Ticket Types)
*   `status` (Published, Cancelled, Sold Out)

**Interaction:**
*   `Follow` (User -> Organizer)
*   `Save` (User -> Event)
*   `Message` (User -> Organizer)

## 4. UX/UI Observations
*   **Trust First:** The design heavily emphasizes the *person* behind the event. Organizer faces/logos and review counts are ubiquitous.
*   **Community Feel:** Language like "Volgen" (Follow) and "Community" suggests a social network layer on top of a ticketing platform.
*   **Clean & Visual:** Generous whitespace, large images, distinct typography.

## 5. Potential "Missed" Features (Opportunities)
*   **"Who is going":** Did not observe a public guest list or "friends going" feature (privacy focused?).
*   **Discussion/Comments:** No public comment section on events (only private messaging to organizer).
