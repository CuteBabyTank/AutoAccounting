# AutoAccounting Books of Accounts — design

Date: 2026-10-09 · Branch: AutoAccounting · Status: sections 1–2 approved in chat; 3–7 pending spec review

## Goal

Keep the client's **books of accounts** from the documents AutoAccounting already sorts, in the form the BIR
accepts as **loose-leaf books**: journals, General Ledger, trial balance and year-end financial statements,
printed month by month with continuous page numbers and bound at year end. The returns stay as they are; the
books sit beside them in the same Company → Year → Quarter flow, and at year end the annual return reads the
book figures instead of hand-typed balance-sheet inputs.

## Decisions (from the brainstorm)

- Scope is the accounting cycle steps that were missing: **journals (3), ledgers (4), year-end TB + FS (6).**
- Output is the client's **BIR loose-leaf books** (not just internal working papers).
- **Cash dates** come from a payment field on each document plus **receipt matching**: an official / collection /
  acknowledgement receipt is linked to the invoice it pays and becomes payment evidence, not a second sale or
  expense.
- **Chart of accounts:** a standard PH SME chart seeded per company; firms rename accounts and add sub-accounts;
  accounts the posting rules rely on are locked against deletion.
- **Opening trial balance + manual journal entries** are entered by people; everything else posts automatically.
- **Approach C — computed, with closed months.** Postings are recomputed from documents by a pure engine (like the
  returns). Printing a month **closes** it: its postings are frozen. A later change to a closed month never
  rewrites printed pages; it posts a correcting entry in the first open month.
- Follow the AutoAccounting flow: books are produced by the **same Generate** that produces the returns, live in
  the **same versioned workbook**, get the same pastel-yellow change highlighting, and PDFs are made on demand
  like Prepare returns.

## 1. PH standards this follows

| Rule | Source | Design |
|---|---|---|
| Journal + Ledger for every taxpayer; Cash Receipts + Cash Disbursements journals for businesses; Sales + Purchase journals for VAT-registered (some RDOs require all six) | NIRC Sec. 232–233; RMO 29-2002 | `books_kept` per company: VAT default 6 books, non-VAT default GJ/GL/CRJ/CDJ. A book not kept routes its entries to the GJ (credit transactions) or CRJ/CDJ (cash). |
| Loose-leaf: consecutively numbered pages, permanently bound within 15 days after the close of the taxable year, sworn declaration of pages and volumes, stamped at the RDO; registration via ORUS | RR 9-2009; RMC 3-2023; RMC 4-2026 | Page numbers per book continue across the fiscal year; the binder adds a cover (with a blank box for the ORUS QR stamp) and a sworn declaration; the binding deadline is shown like a return due date. |
| Bound pages can't change; errors are fixed by correcting entries | Bookkeeping practice for bound books | Closed months frozen; corrections post in the first open month with a reference to the original. |
| Since 27 Apr 2024 the **invoice** is the primary evidence of a sale of goods or services; ORs / collection / acknowledgement receipts are supplementary proof of payment | RA 11976 (EOPT); RR 7-2024 | Receipts linked to an invoice post only the cash movement. This also removes the invoice + receipt double count from the returns. |
| Preserve books and supporting records for 5 years | NIRC Sec. 235 as amended by EOPT | Closed and bound PDFs are never deleted by the app; the storage root must be long-retention before going live. |
| Books audited by an independent CPA when gross **quarterly** sales exceed ₱3,000,000 | NIRC Sec. 232 as amended by TRAIN | Year-end FS are marked "for audit" with a warning when any quarter's sales pass ₱3M. |
| FS framework: PFRS for SMEs / PFRS for Small Entities; micro entities may use the income-tax basis | SEC | Statement of Financial Position, Income Statement, Statement of Changes in Equity, Statement of Cash Flows (indirect). Notes are left to the CPA. |

Method: **accrual basis, periodic inventory** — the same basis the returns already use (purchases flow through
cost of sales; ending inventory is an input).

## 2. Phasing

One spec, three plans, each shippable on its own behind the `accounting` feature toggle:

1. **Ledger core** — chart, payments + receipt matching, posting engine, manual entries + opening TB, journals /
   GL / subsidiary ledgers / TB as workbook tabs in each quarter's Generate.
