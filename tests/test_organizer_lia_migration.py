"""
TDD tests for Organizer LIA + consent_method migration (bead kb-9kh.2).

Tests:
- test_migration_forward_rewrites_existing_rows
- test_migration_idempotent
- test_migration_reversible
- test_admin_dropdown_shows_new_choice
- test_lia_doc_exists_with_required_sections
"""

import os
import unittest

from django.db import connection
from django.test import TestCase  # noqa: E402

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_organizer(slug, consent_method, consent_notes=""):
    """Create an Organizer with the given consent_method."""
    from organizers.models import Profile

    org = Profile(
        name=f"Organizer {slug}",
        slug=slug,
        consent_method=consent_method,
        consent_notes=consent_notes,
    )
    # save with update_fields skips full_clean, allowing out-of-choices values
    org.save()
    return org


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------


def _get_migration_functions(migration_label):
    """Return (forward_fn, reverse_fn) from the named migration."""
    from django.db import connections
    from django.db.migrations.loader import MigrationLoader

    loader = MigrationLoader(connections["default"])
    migration = loader.get_migration("organizers", migration_label)
    # The data migration has exactly one RunPython operation
    for operation in migration.operations:
        if hasattr(operation, "code"):
            return operation.code, operation.reverse_code
    raise ValueError(f"No RunPython found in migration {migration_label}")


def _apply_migration_forward(migration_label, apps, schema_editor):
    forward_fn, _ = _get_migration_functions(migration_label)
    forward_fn(apps, schema_editor)


def _apply_migration_reverse(migration_label, apps, schema_editor):
    _, reverse_fn = _get_migration_functions(migration_label)
    reverse_fn(apps, schema_editor)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@unittest.skipIf(
    connection.vendor == "sqlite",
    "TestOrganizerLIAMigrationForward uses connection.schema_editor() inside a test "
    "transaction, which SQLite does not support (NotSupportedError: FK constraint "
    "checks are enabled). Run under default Postgres settings instead.",
)
class TestOrganizerLIAMigrationForward(TestCase):
    """Forward migration rewrites telegram_forward_implied → legitimate_interest."""

    def test_migration_forward_rewrites_existing_rows(self):
        """All telegram_forward_implied rows become legitimate_interest."""
        from django.apps import apps
        from django.db import connection

        # Create test organizers with telegram_forward_implied
        org1 = _make_organizer("org-forward-1", "telegram_forward_implied", "")
        org2 = _make_organizer("org-forward-2", "telegram_forward_implied", "some notes")
        # One that should NOT be touched
        org3 = _make_organizer("org-forward-3", "explicit_opt_in", "unchanged")

        with connection.schema_editor() as schema_editor:
            _apply_migration_forward("0006_backfill_consent_method", apps, schema_editor)

        org1.refresh_from_db()
        org2.refresh_from_db()
        org3.refresh_from_db()

        assert org1.consent_method == "legitimate_interest"
        assert "ADR-006" in org1.consent_notes

        assert org2.consent_method == "legitimate_interest"
        assert "ADR-006" in org2.consent_notes
        assert "some notes" in org2.consent_notes

        # explicit_opt_in should be untouched
        assert org3.consent_method == "explicit_opt_in"
        assert org3.consent_notes == "unchanged"

    def test_migration_idempotent(self):
        """Running the forward migration twice does not double-append the note."""
        from django.apps import apps
        from django.db import connection

        org = _make_organizer("org-idempotent", "telegram_forward_implied", "")

        with connection.schema_editor() as schema_editor:
            _apply_migration_forward("0006_backfill_consent_method", apps, schema_editor)

        org.refresh_from_db()
        first_notes = org.consent_notes

        # Run again — the row is now legitimate_interest, not telegram_forward_implied
        # so it won't be touched a second time
        with connection.schema_editor() as schema_editor:
            _apply_migration_forward("0006_backfill_consent_method", apps, schema_editor)

        org.refresh_from_db()
        second_notes = org.consent_notes

        assert first_notes == second_notes, f"Note was appended twice:\n{second_notes!r}"
        assert second_notes.count("ADR-006") == 1

    def test_migration_reversible(self):
        """Reverse migration restores consent_method=telegram_forward_implied."""
        from django.apps import apps
        from django.db import connection

        org = _make_organizer("org-reversible", "telegram_forward_implied", "original notes")

        with connection.schema_editor() as schema_editor:
            _apply_migration_forward("0006_backfill_consent_method", apps, schema_editor)

        org.refresh_from_db()
        assert org.consent_method == "legitimate_interest"

        with connection.schema_editor() as schema_editor:
            _apply_migration_reverse("0006_backfill_consent_method", apps, schema_editor)

        org.refresh_from_db()
        assert org.consent_method == "telegram_forward_implied"


class TestAdminDropdown(TestCase):
    """Admin change form shows the new legitimate_interest choice."""

    def test_admin_dropdown_shows_new_choice(self):
        """The Organizer model's consent_method field includes legitimate_interest."""
        from organizers.models import Profile

        field = Profile._meta.get_field("consent_method")
        choices_dict = dict(field.choices)

        assert "legitimate_interest" in choices_dict, (
            f"'legitimate_interest' not in choices: {list(choices_dict.keys())}"
        )
        assert choices_dict["legitimate_interest"] == "Legitimate interest (Art. 6(1)(f))"

    def test_legitimate_interest_is_first_choice(self):
        """legitimate_interest must appear first in the choices list."""
        from organizers.models import Profile

        field = Profile._meta.get_field("consent_method")
        first_key, first_label = field.choices[0]
        assert first_key == "legitimate_interest", f"Expected legitimate_interest first, got {first_key!r}"


class TestLIADocExists(TestCase):
    """docs/compliance/organizer-lia.md exists with required content."""

    LIA_PATH = os.path.join(
        os.path.dirname(__file__),  # tests/
        "..",
        "docs",
        "compliance",
        "organizer-lia.md",
    )

    def _read_lia(self):
        path = os.path.normpath(self.LIA_PATH)
        assert os.path.exists(path), f"LIA document not found at {path}"
        with open(path) as f:
            return f.read()

    def test_lia_doc_exists(self):
        """docs/compliance/organizer-lia.md must exist."""
        self._read_lia()  # raises if missing

    def test_lia_contains_art6_reference(self):
        """LIA must reference Art. 6(1)(f)."""
        content = self._read_lia()
        assert "Art. 6(1)(f)" in content

    def test_lia_contains_balancing(self):
        """LIA must contain a balancing test section."""
        content = self._read_lia()
        assert "balancing" in content.lower()

    def test_lia_contains_takedown_reference(self):
        """LIA must reference the /takedown/ opt-out path."""
        content = self._read_lia()
        assert "takedown" in content.lower()

    def test_lia_contains_necessity_section(self):
        """LIA must contain a Necessity section."""
        content = self._read_lia()
        assert "necessity" in content.lower() or "Necessity" in content

    def test_lia_contains_purpose_section(self):
        """LIA must contain a Purpose section."""
        content = self._read_lia()
        assert "purpose" in content.lower() or "Purpose" in content
