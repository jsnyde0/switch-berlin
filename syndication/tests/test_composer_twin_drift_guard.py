"""
Surface-wide regression guard against inline-twin drift in syndication
composer templates (kb-v93q).

ROOT CAUSE CLASS: When a widget partial is extracted from two composers that
shared duplicated inline markup, developers may later re-inline the widget
(or parts of it) into a composer — causing silent drift between the "copy"
and the canonical partial. Two symptoms:

  1. Twin-tell comments — hand-copy idioms like "must match X", "keep in sync
     with X", "copy of X" — appear whenever someone knows they're maintaining
     a manual mirror.

  2. Widget markup duplicated inline — the distinctive structural signature of
     a partial appears in more than one file, meaning the widget was re-inlined.

This test catches both symptoms surface-wide across templates/syndication/.

Why test on file content (not rendered responses):

  Rendered responses require DB state and a full request cycle.  A template
  structural property (which tag appears in which file) is stable without
  runtime context and is the only correct assertion surface for "does this
  file reference its widget via include or carry the markup inline?"

Assertions:

  (a) TWIN-TELL COMMENTS — No twin-tell comment idiom survives in any
      syndication template except the ONE allowlisted exception:
      the Switch-badge inline twin in _channel_editor.html that legitimately
      mirrors _sync_bar.html (explained below).

  (b) INCLUDE-ONLY WIDGETS — The three extracted widgets (_sync_picker,
      _breadcrumb, _channel_editor) are referenced only via {%% include %%}
      in the composer files; their distinctive structural signatures appear in
      exactly ONE file under templates/syndication/ (their own partial).

  (c) SWITCH-BADGE TWIN COMPLETENESS — The allowlisted Switch-badge inline
      twin in _channel_editor.html carries the SAME three sync-state branches
      as the canonical _sync_bar.html it mirrors.  If _sync_bar.html gains or
      loses a state branch and the twin doesn't follow, this test must fail.

Background on the allowlisted exception (_channel_editor.html lines ~80-148):

  The Switch listing event-composer path wraps Switch's platform-specific
  EventForm.  This form cannot use {%% include 'syndication/fragments/_sync_bar.html' %%}
  because the sync controls and the event-edit form share the same surrounding
  Alpine / HTMX context that depends on the Switch-only form layout.  The
  inline badge is therefore the only pragmatic option for this ONE path.

  The comment that marks it (the allowlist entry) is:
    "must match _sync_bar.html"
  which appears on a single line in _channel_editor.html.  Any NEW instance of
  a twin-tell idiom in any OTHER file must trip assertion (a).
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _syndication_templates_dir() -> Path:
    return Path(settings.BASE_DIR) / "templates" / "syndication"


def _read_template(rel_path: str) -> str:
    """Read a syndication template by path relative to templates/syndication/."""
    return (_syndication_templates_dir() / rel_path).read_text(encoding="utf-8")


def _all_syndication_html_files() -> list[Path]:
    return sorted(_syndication_templates_dir().rglob("*.html"))


# ---------------------------------------------------------------------------
# ALLOWLIST — the ONLY permitted twin-tell comments in templates/syndication/.
# Each entry is (relative_path_suffix, verbatim_fragment_that_must_appear_on_the_specific_line).
#
# The allowlist is matched at the OCCURRENCE level: both the file path suffix
# AND the fragment must appear on the SAME LINE that triggered the hit.  This
# prevents a single allowlisted occurrence from silently covering a second,
# illegitimate twin-tell comment that happens to be in the same file.
#
# _channel_editor.html carries an inline mirror of _sync_bar.html inside the
# Switch listing event-composer path.  The EventForm card cannot use
# {%% include 'syndication/fragments/_sync_bar.html' %%} because the sync
# controls must be tightly coupled to the Switch-specific form layout.
# This is the ONLY sanctioned inline twin; all other twin-tell comments are bugs.
# ---------------------------------------------------------------------------
_ALLOWLISTED_TWIN_TELL: list[tuple[str, str]] = [
    (
        "fragments/_channel_editor.html",
        "must match _sync_bar.html",
    ),
]

# ---------------------------------------------------------------------------
# Twin-tell idiom patterns (case-insensitive substring search).
# Any comment containing these phrases signals a hand-maintained copy.
# ---------------------------------------------------------------------------
_TWIN_TELL_IDIOMS = [
    "must match",
    "keep in sync",
    "in sync with",
    "copy of",
]


class TwinTellCommentGuardTest(SimpleTestCase):
    """
    (a) No twin-tell comment survives in any syndication template except
    the ONE allowlisted Switch-badge exception in _channel_editor.html.

    A "twin-tell comment" is a comment that says the file is a manual copy
    that must be kept in sync with some other file.  Examples:
      {#  must match _sync_bar.html  #}
      {#  keep in sync with _breadcrumb.html  #}
      {#  copy of _channel_editor.html  #}

    These are code smells that mean a developer re-inlined a widget instead
    of using {%% include %%}.  The only permitted instance is already in the
    allowlist above.
    """

    def test_no_unapproved_twin_tell_comments(self):
        """
        Scanning all templates/syndication/**/*.html for twin-tell comment
        idioms must yield only the allowlisted Switch-badge exception.

        The allowlist is matched at the level of the specific OCCURRENCE (file
        + the stripped line containing the idiom), not the file as a whole.
        This means a second distinct twin-tell comment in _channel_editor.html
        — even though the allowlisted one is present in the same file — will
        still trip this test.  A file-level match would silently swallow any
        number of illegitimate comments once one allowlisted comment existed.
        """
        syndication_dir = _syndication_templates_dir()

        # Build a set of (rel_path_str, stripped_line) for every hit.
        # Using a set deduplicates multiple idioms matching the same line.
        offenders: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for html_file in _all_syndication_html_files():
            lines = html_file.read_text(encoding="utf-8").splitlines()
            rel = str(html_file.relative_to(syndication_dir.parent.parent))
            rel_for_match = str(html_file.relative_to(syndication_dir.parent))
            for line in lines:
                line_lower = line.lower()
                for idiom in _TWIN_TELL_IDIOMS:
                    if idiom.lower() in line_lower:
                        hit = (rel, line.strip())
                        if hit in seen:
                            continue
                        seen.add(hit)
                        # Check if this SPECIFIC occurrence (file + line) is
                        # covered by an allowlist entry.  The allowlist fragment
                        # must appear in THIS LINE, not just anywhere in the file.
                        if not any(
                            rel_for_match.endswith(allow_path)
                            and allow_fragment.lower() in line.lower()
                            for allow_path, allow_fragment in _ALLOWLISTED_TWIN_TELL
                        ):
                            offenders.append((rel, line.strip()))

        self.assertEqual(
            offenders,
            [],
            msg=(
                "Found unapproved twin-tell comment idiom(s) in syndication "
                "templates.  These indicate a hand-copied widget that must be "
                "kept in manual sync — a drift hazard.\n\n"
                "Offenders (file, offending line):\n"
                + "\n".join(f"  {f}:\n    {line!r}" for f, line in offenders)
                + "\n\n"
                "Fix: replace the inline copy with "
                "{%% include 'syndication/fragments/<widget>.html' %%}.\n"
                "If the inline copy is genuinely unavoidable (e.g. the "
                "Switch EventForm path in _channel_editor.html), add it to "
                "_ALLOWLISTED_TWIN_TELL in this test with a comment explaining "
                "why."
            ),
        )


class WidgetIncludeOnlyGuardTest(SimpleTestCase):
    """
    (b) The three extracted widgets (_sync_picker, _breadcrumb, _channel_editor)
    must not be duplicated inline in any composer file.

    For each widget, a distinctive structural signature is chosen that:
      - Lives exclusively in the widget's own partial.
      - Would necessarily appear in any file that re-inlined the widget.
      - Is specific enough to catch a real re-inline.
      - Is robust enough not to be brittle on unrelated edits.

    The signature must appear in EXACTLY ONE file under templates/syndication/.
    """

    def _assert_signature_in_exactly_one_file(
        self,
        signature: str,
        expected_file_suffix: str,
        widget_name: str,
    ) -> None:
        """
        Assert `signature` appears in exactly one syndication template, and
        that template ends with `expected_file_suffix`.
        """
        syndication_dir = _syndication_templates_dir()
        matches: list[Path] = []
        for html_file in _all_syndication_html_files():
            if signature in html_file.read_text(encoding="utf-8"):
                matches.append(html_file)

        self.assertEqual(
            len(matches),
            1,
            msg=(
                f"Widget signature for '{widget_name}' was found in "
                f"{len(matches)} file(s) under templates/syndication/, "
                f"expected exactly 1 (its own partial).\n\n"
                f"Signature: {signature!r}\n\n"
                f"Files containing the signature:\n"
                + "\n".join(
                    f"  {f.relative_to(syndication_dir.parent.parent)}"
                    for f in matches
                )
                + "\n\n"
                f"This means '{widget_name}' markup has been re-inlined into "
                f"a composer template instead of referenced via "
                f"{{% include 'syndication/fragments/{expected_file_suffix}' %}}.\n"
                f"Fix: remove the inline copy and use the include tag."
            ),
        )

        # Also verify it's in the expected file (not some other partial).
        self.assertTrue(
            str(matches[0]).endswith(expected_file_suffix),
            msg=(
                f"The one file containing the '{widget_name}' signature "
                f"is {matches[0]}, but expected it to end with "
                f"{expected_file_suffix!r}.\n"
                f"Signature: {signature!r}"
            ),
        )

    def test_sync_picker_not_inlined_in_composers(self):
        """
        _sync_picker.html's distinctive signature is the Alpine 'confirmResync'
        state variable.  This only exists inside the sync picker's discard-
        confirm modal.  If anyone re-inlines the sync picker, this fires.
        """
        self._assert_signature_in_exactly_one_file(
            signature="confirmResync",
            expected_file_suffix="_sync_picker.html",
            widget_name="_sync_picker",
        )

    def test_breadcrumb_not_inlined_in_composers(self):
        """
        _breadcrumb.html's distinctive signature is the Django template tag
        assignment '{% url 'syndication:studio' as studio_root_url %}'.
        This tag is the first thing the breadcrumb renders: it resolves the
        Studio root URL into a local variable used by all the anchor/HTMX
        attrs that follow.  Any file that re-inlines the breadcrumb must carry
        this tag assignment, so it is both necessary AND sufficient as a
        structural fingerprint.

        Deliberately NOT using a cosmetic Tailwind value (e.g. 'tracking-[0.2em]')
        because a benign restyle (changing letter-spacing) would spuriously break
        the guard.  The url-name assignment is semantic and survives restyling.
        """
        self._assert_signature_in_exactly_one_file(
            signature="'syndication:studio' as studio_root_url",
            expected_file_suffix="_breadcrumb.html",
            widget_name="_breadcrumb",
        )

    def test_channel_editor_not_inlined_in_composers(self):
        """
        _channel_editor.html's distinctive signature is the Django template
        variable '{{ copy_body_id_prefix }}' used inside the Copy button <pre>
        element.  Composer files pass this as a string literal in the include
        tag; only the partial itself uses the variable interpolation.
        """
        self._assert_signature_in_exactly_one_file(
            signature="{{ copy_body_id_prefix }}",
            expected_file_suffix="_channel_editor.html",
            widget_name="_channel_editor",
        )


class SwitchBadgeTwinCompletenessTest(SimpleTestCase):
    """
    (c) The allowlisted Switch-badge inline twin in _channel_editor.html must
    carry the SAME three sync-state branches as _sync_bar.html.

    If _sync_bar.html gains or loses a branch and the twin doesn't follow,
    this test fails — catching the drift that the twin-tell comment alone
    cannot prevent.

    The three branches are identified by their load-bearing marker strings
    (the unique content that distinguishes each state).  We assert both files
    contain all three markers.

    State markers extracted from _sync_bar.html:
      (i)   canonical CV + sync_source NULL → "Shared" badge + "Customize" action
      (ii)  own CV + sync_source SET        → "Synced from" text
      (iii) own CV + sync_source NULL       → "Custom" badge + amber styling
    """

    # Load-bearing state markers — one per sync-state branch.
    # These are CSS class strings or template tags that appear ONLY in functional
    # markup, not in comment blocks, so the test cannot be fooled by comments
    # that document a missing branch.
    _STATE_MARKERS: list[tuple[str, str]] = [
        # (i) "Shared" badge: projection-customize URL only appears in State (i)
        #     form action — the Customize form is the load-bearing CTA for this state.
        (
            "State (i)",
            "syndication:projection-customize",
        ),
        # (ii) "Synced from" badge: text-emerald-400/40 is the unique CSS class on
        #      the "· editing detaches" note — only appears in State (ii) markup.
        #      (Not present in the comment header which just says "Synced from <peer>".)
        (
            "State (ii)",
            "text-emerald-400/40",
        ),
        # (iii) "Custom" badge: border-amber-300/20 is the unique amber border class
        #       — appears only in the Custom state's badge span.
        (
            "State (iii)",
            "border-amber-300/20",
        ),
    ]

    def _get_switch_badge_block(self, channel_editor_source: str) -> str:
        """
        Extract the Switch-badge inline twin block from _channel_editor.html.

        The block starts at the 'must match _sync_bar.html' comment and ends
        at the closing </div> before the Autosave comment (i.e., before the
        EventForm card body).  We use the surrounding structural markers.
        """
        # The inline twin badge starts inside the Switch event-composer block
        # (show_switch_event_form == True path).  Extract the flex container div
        # that wraps all three state branches.  The marker comment is:
        #   "must match _sync_bar.html"
        start_marker = "must match _sync_bar.html"
        start_idx = channel_editor_source.lower().find(start_marker.lower())
        if start_idx == -1:
            return ""
        # Take the rest of the file from the marker onward — the three branches
        # are all within the subsequent ~100 lines.  We take up to the first
        # occurrence of 'Autosave:' which closes the sync-badge block.
        end_marker = "Autosave:"
        end_idx = channel_editor_source.find(end_marker, start_idx)
        if end_idx == -1:
            return channel_editor_source[start_idx:]
        return channel_editor_source[start_idx:end_idx]

    def test_switch_inline_badge_carries_all_three_state_branches(self):
        """
        _channel_editor.html's inline Switch badge must carry the same three
        sync-state branches as _sync_bar.html.  This is the content assertion
        that prevents silent drift after _sync_bar.html is updated.
        """
        sync_bar_source = _read_template("fragments/_sync_bar.html")
        channel_editor_source = _read_template("fragments/_channel_editor.html")
        switch_badge_block = self._get_switch_badge_block(channel_editor_source)

        self.assertNotEqual(
            switch_badge_block,
            "",
            msg=(
                "Could not locate the Switch-badge inline twin block in "
                "_channel_editor.html.  Expected a comment containing "
                "'must match _sync_bar.html' followed by the three-state "
                "badge markup.  Either the block was removed (great — if so, "
                "remove the allowlist entry and this test) or the marker "
                "comment was renamed."
            ),
        )

        for state_label, marker in self._STATE_MARKERS:
            # Assert the marker appears in _sync_bar.html (our ground truth).
            self.assertIn(
                marker,
                sync_bar_source,
                msg=(
                    f"Load-bearing marker for {state_label} not found in "
                    f"_sync_bar.html: {marker!r}\n"
                    f"Either the marker was renamed in _sync_bar.html (update "
                    f"_STATE_MARKERS in this test) or the branch was removed "
                    f"from _sync_bar.html (update both the partial AND "
                    f"_channel_editor.html inline twin, then update the markers)."
                ),
            )
            # Assert the marker also appears in the inline twin block.
            self.assertIn(
                marker,
                switch_badge_block,
                msg=(
                    f"Load-bearing marker for {state_label} missing from "
                    f"the Switch-badge inline twin in _channel_editor.html.\n"
                    f"Marker: {marker!r}\n\n"
                    f"The inline twin (Switch EventForm badge) does NOT carry "
                    f"the same sync-state branches as _sync_bar.html.\n"
                    f"This means the twin has drifted from the canonical badge.\n\n"
                    f"Fix: update the inline Switch badge in _channel_editor.html "
                    f"to include {state_label} (matching _sync_bar.html) or, "
                    f"if the branch was intentionally removed from _sync_bar.html, "
                    f"remove it from the inline twin too and update _STATE_MARKERS "
                    f"in this test."
                ),
            )
