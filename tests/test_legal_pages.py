"""Tests for legal pages: Impressum (kb-8qp) and Terms (kb-7hg).

Verifies:
- Anonymous GET /impressum/ returns 200 under both PUBLIC_READ_ENABLED states.
- All required Impressum legal sections are present.
- Anonymous GET /terms/ returns 200 under both PUBLIC_READ_ENABLED states.
- All required Terms legal sections are present (DSA Art. 12/14/20, JuSchG, etc.).
- German translation renders when LANGUAGE_CODE='de'.
"""

import pytest
from django.core.cache import cache
from django.test import override_settings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def public_read_on(db):
    """Ensure PUBLIC_READ_ENABLED=True in DB and clear cache."""
    from a_core.models import FeatureFlag

    FeatureFlag.objects.get_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
    )
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=True)
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def public_read_off(db):
    """Set PUBLIC_READ_ENABLED=False in DB and clear cache; restore after."""
    from a_core.models import FeatureFlag

    FeatureFlag.objects.get_or_create(
        key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
    )
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=False)
    cache.clear()
    yield
    FeatureFlag.objects.filter(key="PUBLIC_READ_ENABLED").update(enabled=True)
    cache.clear()


# ---------------------------------------------------------------------------
# Group 1: HTTP smoke — both PUBLIC_READ_ENABLED states
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_impressum_returns_200_public_read_on(client, public_read_on):
    """Anonymous GET /impressum/ with PUBLIC_READ_ENABLED=True -> 200."""
    response = client.get("/impressum/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_impressum_returns_200_public_read_off(client, public_read_off):
    """Anonymous GET /impressum/ with PUBLIC_READ_ENABLED=False -> 200."""
    response = client.get("/impressum/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Group 2: Required sections present (EN, default language)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_impressum_has_ddg_heading(client, public_read_on):
    """Page must include the §5 DDG primary heading."""
    response = client.get("/impressum/")
    assert b"DDG" in response.content


@pytest.mark.django_db
def test_impressum_has_imprint_subtitle(client, public_read_on):
    """Page must include 'Imprint' as secondary heading."""
    response = client.get("/impressum/")
    assert b"Imprint" in response.content


@pytest.mark.django_db
def test_impressum_has_mstv_section(client, public_read_on):
    """Page must include §18 Abs. 2 MStV responsible-person block."""
    response = client.get("/impressum/")
    assert b"MStV" in response.content


@pytest.mark.django_db
def test_impressum_has_dsa_section(client, public_read_on):
    """Page must include DSA Art. 11/12 contact point paragraph."""
    response = client.get("/impressum/")
    assert b"DSA" in response.content


@pytest.mark.django_db
def test_impressum_has_vsbg_statement(client, public_read_on):
    """Page must include §36 VSBG consumer arbitration statement."""
    response = client.get("/impressum/")
    # The VSBG statement must appear in German (language-neutral legal text).
    assert b"Streitbeilegungsverfahren" in response.content


@pytest.mark.django_db
def test_impressum_has_liability_section(client, public_read_on):
    """Page must include liability (Haftung) section — check EN heading."""
    response = client.get("/impressum/")
    # In EN the heading renders as "Disclaimer"; in DE as "Haftungsausschluss".
    assert b"Liability" in response.content


@pytest.mark.django_db
def test_impressum_has_copyright_section(client, public_read_on):
    """Page must include Copyright / Urheberrecht paragraph (EN heading)."""
    response = client.get("/impressum/")
    assert b"Copyright" in response.content


@pytest.mark.django_db
def test_impressum_no_placeholder_brackets(client, public_read_on):
    """Page must NOT contain any placeholder brackets like [MAINTAINER NAME]."""
    response = client.get("/impressum/")
    assert b"[MAINTAINER" not in response.content
    assert b"[CONTACT" not in response.content


# ---------------------------------------------------------------------------
# Group 3: German translation renders
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_impressum_de_renders_german_heading(client, public_read_on):
    """With LANGUAGE_CODE='de', page heading appears in German."""
    with override_settings(LANGUAGE_CODE="de"):
        response = client.get("/impressum/", HTTP_ACCEPT_LANGUAGE="de")
    assert response.status_code == 200
    # The §5 DDG heading is language-neutral (German legal term used in both).
    assert b"DDG" in response.content


@pytest.mark.django_db
def test_impressum_de_renders_translated_liability(client, public_read_on):
    """With LANGUAGE_CODE='de', Haftung section uses German strings."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/impressum/")
    assert response.status_code == 200
    # The VSBG paragraph is always in German (language-neutral legal text).
    assert b"Streitbeilegungsverfahren" in response.content


@pytest.mark.django_db
def test_impressum_de_renders_translated_copyright(client, public_read_on):
    """With LANGUAGE_CODE='de', Urheberrecht heading appears."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/impressum/")
    assert response.status_code == 200
    # Once translations are compiled, "Copyright" heading renders as "Urheberrecht".
    assert b"Urheberrecht" in response.content


# ===========================================================================
# Terms tests (kb-7hg)
# ===========================================================================

# ---------------------------------------------------------------------------
# Group 4: HTTP smoke — /terms/ under both PUBLIC_READ_ENABLED states
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_terms_returns_200_public_read_on(client, public_read_on):
    """Anonymous GET /terms/ with PUBLIC_READ_ENABLED=True -> 200."""
    response = client.get("/terms/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_terms_returns_200_public_read_off(client, public_read_off):
    """Anonymous GET /terms/ with PUBLIC_READ_ENABLED=False -> 200."""
    response = client.get("/terms/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Group 5: Required sections present (EN, default language)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_terms_has_dsa_art12_contact(client, public_read_on):
    """Terms must include DSA Art. 12 contact-point reference at the top."""
    response = client.get("/terms/")
    assert b"DSA Art. 12" in response.content


@pytest.mark.django_db
def test_terms_has_juschg_age_restriction(client, public_read_on):
    """Terms must include JuSchG 18+ age-restriction clause."""
    response = client.get("/terms/")
    # Must mention 18+ explicitly
    assert b"18" in response.content
    # Must reference JuSchG
    assert b"JuSchG" in response.content


@pytest.mark.django_db
def test_terms_has_dsa_art14_moderation(client, public_read_on):
    """Terms must include DSA Art. 14 content-moderation section."""
    response = client.get("/terms/")
    assert b"DSA Art. 14" in response.content


@pytest.mark.django_db
def test_terms_has_dsa_art20_appeal(client, public_read_on):
    """Terms must include DSA Art. 20 appeal path with 14-day window."""
    response = client.get("/terms/")
    assert b"DSA Art. 20" in response.content
    # 14-day appeal window must be mentioned
    assert b"14" in response.content


@pytest.mark.django_db
def test_terms_has_user_generated_content_clause(client, public_read_on):
    """Terms must include user-generated content (ratings/flags) liability clause."""
    response = client.get("/terms/")
    # The clause covers ratings and flags
    assert b"rating" in response.content.lower()


@pytest.mark.django_db
def test_terms_has_berlin_jurisdiction(client, public_read_on):
    """Terms must include Berlin as jurisdiction for non-consumer disputes."""
    response = client.get("/terms/")
    assert b"Berlin" in response.content


@pytest.mark.django_db
def test_terms_has_german_governing_law(client, public_read_on):
    """Terms must state German law applies."""
    response = client.get("/terms/")
    assert b"German law" in response.content


@pytest.mark.django_db
def test_terms_has_severability(client, public_read_on):
    """Terms must include severability clause."""
    response = client.get("/terms/")
    assert b"severab" in response.content.lower()


@pytest.mark.django_db
def test_terms_has_no_widerrufsrecht(client, public_read_on):
    """Terms must state Widerrufsrecht does not apply (free service)."""
    response = client.get("/terms/")
    assert b"Widerrufsrecht" in response.content


@pytest.mark.django_db
def test_terms_has_last_updated(client, public_read_on):
    """Terms must display a 'Last updated' date."""
    response = client.get("/terms/")
    assert b"Last updated" in response.content


@pytest.mark.django_db
def test_terms_has_dsa_contact_email(client, public_read_on):
    """Terms must display the DSA contact email from legal_contact context."""
    response = client.get("/terms/")
    # dsa_email must appear somewhere on the page
    assert b"@" in response.content


# ---------------------------------------------------------------------------
# Group 6: German translation renders
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_terms_de_renders_berlin_gerichtsstand(client, public_read_on):
    """With LANGUAGE_CODE='de', Gerichtsstand Berlin appears in German copy."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/terms/")
    assert response.status_code == 200
    # Gerichtsstand is the German legal term for jurisdiction
    assert b"Berlin" in response.content


@pytest.mark.django_db
def test_terms_de_renders_14_tage_frist(client, public_read_on):
    """With LANGUAGE_CODE='de', the 14-Tage-Frist (14-day deadline) appears."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/terms/")
    assert response.status_code == 200
    assert b"14" in response.content


@pytest.mark.django_db
def test_terms_de_renders_german_key_phrases(client, public_read_on):
    """With LANGUAGE_CODE='de', distinctively German legal phrases appear in the
    page."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/terms/")
    assert response.status_code == 200
    # Page title must render in German
    assert b"Nutzungsbedingungen" in response.content
    # Severability section heading must appear in German
    assert b"Salvatorische Klausel" in response.content
    # Widerrufsrecht N/A must be stated in German legal prose
    assert b"unentgeltlich" in response.content


# ===========================================================================
# Privacy tests (kb-nyr)
# ===========================================================================

# ---------------------------------------------------------------------------
# Group 7: HTTP smoke — /privacy/ under both PUBLIC_READ_ENABLED states
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_privacy_returns_200_public_read_on(client, public_read_on):
    """Anonymous GET /privacy/ with PUBLIC_READ_ENABLED=True -> 200."""
    response = client.get("/privacy/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_privacy_returns_200_public_read_off(client, public_read_off):
    """Anonymous GET /privacy/ with PUBLIC_READ_ENABLED=False -> 200."""
    response = client.get("/privacy/")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Group 8: Required sections present (EN, default language)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_privacy_has_controller_identity(client, public_read_on):
    """Privacy page must include controller identity block from legal_contact."""
    response = client.get("/privacy/")
    # The controller section renders legal_contact.name and legal_contact.email
    assert b"Verantwortlicher" in response.content or b"Controller" in response.content


@pytest.mark.django_db
def test_privacy_has_art_6_1_b(client, public_read_on):
    """Privacy page must reference Art. 6(1)(b) for account management."""
    response = client.get("/privacy/")
    assert b"Art. 6(1)(b)" in response.content


@pytest.mark.django_db
def test_privacy_has_art_9_2_a(client, public_read_on):
    """Privacy page must reference Art. 9(2)(a) explicit consent for attendance data."""
    response = client.get("/privacy/")
    assert b"Art. 9(2)(a)" in response.content


@pytest.mark.django_db
def test_privacy_has_art_6_1_f(client, public_read_on):
    """Privacy page must reference Art. 6(1)(f) legitimate interest."""
    response = client.get("/privacy/")
    assert b"Art. 6(1)(f)" in response.content


@pytest.mark.django_db
def test_privacy_has_art_7_3_withdrawal(client, public_read_on):
    """Privacy page must reference Art. 7(3) consent withdrawal right."""
    response = client.get("/privacy/")
    assert b"Art. 7(3)" in response.content


@pytest.mark.django_db
def test_privacy_has_art_21_objection_for_organizers(client, public_read_on):
    """Privacy page must include Art. 21 objection right for organizers."""
    response = client.get("/privacy/")
    assert b"Art. 21" in response.content


@pytest.mark.django_db
def test_privacy_has_blnbdi_complaint_authority(client, public_read_on):
    """Privacy page must include BlnBDI supervisory authority complaint information."""
    response = client.get("/privacy/")
    assert b"BlnBDI" in response.content or b"datenschutz-berlin" in response.content


@pytest.mark.django_db
def test_privacy_has_hosting_provider(client, public_read_on):
    """Privacy page must mention hosting provider (Hetzner or EU hosting)."""
    response = client.get("/privacy/")
    # Must mention either Hetzner specifically or some EU hosting reference
    content_lower = response.content.lower()
    assert b"hetzner" in content_lower or b"hosting" in content_lower


@pytest.mark.django_db
def test_privacy_has_llm_processor_with_scc_transfer(client, public_read_on):
    """Privacy page must mention LLM processor with Art. 44ff SCC transfer statement."""
    response = client.get("/privacy/")
    # OpenAI or Anthropic must be mentioned
    content = response.content
    assert b"OpenAI" in content or b"Anthropic" in content
    # SCC or Standard Contractual Clauses must be mentioned
    assert (
        b"SCC" in content or b"Standard Contractual" in content or b"Art. 44" in content
    )


@pytest.mark.django_db
def test_privacy_has_retention_schedule(client, public_read_on):
    """Privacy page must include a retention schedule covering key data categories."""
    response = client.get("/privacy/")
    content = response.content
    # Must mention retention periods
    assert b"90 days" in content or b"90 Tage" in content
    assert b"30 days" in content or b"30 Tage" in content


@pytest.mark.django_db
def test_privacy_has_ttdsg_cookie_section(client, public_read_on):
    """Privacy page must include TTDSG §25(2) age-gate cookie explanation."""
    response = client.get("/privacy/")
    assert b"TTDSG" in response.content


@pytest.mark.django_db
def test_privacy_has_juschg_minimum_age(client, public_read_on):
    """Privacy page must include JuSchG 18+ minimum age clause."""
    response = client.get("/privacy/")
    assert b"JuSchG" in response.content
    assert b"18" in response.content


@pytest.mark.django_db
def test_privacy_has_last_updated(client, public_read_on):
    """Privacy page must display a 'Last updated' date."""
    response = client.get("/privacy/")
    assert (
        b"Last updated" in response.content
        or b"Zuletzt aktualisiert" in response.content
    )


@pytest.mark.django_db
def test_privacy_has_automated_processing_disclosure(client, public_read_on):
    """Privacy page must include Art. 13(2)(f) automated processing disclosure."""
    response = client.get("/privacy/")
    content = response.content
    # LLM extraction must be disclosed
    assert b"LLM" in content or b"language model" in content.lower()


@pytest.mark.django_db
def test_privacy_has_no_placeholder_brackets(client, public_read_on):
    """Privacy page must NOT contain any placeholder brackets like [CONTACT EMAIL]."""
    response = client.get("/privacy/")
    assert b"[CONTACT" not in response.content
    assert b"[MAINTAINER" not in response.content


# ---------------------------------------------------------------------------
# Group 9: German translation renders
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_privacy_de_renders_verantwortlicher(client, public_read_on):
    """With LANGUAGE_CODE='de', Verantwortlicher (controller) appears in German."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/privacy/")
    assert response.status_code == 200
    assert b"Verantwortlicher" in response.content


@pytest.mark.django_db
def test_privacy_de_renders_berechtigtes_interesse(client, public_read_on):
    """With LANGUAGE_CODE='de', Berechtigtes Interesse appears for organizer LIA."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/privacy/")
    assert response.status_code == 200
    assert b"Berechtigtes Interesse" in response.content


@pytest.mark.django_db
def test_privacy_de_renders_widerruf(client, public_read_on):
    """With LANGUAGE_CODE='de', Widerruf (consent withdrawal) appears."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/privacy/")
    assert response.status_code == 200
    assert b"Widerruf" in response.content


