# Fixes: phase-0.1-schema-admin
Date: 2026-04-17
Review passes: 1 (architecture + implementation reviewers in parallel)

## Critical

- **accounts/middleware.py (new file) + a_core/settings.py MIDDLEWARE** — Missing approval-middleware placeholder. Revised design Scope-In says "Approval flag on User + middleware placeholder (field exists, middleware registered but wired to no route yet)." The field exists; the middleware does not. Add a no-op `accounts.middleware.ApprovalGateMiddleware` that is a pass-through (e.g. `def __call__(self, request): return self.get_response(request)`) and register it in `MIDDLEWARE` after `AuthenticationMiddleware`. Document (comment in the class) that exemption logic for `/admin/` and allauth routes will be wired in a later phase.

## Important

- **events/models.py (Event.status) + design doc** — `archived` is mashed into the `status` CharField, but the design explicitly calls `archived` a "separate axis, not enforced at DB level." Two mutually exclusive options, pick one: (a) **Simpler (recommended)**: update the design doc's `Event` section + revision log to accept `archived` as a terminal status alongside `cancelled`/`rejected`, drop the "separate axis" language — code already does this. (b) Drop `archived` from `status`, add `archived_at = DateTimeField(null=True, blank=True)` with a data migration + admin action. Default: option (a) — cheaper, no code churn, no user-facing impact.

- **events/models.py (Event.raw_message FK)** — Missing `related_name`. Every other FK in the schema names its reverse accessor explicitly; `raw_message = FK("ingestion.RawMessage", ...)` doesn't, so the reverse is the default `event_set`. Inconsistent. Add `related_name="extracted_events"` (or `events`) and run `makemigrations`/`migrate` — this generates a schema-free AlterField (name-only change, no downtime).

- **All model Meta classes** — No `Meta.ordering` on any model. Admin changelists will order by PK (effectively random for the maintainer's mental model). Impacts go/no-go ("<30s per event"). Add:
  - `Event.Meta.ordering = ["-start"]`
  - `EventImage.Meta.ordering = ["order", "id"]`
  - `HeartbeatLog.Meta.ordering = ["-ran_at"]`
  - `RawMessage.Meta.ordering = ["-received_at"]`
  - `SourceFailure.Meta.ordering = ["-occurred_at"]`
  - `Review.Meta.ordering = ["-created_at"]`
  - `Organizer.Meta.ordering = ["name"]`; `Venue.Meta.ordering = ["name"]`; `Tag.Meta.ordering = ["label"]`.

- **ingestion/admin.py:13-15 (RawMessageAdmin.readonly_fields)** — Computed at class-body import time. Replace with `def get_readonly_fields(self, request, obj=None): return [f.name for f in self.model._meta.concrete_fields]`. Cheaper, future-proof (0.2 extraction pipeline may want per-role unlocking), and avoids the `hasattr(f, "column")` workaround for reverse relations.

- **events/admin.py:26-35 (raw_message_preview)** — Only shows `raw_message.text`. Design spec says panel should display "linked `RawMessage.text` **and `enriched_payload`**." Extend `format_html` to render both sections. At 0.2 the enriched_payload column starts getting populated; admin needs to see it.

- **organizers/admin.py:15-18 (event_count)** — N+1 on changelist: `obj.events.count()` per row. Override `get_queryset` with `.annotate(event_count=Count("events"))` and read `obj.event_count` in the method. Sets correct pattern before scale matters.

- **organizers/admin.py:21-30 (mark_approved_record_consent)** — Hardcodes `consent_method="explicit_opt_in"` regardless of actual consent source. Two options: (a) **Minimum fix**: rename the admin action label to `"Mark approved — explicit opt-in consent"` so the admin knows exactly what they're asserting before clicking, AND keep three separate bulk actions (one per consent_method value). (b) Convert to a confirmation-form action using `admin.action` + intermediate page. Default: option (a), add three actions — cheap and explicit.

- **events/admin.py + tests** — Bulk actions (`publish_events`, `reject_events`, `archive_events`, `mark_approved_record_consent`) have zero tests. Design go/no-go depends on admin workflow usability. Add pytest-django tests that POST to `admin:events_event_changelist` with each `action=...` and assert status transitions. Include one test for `publish_events` re-publishing a previously-rejected event — verify whether overwriting `published_at` is intended (it currently overwrites; likely should only set if null — fix in same pass).

## Minor

- **All model Meta classes** — Missing `verbose_name` / `verbose_name_plural` with `gettext_lazy`. ADR-003 F6 exists precisely to avoid this retrofit tax. Add on each model: `verbose_name = _("…")`, `verbose_name_plural = _("…")`.

- **accounts/admin.py:10 (fieldset label)** — `("Approval", {...})` should be `(_("Approval"), {...})`.

- **venues/admin.py** — Inconsistent with peer admins: no `readonly_fields = ["created_at"]`. Add it.

- **tests/test_heartbeat_task.py** — Unit tests call `heartbeat()` without isolating logfire. Currently works because project `.env` sets `LOGFIRE_TOKEN=` (empty) — fragile for contributors with real tokens. Add `monkeypatch.setenv("LOGFIRE_TOKEN", "")` in each heartbeat-invoking test, OR add an autouse fixture at `tests/conftest.py` doing the same scoped to `test_heartbeat_task.py` and `tests/integration/test_phase_0_1.py::test_heartbeat_task_inserts_row`.

- **pyproject.toml (`addopts`)** — `slow`-marked test runs by default; also `makemessages` shells out and depends on `gettext` being on the host. Either add `"-m", "not slow"` to `addopts` (and add a CI step that explicitly runs `pytest -m slow`) OR add `sudo apt-get install -y gettext` to the CI test job. The first is cleaner.

## ADR Updates

- **ADR-001 D6** — Updated from "Django 5" to "Django 6" in both the section heading and the stack line. `uv.lock` pins 6.0.x; ADR text incorrectly still said 5. Added a trailing parenthetical noting the `pyproject.toml` `django>=5.2` floor remains for now and will be bumped during phase 0.3 cleanup. Applied directly to `docs/decisions/ADR-001-core-product-and-stack.md`.

- **ADR-003 F2 (Review multiplicity)** — No action taken in this pass, but noted: ADR-003 F2 does not specify whether a (author, target) pair can have multiple reviews. Deferred to 0.6/0.7 when the review surface ships. Flag: adding the constraint then will require deduplication migration.

## Discarded (with reasoning)

- **Arch F2 (a_core as INSTALLED_APP carrying pgvector migration)** — Works correctly. Rename to `core_db` is a taste call; defer. If we accrue more DB-level migrations (pg_trgm, unaccent), revisit at 0.3.

- **Arch F7 (blur_radius_m default as settings)** — Gold-plating for 0.1. Model-level `default=250` is fine; revisit at 0.4 when map-privacy surface ships and the policy knob actually matters.

- **Arch F12 (Review unique_together per author/target)** — Under-specified in ADR-003 F2, intentional deferral to 0.6/0.7. Captured above under ADR Updates.

- **Impl F7 (RawMessage.source_type vs SourceFailure.source_type max_length asymmetry)** — Both are correct Django 6 idiom. Comment would be noise.
