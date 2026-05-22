"""
System-check tests for a_core W006/E006 legal-contact deploy checks.

Parametrized across {DEBUG, PUBLIC_READ_ENABLED} × {complete, missing name, missing
address, missing email}.
"""

from django.test import TestCase, override_settings

FULL_LEGAL_SETTINGS = {
    "IMPRESSUM_NAME": "Jane Doe",
    "IMPRESSUM_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "IMPRESSUM_EMAIL": "jane@example.com",
    "IMPRESSUM_PHONE": "+49 30 12345678",
    "RESPONSIBLE_PERSON_NAME": "Jane Doe",
    "RESPONSIBLE_PERSON_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "DSA_CONTACT_EMAIL": "jane@example.com",
    "LEGAL_CONTACT": {
        "name": "Jane Doe",
        "address": "Musterstr. 1, 12345 Berlin",
        "email": "jane@example.com",
        "phone": "+49 30 12345678",
        "responsible_name": "Jane Doe",
        "responsible_address": "Musterstr. 1, 12345 Berlin",
        "dsa_email": "jane@example.com",
    },
}

MISSING_NAME_SETTINGS = {
    "IMPRESSUM_NAME": "",
    "IMPRESSUM_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "IMPRESSUM_EMAIL": "jane@example.com",
    "IMPRESSUM_PHONE": "",
    "RESPONSIBLE_PERSON_NAME": "",
    "RESPONSIBLE_PERSON_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "DSA_CONTACT_EMAIL": "jane@example.com",
    "LEGAL_CONTACT": {
        "name": "",
        "address": "Musterstr. 1, 12345 Berlin",
        "email": "jane@example.com",
        "phone": "",
        "responsible_name": "",
        "responsible_address": "Musterstr. 1, 12345 Berlin",
        "dsa_email": "jane@example.com",
    },
}

MISSING_ADDRESS_SETTINGS = {
    "IMPRESSUM_NAME": "Jane Doe",
    "IMPRESSUM_ADDRESS": "",
    "IMPRESSUM_EMAIL": "jane@example.com",
    "IMPRESSUM_PHONE": "",
    "RESPONSIBLE_PERSON_NAME": "Jane Doe",
    "RESPONSIBLE_PERSON_ADDRESS": "",
    "DSA_CONTACT_EMAIL": "jane@example.com",
    "LEGAL_CONTACT": {
        "name": "Jane Doe",
        "address": "",
        "email": "jane@example.com",
        "phone": "",
        "responsible_name": "Jane Doe",
        "responsible_address": "",
        "dsa_email": "jane@example.com",
    },
}

MISSING_EMAIL_SETTINGS = {
    "IMPRESSUM_NAME": "Jane Doe",
    "IMPRESSUM_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "IMPRESSUM_EMAIL": "",
    "IMPRESSUM_PHONE": "",
    "RESPONSIBLE_PERSON_NAME": "Jane Doe",
    "RESPONSIBLE_PERSON_ADDRESS": "Musterstr. 1, 12345 Berlin",
    "DSA_CONTACT_EMAIL": "",
    "LEGAL_CONTACT": {
        "name": "Jane Doe",
        "address": "Musterstr. 1, 12345 Berlin",
        "email": "",
        "phone": "",
        "responsible_name": "Jane Doe",
        "responsible_address": "Musterstr. 1, 12345 Berlin",
        "dsa_email": "",
    },
}


def run_check(**settings_overrides):
    """Run the legal_contact system check with the given settings overrides."""
    from a_core.checks import check_legal_contact

    with override_settings(**settings_overrides):
        return check_legal_contact(app_configs=None)