2. **Loose-leaf** — close a month, page numbering, book PDFs, correcting entries, reopen, year-end binding,
   storage layout.
3. **Year-end** — inventory adjustment, closing entries, the four financial statements, annual return reading the
   books, book-vs-return reconciliation.

## 3. Data model

New tables are `aa_*`, created by `create_all`, columns added via `startup_migrations._add_column_if_missing`,
FORCE RLS added in the existing accounting RLS stage; every session binds the user (`bind_session_user`).

### `aa_accounts` — chart of accounts per company

| Column | Type | Notes |
|---|---|---|
| `company_id`, `enterprise_id` | UUID | |
| `code` | `String(10)` | unique per company |
| `name` | `String(120)` | renamable |
| `type` | `String(12)` | `asset` `liability` `equity` `income` `cost` `expense` |
| `contra` | bool | accumulated depreciation, sales returns, drawings |
| `parent_code` | `String(10)` null | sub-accounts |
| `system_key` | `String(40)` null | unique per company; set → can't be deleted or change type |
| `active` | bool | inactive accounts can't receive new postings |

Seeded lazily the first time a company's books are used (`books/chart.py::STANDARD_CHART`). Equity names follow
`taxpayer_type` (Share capital / Owner's capital / Partners' capital).

**Standard chart** (system keys in brackets):

- **1 Assets** — 1010 Cash on hand [`cash`] · 1020 Cash in bank [`bank`] · 1030 E-wallet [`ewallet`] ·
  1100 Accounts receivable – trade [`ar`] · 1200 Merchandise / materials inventory [`inventory`] ·
  1300 Input VAT [`input_vat`] · 1320 Creditable withholding tax [`cwt`] · 1500 Property and equipment [`ppe`] ·
  1510 Accumulated depreciation [`accum_dep`, contra]
- **2 Liabilities** — 2010 Accounts payable – trade [`ap`] · 2100 Output VAT [`output_vat`] · 2110 VAT payable
  [`vat_payable`] · 2120 Percentage tax payable [`pt_payable`] · 2130 Expanded withholding tax payable
  [`ewt_payable`] · 2140 Withholding tax on compensation payable [`wtc_payable`] · 2150 Income tax payable
  [`it_payable`] · 2160 Salaries payable [`salaries_payable`] · 2170 SSS / PhilHealth / Pag-IBIG payable · 2200
  Loans payable
- **3 Equity** — 3010 capital [`capital`] · 3020 Retained earnings [`retained_earnings`] · 3030 Drawings
  [`drawings`, contra] · 3900 Income summary [`income_summary`]
- **4 Income** — 4010 Sales [`sales`] · 4020 Sales returns and discounts [`sales_returns`, contra] · 4100 Other
  income [`other_income`]
- **5 Cost of sales / services** — 5010 Purchases [`doc:purchases`] · 5020 Raw materials [`doc:raw_materials`] ·
  5030 Importations [`doc:importation`] · 5090 Cost of sales [`cogs`]
- **6 Operating expenses** — 6010 Salaries and wages [`doc:salaries`] · 6020 Rent [`doc:rent`] · 6030 Utilities
  [`doc:utilities`] · 6040 Professional fees [`doc:professional_fees`] · 6050 Office supplies
  [`doc:office_supplies`] · 6060 Representation [`doc:representation`] · 6070 Transportation and travel
  [`doc:transportation`] · 6080 Repairs and maintenance [`doc:repairs`] · 6090 Taxes and licenses
  [`doc:taxes_licenses`] · 6100 Depreciation [`depreciation`] · 6110 Percentage tax [`pt_expense`] · 6120
  Non-creditable input VAT [`input_vat_expense`] · 6900 Miscellaneous [`doc:other`]
- **7 Income tax** — 7010 Income tax expense [`income_tax`]

`capital_goods` documents post to [`ppe`]. Every document account in `extraction.EXPENSE_ACCOUNTS` has a
`doc:` key, so no document is ever unmapped.

### `aa_documents` — new columns

