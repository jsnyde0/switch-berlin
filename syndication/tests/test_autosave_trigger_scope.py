"""
Template-structure guard for per-channel autosave trigger scoping (kb-kgza.12).

ROOT CAUSE (verified 2026-06-06): HTMX evaluates `from:<selector>` against the
WHOLE document, not the local form. Every channel tab is rendered into the DOM
at once (only hidden via Alpine x-show). So a document-scoped
  hx-trigger="input changed delay:600ms from:textarea[name='body']"
fires EVERY channel's autosave endpoint per keystroke, plus the canonical
event-edit form — causing concurrent detach-and-edit racing and data loss.

FIX: drop the document-scoped `from:` selector from both autosave triggers so
each form fires only on input events that bubble up from its own descendants.

This test asserts the structural property on the template source — not on a
rendered HTTP response — because the race condition is invisible to a single-
request test (a single POST has no competitor and always persists fine).

We assert on the template FILE CONTENT, not response.context, per the
hollow-test anti-pattern documented throughout this codebase.
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _channel_editor_source() -> str:
    """Return the raw source of the channel editor fragment template."""
    template_path = Path(settings.BASE_DIR) / "templates" / "syndication" / "fragments" / "_channel_editor.html"
    return template_path.read_text(encoding="utf-8")


class ChannelAutosaveTriggerScopeTest(SimpleTestCase):
    """
    The per-channel body autosave form must NOT use a document-scoped
    `from:` selector in its hx-trigger attribute.

    A document-scoped from: causes every channel's autosave endpoint to fire
    on every keystroke in any channel body, racing against the canonical
    event-edit form and dropping in-flight content (kb-kgza.12 root cause).
    """

    def test_body_autosave_has_no_document_scoped_from_selector(self):
        """
        The per-channel body form hx-trigger must not contain `from:textarea`
        (the document-scoped form that fires across all channel forms).

        Correct form: `hx-trigger="input changed delay:600ms"` with no `from:`
        so the trigger fires only on events bubbling up within the same form.
        """
        source = _channel_editor_source()

        # The broken pattern: `from:textarea` on the body autosave form.
        # This is document-scoped and causes cross-channel broadcast.
        broken_pattern = r'hx-trigger="[^"]*from:textarea[^"]*"'
        matches = re.findall(broken_pattern, source)

        self.assertEqual(
            matches,
            [],
            msg=(
                "Found document-scoped `from:textarea` in hx-trigger "
                "in _channel_editor.html — this fires every channel's "
                "autosave on every keystroke, causing data loss via "
                "concurrent detach-and-edit racing.\n"
                f"Offending hx-trigger attributes found: {matches}\n"
                "Fix: remove the `from:textarea[name='body']` selector "
                "and let the trigger bind to the form element itself."
            ),
        )

    def test_event_edit_autosave_has_no_document_scoped_from_selectors(self):
        """
        The Switch event-edit autosave form hx-trigger must not use
        document-scoped `from:input`, `from:textarea`, or `from:select`
        selectors that fire on changes in OTHER forms on the page.

        Correct form: `hx-trigger="input changed delay:600ms"` on the form
        element, which picks up events bubbling from its own descendants only.
        """
        source = _channel_editor_source()

        # The broken pattern: from:<element-type> on the event-edit form.
        # These are document-scoped and fire on inputs in every other form too.
        broken_from_patterns = [
            r'hx-trigger="[^"]*from:input[^"]*"',
            r'hx-trigger="[^"]*from:select[^"]*"',
        ]

        for pattern in broken_from_patterns:
            matches = re.findall(pattern, source)
            self.assertEqual(
                matches,
                [],
                msg=(
                    f"Found document-scoped `from:` selector matching "
                    f"`{pattern}` in _channel_editor.html hx-trigger — "
                    "this fires the event-edit autosave when input occurs "
                    "in per-channel body forms (siblings on the same page), "
                    "racing with detach-and-edit and dropping typed content.\n"
                    f"Offending hx-trigger attributes found: {matches}\n"
                    "Fix: remove the document-scoped `from:` selectors so "
                    "the trigger binds to the form's own descendants."
                ),
            )
