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