class TestLegalCheckNoErrors(TestCase):
    """No checks fire when all required vars are set."""

    def test_no_errors_when_complete_debug_true(self):
        """Complete settings in DEBUG mode: no warnings, no errors."""
        errors = run_check(DEBUG=True, **FULL_LEGAL_SETTINGS)
        self.assertEqual(errors, [])

    def test_no_errors_when_complete_public_read_enabled(self):
        """Complete settings with PUBLIC_READ_ENABLED=True: no warnings, no errors."""
        from django.core.cache import cache

        from a_core.models import FeatureFlag

        cache.clear()
        FeatureFlag.objects.update_or_create(
            key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
        )
        errors = run_check(DEBUG=False, **FULL_LEGAL_SETTINGS)
        self.assertEqual(errors, [])

    def test_no_errors_when_complete_both_flags_off(self):
        """Complete settings with DEBUG=False and PUBLIC_READ_ENABLED=False: no
        errors."""
        from django.core.cache import cache

        from a_core.models import FeatureFlag

        cache.clear()
        FeatureFlag.objects.update_or_create(
            key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
        )
        errors = run_check(DEBUG=False, **FULL_LEGAL_SETTINGS)
        self.assertEqual(errors, [])


class TestLegalCheckW006(TestCase):
    """W006 fires when DEBUG=True and required vars are missing."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        from a_core.models import FeatureFlag

        FeatureFlag.objects.update_or_create(
            key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
        )

    def test_w006_missing_name_debug_true(self):
        """W006 warning fires when IMPRESSUM_NAME is empty and DEBUG=True."""
        errors = run_check(DEBUG=True, **MISSING_NAME_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.W006")

    def test_w006_missing_address_debug_true(self):
        """W006 warning fires when IMPRESSUM_ADDRESS is empty and DEBUG=True."""
        errors = run_check(DEBUG=True, **MISSING_ADDRESS_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.W006")

    def test_w006_missing_email_debug_true(self):
        """W006 warning fires when IMPRESSUM_EMAIL is empty and DEBUG=True."""
        errors = run_check(DEBUG=True, **MISSING_EMAIL_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.W006")

    def test_w006_is_warning_not_error(self):
        """W006 is a Warning (not Error)."""
        from django.core.checks import Warning as DjangoWarning

        errors = run_check(DEBUG=True, **MISSING_NAME_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DjangoWarning)


class TestLegalCheckE006(TestCase):
    """E006 fires when PUBLIC_READ_ENABLED=True and required vars are missing."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        from a_core.models import FeatureFlag

        FeatureFlag.objects.update_or_create(
            key="PUBLIC_READ_ENABLED", defaults={"enabled": True}
        )

    def test_e006_missing_name_public_read(self):
        """E006 error fires when IMPRESSUM_NAME is empty and
        PUBLIC_READ_ENABLED=True."""
        errors = run_check(DEBUG=False, **MISSING_NAME_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.E006")

    def test_e006_missing_address_public_read(self):
        """E006 error fires when IMPRESSUM_ADDRESS is empty and
        PUBLIC_READ_ENABLED=True."""
        errors = run_check(DEBUG=False, **MISSING_ADDRESS_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.E006")

    def test_e006_missing_email_public_read(self):
        """E006 error fires when IMPRESSUM_EMAIL is empty and
        PUBLIC_READ_ENABLED=True."""
        errors = run_check(DEBUG=False, **MISSING_EMAIL_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.E006")

    def test_e006_is_error_not_warning(self):
        """E006 is an Error (not Warning)."""
        from django.core.checks import Error as DjangoError

        errors = run_check(DEBUG=False, **MISSING_NAME_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DjangoError)

    def test_e006_takes_precedence_over_w006_when_public_read_and_debug(self):
        """E006 fires (not W006) when both PUBLIC_READ_ENABLED=True and DEBUG=True."""
        errors = run_check(DEBUG=True, **MISSING_NAME_SETTINGS)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, "a_core.E006")


class TestLegalCheckNoFireWhenBothFalse(TestCase):
    """No check fires when DEBUG=False, PUBLIC_READ_ENABLED=False (internal cohort)."""

    def setUp(self):
        from django.core.cache import cache

        cache.clear()
        from a_core.models import FeatureFlag

        FeatureFlag.objects.update_or_create(
            key="PUBLIC_READ_ENABLED", defaults={"enabled": False}
        )

    def test_no_check_fires_when_debug_false_and_public_read_false(self):
        """No warning or error when DEBUG=False and PUBLIC_READ_ENABLED=False, even
        with missing vars."""
        errors = run_check(DEBUG=False, **MISSING_NAME_SETTINGS)
        self.assertEqual(errors, [])


class TestCheckSafeOnFreshDb(TestCase):
    """check_legal_contact must not crash when the DB table doesn't exist yet."""

    def test_check_safe_on_fresh_db_before_migrations(self):
        """Patching get_flag to raise ProgrammingError simulates pre-migrate state.

        The check must return [] instead of propagating the exception, so that
        `manage.py migrate` on a fresh DB is not aborted by its own system checks.
        """
        from unittest.mock import patch

        from django.db.utils import ProgrammingError

        from a_core.checks import check_legal_contact

        # get_flag is imported inside the function body, so patch the source module
        with patch(
            "a_core.models.get_flag",
            side_effect=ProgrammingError("table does not exist"),
        ):
            errors = check_legal_contact(app_configs=None)

        self.assertEqual(errors, [])

    def test_check_safe_on_fresh_db_operational_error(self):
        """Patching get_flag to raise OperationalError (SQLite fresh DB) returns []."""
        from unittest.mock import patch

        from django.db.utils import OperationalError

        from a_core.checks import check_legal_contact

        # get_flag is imported inside the function body, so patch the source module
        with patch(
            "a_core.models.get_flag",
            side_effect=OperationalError("no such table"),
        ):
            errors = check_legal_contact(app_configs=None)

        self.assertEqual(errors, [])


class TestLegalContactDict(TestCase):
    """Unit tests for legal_contact dict assembly from settings."""

    def test_legal_contact_contains_all_keys(self):
        """LEGAL_CONTACT dict has all required keys."""
        with override_settings(**FULL_LEGAL_SETTINGS):
            from a_core.legal import get_legal_contact

            contact = get_legal_contact()
        self.assertIn("name", contact)
        self.assertIn("address", contact)
        self.assertIn("email", contact)
        self.assertIn("phone", contact)
        self.assertIn("responsible_name", contact)
        self.assertIn("responsible_address", contact)
        self.assertIn("dsa_email", contact)

    def test_legal_contact_returns_settings_values(self):
        """get_legal_contact() returns values from settings.LEGAL_CONTACT."""
        with override_settings(**FULL_LEGAL_SETTINGS):
            from a_core.legal import get_legal_contact

            contact = get_legal_contact()
        self.assertEqual(contact["name"], "Jane Doe")
        self.assertEqual(contact["email"], "jane@example.com")

    def test_legal_contact_empty_strings_when_missing(self):
        """get_legal_contact() returns empty strings for missing optional vars."""
        with override_settings(**MISSING_NAME_SETTINGS):
            from a_core.legal import get_legal_contact

            contact = get_legal_contact()
        self.assertEqual(contact["name"], "")
        self.assertEqual(contact["address"], "Musterstr. 1, 12345 Berlin")


class TestContextProcessor(TestCase):
    """Test that context processor makes legal_contact available in templates."""

    def test_context_processor_returns_legal_contact_key(self):
        """legal_contact_processor returns dict with 'legal_contact' key."""
        with override_settings(**FULL_LEGAL_SETTINGS):
            from a_core.context_processors import legal_contact_processor

            ctx = legal_contact_processor(None)
        self.assertIn("legal_contact", ctx)

    def test_context_processor_legal_contact_has_email(self):
        """Context processor's legal_contact.email is populated from settings."""
        with override_settings(**FULL_LEGAL_SETTINGS):
            from a_core.context_processors import legal_contact_processor

            ctx = legal_contact_processor(None)
        self.assertEqual(ctx["legal_contact"]["email"], "jane@example.com")