| Column | Type | Meaning |
|---|---|---|
| `paid_on` | Date null | fully paid / collected on this date |
| `paid_via` | `String(10)` | `cash` `bank` `ewallet` (check → `bank`) |
| `payment_ref` | `String(60)` | check / transfer / receipt no. |
| `settles_document_id` | UUID null, FK self, `ON DELETE SET NULL` | on a receipt: the invoice it pays |
| `gl_account_code` | `String(10)` | override of the mapped account (e.g. a sub-account); "" = mapped |

`aa_supplier_rules` gains `gl_account_code`, remembered the same way `ewt_atc` is.

### `aa_journal_entries` — entries people type

`company_id`, `enterprise_id`, `kind` (`opening` | `manual`), `book` (`GJ` | `CRJ` | `CDJ`), `entry_date`,
`reference` (≤ 60), `particulars` (≤ 255), `lines` JSONB `[{account_code, debit, credit, party_name, party_tin}]`,
`created_by`, `created_at`, `updated_at`, `deleted_at`. Validation: ≥ 2 lines, each line debit xor credit,
Σ debit = Σ credit, accounts active. One `opening` entry per company, dated `books_start`; AR/AP lines may carry a
party for the subsidiary ledgers. An entry dated in a closed month is rejected (post it in an open month).

### `aa_book_closes` — closed months and bound years

`company_id`, `enterprise_id`, `fiscal_year`, `month` (1–12 = fiscal month; 0 = the bound year), `output_id`
(version closed from), `postings` JSONB (frozen entries, §4.6 shape), `pages` JSONB `{book: [first, last]}`,
`files` JSONB `{book: relative path}`, `closed_by`, `closed_at`, `voided_at` (reopened). Unique on
(`company_id`, `fiscal_year`, `month`) where `voided_at IS NULL`.

### `aa_companies` — new columns

`books_kept` JSONB (list of `SJ` `PJ` `CRJ` `CDJ` `GJ` `GL`; GJ and GL always on), `books_start` Date null
(first day on the books; null = books off for this company), `books_signatory` `String(120)` and
`books_signatory_title` `String(60)` (printed on the sworn declaration).

## 4. Posting rules

Pure module `services/accounting/compute/books.py`: input = company facts, chart, document lines (with payment
fields and links), manual entries, the quarter results already computed by `build_quarter` (forms, EWT rows),
filed forms, assets, frozen months. Output = a list of **entries**:

```
Entry(id, date, book, reference, party_name, party_tin, particulars, source, lines=[Line(account, debit, credit)])
```

`id` is stable (`doc:<uuid>:sale`, `doc:<uuid>:collect:<receipt uuid>`, `tax:2550Q:2026Q3:close`,
`dep:<asset>:2026-07`, `je:<uuid>`) so versions diff and closed months compare row by row. Every entry balances;
the engine asserts it.

Amounts reuse the returns engine so books and returns agree: `split_vat_sales`, `cost_base`, `claims_input_vat`,
`compute_ewt(...).by_line()`, `depreciation_between`.

### 4.1 Documents (recognised on `doc_date`)

| Document | Book | Entry |
|---|---|---|
| Sale (client is seller) | SJ (else GJ) | Dr AR gross · Cr Sales (VATable + zero-rated + exempt; non-VAT: gross) · Cr Output VAT. Negative amounts (credit memo): Dr Sales returns, Dr Output VAT, Cr AR. |
| Purchase / expense (client is buyer) | PJ (else GJ) | Dr mapped account (`cost_base`) — PPE for capital goods · Dr Input VAT (when claimed) · Cr EWT payable (computed EWT for the line, same as the 0619-E/1601-EQ) · Cr AP (gross − EWT). |
| Payroll register | GJ | Dr Salaries gross · Cr WTC payable (withheld) · Cr Salaries payable (gross − withheld). |
| 2307 received (client is payee) | GJ | Dr CWT · Cr AR, party = payor. |
| 2307 issued (client is payor) | — | Not posted: the EWT is already in the purchase entry. |
| Receipt linked to an invoice (`settles_document_id`) | — | Not a sale/expense; it produces the payment entry below. |
| Support, unsorted, excluded, deleted | — | Not posted. |

### 4.2 Payments (recognised on the payment date)

