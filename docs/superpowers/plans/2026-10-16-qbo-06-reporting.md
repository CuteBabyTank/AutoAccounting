# QBO 06 — Reporting depth, drill-down, KPIs and the management pack

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Live reports from the books (P&L by month / comparison, Balance Sheet comparison, GL detail, transaction
list, Adjusted TB, Adjusting Journal Entries, Invalid Journal Transactions), a report viewer with drill-down to the
source document page, KPI tiles per company and a quarterly management report pack (PDF + DOCX).

**Architecture:** All figures come from the books engine's entries (`books.bank.book_entries(db, company, through)`),
reshaped by a pure module `compute/reports.py` (tested with hand-built `Entry` lists, no DB). An async glue module
`services/accounting/reports.py` loads entries once per request (through the latest date a report needs) and catches
engine failures, so a broken entry becomes an Invalid Journal Transactions row and a 409 on the other reports, never a
500. Exports: `report_export.py` (XLSX via openpyxl with `csv_safe`, PDF via PyMuPDF `_Writer` from
`subledger_report.py`) and `report_pack.py` (pack PDF + a hand-written minimal DOCX). Routes in
`routers/accounting_reports.py`. UI: a per-company **Reports** node (when books are on) → `ReportsPanel.tsx`
(viewer + drill drawer + pack), KPI tiles in `CompanyOverviewPanel.tsx`, an Adjusting checkbox in
`JournalEntryForm.tsx`.

**Tech Stack:** FastAPI + SQLAlchemy async, PyMuPDF, openpyxl, zipfile (DOCX), Next.js / React / TS.

**Spec:** `2026-10-16-quickbooks-parity-plan.md` §3 "P2 — Reporting depth and drill-down" and "P2 — Smaller wins"
(Adjusting-entry flag, Invalid Journal Transactions, Report viewer upgrades, KPI and ratio tiles, Management report
pack); catalogue §8; books design `../specs/2026-10-09-autoaccounting-books-design.md`.

## Global Constraints

- Additive column `aa_journal_entries.is_adjusting BOOLEAN NOT NULL DEFAULT false` in the model **and** `schema.py`;
  `aa_periods.pack_notes TEXT NOT NULL DEFAULT ''` and `aa_periods.pack_files JSONB NOT NULL DEFAULT '{}'`.
- Every query filters `enterprise_id` (via `company_or_404(db, scope_for(user), id)`); mutations write `audit.record`.
- Every XLSX text cell goes through `csv_safe`. Theme CSS vars only, no `dark:`. `seg()` for every id in a URL path.
- Accrual basis only (see Decisions). Pure tests in `backend/tests`, no DB, no Gemini.
- Closing entries (`close:*` and corrections of them `fix:close:*`) are left out of every report; prior fiscal years'
  income and expense are shown as "Prior years' earnings not yet closed" on the Balance Sheet instead.

## Review Focus

- A report spanning a fiscal year boundary (FYE June, Jan–Dec range) must not mix a closed year's P&L into the
  Balance Sheet's current-year earnings (`test_bs_virtual_close_fiscal_june`).
- An unbalanced or bad stored JE must not 500 every report: invalid report lists it, others answer 409 with a pointer
  (`test_invalid_manual_entries`, `test_engine_error_row`).
- % change with a zero or negative base: blank when the base is 0, sign follows (current − prior) / |prior|
  (`test_pct_change_zero_and_negative_base`).
- Divide by 1000 and non-zero rows only must not hide header/total rows or change totals' arithmetic
  (`test_shape_nonzero_keeps_totals`).
- Drill-down of a total row returns the postings of every account in it within the column window, and the sum of the
  postings equals the cell (`test_drill_sums_to_cell`).

---

### Task 1: Pure reports (`compute/reports.py`)

**Files:** Create `backend/app/services/accounting/compute/reports.py`, `backend/tests/test_aa_reports.py`.

**Produces:**
- `Column(key: str, label: str, start: date | None, end: date)`; `columns_for(start, end, by: "total"|"month"|"quarter", fye) -> list[Column]`.
- `prior_window(start, end, mode: "period"|"year") -> tuple[date, date]` (period = same number of whole months
  immediately before when start/end are month bounds, else same number of days; year = minus one year, Feb 29 → 28).
- `is_closing(e)` (ids `close:` / `fix:close:`), `entry_ref(entry_id) -> dict` → `{"kind": "document"|"bank_line"|
  "journal_entry"|"asset"|"tax"|"system", "id": str}` (`doc:<id>:*`, `pay:rcpt:<id>`, `pay:paid:<id>` → document;
  `pay:bank:<id>`, `bank:<id>` → bank_line; `je:<id>` → journal_entry; `dep:<asset>:*` → asset; `tax:*` → tax;
  `fix:<inner>:rev|new` → `entry_ref(inner)`; else system).
- Report dict shape (P&L, BS, Adjusted TB): `{"columns": [{key,label,start,end,kind}], "rows": [{key,label,level,
  kind: header|account|total, codes: [..], window: "range"|"to_date"|"before_fy", values: [Decimal|None]}]}`; column
  kind `amount|change|pct`.