# ---------------------------------------------------------------------------
# Group 10: LIA inline text present (Fix kb-9kh.6)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_privacy_lia_inline_text_present(client, public_read_on):
    """Privacy page must describe LIA inline — no dead .md link."""
    response = client.get("/privacy/")
    content = response.content
    # The inline LIA text must mention key concepts: organizer events are public,
    # curation serves legitimate interest, objection via /takedown/
    assert b"organizer-lia.md" not in content, (
        "Dead link to organizer-lia.md must not appear on privacy page"
    )
    # Must still mention the LIA/legitimate interest concepts inline
    assert b"Art. 6(1)(f)" in content
    assert b"/takedown/" in content


@pytest.mark.django_db
def test_privacy_de_lia_inline_text_present(client, public_read_on):
    """With LANGUAGE_CODE='de', privacy page LIA inline text has no dead .md link."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/privacy/")
    assert response.status_code == 200
    assert b"organizer-lia.md" not in response.content, (
        "Dead link to organizer-lia.md must not appear in German privacy page"
    )


# ===========================================================================
# Takedown tests (kb-9kh.5, kb-9kh.7)
# ===========================================================================

# ---------------------------------------------------------------------------
# Group 11: Takedown mailto not hardcoded (Fix kb-9kh.5)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@override_settings(
    LEGAL_CONTACT={
        "name": "Test Org",
        "address": "",
        "email": "hello@example.com",
        "phone": "",
        "responsible_name": "",
        "responsible_address": "",
        "dsa_email": "dsa@example.com",
    }
)
def test_takedown_no_hardcoded_email(client, public_read_on):
    """Takedown page must NOT contain a hardcoded takedown@ email."""
    response = client.get("/takedown/")
    assert response.status_code == 200
    assert b"takedown@switch.berlin" not in response.content, (
        "Hardcoded mailto takedown@switch.berlin must not appear; "
        "use legal_contact.dsa_email"
    )
    assert b"takedown@kinkybubbles.de" not in response.content, (
        "Legacy hardcoded mailto takedown@kinkybubbles.de must not appear; "
        "use legal_contact.dsa_email"
    )


# ---------------------------------------------------------------------------
# Group 12: Takedown DE translations present (Fix kb-9kh.7)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_takedown_de_title_translated(client, public_read_on):
    """With LANGUAGE_CODE='de', takedown page title appears in German."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/takedown/")
    assert response.status_code == 200
    # German title must be present
    assert b"Inhalt melden" in response.content


@pytest.mark.django_db
def test_takedown_de_false_report_warning_translated(client, public_read_on):
    """With LANGUAGE_CODE='de', false-report warning appears in German."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/takedown/")
    assert response.status_code == 200
    # Must contain German warning text
    assert "falsch" in response.content.decode("utf-8").lower()


@pytest.mark.django_db
def test_takedown_de_submit_button_translated(client, public_read_on):
    """With LANGUAGE_CODE='de', submit button label appears in German."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/takedown/")
    assert response.status_code == 200
    content_decoded = response.content.decode("utf-8")
    assert "Meldung absenden" in content_decoded


@pytest.mark.django_db
def test_takedown_de_gdpr_notice_translated(client, public_read_on):
    """With LANGUAGE_CODE='de', GDPR processing notice appears in German."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/takedown/")
    assert response.status_code == 200
    content_decoded = response.content.decode("utf-8")
    # Must mention DSGVO or Art. 6(1)(c) in German context
    assert "DSGVO" in content_decoded or "Datenschutz" in content_decoded