A document is settled by **linked receipts** (each one a partial or full payment, at the receipt's gross amount on
the receipt's date) or, if it has none, by **`paid_on`** (full balance on that date). Cash account by `paid_via`.

| Settles | Book | Entry |
|---|---|---|
| Sale | CRJ | Dr Cash/Bank/E-wallet · Cr AR. With `paid_on`, amount = gross − withholding shown on the invoice; the withheld part stays in AR until the customer's 2307 arrives (§4.1). |
| Purchase / expense | CDJ | Dr AP · Cr Cash/Bank/E-wallet. With `paid_on`, amount = the AP balance (gross − EWT). |
| Payroll | CDJ | Dr Salaries payable · Cr Cash/Bank. |

Receipts that pay more than the open balance: the excess stays in AR/AP (advance) with a warning. Same-day cash
sales and purchases go through SJ/PJ **and** CRJ/CDJ, so the Sales and Purchase journals stay complete registers
that tie to the SLS/SLP.

### 4.3 Receipt matching (fixes the invoice + receipt double count)

At extraction (`classify.py`) and when documents change, a receipt (`doc_type == "receipt"` or title with
OFFICIAL / COLLECTION / ACKNOWLEDGEMENT / PAYMENT RECEIPT) is matched to an **invoice** of the same company where:
same counterparty (TIN, else normalised name), receipt date on or after the invoice date and within 180 days, and
the amount equals the invoice gross or gross − withholding (± ₱1).

- Exactly one candidate → linked automatically and shown as "Pays invoice …" in the document panel; it does not
  set `needs_review` (the link can be removed there).
- Several candidates → not linked; review reason `possible_payment` with the candidates listed in the document
  panel.
- None → the receipt stays a primary document (a pre-EOPT OR, or a cash purchase with only a receipt).

**Returns engine change:** `doc_line` / `load_periods` skip documents with `settles_document_id` set, so a receipt
that pays an invoice is no longer counted as a second sale or expense on any return.

### 4.4 Taxes, from the AutoAccounting flow

Period-end entries are built from the forms of the **version being generated** (quarter) — the same numbers on
the returns. Payment entries come from **Prepare returns → filed forms**: marking a form filed posts its payment,
dated the filed date, amount = the form's `PAYABLE_ITEM` from the filed version.

| Tax | Accrual (GJ, quarter end) | Payment (CDJ, when filed) |
|---|---|---|
| VAT (2550-Q) | Dr Output VAT (37B) · Cr Input VAT min(60B, 37B) · Cr VAT payable max(61B, 0). Dr Non-creditable input VAT · Cr Input VAT (57B). VAT withheld by customers (item 16): Dr VAT payable · Cr AR. | Dr VAT payable · Cr Bank (item 26) |
| Percentage tax (2551-Q) | Dr Percentage tax · Cr PT payable (item 14). Item 15 withheld: Dr PT payable · Cr AR. | Dr PT payable · Cr Bank (item 24) |
| Expanded withholding | Accrued line by line in §4.1 | 0619-E (item 18), 1601-EQ (item 31): Dr EWT payable · Cr Bank |
| Compensation withholding | Accrued in §4.1 | 1601-C (item 36): Dr WTC payable · Cr Bank |
| Income tax, Q1–Q3 (1701-Q / 1702-Q) | Dr Income tax expense · Cr Income tax payable for this quarter's increase in tax due year-to-date. Dr Income tax payable · Cr CWT for the quarter's CWT credited. | Dr Income tax payable · Cr Bank (item 25 / 68) |
| Income tax, annual (phase 3) | Same, for the year's tax due less Q1–Q3 accruals, and Q4 CWT | 1702-RT / 1701 / 1701-A payable, posted when filed (usually in the next fiscal year's books) |

A debit balance in Income tax payable (excess credits) is presented on the FS as an asset, "Excess income tax
credits".

### 4.5 Automatic adjustments

