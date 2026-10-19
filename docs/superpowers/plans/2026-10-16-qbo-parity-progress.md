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

Code review fixes (1e65613, 4b38149): confirming a suggested bank posting (a rule's account) now refuses a locked or inactive account like a manual posting does; reclassify drops `account_locked` from documents it moves off the locked account, and its preview shows a new ATC only on purchase / expense documents (an ATC-only move skips payroll documents and JEs instead of counting them as moved). Tests 777 → 782.

Not done: reclassify doesn't move opening balances (edit them in Books), sales lines (always post to Sales) or capital
goods (asset register); existing documents already on a newly locked account are not flagged (lock blocks new
postings only); templates don't import / export as files; no batch "make inactive" across many accounts.


## 08 Opening TB import, opening open items, JE import (2026-10-18)

Plan: `2026-10-16-qbo-08-imports.md` (Decisions section there).

Shipped:
- Pure `services/accounting/importing.py`: tolerant amounts (₱, commas, parentheses, CR / DR, a formula-guard
  apostrophe), date-format detection over a column (asks only when several formats read every value, MM/DD first),
  column guesses, account matching code → leading code in the name → normalised name (abbreviations expanded:
  accts, A/R, A/P, PPE…) → closest name (difflib ≥ 0.72, alternatives listed).
- Pure `services/accounting/import_rows.py`: `build_tb` (merges split rows, skips totals, negative debit = credit,
  signed balance column, difference only to an explicitly chosen account, as-of check), `build_open_items` (AR / AP
  per row or for the sheet, terms, due dates, dates must be before the books start, duplicates in the sheet / already
  imported), `control_tie`, `build_journals` (group by journal no. or date + reference, signed amount column,
  adjusting flag, per-entry balance / line / date / account errors, closed-month entries post on the first open day);
  templates.
- `aa_opening_items` (FORCE RLS, firm policy) + pure `opening_items.py`: the items enter the books engine as
  sales / bills dated the day before the books start (no document entry, so A/R / A/P isn't doubled; only payments
  post), the subledger aging (`OpenDoc.opening`, "Opening balance" chip on the contact page), contacts, and the bank
  matcher's candidates. Payments: a matched bank line, or one recorded on the item (`paid_on` / via / account).
- Routes (`routers/accounting_imports.py`): `POST /companies/{id}/imports/{kind}/preview` and `/imports/{kind}`
  (kind `opening-tb | open-items | journal-entries`, multipart file + options JSON, stateless: the confirm re-reads
  and must be ready again), `GET /imports/templates/{kind}?format=csv|xlsx` (csv_safe, numbers kept numeric),
  `GET /companies/{id}/opening-items`, `PATCH|DELETE /opening-items/{id}`. 5 MB / 5000 rows / 500 JEs / 2000 items.
  The opening TB writes the opening JE (create or replace its lines) and re-runs `refresh_opening_flag`; JEs go
  through the JE form's checks (`accounting_books.entry_problem`, now shared). Audited: `journal_entry` `import`
  per entry, `opening_item` import / update / delete.
- UI: company → Import (books on): Opening balances / Open items / Journal entries tabs, templates, column and date
  format selects, account table (matched by code / name / closest, fix with a select, problems in red), opening
  entry / items / entries preview, difference account picker, control-tie warnings, confirm; opening items list
  with record payment and delete. Hint, tour line, audit labels.
- Live smoke on the dev stack (Bayanihan bank smoke company, restored afterwards): TB with renamed Capital → mapped
  by hand, difference to Retained earnings; December closed → warning; after reopening, a wrong opening cash set
  `opening_balance_missing` (400,000 vs 412,880.15) and the right one cleared it; open items in A/R / A/P aging
  (1–30 bucket), control-tie warnings, re-import skipped duplicates, a recorded payment posted Dr 1010 / Cr 1100;
  JE CSV with ambiguous dates (format chosen), name-matched and overridden accounts, negative lines, adjusting flag,
  audit events. UI checked in the browser.

Tests: 782 → 829 passing. Gates: pytest, ruff, lint, tsc, build all green.

Not done: receipts (OR scans) can't link to an opening item (`settles_document_id` is a document FK used in ~40
places); record the payment on the item and exclude the OR instead. No undo of a whole import batch (delete items /
JEs one by one). Opening TB over 200 non-zero accounts is refused (JE line limit).

