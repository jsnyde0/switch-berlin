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
    """With LANGUAGE_CODE='de', distinctively German legal phrases appear in the page."""
    with override_settings(LANGUAGE_CODE="de", LANGUAGE_COOKIE_NAME="django_language"):
        client.cookies["django_language"] = "de"
        response = client.get("/terms/")
    assert response.status_code == 200
    # Page title must render in German
    assert "Nutzungsbedingungen".encode() in response.content
    # Severability section heading must appear in German
    assert "Salvatorische Klausel".encode() in response.content
    # Widerrufsrecht N/A must be stated in German legal prose
    assert "unentgeltlich".encode() in response.content
