# QBO 02 Audit log Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every change a person makes to a firm's accounting data is recorded (who, when, what, before → after, why) and can be read back per document and per company.

**Architecture:** One append-only table `aa_audit_events` under FORCE RLS. A small service `services/accounting/audit.py` turns
before/after snapshots into a JSON-safe diff of changed fields and adds the event to the request's session, so it commits
atomically with the change it describes. Routers snapshot the row before mutating, then call `audit.record(...)`.
A firm-scoped list endpoint feeds a document "History" tab and a per-company "Audit log" view in the folder tree.

**Tech Stack:** FastAPI + SQLAlchemy async (Postgres JSONB), Next.js/React/TS.

**Spec:** `docs/superpowers/plans/2026-10-16-quickbooks-parity-plan.md` §3 "P1 — Audit log"; working rules in
`2026-10-16-qbo-parity-program.md`.

## Global Constraints

- FORCE RLS on the new table, policy keyed on `app.current_user_id` → firm, applied from `services/accounting/rls.py`.
- `enterprise_id` filter on every query, even with RLS.
- Table created by `create_all` (model registered in `models/accounting.py`); no alembic.
- Theme CSS vars only (no `dark:`); UI consistent with `components/accounting/*`; Hint on the new view.
- Acceptance: editing an amount, overriding a flag and reopening a month each produce an event with a before/after diff,
  visible to the firm only.

## Review Focus

1. Decimal / date / UUID / enum values in snapshots: `json_safe` must turn them into strings so the JSONB insert never 500s (test in Task 1).
2. A PATCH that changes nothing (same values re-sent) must not write an empty "update" event (test in Task 1: `diff` empty → `record` returns None).
3. Lists (JE lines, review_reasons) compare as whole values; a reordered/identical list is not a change unless the value differs (test in Task 1).
4. Date-range filter on a Manila calendar day: an event at 23:30 Manila on the end date is included, 00:10 next day excluded (test in Task 2: `day_bounds`).
5. Another firm's events never show: the list query always carries `enterprise_id` (test in Task 2 compiles the SQL and asserts the filter).

---

### Task 1: Model, RLS, audit service (pure diff + record)

**Files:**
- Modify: `backend/app/models/accounting.py` (add `AAAuditEvent`)
- Modify: `backend/app/services/accounting/rls.py` (append-only policies for `aa_audit_events`)
- Create: `backend/app/services/accounting/audit.py`
- Test: `backend/tests/test_accounting_audit.py`, update `backend/tests/test_accounting_rls.py`

**Interfaces — Produces:**
- `AAAuditEvent` columns: `id` UUID pk, `enterprise_id` UUID FK users CASCADE not null, `company_id` UUID FK aa_companies CASCADE not null,
  `user_id` UUID FK users SET NULL nullable, `user_label` String(255) (email snapshot), `at` timestamptz default now,
  `entity` String(30), `entity_id` String(64), `action` String(30), `before` JSONB `{}`, `after` JSONB `{}`, `reason` Text `""`.
  Indexes: `(company_id, at)`, `(entity, entity_id)`.
- `json_safe(value) -> JSON-able` (Decimal → `format(v, "f")`, date/datetime → isoformat, UUID → str, Enum → value, dict/list/tuple recursive).
- `snapshot(obj, fields: Iterable[str]) -> dict` — `{f: json_safe(getattr(obj, f))}`.
- `diff(before: dict, after: dict) -> tuple[dict, dict]` — only keys whose json-safe values differ (keys missing on one side count as `None`).
- `record(db, *, ent, company_id, user, entity, entity_id, action, before=None, after=None, reason="", always=False) -> AAAuditEvent | None`
  — diffs, returns None (writes nothing) when the diff is empty and `always` is False; otherwise `db.add(...)`. Never commits.
- Entity names (constants `ENTITIES`): `company, document, account, journal_entry, books_month, period, output, asset, employee, atc, upload`.

- [ ] Step 1: tests — `test_json_safe_handles_decimal_date_uuid_enum`, `test_diff_keeps_only_changed_fields` (gross 1000.00 → 1200.00 kept, unchanged seller dropped, list equal dropped),
  `test_record_skips_empty_update_and_adds_otherwise` (fake session with `.add` list), `test_record_always_writes_create_events`; RLS test includes `aa_audit_events` and asserts no `FOR ALL` / `FOR UPDATE` / `FOR DELETE` policy on it.
- [ ] Step 2: run, expect ImportError.
- [ ] Step 3: implement model, policies (`aa_audit_events_firm` FOR SELECT USING; `aa_audit_events_insert` FOR INSERT WITH CHECK), service.
- [ ] Step 4: pytest + ruff green; restart backend, check `\d aa_audit_events` and policies exist.
- [ ] Step 5: commit `feat: aa_audit_events table (append-only RLS) and audit.record diff helper`.

### Task 2: List API

