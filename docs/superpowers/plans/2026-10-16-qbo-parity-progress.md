# QBO parity progress

## 01 Review rules from the Q4 pack (2026-10-16)

Plan: `2026-10-16-qbo-01-review-rules.md` (Decisions section there).

Shipped:
- Extraction reads `cash_tendered`, `change`, `payment_terms`, `marked_paid` (optional; old replies still parse).
- New review reasons: `tendered_less_than_total`, `ewt_expected` (suggested ATC + amount in `review_notes`),
  `payment_source_unknown`, `payment_unverified` (soft: never queues or blocks close), `duplicate_invoice_number`
  (per-supplier number reuse on another date; shows in the duplicate compare view), `personal_purchase`.
- `vat_math_mismatch` alone no longer loses input VAT: books and 2550-Q claim min(printed, 12%), excess to new chart
  account `1310 VAT difference - for review` (seeded into existing charts by `ensure_chart`).
- Purchases in an owner's/officer's name (new company field "Owner / officer names", plus the books signatory) are
  excluded by default.
- Payment flags cleared by evidence via `review_rules.sync_payment_flags` (paid_on, linked receipt; bank lines next).
- New columns: `aa_documents.review_notes`, `aa_companies.owner_names`.
- UI: labels + details in the document panel, soft reasons as a neutral note, badges, guide line.
- Q4 fixtures: Luzon Paint SI 5838 duplicate, Golden ₱2,600 vs ₱2,400, Reyes Santos RS-1048, Tindahan 0048029,
  13th month ₱120,000, Pacific Steel credit terms, p38 owner's name.

Tests: 569 → 592 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: existing documents are not re-classified (old `vat_math_mismatch` docs keep input VAT disallowed);
`payment_source_unknown` for BOC freight/brokerage waits on the landed-cost CPA question; A/P aging display of
`payment_unverified` belongs to workstream 04.

