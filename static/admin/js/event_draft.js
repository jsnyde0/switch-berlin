document.addEventListener('DOMContentLoaded', function() {
  const btn = document.getElementById('apply-draft-btn');
  const draftEl = document.getElementById('extracted-draft-data');
  if (!btn || !draftEl) return;

  const draft = JSON.parse(draftEl.textContent);

  btn.addEventListener('click', function() {
    // Map draft fields to Django admin form input IDs (id_<fieldname>)
    const fieldMap = {
      title: 'id_title',
      description: 'id_description',
      external_url: 'id_external_url',
      price_min_cents: 'id_price_min_cents',
      price_max_cents: 'id_price_max_cents',
      is_free: 'id_is_free',
    };
    Object.entries(fieldMap).forEach(function([draftKey, inputId]) {
      const el = document.getElementById(inputId);
      if (el && draft[draftKey] !== undefined && draft[draftKey] !== null) {
        if (el.type === 'checkbox') {
          el.checked = draft[draftKey];
        } else {
          el.value = draft[draftKey];
        }
      }
    });
    // Handle datetime fields -- Django admin uses SplitDateTimeWidget (two inputs):
    // id_start_0 = date portion (YYYY-MM-DD), id_start_1 = time portion (HH:MM)
    if (draft.start) {
      const [datePart, timePart] = draft.start.split('T');
      const startDate = document.getElementById('id_start_0');
      const startTime = document.getElementById('id_start_1');
      if (startDate) startDate.value = datePart;
      if (startTime) startTime.value = timePart ? timePart.substring(0, 5) : '';
    }
    if (draft.end) {
      const [datePart, timePart] = draft.end.split('T');
      const endDate = document.getElementById('id_end_0');
      const endTime = document.getElementById('id_end_1');
      if (endDate) endDate.value = datePart;
      if (endTime) endTime.value = timePart ? timePart.substring(0, 5) : '';
    }
  });

  // Keyboard shortcuts (only when not focused on a form input)
  document.addEventListener('keydown', function(e) {
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
    const statusSelect = document.getElementById('id_status');
    const saveBtn = document.querySelector('[name="_save"]');
    if (e.key === 'a' || e.key === 'A') {
      if (statusSelect) statusSelect.value = 'published';
      if (saveBtn) saveBtn.click();
    } else if (e.key === 'r' || e.key === 'R') {
      if (statusSelect) statusSelect.value = 'rejected';
      if (saveBtn) saveBtn.click();
    }
    // J/K next/prev navigation requires server-side cursor -- deferred to future bead
  });
});
