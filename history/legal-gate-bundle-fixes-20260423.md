# Fixes: legal-gate-bundle
Date: 2026-04-23
Review passes: 1 (architecture + implementation, parallel)

## Critical

- **`a_core/checks.py:26`** — `check_legal_contact` calls `get_flag("PUBLIC_READ_ENABLED")`, which issues `FeatureFlag.objects.get(...)`. Django runs system checks during `manage.py migrate` itself, so on a fresh DB (pre-migrate) the check crashes with `ProgrammingError: relation "a_core_featureflag" does not exist`, aborting the migration. This violates ADR-006 D3's promise that the deploy check is an always-safely-runnable tripwire. **Fix:** wrap the `get_flag` call in `try/except (ProgrammingError, OperationalError)` and return empty errors list in that branch (pre-migrate state is not a deploy check failure — deploy-time validation will re-run after migrations). Both reviewers found this independently.

## Important

- **`accounts/views.py:90-92`** — `art9_consent_view` reads `request.POST.get("next", "/")` and sets `response["HX-Redirect"] = next_url` without validation. Any logged-in user can POST `next=https://evil.com` and be redirected off-site (OWASP A01 open redirect). `pages/views.py:31-37` uses `url_has_allowed_host_and_scheme` for the same pattern — mirror it. **Fix:**
  ```python
  from django.utils.http import url_has_allowed_host_and_scheme
  next_url = request.POST.get("next", "/")
  if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
      next_url = "/"
  ```
- **`tests/test_art9_consent.py`** — add a test that POSTs `next=https://evil.com` to the consent endpoint and asserts the redirect is scrubbed to `/`. Same pattern for the withdrawal view if it also takes `next`.
- **`reviews/admin.py:51-55`** — `good_faith_confirmed` and `law_reference` are invisible in the Flag changelist. DSA Art. 16(2) audit trail benefits from being able to filter by `good_faith_confirmed` and see `law_reference` inline. **Fix:** add `"good_faith_confirmed"` to `list_filter`, add `"law_reference"` to `list_display`.

## Minor

- **`a_core/legal.py` vs `a_core/context_processors.py`** — `get_legal_contact()` is dead code: production reads `settings.LEGAL_CONTACT` directly; only tests call the helper. Pick ONE: (a) route the context processor through `get_legal_contact()` so the module is the single source of truth (per ADR-006 D3 wording), or (b) delete `a_core/legal.py` and call `settings.LEGAL_CONTACT` from tests directly. Prefer (a) — cheaper change, preserves the module as a future validation/normalization seam. **Fix:** update `legal_contact_processor` to call `get_legal_contact()`.
- **`docs/plans/2026-04-22-legal-gate-bundle-design.md:38`** — design says "`views.attend` and `views.interested`" but code consolidated into a single `event_attend` view dispatching on POST `status`. Update the design doc to match implementation.
- **`docs/compliance/organizer-lia.md`** — add a one-line reminder at the top: "If this balancing changes, sync `templates/pages/privacy.html` lines 58-73." Prevents drift between the doc and the inline Privacy prose.

## ADR Updates

- **ADR-006 D3 (FLEXIBLE):** no revision needed. The Critical finding is a bug in the implementation, not a reason to change the decision. After the fix, D3 holds as written.

## Discarded

- **revoke_art9_consent pre_delete signal redundant with FK cascade** (arch #7) — the belt+suspenders pattern is explicitly specified in kb-9kh.1 per ADR-006 D1 design intent. Discard as Decision Challenge; don't remove the signal.
- **Consent gate returns 200 for non-HTMX POST** (arch #8) — no non-HTMX caller exists today; HTMX-only is the established pattern in this codebase. Discard as speculative.
- **Consent revocation TOCTOU race** (arch #9) — low-probability, single-user app, acceptable risk. Discard.
- **Silent check under DEBUG=False, PUBLIC_READ_ENABLED=False** (impl #4) — per-design per ADR-006 D3 ("internal cohort runs fine with placeholders"). Not a code bug; the Readiness Check section of the design doc already specifies running `manage.py check --deploy` before the flip. Discard.
- **Migration reverse leaves note in consent_notes** (impl #5) — documented, solo maintainer, reverse only in dev. Discard.
- **Pre-existing complexity in `a_core/models.py`** (arch #3, #12) — out of scope for this bundle. Discard.
- **Byte literals in legal-page tests** (impl #6) — style, working correctly. Discard.
- **Admin XSS for `law_reference`** — verified by impl reviewer as non-issue (Django admin auto-escapes). Discard.
- **TakedownForm.clean bypass via `initial`** — verified non-exploitable. Discard.