- **Depreciation:** monthly, dated the month end, per asset in the register: Dr Depreciation · Cr Accumulated
  depreciation (`depreciation_between`, so it equals the returns' depreciation).
- **Inventory (phase 3):** at fiscal year end — Dr Cost of sales · Cr Inventory (beginning); Dr Cost of sales ·
  Cr Purchases / Raw materials / Importations (closing them); Dr Inventory · Cr Cost of sales (ending, from the
  annual inputs or Q4). Needs the year's ending inventory; month 12 can't close without it.
- **Closing entries (phase 3):** after year-end adjustments, dated the last day of the fiscal year in the GJ:
  income and expense accounts → Income summary → Retained earnings (corporation) or capital (individual,
  partnership; Drawings also closed to capital).

### 4.6 Closed months and correcting entries

On every Generate the engine recomputes all entries, then compares each closed month's **frozen** entries with
the recomputed ones for that month (by `id`, comparing date, book, lines):

- unchanged → the frozen entry is used (pages stay identical);
- changed or removed → a **reversal** of the frozen entry plus (if changed) the **new** entry, both dated the first
  day of the earliest open month, in the GJ, particulars "Correction of <book> <reference> (<closed month>)";
- new entry dated in a closed month (late document, late payment) → posted on the first day of the earliest open
  month, particulars "Late recording of <reference> dated <date>".

Correcting entries are listed as warnings ("3 changes to closed months were posted as corrections in Nov 2026").
The **returns are unaffected**: they still follow document dates.

## 5. Outputs and storage

### 5.1 In the quarter version (phase 1)

`build_quarter` gains a books step; `QuarterResult.ledgers` gets new keyed tabs (so `diff_snapshots`, the yellow
highlighting, the clean workbook and the output viewer work unchanged): **SJ, PJ, CRJ, CDJ, GJ, GL, AR, AP, TB**.
Books tabs cover the quarter's three months; GL and subsidiary ledgers start with the balance brought forward;
TB is as of quarter end ("unadjusted" until phase 3 adds year-end entries). A company with `books_start` null
produces no books tabs.

Columns (columnar journals as kept in PH loose-leaf books):

| Book | Columns |
|---|---|
| SJ | Date · Invoice no. · Customer · TIN · Particulars · AR (Dr) · VATable sales · Zero-rated · Exempt · Output VAT (non-VAT: Date · Invoice no. · Customer · TIN · Amount) |
| PJ | Date · Supplier invoice no. · Supplier · TIN · Account · Purchases/expense (Dr) · Input VAT (Dr) · EWT payable (Cr) · AP (Cr) |
| CRJ | Date · Receipt / ref no. · Received from · TIN · Particulars · Cash (Dr) · Bank (Dr) · CWT (Dr) · AR (Cr) · Sundry account · Sundry Dr · Sundry Cr |
| CDJ | Date · Voucher / check / ref no. · Payee · TIN · Particulars · Cash (Cr) · Bank (Cr) · AP (Dr) · Input VAT (Dr) · EWT payable (Cr) · Sundry account · Sundry Dr · Sundry Cr |
| GJ | Date · JE no. · Account code · Account title · Particulars · Debit · Credit |
| GL | per account: Date · Book + page / JE no. · Particulars · Debit · Credit · Balance |
| AR / AP | per party: Date · Reference · Particulars · Debit · Credit · Balance |
| TB | Code · Account title · Debit · Credit (totals must agree) |

Entry numbers (`JE no.`, CRJ/CDJ voucher sequence) are per book per fiscal year; provisional (`GJ-2026-P012`) in
open months, final when the month closes.

Warnings added to the version: TB doesn't balance (an engine bug — blocks closing); a quarter input (non-operating income, VAT
withheld, prior-year credits) with no matching book entry; SSS / PhilHealth / Pag-IBIG employer shares aren't in
documents (once per year when `has_employees`); CWT on invoices with no 2307 received by year end.

### 5.2 Loose-leaf PDFs (phase 2)

- **Close a month** (Books panel): needs every earlier month of the fiscal year closed (or the month is
  `books_start`), no open reviews among the month's posted documents, the quarter's latest version not stale, and
  a balanced TB. It freezes the month's entries from that version, assigns final entry numbers, continues each
  book's page numbers from the previous closed month, and renders one PDF per kept book.
- **Page format:** 8.5" × 13" (long bond) landscape, PyMuPDF. Header on every page: registered name, TIN-branch,
  address, book title, "For the month of …", "Page N". Columnar journals show "Brought forward" / "Carried
  forward" column totals on each page and month totals at the end. GL prints each account with a posting in the
  month, with balance brought forward.
