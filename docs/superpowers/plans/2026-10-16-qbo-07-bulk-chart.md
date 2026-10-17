# QBO 07 — Bulk and chart tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking. (Run unattended overnight: native execution, no subagents.)

**Goal:** Reclassify postings in bulk, bulk-resolve the review queue, firm chart-of-accounts templates, lock /
inactive chart accounts with a "where it lands" preview, and supplier defaults (account + terms) feeding
classification and due dates.

**Architecture:** Pure logic in `compute/reclassify.py`, `books/chart.py` (lock, placement, templates) with tests;
thin async routers (`routers/accounting_reclassify.py`, `routers/accounting_templates.py`, additions to
`accounting.py` / `accounting_books.py` / `accounting_contacts.py`). Reclassify changes the *classification*
(`aa_documents.gl_account_code` / `ewt_atc`, typed JE line accounts); the books engine recomputes and
`book_close.apply_closes` turns changes to closed months into correcting entries automatically.

**Tech Stack:** FastAPI, SQLAlchemy async, Postgres (FORCE RLS), Next.js / TypeScript.

**Spec:** `2026-10-16-quickbooks-parity-plan.md` §3 "P2 — Bulk tools", "Lock account and make inactive",
"Supplier defaults"; catalogue §3 Chart of accounts, §10.3 Reclassify / COA templates; program rules in
`2026-10-16-qbo-parity-program.md`.

## Global Constraints

- Every aa_* query filters `enterprise_id` (or company scope); new table `aa_coa_templates` gets the firm RLS policy.
- Additive columns in the model **and** `services/accounting/schema.py`.
- Every mutation writes `audit.record` (per document / per JE / per account / per template).
- Every id in a frontend URL path goes through `seg()`; new books-loading routes validate the window with
  `compute.reports.check_window` (400 on a bad window).
- Theme CSS vars, no `dark:`; Hint on each new page; gates: pytest, ruff F,E9, lint, tsc, build.

## Review Focus