- `profit_and_loss(entries, chart, columns) -> dict` — sections Revenue (sales, sales returns), Cost of sales, Gross
  profit, Operating expenses (expense excl. income tax), Operating income, Other income, Income before tax, Income tax,
  Net income; revenue and income shown positive.
- `balance_sheet(entries, chart, as_of: list[date], fye, closing_account) -> dict` — assets / liabilities / equity
  account rows (balance to date), plus "Prior years' earnings not yet closed" (P&L before the as-of's fiscal year
  start; window `before_fy`) and "Current year earnings" (window `range` from FY start); totals and a check that
  assets = liabilities + equity.
- `with_change(report, base: int, other: int) -> dict` — appends ₱ change and % change columns.
- `shape(report, *, nonzero: bool, thousands: bool) -> dict` — drops account rows whose values are all 0 (headers /
  totals stay); divides amount and change columns by 1000 (rounded to 2 places); pct untouched.
- `gl_detail(entries, chart, start, end, *, account=None, party=None) -> list[dict]` — per account with activity:
  `{code, name, opening, lines: [{entry_id, date, book, reference, party, particulars, debit, credit, balance, ref}], closing}`;
  party matches entry or line party name/TIN, case-insensitive substring.
- `transaction_list(entries, chart, start, end, *, account=None, party=None) -> list[dict]` — one row per entry by
  date: `{entry_id, date, book, source, reference, party, particulars, accounts: [codes], amount, ref}`.
- `adjusted_tb(entries, chart, as_of, fye, closing_account, adjusting_ids: set[str]) -> dict` — columns unadjusted /
  adjustments / adjusted (each as signed debit-positive balance; UI shows Dr/Cr); adjustments = entries in the as-of's
  fiscal year with id in `adjusting_ids` or source `depreciation` / `inventory`.
- `adjusting_entries(entries, chart, start, end, adjusting_ids) -> list[dict]` — same selection, with lines.
- `check_entries(entries, chart) -> list[dict]`, `check_manual(rows: list[dict], chart) -> list[dict]` — invalid
  rows `{entry_id, date, reference, problem, detail}` for: unbalanced, fewer than 2 lines, a line with both/neither
  side, account not in chart, account inactive.
- `postings(entries, chart, codes, start, end, limit=500) -> dict` — `{lines: [...gl line + account], total, truncated}`.
- `kpis(pnl_totals, balances, chart) -> dict` — gross margin, net margin, opex ratio (% of net sales; None when net
  sales 0), current ratio, quick ratio (cash + AR + CWT / current liabilities; None when 0).
- `cash_flow(entries, chart, start, end, fye, closing_account) -> list[dict]` — indirect method over a window, rows like
  `statements.build_statements` SCF; reconciles to the cash accounts.

Tests (fixture: chart from `standard_chart("corporation")`, a handful of entries across Oct–Dec 2026 and 2025): P&L by
month amounts, net income; comparison ₱/% with zero and negative base; BS balances at two dates with A = L + E; FYE
June virtual close; GL detail opening/closing and party filter; transaction list order; adjusted TB with a flagged
JE + depreciation; AJE list; check_entries/check_manual each problem; entry_ref each kind; postings sum equals cell;
shape nonzero/thousands; kpis incl. None cases; cash flow reconciles; prior_window month and day cases.

### Task 2: Adjusting flag (model, schema, API, form, audit)

**Files:** `models/accounting.py`, `services/accounting/schema.py`, `schemas/accounting_books.py`
(`JournalEntryIn.is_adjusting: bool = False`, `JournalEntryOut.is_adjusting`), `routers/accounting_books.py`
(`_ENTRY_FIELDS` + set on create/update; opening entries are never adjusting), `types/accounting.ts`,
`JournalEntryForm.tsx` (checkbox "Adjusting entry", hidden for opening), BooksPanel list chip "Adjusting".
Test: `tests/test_aa_books_schemas.py`-style schema test that `is_adjusting` defaults False and opening + adjusting is
rejected.

### Task 3: Report glue + routes + exports

**Files:** Create `services/accounting/reports.py` (load entries, chart, adjusting ids, invalid rows, company
header), `services/accounting/report_export.py` (`report_xlsx(title, header, subtitle, table) -> bytes`,
`report_pdf(...) -> bytes`, `table_for(kind, data) -> (heads, rows)`), `routers/accounting_reports.py`,
`schemas` inline (dict responses), register in `main.py`. Test `tests/test_aa_report_export.py`: XLSX cells are
`csv_safe` (a party "=cmd" comes back "'=cmd"), PDF bytes start `%PDF`, thousands scaling in table.

Routes (all `GET /api/accounting/companies/{company_id}/reports/...`):
`pnl?start&end&by&compare=none|period|year&nonzero&thousands`, `balance-sheet?as_of&compare=none|period|year`,
`gl?start&end&account&party`, `transactions?start&end&account&party`, `adjusted-tb?as_of`, `adjusting?start&end`,
`invalid`, `postings?codes&start&end`, `kpis?start&end`, `{report}/export?format=xlsx|pdf&...same params`.
`GET /api/accounting/companies/{company_id}/reports/source/{entry_id}` → document `{document_id, page}`,
journal entry lines, bank line (+ its statement document), asset, tax.

