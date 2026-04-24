/**
 * Keyboard shortcuts for Django admin changelist review queues.
 *
 * A = approve/resolve  (clicks approve/publish bulk action)
 * R = reject           (clicks reject bulk action)
 * J = move selection to next row
 * K = move selection to previous row
 *
 * Keypresses are ignored when an input, textarea, or select has focus.
 */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    // Guard: only activate on changelist pages (they have the action form).
    var actionForm = document.getElementById('changelist-form');
    if (!actionForm) return;

    var actionSelect = actionForm.querySelector('select[name="action"]');
    var goButton = actionForm.querySelector('[type="submit"][name="index"]');
    if (!goButton) {
      // Fallback: any submit inside the form
      goButton = actionForm.querySelector('[type="submit"]');
    }

    function isInputFocused() {
      var tag = document.activeElement && document.activeElement.tagName;
      return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
    }

    function runAction(actionName) {
      if (!actionSelect || !goButton) return;
      // Check at least one row is selected; if not, select the current one first.
      var checked = actionForm.querySelectorAll('input[name="_selected_action"]:checked');
      if (checked.length === 0) return;

      // Find and select the named option.
      var found = false;
      for (var i = 0; i < actionSelect.options.length; i++) {
        if (actionSelect.options[i].value === actionName) {
          actionSelect.value = actionName;
          found = true;
          break;
        }
      }
      if (!found) return;
      goButton.click();
    }

    /**
     * Move the highlighted (selected) row to the next or previous row.
     * "Highlighted" means the row whose checkbox is checked.  When multiple
     * rows are checked we move the last one (for J) or the first one (for K).
     */
    function moveSelection(direction) {
      var rows = Array.from(actionForm.querySelectorAll('tr[class]'));
      // Filter to data rows (skip header row which has no checkbox or an id of "action-toggle")
      var dataRows = rows.filter(function (tr) {
        return tr.querySelector('input[name="_selected_action"]');
      });
      if (dataRows.length === 0) return;

      var checkedRows = dataRows.filter(function (tr) {
        return tr.querySelector('input[name="_selected_action"]').checked;
      });

      var targetRow;
      if (checkedRows.length === 0) {
        // Nothing selected — select first (J) or last (K)
        targetRow = direction === 'next' ? dataRows[0] : dataRows[dataRows.length - 1];
      } else {
        // Deselect all currently checked rows.
        checkedRows.forEach(function (tr) {
          tr.querySelector('input[name="_selected_action"]').checked = false;
        });
        var anchorRow = direction === 'next'
          ? checkedRows[checkedRows.length - 1]
          : checkedRows[0];
        var anchorIndex = dataRows.indexOf(anchorRow);
        var nextIndex = direction === 'next'
          ? Math.min(anchorIndex + 1, dataRows.length - 1)
          : Math.max(anchorIndex - 1, 0);
        targetRow = dataRows[nextIndex];
      }

      var targetCheckbox = targetRow.querySelector('input[name="_selected_action"]');
      targetCheckbox.checked = true;
      // Scroll into view if needed.
      targetRow.scrollIntoView({ block: 'nearest' });
    }

    document.addEventListener('keydown', function (e) {
      if (isInputFocused()) return;
      // Ignore modified keypresses (ctrl, cmd, alt).
      if (e.ctrlKey || e.metaKey || e.altKey) return;

      switch (e.key) {
        case 'a':
        case 'A':
          // approve: try publish_events first (EventAdmin, GDPR-correct), then resolve_approved (FlagAdmin)
          if (actionSelect) {
            var approveAction = null;
            for (var i = 0; i < actionSelect.options.length; i++) {
              var val = actionSelect.options[i].value;
              if (val === 'publish_events' || val === 'resolve_approved') {
                approveAction = val;
                break;
              }
            }
            if (approveAction) runAction(approveAction);
          }
          break;
        case 'r':
        case 'R':
          // reject: try reject_events first (EventAdmin), then resolve_rejected (FlagAdmin)
          if (actionSelect) {
            var rejectAction = null;
            for (var j = 0; j < actionSelect.options.length; j++) {
              var rval = actionSelect.options[j].value;
              if (rval === 'reject_events' || rval === 'resolve_rejected') {
                rejectAction = rval;
                break;
              }
            }
            if (rejectAction) runAction(rejectAction);
          }
          break;
        case 'j':
        case 'J':
          moveSelection('next');
          break;
        case 'k':
        case 'K':
          moveSelection('prev');
          break;
      }
    });
  });
}());