**Files:** Create `backend/app/routers/accounting_audit.py`, `backend/app/schemas/accounting_audit.py`; modify `routers/accounting.py` (include router); test `backend/tests/test_accounting_audit.py`.

**Interfaces — Produces:**
- `day_bounds(start: date | None, end: date | None) -> tuple[datetime | None, datetime | None]` (Asia/Manila midnight of start, midnight after end).
- `events_query(ent, *, company_id=None, user_id=None, start=None, end=None, entity=None, entity_id=None)` → Select (filters always include `enterprise_id == ent`).
- `GET /api/accounting/audit-events?company_id&user_id&start&end&entity&entity_id&limit(1..200, 50)&offset(≥0)` →
  `AuditPageOut {events: [AuditEventOut], total: int, users: [AuditUserOut {id, name}]}`; `AuditEventOut {id, at, company_id, user_id, user_name, entity, entity_id, action, before, after, reason}`.
  `users` = distinct users with events in the same company/entity scope (for the filter dropdown). `user_name` = nickname or email or stored label.
- [ ] Steps: tests `test_day_bounds_cover_manila_days`, `test_events_query_always_scopes_to_firm`, `test_events_query_applies_filters`, route resolves; implement; gates; commit `feat: firm-scoped audit events list API with filters and paging`.

### Task 3: Router hooks

**Files:** modify `routers/accounting.py`, `accounting_books.py`, `accounting_annual.py`, `accounting_periods.py`, `accounting_employees.py`, `accounting_atc.py`; `schemas/accounting.py` (`DocumentPatch.reason`, `NotDuplicateIn.reason`), `schemas/accounting_books.py` (`ReopenMonthIn.reason`). Test: `backend/tests/test_accounting_audit.py` (pure helpers: `document_action(before, after)`).

Events (entity / action):
- company: create (always), update (diff of `CompanyIn` fields).
- document: update / mark_reviewed / unmark_reviewed / exclude / include / move (via `document_action`); delete; not_duplicate (reason);
  supplier-rule moves of other docs (action `supplier_rule`, reason names the source doc). Marking reviewed stores the open `review_reasons` in `after.overridden_reasons`. `DocumentPatch.reason` (≤500) → event reason.
- upload: confirm (one event per company: files assigned).
- account: create, update. journal_entry: create, update, delete.
- books_month: close, reopen (optional body `{reason}`), bind.
- period: inputs, filed, form_filed; annual same; output: generate (after `{version, form folder}`).
- asset: create, update, delete. employee: create, update, delete, import (count).
- atc: supplier (entity_id = TIN), use_suggestions, account default (entity_id = account).
- [ ] Steps: test `test_document_action_names_the_override`; implement hooks; gates; commit `feat: write audit events from every accounting mutation`.

### Task 4: Frontend

**Files:** `frontend/src/types/accounting.ts`, `lib/accounting-api.ts`, create `components/accounting/AuditTrail.tsx` (event list + diff renderer) and `components/accounting/AuditLogPanel.tsx` (filters user/date/entity, Load more); modify `DocumentPanel.tsx` (Details | History tabs; Mark reviewed / Exclude ask for an optional reason), `BookMonths.tsx` (reopen reason), `FolderTree.tsx` (`Audit log` leaf, view `audit`), `app/accounting/page.tsx`.
- [ ] Steps: implement; `npm run lint && npx tsc --noEmit`; commit `feat: document History tab and company Audit log view`.

### Task 5: Docs + final gates

CLAUDE.md gotcha (call `audit.record` from any new mutating router), progress entry, `npm run build`. Commit `docs: QBO 02 audit log progress entry and CLAUDE.md`.

## Decisions

- **Append-only at the database:** `aa_audit_events` gets SELECT and INSERT policies only; under FORCE RLS the app role cannot UPDATE or DELETE events.
- **Same transaction:** events are added to the request session and commit with the change; a failed change leaves no event.
- **Diff only changed fields;** a no-op PATCH writes nothing. Lists/dicts (JE lines, filed forms, inputs) are compared whole.
- **System side effects are not logged** (receipt relinking, duplicate re-flagging, background extraction). Supplier-rule moves of other unreviewed documents *are* logged on those documents, because a person's correction caused them. Document History shows the extraction as its first line from `created_at` (no event row).
- **company_id required, CASCADE with the company** like every other aa_* row (there is no company delete in the app). `user_id` SET NULL plus an email snapshot so the log survives removing a staff member.
- **entity_id is a string** (UUIDs, supplier TINs, account keys).
- **Who can read:** every firm member who can use AutoAccounting (same as documents). Not restricted to managers.
- **Reasons are optional** on mark reviewed, exclude, keep-both (not duplicate) and reopen month; the UI asks but never blocks.
- Not logged: upload create/retry (no firm data changes until confirm), read-only POSTs (PDF download, import preview).