### Task 4: Management pack

**Files:** Create `services/accounting/report_pack.py` (`pack_pdf(pack) -> bytes`, `pack_docx(pack) -> bytes` with
zipfile + minimal WordprocessingML), routes `GET/PUT .../reports/pack/{year}/{quarter}` (notes, audited
`period` action `pack_notes`), `POST .../reports/pack/{year}/{quarter}` (builds, writes
`accounting/outputs/<company>/<year>Q<q>/pack-<stamp>.pdf|.docx`, stores paths in `aa_periods.pack_files`, audited
`pack_generated`), `GET .../reports/pack/{year}/{quarter}/file?format=pdf|docx`. Test
`tests/test_aa_report_pack.py`: PDF has the section titles in order (cover, contents, P&L, BS, cash flow, aging,
notes); DOCX is a valid zip with `word/document.xml` containing the notes text XML-escaped.

### Task 5: UI

**Files:** `types/accounting.ts`, `lib/accounting-api.ts` (report calls with `seg()`), `FolderTree.tsx` (Reports node
when books are on), `app/accounting/page.tsx`, create `components/accounting/ReportsPanel.tsx` (report picker,
presets This month / This quarter / This year / Last quarter / Last year / Custom, columns Total/Month/Quarter,
compare None/Prior period/Prior year, Non-zero rows, ÷1000, Export XLSX/PDF, drill drawer → postings → Open document /
JE lines / bank line + statement; GL, transactions, adjusted TB, AJE, invalid tabs; Management pack section),
`CompanyOverviewPanel.tsx` (KPI tiles + aging buckets), Hint + tour line, audit labels for `pack_notes` /
`pack_generated`.

### Task 6: Docs + gates

Progress entry, CLAUDE.md layout lines, full gates incl. `npm run build`.

## Decisions

- **Accrual only.** The engine posts accrual entries (sales on invoice date, payments separately); a cash basis would
  need re-deriving every entry from payment dates and partial payments. The viewer shows "Accrual basis" and no toggle.
- **What counts as an adjustment** in the Adjusted TB and AJE report: journal entries flagged *Adjusting* plus the
  engine's period-end adjustments (monthly depreciation, quarter-end inventory count). Tax accruals and closing
  entries are not adjustments (closing entries are left out of the Adjusted TB, which is pre-closing).
- **Closing entries are excluded from all live reports;** prior years' P&L is virtually closed on the Balance Sheet as
  its own row, so the BS balances whether or not a year's closing entries exist yet.
- **Invalid Journal Transactions** checks typed entries straight from the database (unbalanced, < 2 lines, a line with
  both or neither side, missing / inactive account) and every posted entry's accounts; if the engine itself raises
  (an unbalanced computed entry), that error is a row too. The other reports answer 409 "The books can't be built …
  see Invalid Journal Transactions" instead of 500.
- **Drill-down page:** a document opens in the existing document panel, which shows the document's own pages from
  `page_start`. Bank lines carry no page number, so a bank-line posting opens the statement document (its first page)
  with the line's date / narration / amount shown in the drawer. Tax, depreciation and system entries show their
  lines and a label; no source document.
- **DOCX without a new dependency:** the pack's DOCX is written with `zipfile` + minimal WordprocessingML (headings,
  paragraphs, tables). python-docx is not added, so no image rebuild.
- **Pack storage:** files go in the quarter's output folder (`accounting/outputs/<company>/<year>Q<q>/`), latest paths
  kept on `aa_periods.pack_files`; each Generate pack writes new uniquely-stamped files and never deletes old ones.
- **Pack cash flow** is the indirect method over the quarter (or fiscal YTD column not shown) computed live; the
  year-end SCF in the annual version remains the authoritative statement.
- **KPI quick ratio** = (cash + A/R + CWT) / current liabilities (inventory and prepaid excluded); ratios show "—"
  when the denominator is zero.
- **Compare works with a single total column.** "Compare to" (previous period / same period last year) adds ₱ and %
  change columns; with Months / Quarters columns the API answers 400 and the UI disables the Columns select.
- **Balance Sheet uses the same From / As of** as the P&L: columns by month / quarter show the balance at each column
  end; compare shows the balance at the end of the previous period / a year earlier.
- **Report window cap (security review):** every report route, including drill-down postings, refuses dates before
  2000-01-01, after the end of the next fiscal year, or spans over ten years, because the books engine's work grows
  with the date (`compute/reports.check_window`).
- **The pack's KPIs and P&L** use the quarter; a fiscal-year-to-date column sits next to the quarter in the P&L. The
  balance sheet compares the quarter end with the previous quarter end.
- **Invalid report duplicates:** a bad typed entry can show both its own problem and the engine's refusal to post it;
  both are kept so the person sees why every other report answers 409.
