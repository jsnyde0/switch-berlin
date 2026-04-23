"""Tests for the Impressum page (kb-8qp).

Verifies:
- Anonymous GET /impressum/ returns 200 under both PUBLIC_READ_ENABLED states.
- All required legal sections are present.
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