- Reclassify apply with stale / forged selection (ids not in the current candidate list, another firm's ids):
  server re-derives candidates and moves only the intersection → test `test_apply_selection_is_intersection`.
- Moving a document whose month is closed: preview says "correcting entry on <first open day>" → test
  `test_preview_marks_closed_month_items`.
- Target account inactive / locked / on the other statement (P&L ↔ BS) / a system-only account → refused with a
  message, nothing moved → tests in Task 1.
- Bulk resolve with mixed reasons or already-reviewed / deleted docs: those are skipped and reported, others
  resolved → test `test_bulk_targets_skip_other_reasons`.
- Template with a duplicated code or a parent that doesn't exist → `ValueError` on save/apply → test
  `test_template_validation`.

---

### Task 1: Pure reclassify logic

**Files:** Create `backend/app/services/accounting/compute/reclassify.py`; Test `backend/tests/test_aa_reclassify.py`.

**Interfaces — Produces:**
- `document_main_account(line: DocLine, chart: Chart) -> str | None` — the account a purchase/expense
  (`doc:<id>:buy`) or payroll (`doc:<id>:payroll`) entry debits; `None` for sales, 2307s, capital goods (asset
  register) and other categories.
- `@dataclass Candidate(key: str, kind: "document"|"journal_entry"|"other", source_id: str, entry_id: str,
  date, book, reference, party, particulars, amount: Decimal, atc: str, movable: bool, why_not: str, closed: bool)`
  — `key` = `"document:<uuid>"` / `"journal_entry:<uuid>"` / entry id.
- `candidates(entries, chart, account, start, end, docs: dict[str, tuple[str|None, str]], manual: dict[str, str],
  last_closed: date | None, atc: str = "") -> list[Candidate]` — `docs`: doc id → (current main account, effective
  ATC); `manual`: JE id → kind. Skips `close:*`, `fix:*:rev`; maps `fix:<id>:new` through to its source. amount = net
  debit − credit on `account` in the entry. Document movable iff current main account == account; JE movable iff kind
  "manual". `closed` = date ≤ last_closed. With `atc`, keeps documents whose effective ATC == atc only.
- `check_target(chart, source: str, target: str, kinds: set[str]) -> str` — "" if fine else the message: unknown /
  inactive / locked target; same as source; different statement side (P&L = income/cost/expense); documents need
  a cost/expense target; non-`doc:` system accounts other than the source's are refused.
- `preview(selected: list[Candidate], chart, to_account: str, to_atc: str, first_open: date | None) -> dict` —
  `{"items": [{key, date, amount, from, to, from_atc, to_atc, posts_on}], "total": Decimal, "count": int,
  "corrections": int}`; `posts_on` = first_open for closed items, else the item date.

- [ ] Step 1: tests with the standard chart: `test_main_account_purchase_payroll_sale_capital`,
  `test_candidates_list_document_and_je_and_other` (a `doc:x:buy` on 6020, a `je:y` on 6020, a `tax:` entry on
  6020 → other, not movable), `test_candidates_already_moved_document_not_movable`, `test_candidates_atc_filter`,
  `test_candidates_skip_closing_and_reversals`, `test_check_target_rules` (inactive, locked, 1010 for a
  document, 2010 from 6020, `input_vat_expense` refused, sub-account 6021 ok), `test_preview_marks_closed_month_items`.
- [ ] Step 2: run → fail; Step 3: implement; Step 4: pass; Step 5: commit
  `feat: pure reclassify candidates, target check and preview`.

### Task 2: Chart lock, placement, templates (pure) + column

**Files:** Modify `books/chart.py` (`ChartAccount.locked: bool = False`), `models/accounting.py`
(`AAAccount.locked`, new `AACoaTemplate`), `schema.py`, `rls.py`, `books/loader.py::_chart_account`;
Create `books/templates.py`; Tests `tests/test_aa_chart_tools.py`, update `tests/test_accounting_rls.py`.

**Interfaces — Produces:**
- `Chart.locked(code) -> bool`.
- `placement(type: str, contra: bool, system_key: str | None) -> dict` → `{"statement": "Balance sheet"|"Profit and
  loss", "section": ...}` (asset → Assets, liability → Liabilities, equity → Equity, income → Revenue / "Less: sales
  returns" when contra, cost → Cost of sales, expense → Operating expenses, `income_tax` → Income tax expense,
  contra asset → "Assets (less)"). Mirrored in TS `lib/chart-placement.ts`.
- `BUILTIN_TEMPLATES: dict[str, tuple[str, str, tuple[(code, name, parent_code)]]]` keys `trading`, `services`,
  `manufacturing`, `non_vat`: label, description, extra sub-accounts on the standard chart.
- `template_accounts(key_or_rows, taxpayer_type) -> list[ChartAccount]` — builtin key or stored rows; validates
  (unique codes / keys, known types, parent exists, code 4–10 digits) raising `ValueError`; system keys missing from
  stored rows are filled from the standard chart; the capital account takes the taxpayer type's name when the
  stored name is one of the standard capital names.
- `template_rows(accounts: list[ChartAccount]) -> list[dict]` (stored JSON).
- `AACoaTemplate(id, enterprise_id, name (unique per firm), description, accounts JSONB, created_by, created_at,
  updated_at)` table `aa_coa_templates`, firm RLS.

- [ ] Steps: tests `test_placement`, `test_builtin_templates_extend_standard`, `test_template_validation`,
  `test_template_capital_name_follows_taxpayer`, `test_rls_covers_coa_templates`; implement; commit
  `feat: account lock flag, BS/P&L placement and chart templates (pure + table)`.

### Task 3: Lock / inactive routes and enforcement

**Files:** `routers/accounting_books.py`, `schemas/accounting_books.py`, `routers/accounting.py` (document PATCH),
`routers/accounting_contacts.py` (default account), `services/accounting/pipeline.py`, `review_rules.py` / `classify.py`
(`account_locked` reason), `books/bank.py` confirm-posting check if it takes an account.

- `AccountPatch.locked: bool | None`; `AccountOut.locked`. Locking a non-`doc:` system account → 400.
  Deactivation guard also counts supplier-rule defaults; message points to Reclassify.
- Helper `locked_message(chart, codes) -> str` (pure, in `books/chart.py`): "Account 6060 Representation is locked:
  choose another account (unlock it in the chart first if this posting is right)."
- JE create/update: lines on a locked account → 400 unless the stored JE already had that account.
- Document PATCH: new `gl_account_code` locked → 400; a category/account change whose new main account is locked and
  differs from the old → 400; when the new main account is unlocked, `account_locked` is dropped from the reasons.
- Contact default account locked → 400.
- Pipeline: after `classify_document`, a document whose main account (supplier gl default applied) is locked gets
  review reason `account_locked` (hard).
- [ ] Steps: test `test_locked_message`, `test_flag_locked_documents` (pure `flag_locked(fields, chart, gl_rules)`
  in `review_rules.py`); implement; gates; commit `feat: lock chart accounts …`.

### Task 4: Reclassify routes

**Files:** Create `routers/accounting_reclassify.py` (registered like the others); Test `tests/test_aa_reclassify.py`
(route-free pure parts only).

- `GET /companies/{id}/reclassify?start&end&account&atc` → `{"candidates": [...], "accounts": [...codes with activity]}`.
- `POST /companies/{id}/reclassify/preview` body `ReclassifyIn{start, end, account, atc="", keys: list[str] ≤500,
  to_account="", to_atc="", reason=""}` → preview.
- `POST /companies/{id}/reclassify` same body, `reason` required (≥3 chars) → sets `gl_account_code` / `ewt_atc` per
  document, rewrites JE lines on `account` → `to_account`, `audit.record(entity="document"|"journal_entry",
  action="reclassify", reason=…)` each, `touch_books`, bumps the documents' `updated_at` (quarters go stale).
  Manager-only? No: any firm member (same as document edits). Returns `{moved, skipped, preview}`.
- Pure `apply_selection(cands, keys) -> (list[Candidate], list[str])` (movable ∩ keys, skipped keys) tested by
  `test_apply_selection_is_intersection`.
- Window: `check_window` → 400.
- [ ] Steps: test, implement, live smoke on the dev stack, commit `feat: reclassify routes`.

### Task 5: Bulk resolve review queue

**Files:** `routers/accounting.py`, `schemas/accounting.py`, `review_rules.py` (pure `bulk_targets`).

- `POST /documents/bulk-resolve` body `{document_ids: list[UUID] 1..200, reason_code: str, action:
  "reviewed"|"exclude", reason: str (3..500)}`. Pure `bulk_targets(docs, reason_code) -> (ok, skipped)`: open
  (needs_review, not reviewed, not excluded, not deleted) and carrying `reason_code`. Each ok doc: same effect as
  PATCH reviewed / excluded, audit per document (`mark_reviewed` with `overridden_reasons`, or `exclude`); then
  once per company `relink_receipts`, `duplicates.refresh_flags`, bank rematch when excluding. Returns
  `{resolved, skipped: [{id, why}]}`.
- [ ] Steps: test `test_bulk_targets_skip_other_reasons`; implement; commit `feat: bulk resolve review queue`.

### Task 6: COA template routes + company create

**Files:** Create `routers/accounting_templates.py`; modify `routers/accounting.py` (`create_company`),
`schemas/accounting.py` (`CompanyCreateIn(CompanyIn)` with `coa_template: str = ""`), `services/accounting/audit.py`
(`coa_template` entity).

- `GET /coa-templates` → built-ins + firm's (`{id, key, name, description, builtin, accounts_count}`);
  `GET /coa-templates/{key}` → accounts with placement; `POST /companies/{id}/coa-template {name, description}`
  (manager; 409 on duplicate name) saves the company's chart; `DELETE /coa-templates/{id}` (manager). Audited
  firm-level (`company_id` = source company for save, None for delete).
- Company create with `coa_template` ("" = lazy standard chart; builtin key; or a firm template uuid) inserts the
  accounts in the same transaction; unknown template → 400.
- [ ] Steps: implement, smoke, commit `feat: firm chart-of-accounts templates`.

### Task 7: Supplier defaults

Already shipped in 04 (contact page: default account → `aa_supplier_rules.gl_account_code`, default ATC, payment
terms → due dates). Add: default account + terms columns on the Suppliers list (`ContactRowOut.default_account`,
`payment_terms_days`), the lock check (Task 3), and the default account also used for `account_locked`. Commit with
the frontend task.

### Task 8: Frontend

- `types/accounting.ts`, `lib/accounting-api.ts` (all ids via `seg()`).
- `ChartEditor.tsx`: Lock / Unlock, inactive rows hidden behind "Show inactive", placement preview while adding,
  "Save as firm template" + list/delete of firm templates.
- Pickers (`JournalEntryForm`, `DocumentPanel`, `ContactPanel`, `BankPanel`) hide locked accounts.
- `CompanyForm.tsx`: "Chart of accounts" select on create.
- `FileGrid.tsx` review tile: reason filter chips with counts, row checkboxes, select all of a reason, Mark
  reviewed / Exclude with a reason prompt.
- New `ReclassifyPanel.tsx` + tree node "Reclassify" (books on) + view type; Hint; audit labels; reason label
  `account_locked`.
- [ ] Steps: lint, tsc, build; browser smoke; commit `feat: bulk and chart tools UI`.

### Task 9: Docs

Progress entry, CLAUDE.md, this file's Decisions kept current. Commit `docs: QBO 07 …`.

## Decisions

- **Reclassify moves classification, not postings.** Documents: `gl_account_code` (the existing per-document
  account override) and `ewt_atc`. Typed manual JEs: their line accounts. Every other posting behind an account
  (tax closes, payments, bank postings, depreciation, opening balances, the VAT / A/P side of a document) is listed
  but not movable, with the reason. Opening balances are edited in Books, not reclassified.
- **Closed months:** nothing special is written; the books engine's `apply_closes` already reverses the frozen entry
  and reposts it on the first day of the earliest open month. The preview says which items will post that way.
- **Targets:** same statement (P&L ↔ P&L, BS ↔ BS); documents only to cost / expense accounts; never to an inactive
  or locked account or to an engine-only system account (input VAT, A/P, depreciation…). Capital goods are not
  movable (they go through the asset register).
- **Reclassify does not teach the supplier rule** (a one-off bulk correction shouldn't change future documents);
  change the supplier's default account on the contact page for that.
- **Any firm member can reclassify** (same as editing a document); a reason is required and every moved item is
  audited with it.
- **Lock = no new postings by a person or by extraction.** People get a 400 with a clear message (JE lines, document
  account, supplier default, reclassify target). A newly extracted document whose account (incl. the supplier's
  default) is locked is filed with review reason `account_locked` (blocks month close until changed or reviewed),
  never rejected, so no page is lost. Existing postings stay; a JE already on the account can still be edited.
  Engine-only system accounts can't be locked (the engine posts there regardless); `doc:` accounts can.
- **Inactive** keeps the existing rule (can't deactivate while documents, JEs or a supplier default use it — move
  them with Reclassify first), so inactive accounts never carry new activity; they stay in reports and the chart
  (shown dimmed behind "Show inactive"), hidden from pickers.
- **Templates:** built-ins (trading, services, manufacturing, non-VAT) live in code as the standard chart plus
  industry sub-accounts (system accounts can't be removed: the engine needs them; non-VAT keeps the VAT accounts,
  which simply stay empty). Firm templates are rows in `aa_coa_templates` saved from a company's chart (codes,
  names, types, parents, active flags; no bank numbers). Default on create stays the lazily seeded standard chart.
  Templates apply only at creation; changing a template later doesn't touch existing companies.
- **Bulk resolve** acts only on open documents that carry the chosen reason; others are skipped and listed. A reason
  (≥3 chars) is required; each document gets its own audit event. Capped at 200 per call.
- **Supplier defaults** were already built in 04 (no duplication): added the lock check, the default account in the
  locked-account flag, and the default account / terms on the Suppliers list.