Review fixes (2026-10-17): `tendered_less_than_total` compares against the total net of withholding (an OR's
"amount received" after the payer's EWT is not short); month close no longer counts reviewed documents as open
reviews (`closing.open_review_query`), so a reviewed `ewt_expected` / `payment_source_unknown` doc can't block it.

## 02 Audit log (2026-10-17)

Plan: `2026-10-16-qbo-02-audit-log.md` (Decisions section there).

Shipped:
- `aa_audit_events` (firm, company, user + email snapshot, at, entity, entity_id, label, action, before/after with
  changed fields only, reason). FORCE RLS, append-only: SELECT and INSERT policies only (checked with a NOBYPASSRLS
  role: other firms and unbound sessions see 0 rows, UPDATE/DELETE affect 0 rows).
- `services/accounting/audit.py`: `json_safe`, `snapshot`, `diff`, `record` (adds to the request session, commits with
  the change), `document_action`, label helpers.
- Events from every mutating route in `routers/accounting*.py`: company create/update, upload confirm, document edit /
  mark reviewed (with the accepted flags) / exclude / include / move / delete / keep both / supplier-rule moves, chart
  account create/update, JE create/update/delete, month close/reopen/bind, quarter and annual inputs / filed / per-form
  filed, version generated, assets, employees (incl. sheet import), ATC databank.
- Optional `reason` on document PATCH, keep-both and reopen month.
- `GET /api/accounting/audit-events` (company, user, Manila date range, entity, entity_id; limit/offset; distinct
  users for the filter).
- UI: document panel Details | History tab; per-company "Audit log" in the folder tree (person / kind / date filters,
  Load more, Hint, tour line); reason prompts on Mark reviewed, Exclude, Keep both, Reopen.

Tests: 593 → 608 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: system side effects (receipt relinking, duplicate re-flagging, background extraction) are not logged; team
and admin routers (staff/roles/billing) are outside accounting data and not logged; contact merges wait for
workstream 04 (call `audit.record`).

Review fixes (2026-10-17): `json_safe` writes Decimals with at least two places, so re-sending an amount as "1000"
against a stored 1000.00 (documents, asset cost) no longer writes a no-op "Edited" event; `schema.py` adds
`aa_audit_events.label` for databases created before that column existed. Tests 610 passing.

## 03 Bank statements as ledger evidence (2026-10-17)

Plan: `2026-10-16-qbo-03-bank.md` (Decisions section there).

Shipped:
- Extraction prompt asks statements for header + lines (`statement` object, optional, old replies still parse);
  `bank_statement.py` parses it, splits check numbers out of narrations and checks the running balance
  (`ties`, breaking line numbers).
- Tables `aa_bank_statements`, `aa_bank_lines`, `aa_bank_rules`, `aa_bank_reconciliations` (FORCE RLS, firm policy);
  columns `aa_accounts.bank_account_no`, `aa_companies.review_flags`; chart accounts `6130 Bank charges`,
  `4110 Interest income`.
- `bank_match.py` (pure): exact amount + date window (−7/+90 days) + payee / document / check number in the narration;
  one strong candidate links, several → `bank_match_ambiguous`, amount-only or narration naming someone else never
  links; partial payments when the narration names payee and number (or "partial"); suggested postings (bank charges,
  interest, ATM/withdrawal, own-account transfers); cash deposit auto-links as a transfer from cash on hand; learned
  payee / posting rules from confirmed matches; open-item amounts shared with the books (`due_amount`).
- Books: matched lines become payments to the right bank account (replacing `paid_on`; a linked receipt's payment is
  moved to the bank), postings for charges/transfers, tax matches name the account; reconciliation per account per
  month (uncleared items, brought-forward opening) with a report PDF in the month's books folder; `opening_balance_missing`
  flag; month close soft-block with override reason (audited).
- Routes: overview, month lines, confirm / reject / exclude / re-match, statement account, reconcile + file, rules.
  Every mutation writes an audit event (`bank_line`, `bank_statement`, `bank_rule`, `bank_reconciliation`).
- UI: Company → Year → Bank → account → month in the folder tree (open-line counts, Reconciled chip); BankPanel with
  tie-out, opening-balance banner, match chips, Confirm / Reject / Re-match (candidates, part payment, post to account)
  / Exclude, Reconcile, "reconciled through", report download, bank rules; account number in the chart editor;
  "Close anyway" with a reason in BookMonths.
- Acceptance: pure test from the Q4 December statement — 7/8 auto-link (rent check, fuel POS — the City permit ₱3,500
  rejected by the narration — Mabuhay ₱50,000 partial of SI 0008, cash deposit transfer, QuickFix, payroll ₱105,405.30,
  Golden), ₱150 → suggested Bank charges with Park-N-Go only an alternative; after confirming it, book bank =
  ₱330,854.85 = statement, December reconciles with zero uncleared. Also verified live on the dev stack (seeded
  company "Bayanihan Hardware (bank smoke test)": same 7/8, reconcile, PDF, close blocked then allowed).

Tests: 610 → 652 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: statements are not auto-assigned to a sole bank account with no number (a person picks it once; the number
is then remembered); a cheque written before the first statement and cleared on it shows as a difference (no
brought-forward outstanding list yet); one line paying several bills is not split automatically (link one, post the
rest by JE); A/P/A/R open-item views of bank payments belong to workstream 04.

Review fixes (2026-10-17): lines of a deleted / excluded statement document stop posting, matching, reconciling and
blocking the close (`bank.live_line()`; a delete / exclude voids its reconciliations and re-matches); both sides of a
transfer between own bank accounts post once; picking an invoice a linked receipt pays links the receipt (no second
payment); excluded lines are out of the statement balance; "Balance forward" rows (no amount) aren't stored as lines;
one shared trade word ("builders") no longer names a payee, nor does a learned rule whose name is all stop words.
Tests 652 → 660.

## 04 Customer and supplier subledgers (2026-10-17)

Plan: `2026-10-16-qbo-04-subledgers.md` (Decisions section there).

Shipped:
- `aa_contacts` (FORCE RLS, firm policy): key = TIN else normalized name, role customer / supplier / both, name
  variants as aliases, address, VAT status, payment terms (days), fields a person set are never overwritten by sync,
  `merged_into_id` for manual merges (cycle-safe). Default account / ATC stay in the supplier databank
  (`aa_supplier_rules`), edited from the contact page. Column `aa_documents.cwt_2307` for a person's 2307 mark.
- Extraction reads optional `due_date` and `terms_days`.
- Pure `compute/subledger.py`: open items (total − customer CWT / computed EWT − the books' payments up to the date;
  counter-paid cash receipts never open; credit memos as negative items), due dates (printed → terms → contact terms
  → document date), buckets current / 1–30 / 31–60 / 61–90 / 90+, aging by contact, 2307-to-receive items
  (auto-received by a same-customer 2307 in the same fiscal quarter; a person's mark wins).
- `books/subledger.py` glue reuses `document_payments` + `apply_bank_lines` (receipts, `paid_on`, matched bank lines).
- Routes (`routers/accounting_contacts.py`): contact lists with open balance / overdue / 2307 pending / unverified,
  contact detail (documents, payments, open items, 2307s to receive, outgoing 2307 links to the quarter's ZIP), edit and
  merge (audited), 2307 marks (audited), live aging JSON / XLSX (csv_safe) / PDF, customer statement PDF. Quarter
  generation stores `ARAging` / `APAging` tabs (workbook + `/outputs/{id}/aging` PDF). `payment_unverified` shows on
  the A/P aging (column, PDF marker, chip).
- UI: Company → Customers / Suppliers (as-of date, tiles, aging columns, chips, XLSX / PDF), contact page (open items,
  2307s to receive with mark / link, 2307s to issue, payments, documents opening the document panel, details form,
  merge, statement), A/R / A/P aging buttons on a version, Hints, tour line, audit labels.
- Acceptance: pure test from the Q4 pack (CSV-derived detail) — A/R ₱467,623.82 across 3 invoices (current 81,476.80,
  31–60 386,147.02), A/P ₱757,042.80 across 8 bills (current 263,872.00, 1–30 38,640.00, 31–60 294,303.60, 61–90
  160,227.20); Kalayaan 0006 ₱2,415.70 2307 pending. Live smoke on the dev stack (lists, contact page, edit, merge,
  version aging PDF, XLSX, statement).

Tests: 660 → 699 passing. Gates: pytest, ruff, lint, tsc, build all green.

Review fixes (2026-10-17): contacts sync tolerates concurrent page loads (insert ON CONFLICT DO NOTHING; the list and
aging requests used to race into a 500 on `uq_aa_contact_key`); a placeholder TIN (000-000-000, one repeated digit) keys
by name so walk-in customers don't merge into one contact (old `000000000` contacts stay with no documents); aging /
statement PDFs cut long names and document numbers at the drawn 8 pt so they don't run into the next column. 702 tests.

Not done / left to the owner: the books still keep cash-terms documents without `paid_on` in A/P (the aging treats them
as paid at the counter), and keep customer CWT in A/R until the 2307 document arrives, so books A/R / A/P control can
differ from the aging (see Decisions); credit memos are not auto-applied to invoices; no unmerge; contacts are not
synced inside the extraction pipeline (synced on read and at generation); one import document is not split into
foreign supplier / broker payables (landed-cost CPA question).

## 05 Firm work board, client health, tasks, approve-before-close, notifications (2026-10-17)

Plan: `2026-10-16-qbo-05-work-board.md` (Decisions section there).

Shipped:
- Pure `compute/work.py`: the filings a company owes in a date window (quarterly forms from `expected_forms` incl.
  payroll-driven 1601-C, the annual return, the 1604-C for employers due Jan 31 → `due_dates.alphalist_due_date`),
  derived status no documents → documents in → needs review → generated → filed (a real filing always wins over an
  override), labels ("0619-E Oct 2026", "FY Jun 2026"), filters; filings whose deadline had already passed when the
  client was added and have nothing on file are skipped.
- Pure `compute/health.py`: wrong-way asset/liability balances (negative Cash on hand), non-zero VAT-difference /
  Suspense balances, months not closed, unreconciled bank months, reconciled-through (now shared with the bank
  router), aging over 90. `compute/notifications.py`, `compute/tasks.py`.
- Tables `aa_work_items`, `aa_tasks`, `aa_firm_settings`, `aa_notification_states` (FORCE RLS, firm policy);
  `aa_audit_events.company_id` nullable for firm-level events; audit entities `work_item`, `task`, `firm_settings`.
- Routes: `/work/board` (cards + cheap per-client counts), `/work/items` (assignee / status override / board filing,
  audited), `/work/people`, `/work/settings` (owner edits), `/companies/{id}/health`, `/tasks` CRUD (audited),
  `/notifications` + read / dismiss.
- Approve-before-close: firm setting "Managers approve filing" gates the quarter, per-form, annual and board filing
  routes (403 for employees); closing a month was already manager-only. Filing buttons are disabled with a tooltip.
- UI: sidebar "Work" (Filings / Clients / Tasks tabs, client / due-window / status / assignee filters, overdue rows in
  red, assignee and status selects, Mark filed with date / Undo), client health tiles with a full check, company
  "Overview" node in the folder tree (filings due, health check, tasks; deep link `/accounting?company=<id>`),
  notification bell with unread count in the rail and mobile bar (polls every 2 min), Work settings card on Team,
  Work tour + hints, audit labels.
- Live smoke on the dev stack: board, item assign / board filing / audit events, settings, health, tasks,
  notifications read / dismiss, Work page and bell in the browser.

Tests: 702 → 728 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: no email (by design); 1604-E isn't on the board (no 1604-E support yet); the 1604-C card is completed only
by a board filing (its workbook isn't a stored version); 2307 notifications don't follow contact merges made after the
last contacts sync; no reusable task templates / recurring close checklists (workstream 10).

Review fixes (2026-10-17): editing a task re-checks only the links it changes (completing a task whose document was
deleted or whose assignee left the firm used to fail with 404 / 400); `PUT /work/items` for a filing the board doesn't
owe (e.g. 1601-C with no payroll) is rejected with 400 before anything is stored (it was committed, then 500); every
interpolated path segment in `lib/api.ts`, `lib/accounting-api.ts` and `lib/work-api.ts` goes through the shared
`seg()` (encodeURIComponent). Flagged, not fixed: the bell's 2307 count loads every seller document of the firm on each
2-minute poll, and the board loads every period / work item of the firm regardless of the window.

## 06 Reporting depth, drill-down, KPIs, management pack (2026-10-17)

Plan: `2026-10-16-qbo-06-reporting.md` (Decisions section there).

Shipped:
- Pure `compute/reports.py` over the books' entries: P&L with total / month / fiscal-quarter columns, comparison to
  the previous period or the same period last year (₱ and % change, blank % on a zero base), Balance Sheet at one or
  more dates with "Prior years' earnings not yet closed" + "Current year earnings" (balances with or without closing
  entries, any fiscal year end), GL detail (opening from the fiscal year start for P&L accounts, account / party
  filters), transaction list by date, Adjusted TB (unadjusted → adjustments → adjusted), Adjusting Journal Entries,
  invalid-transaction checks (unbalanced, < 2 lines, one-sided lines, bad amounts, missing / inactive accounts),
  drill-down postings, entry → source mapping, KPIs (gross / net margin, opex ratio, current and quick ratio), window
  cash flow (indirect); non-zero rows and ÷1000 shaping; window cap.
- `aa_journal_entries.is_adjusting` (model + schema.py), API, audit field label, "Adjusting entry" checkbox in
  `JournalEntryForm.tsx`, chip in Books.
- Routes (`routers/accounting_reports.py`): `/companies/{id}/reports/{kind}` + `/export?format=xlsx|pdf`
  (`csv_safe` cells), `/report-postings`, `/report-source` (document + page, bank line + its statement, JE, asset,
  tax / system), `/kpis` (with A/R / A/P aging buckets), `/pack/{year}/{quarter}` (notes PUT audited, POST generates
  PDF + DOCX into `accounting/outputs/<company>/<year>Q<q>/`, audited, file download path-checked). An engine
  failure is an Invalid Journal Transactions row and a 409 on the other reports, never a 500.
- Management pack: cover, contents with page numbers, P&L (quarter + fiscal YTD), Balance Sheet vs previous quarter
  end, cash flow, A/R and A/P aging, key ratios, notes; DOCX hand-written with zipfile (no python-docx, no rebuild).
- UI: company → Reports (when books are on): report chips, period presets (month / quarter / fiscal year, this and
  last, custom), columns, compare to, non-zero rows, thousands, Excel / PDF, "Accrual basis" label; every amount opens
  a drawer with the postings → source (Open the document at its page / the statement for a bank line / JE lines);
  GL and transaction rows open the source directly; management pack section (notes, Generate, PDF / Word). KPI and
  aging tiles on the company Overview. Hints, tour line, tree badge help, audit labels.
- Live smoke on the dev stack (Bayanihan bank smoke company): every report and export, BS balances (Cash in bank
  ₱330,854.85), drill to the Sta. Elena rent document and to the statement for a bank payment, a bad typed JE listed
  as invalid while the P&L answers 409, pack PDF / DOCX generated and downloaded, UI checked in the browser.

Tests: 729 → 755 passing. Gates: pytest, ruff, lint, tsc, build all green.

Security review fix: report windows (incl. drill-down postings) are capped — 2000-01-01 to the end of the next fiscal
year, ten years at most — so a far-future date can't make the books engine run unbounded.

Code review fixes (191464b, 45381f0, de10b70, af79e14): a negative % change exports as "(12.50%)" instead of "'-12.50%" in Excel; the pack DOCX strips XML-forbidden characters and gives tables a `w:tblGrid`; closed-month corrections of adjusting JEs / depreciation / inventory counts are adjustments in the Adjusted TB and AJE report; drill-down postings never silently drop accounts past 200 (up to 1000, else 400). Tests 755 → 759.

Not done: cash basis (engine is accrual-only; see Decisions); bank lines have no page number, so a bank posting opens
its statement at the statement's first page; tax / depreciation / engine entries have no source document (the drawer
says what posted them); report customisation is not saved per user; the pack is not emailed (no mail infra).

## 07 Bulk and chart tools (2026-10-18)

Plan: `2026-10-16-qbo-07-bulk-chart.md` (Decisions section there).

Shipped:
- **Reclassify** (company → Reclassify, books on): period, account, optional ATC → every posting on the account with
  whether it can move (document expense / payroll lines and typed manual JEs; tax, payment, bank, depreciation,
  opening and closing entries listed with the reason they can't) → select → move to another account and / or ATC →
  preview (closed-month items "post on <first open day>") → apply with a required reason. Changes the document's
  account override / ATC or the JE's lines and lets the engine recompute; closed months stay as printed and get
  correcting entries. One audit event per item (`reclassify`). Targets: same statement, active, not locked; documents
  only to cost / expense, never to engine-only accounts. Window checked like the reports (400). Pure
  `compute/reclassify.py`; routes in `routers/accounting_reclassify.py`.
- **Bulk resolve** in the review queue: reason chips with counts, select some / all of one reason, Mark reviewed or
  Exclude with a reason; `POST /documents/bulk-resolve` (≤200, skips and lists docs that are resolved or don't carry
  the reason), audited per document.
- **Chart**: Lock / Unlock (`aa_accounts.locked`) — JEs, document account, supplier default, bank posting and
  reclassify targets get a clear 400; newly extracted documents landing on a locked account get review reason
  `account_locked` (cleared when a person moves them off it). Inactive accounts dimmed behind "Show inactive",
  hidden (with locked ones) from every picker; deactivation also refused while a supplier default uses the account.
  `placement` on every account and a "Lands on: Profit and loss · Operating expenses" line when adding a sub-account.
- **Firm COA templates**: built-in Trading / Services / Manufacturing / Non-VAT (standard chart + industry
  sub-accounts), "Save as firm template" from a company's chart (`aa_coa_templates`, FORCE RLS), delete, and a
  "Chart of accounts" choice on Add company (default = the standard chart as before). Audited (`coa_template`).
- **Supplier defaults**: already in 04 (default account / ATC in the supplier databank, terms on the contact);
  added the lock check, the default account in the locked-account flag, and default account / terms on the Suppliers
  list.
- Live smoke on the dev stack: lock / JE refusal / audit, reclassify Dec rent 6020 → 6900 (closed month → correction
  on Jan 1, 2027) and back, invalid-JE report clean, bulk resolve (resolved / skipped / not found, audit), templates
  (built-in on create, save, firm template on create, duplicate name 409, delete); UI checked in the browser.

Tests: 759 → 777 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: reclassify doesn't move opening balances (edit them in Books), sales lines (always post to Sales) or capital
goods (asset register); existing documents already on a newly locked account are not flagged (lock blocks new
postings only); templates don't import / export as files; no batch "make inactive" across many accounts.