Review fixes (2026-10-18): sheets over 5000 rows are refused instead of silently cut, cp1252 CSVs keep ñ (6a973f0);
closest-name account matches must be confirmed ("Use it" / "Use every match shown") (6ac2578); open items
already uploaded as documents are skipped, not aged twice (6ad8fd6); TB over 200 accounts / amounts past 14 digits
fail the preview, not the confirm (24febd4); JE re-import warns about entries already posted (ff20888); a decimal
comma (1.234,50) is refused, not read as 1.23 (32aebb9). Tests: 829 → 838.
A code in the chart whose row name clearly means another account ("1100 Inventory" where 1100 is A/R) is a
`conflict` to confirm, showing the code match and the best name matches (agrees when the normalised names are
equal, the fuzzy score is ≥ 0.72 or one name's words contain the other's). Tests: 838 → 839.

## 09 Global search (2026-10-18)

Plan: `2026-10-16-qbo-09-search.md` (Decisions section there).

Shipped:
- Pure `services/accounting/search.py`: amounts ("1500", "1,500.00", "₱1,500", "P1,500", "PHP 1500"; decimal commas
  refused), TINs in any format (9 or 12–14 digits → the stored 9; 3–8 digits as a TIN prefix), PH dates (ISO, MM/DD/YYYY
  with both readings when ambiguous, DD/MM when only that is valid, two-digit years, "Oct 15, 2026", "15 Oct 2026",
  "Oct 2026" / "2026-10" as the month), review reason short names ("duplicate", "EWT expected"), LIKE escaping, 2-char
  minimum, ranking (exact > prefix > word start > contains, plus TIN / amount / reason / date hits).
- `GET /api/accounting/search` (`routers/accounting_search.py`): documents (number, names, title, payment ref, TIN,
  gross / VATable / VAT / withholding amount, doc date, review reasons; deleted never, excluded with a chip), contacts
  (name, aliases, TIN; merged ones skipped), live bank lines (narration, check no., ± amount, date), journal entries
  (memo, reference, date), tasks (title, notes, due date), companies (name, aliases, TIN). Filters: types, company, date
  range, `review` (documents still needing review; empty query allowed). Every SELECT filters `enterprise_id` (and the
  joined company's). Per group: limit (5 type-ahead, 25 page, max 50), `more` flag, navigation context (document +
  page + period, contact role, bank account / month / fiscal year, JE fiscal year).
- Indexes via `schema.search_index_statements()`: btree (enterprise, amount / TIN / date) and, when pg_trgm is installed
  or can be created (guarded DO block, never fails startup), GIN trigram indexes on the searched text columns. Dev DB:
  pg_trgm 1.6 created, all 14 indexes present.
- UI: Search row in the rail (and an icon in the mobile bar) opening a palette on "/" (not while typing) or Cmd/Ctrl-K:
  250 ms debounce with abort of stale requests, grouped results with "matched …" hints, ↑↓ / Enter / Esc, Review queue
  chip, "See all results and filters" → `/accounting/search` (type chips, company, from / to, Review queue, Hint).
  Results open the document panel in its quarter folder, the contact page (new `initialContactId` on ContactsPanel),
  the bank month, the books year, the company overview, or the Tasks tab; deep links parsed by `lib/search-nav.ts`.
- Live smoke on the dev stack: API ("1500", "Bayanihan", "Dec 2026", "elena", "50%", "a" too short) and in the browser
  (palette from /admin → contact page; Ctrl-K on /accounting → document panel; results page bank filter → December
  bank month).

Tests: 839 → 899 passing. Gates: pytest, ruff, lint, tsc, build all green.