- **Reopen** the latest closed month (only while the year isn't bound): marks the close voided, moves its PDFs to
  `void/`, and warns that printed pages must be discarded.
- **Bind the year** (after month 12 closes): one PDF per book = cover (name, TIN, address, RDO, book, fiscal
  year, volume, blank box for the ORUS QR stamp) + all months' pages + **sworn declaration** (total pages and
  volumes, signatory and title from the company, blanks for signature and notarisation). Deadline = 15 days after
  the fiscal year end, shown on the Books node.

### 5.3 Storage layout

Under the existing accounting root (`settings.accounting_root`, same rules as uploads and outputs — local now,
long-retention bucket before go-live):

```
accounting/books/<company_id>/FY<year>/
    M01-2026-01/   SJ.pdf PJ.pdf CRJ.pdf CDJ.pdf GJ.pdf GL.pdf AR.pdf AP.pdf
    M02-2026-02/   …
    bound/         SJ-FY2026.pdf … GL-FY2026.pdf
    statements/    FS-FY2026-v3.pdf          (phase 3)
    void/<closed_at>-M07/                    (reopened months, kept for the audit trail)
```

Paths are stored relative to the root in `aa_book_closes.files` and checked with `is_stored_path_safe` before
serving. Nothing under `books/` is deleted by the app (5-year retention, NIRC 235).

### 5.4 Year-end statements (phase 3)

The annual Generate (quarter 0) adds year-end adjustments (§4.5) and produces: adjusted TB, closing entries,
post-closing TB, **Statement of Financial Position, Income Statement, Statement of Changes in Equity, Statement of
Cash Flows (indirect)** as workbook tabs (forms), plus a PDF on demand. The 1702-RT / 1701 balance-sheet inputs
and Schedule V / Part IX net income per books **default from the books** when the year's books exist (a typed
input still wins and shows a warning when it differs). Reconciliation warnings compare books with returns: sales,
output/input VAT, EWT, CWT and income tax.

## 6. UI (following the AutoAccounting flow)

- **Folder tree:** Company → Year → **Books** (new node, above the quarters) → months with status chips: Open ·
  Closed p. 12–18 · Corrections pending; the year shows Bound / "Bind by Jan 15".
- **Books panel** (`components/accounting/BooksPanel.tsx`): month grid with Close / Reopen / Download PDFs, Bind
  year, opening TB editor, manual journal entries list + editor (balanced-lines form), link to the chart.
- **Chart of accounts** (`components/accounting/ChartEditor.tsx`, from the Companies page): rename, add
  sub-account, deactivate; system accounts show a lock.
- **Document panel:** Payment section (paid on, via, ref; "Paid by" receipts list; on a receipt, "Pays invoice …"
  picker with the match candidates) and a GL account select (mapped account and its sub-accounts), remembered per
  supplier like the ATC.
- **Company form:** Books section — books start, books kept (defaults from VAT status), signatory.
- **Output viewer:** books tabs appear with the other ledger tabs; nothing new to learn.

## 7. Errors, edge cases, testing

- Every entry and the TB must balance; the engine raises on an unbalanced entry (a bug, surfaced as a 500 with an
  error-log row, never as silently wrong books).
- Fiscal year ≠ calendar: months are fiscal months (`period_for`), folders keep the calendar month in the name.
- Documents dated before `books_start` don't post (the opening TB covers them); payments of them after
  `books_start` post against the opening AR/AP balance of that party.
- Undated documents don't post (they already need review).
- Deleting a document that's in a closed month → correcting reversal (§4.6), never a page change.
- Changing the chart: renaming is safe at any time (closed PDFs keep the old name); deactivating an account with a
  balance is refused.
- **Tests (pytest, pure):** one test per posting rule; property test that random document sets always give a
  balanced TB; SJ/PJ totals tie to SLS/SLP; EWT payable accrual ties to 1601-EQ item 19; receipt matching
  (one / several / no candidates, partial payments); closed-month comparison (unchanged / changed / removed /
  late); page-number continuity across months; sworn-declaration page count; returns no longer double count a
  linked receipt.

## Out of scope

Bank reconciliation and multiple bank accounts (sub-accounts of Cash in bank can be added manually), perpetual
inventory, multi-currency, deferred tax, notes to FS, CAS registration (the app prints loose-leaf books; it isn't
registered as a CAS), SSS/PhilHealth/Pag-IBIG computation, printing the Stock and Transfer Book.