Code review fixes (951afb0, a8c254f): "(1,500)" / "₱(1,500.00)" parse as amounts; control characters are dropped from the query (a NUL reached Postgres as a 500); each trigram CREATE INDEX has its own exception block, so pg_trgm in a schema the app role can't use no longer aborts startup (verified on a scratch DB). acf55ae alone doesn't type-check (imports `types/search`, added in 57c2999). Tests 899 → 908.

Not done: journal entries are not matched by amount (lines are JSON strings); no saved searches or "thumbs" feedback;
help articles / reports aren't in the index; a task result opens the Tasks tab filtered to its company, not the task
itself (no per-task deep link yet); bank lines have no page number, so the bank month opens rather than the
statement page.

## 10 P3 extras (2026-10-19)

Plan: `2026-10-16-qbo-10-extras.md` (Decisions section there).

Shipped:
- **Recurring journal entries** (Books → Recurring entries): `aa_recurring_entries` (FORCE RLS), monthly / quarterly with
  an anchor day (31st → Feb 28 → Mar 31), next / end date, pause. Nothing posts by itself: due occurrences show as
  "N due" and post on "Post N due entries" (row lock, one JE per template per date via `aa_journal_entries.recurring_id`,
  JE checks for books start / inactive / locked accounts, audited per entry with "Recurring: <name>"). Verified live:
  two concurrent presses posted Aug 31 + Sep 30 once; the second got "Nothing is due yet".
- **Write off invoices** (Customers → Write off…, managers): filter open A/R by days past due / balance, select, pick an
  expense account (new standard `6140 Bad debts`), date in an open month, reason → one GJ entry Dr expense / Cr A/R per
  invoice, `aa_journal_entries.writeoff_items` links it to the items, the subledger treats it as payments (aging,
  statements, contact page "Written off"). Write-off JEs can't be edited; deleting reopens the invoices. Audited on the
  JE and on each document / opening item. Verified in-process with today patched to Jan 15, 2027 (closed-month,
  non-expense, unknown-item refusals; post; second write-off refused; edit refused; delete reopened ₱81,476.80).
- **Cash-flow tile** on the company Overview: books cash (cash / bank / e-wallet) at the as-of date + open A/R − open
  A/P by due date over 8 weeks with bars; overdue and later items shown apart, not counted
  (`GET /companies/{id}/cash-forecast`, window-checked; `reports.cash_balance`).
- **Customer statement types**: open item (as before), balance forward (opening line, invoices / payments / write-offs,
  running balance), transaction (period lines and totals); aging footer and 2307 note on all
  (`/contacts/{id}/statement?type=&start=`; `compute/statement.py`). Balance forward ties to the open-item total.
- **Privacy toggle** ("Hide amounts") on the Overview and Work headers: per browser, blurs `.aa-amount` (KPI and aging
  tiles, cash tile, health-check amounts).
- **Close checklists**: built-in Monthly close (7 steps) and Quarter close (5), firm templates on Team (owners /
  managers; copy a built-in), "Add a close checklist" on the Overview tasks (period end, assignee) creates one task per
  step due N days after the period end; re-applying skips steps already there. `aa_checklist_templates` (FORCE RLS),
  audited (`checklist_template`, each task `create` with the checklist as reason).

Tests: 908 → 935 passing. Gates: pytest, ruff, lint, tsc, build all green.

Skipped: QBO / Xero export (COA and contacts are trivial, but QBO's import layout can't be verified here and the GL /
transaction-list XLSX already export the entries), report email scheduling (no mail infra), prepaid schedules (not in
this row). Not done: the bank matcher can still offer a written-off invoice as a candidate; no notification for due
recurring entries; no tour slides (Hints on each new section).

10 review: fixed write-off JE lines carrying the formatted contact TIN (failed JournalLineIn, 500 on the write-off and the Books journal list), backdated write-offs of invoices paid / written off later (double A/R credit; refused), concurrent write-offs (company row lock), undo of a write-off limited to owners / managers, reclassify moving a write-off's A/R lines (blocked), the bank matcher offering written-off invoices (written-off amounts count as paid), and a recurring template's anchor day resetting to 28/30 when edited on a clamped next date (anchor_day); 940 tests pass.
