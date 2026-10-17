# QBO 04 Customer and supplier subledgers (A/R, A/P) with aging: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every client company gets a contacts master (customers / suppliers, deduped by TIN) and open-item A/R and
A/P with aging as of any date, "2307 to receive" tracking for customer CWT, links from supplier EWT to the outgoing
2307s, a customer statement PDF, aging XLSX/PDF in the quarter outputs, and Customers / Suppliers pages.

**Architecture:** A pure `compute/subledger.py` turns documents (reduced to `OpenDoc`), payments (the same `Payment`s
the books post: linked receipts, `paid_on`, matched bank lines through `apply_bank_lines`) and EWT into open items,
aging rows and 2307 items. A pure `contacts.py` plans contacts from documents (key = TIN, else normalized name) and
merges. `aa_contacts` (FORCE RLS) stores the master; default account / ATC stay in the existing supplier databank
(`aa_supplier_rules`). Async glue `books/subledger.py` loads it all; `routers/accounting_contacts.py` serves it, audits
every mutation (entity `contact`, `document` for 2307 marks). `subledger_report.py` renders XLSX (csv_safe) and PDFs
(PyMuPDF, like `bank_report_pdf.py`). Quarter generation adds `ARAging` / `APAging` ledger tabs as of quarter end.

**Tech Stack:** FastAPI + SQLAlchemy async (Postgres JSONB), PyMuPDF, openpyxl, Next.js/React/TS.

**Spec:** `docs/superpowers/plans/2026-10-16-quickbooks-parity-plan.md` §3 "P1 — Customer and supplier subledgers"
and §4 `payment_unverified`; working rules `2026-10-16-qbo-parity-program.md`.

## Global Constraints

- `aa_contacts` carries `enterprise_id`, goes in `rls._FIRM_TABLES`; every query filters `enterprise_id` / company.
- Additive column in the model **and** `schema.py`: `aa_documents.cwt_2307 JSONB NOT NULL DEFAULT '{}'`.
- Every contact edit / merge and every 2307 mark calls `audit.record` (new entity `contact`).
- Spreadsheet cells from documents go through `csv_safe`.
- Extraction stays backward compatible (new optional `due_date`, `terms_days`).
- UI: theme CSS vars, `Hint` on each new page, consistent with `components/accounting/*`.

## Q4 acceptance facts (derived from `research/2026-10-16-qbo-q4-run/*.csv`)

A/R as of 2026-12-31 = ₱467,623.82, 3 open invoices:

| Invoice | Customer | Date | Due | Total | CWT | Paid | Open | Bucket |
|---|---|---|---|---|---|---|---|---|
| 0005 | Mabuhay Builders | 10/03 | 11/02 | 118,004.32 | 0 | 0 | 118,004.32 | 31–60 |
| 0006 | Kalayaan Construction | 10/18 | 11/17 | 270,558.40 | 2,415.70 | 0 | 268,142.70 | 31–60 |
| 0008 | Mabuhay Builders | 12/10 | 01/09/27 | 131,476.80 | 0 | 50,000 (bank 12/11) | 81,476.80 | current |

A/P = ₱757,042.80, 8 open bills: Pacific 88548 160,227.20 (due 10/31, 61–90); Luzon 5838 70,089.60 (11/20, 31–60);
Metro Luzon Electric EB-7781-2525 9,464.00 (11/25, 31–60); Reyes Santos RS-1048 28,000.00 (11/15, 31–60); Guangzhou
C-2026-1119-44812 176,400.00 (11/19 no terms, 31–60); R. Villanueva C-44812-FRT 10,350.00 (11/19, 31–60); Handaan
HC-1219 38,640.00 (12/19, 1–30); Pacific 89904 263,872.00 (01/01/27, current). Every other bill is paid (cash/card
feeds, bank lines: Sta. Elena rent 32,100 net of 1,500 EWT, Petro Bayan 3,500, QuickFix 6,720, Golden 22,600) or a
cash receipt. Buckets: A/R current 81,476.80, 31–60 386,147.02; A/P current 263,872.00, 1–30 38,640.00, 31–60
294,303.60, 61–90 160,227.20.

## Review Focus

- A cash POS receipt with no `paid_on` must not show as an open bill (else A/P is flooded) — test in Task 1.
- A payment dated after the as-of date must not reduce that date's balance — test in Task 1.
- A credit memo (negative gross) for a customer shows as a negative open item, not dropped — test in Task 1.
- Merging a contact into one that is itself merged must resolve to the final target, never loop — test in Task 2.
- A bill fully paid by a bank line that names the receipt (not the invoice) is not open — covered by reusing
  `apply_bank_lines` (Task 4 glue); pure test in Task 1 via a `rcpt:` payment.

---

### Task 1: Pure open items, aging and 2307 items

**Files:** Create `backend/app/services/accounting/compute/subledger.py`; Test `backend/tests/test_aa_subledger.py`

**Interfaces — Produces:**
- `OpenDoc(id, kind: "ar"|"ap", contact_key, contact_name, contact_tin, doc_number, doc_date, total: Decimal,
  withheld: Decimal, terms: str, due_date: date|None, terms_days: int|None, payment_unverified: bool,
  period: tuple[int,int]|None)` — `withheld` = customer CWT on a sale / computed EWT on a bill.
- `counter_paid(terms: str, cash_tendered: Decimal) -> bool` — `terms == "cash"` or `cash_tendered > 0`.
- `due_date_for(doc: OpenDoc, contact_terms_days: int|None) -> date` — raw due date → raw terms days → contact terms → doc date.
- `bucket(days_past_due: int) -> str` in `BUCKETS = ("current", "1-30", "31-60", "61-90", "90+")`.
- `open_items(docs, payments: list[Payment], as_of: date, contact_terms: dict[str,int]) -> list[OpenItem]` —
  `OpenItem(doc, due, paid, open, days_past_due, bucket)`; skips docs dated after `as_of`, counter-paid docs (with
  `terms == "cash"`), and items with `open == 0`; payments with `on > as_of` are ignored; `amount None` = all.
- `aging(items, kind) -> list[AgingRow]` — `AgingRow(contact_key, name, tin, buckets: dict[str,Decimal], total, count)`, sorted by name, plus `aging_totals(rows) -> dict[str, Decimal]`.
- `cwt_items(docs, marks: dict[str, dict], received_2307s: list[Received2307]) -> list[CwtItem]` —
  `CwtItem(doc_id, contact_key, amount, period, status: "pending"|"received", document_id: str|None, source: "auto"|"user"|"")`;
  auto-received when a 2307 from the same contact sits in the same fiscal quarter; a person's mark wins.

- [ ] Step 1: Tests: `test_q4_ar_total_and_buckets`, `test_q4_ap_total_and_buckets` (fixture above, all 42 bills +
  Sta. Elena + 5 sales built from the CSVs; asserts 467,623.82 / 3 items, 757,042.80 / 8 items, bucket totals),
  `test_cash_receipt_is_not_open`, `test_unclear_terms_stay_open`, `test_payment_after_as_of_ignored`,
  `test_credit_memo_negative_item`, `test_due_date_priority`, `test_bucket_edges` (0→current, 1, 30, 31, 60, 61, 90,
  91→90+), `test_kalayaan_cwt_pending_then_received`, `test_user_mark_wins`.
- [ ] Step 2: run, expect ImportError.  Step 3: implement.  Step 4: run green.  Step 5: commit.

### Task 2: Contacts master (model, RLS, schema, pure planning + merge)

**Files:** Modify `models/accounting.py` (`AAContact`, `AADocument.cwt_2307`), `services/accounting/rls.py`,
`services/accounting/schema.py`, `services/accounting/audit.py` (entity `contact`); Create
`services/accounting/contacts.py`; Test `tests/test_aa_contacts.py`, extend `tests/test_accounting_rls.py`.

**Interfaces — Produces:**
- `AAContact`: id, enterprise_id, company_id, key (String 300, unique with company_id), role (customer|supplier|both),
  tin, registered_name, aliases JSONB list, address, vat_status (vat|non_vat|""), payment_terms_days int|None,
  manual JSONB list of field names a person set (sync never overwrites them), merged_into_id UUID|None, timestamps.
- `contact_key(tin, name) -> str` (= `party_key`).  `SeenParty(key, tin, name, address, role, vat: bool|None, on: date|None)`.
- `plan_contacts(seen: list[SeenParty], existing: list[ContactRow]) -> list[ContactChange]` — create missing keys,
  update latest name / address / role union / VAT status unless in `manual`, add name variants to aliases.
- `resolve(key, by_key) -> ContactRow|None` follows `merged_into_id` with a visited set (no loops).
- `merge_check(source, target) -> str|None` — error text for self-merge, cross-company, target merged, cycle.

- [ ] Steps: tests (`test_same_tin_merges_name_variants`, `test_name_only_contact`, `test_role_both`,
  `test_manual_fields_kept`, `test_resolve_follows_chain_without_loop`, `test_merge_check_rejects_cycle`,
  rls test asserts `aa_contacts` forced) → fail → implement → green → commit.

### Task 3: Extraction reads due date and terms days

**Files:** `services/accounting/extraction.py`, `tests/test_accounting_extraction.py`.
- `ExtractedDoc.due_date: date|None`, `terms_days: int|None` parsed from optional `"due_date"`, `"terms_days"`; old
  replies parse with None. Prompt adds both lines. Stored via `raw` as today (check pipeline keeps raw keys).
- [ ] tests → implement → green → commit.

### Task 4: Async glue + routes

**Files:** Create `services/accounting/books/subledger.py`, `routers/accounting_contacts.py`,
`schemas/accounting_contacts.py`; Modify `main.py` (router), `tests/test_accounting_router_isolation.py` if it lists
routers; Test `tests/test_aa_contacts_routes.py` (pure helpers: `open_doc_from` mapping, `outgoing_2307_links`).

**Interfaces — Produces:**
- `sync_contacts(db, company) -> list[AAContact]` (flushes).
- `load_subledger(db, company, as_of) -> Subledger(items, docs, contacts, cwt, ewt_items, payments)`.
- Routes (prefix `/api/accounting`): `GET /companies/{id}/contacts?role=customer|supplier&as_of=`,
  `GET /contacts/{contact_id}?as_of=`, `PATCH /contacts/{contact_id}` (name, role, address, vat_status,
  payment_terms_days, default_account → supplier rule gl, default_atc → supplier rule ATC), `POST /contacts/{id}/merge`
  `{into, reason}`, `PUT /documents/{doc_id}/cwt-2307` `{status, document_id?, reason?}`,
  `GET /companies/{id}/aging?kind=ar|ap&as_of=&format=json|xlsx|pdf`, `GET /contacts/{id}/statement.pdf?as_of=`.

### Task 5: Reports (XLSX + PDF) and quarter outputs

**Files:** Create `services/accounting/subledger_report.py`; Modify `compute/specs.py` (ledgers `ARAging`, `APAging`),
`routers/accounting_periods.py` (add tabs at generation as of quarter end; `GET /outputs/{id}/aging?kind=` PDF);
Test `tests/test_aa_subledger_report.py` (xlsx cells csv_safe, PDF opens and contains totals, statement PDF).

### Task 6: UI

**Files:** `types/accounting.ts`, `lib/accounting-api.ts`, `components/accounting/ContactsPanel.tsx`,
`components/accounting/ContactPanel.tsx`, `FolderTree.tsx` (Customers / Suppliers leaves, view `contacts`),
`app/accounting/page.tsx`, `components/accounting/PeriodPanel.tsx` or `OutputViewer.tsx` (aging PDF links).
Gates: lint, tsc, build.

### Task 7: Docs

Progress entry, CLAUDE.md layout / gotchas, Decisions below kept current.

## Decisions

- **Open items** are live sales (client is seller) and purchases / expenses (client is buyer) that aren't receipts
  linked to an invoice. Payroll stays out (it is not a supplier balance).
- **Settled at the counter.** A document Gemini read as `payment_terms: cash`, or with cash tendered printed, is paid
  on its own date and is never an open item. Unclear terms with no payment evidence stay **open** (conservative: a
  person sees it). The **books are unchanged**: they still leave such a document in A/P until `paid_on` / a receipt /
  a bank line pays it, so the books' A/P control can be higher than the A/P aging. Posting an implicit cash payment in
  the books is left to the owner.
- **Payments** are exactly the books' payments (linked receipts, `paid_on`, matched / confirmed bank lines through
  `apply_bank_lines`), so the subledger and the books never disagree on what paid what.
- **Withholding.** A sale's open balance is net of the customer's CWT (what cash is still due); the CWT is a separate
  "2307 to receive" item. The books keep the CWT in A/R until the 2307 document arrives, so books A/R = aging + CWT
  still pending. A bill's open balance is net of the computed EWT (the books' figure).
- **2307 to receive** auto-marks received when a 2307 from the same customer is filed in the same fiscal quarter;
  a person can mark received / pending or link a specific uploaded 2307 (stored in `aa_documents.cwt_2307`, audited).
- **Credit memos** (negative gross) appear as negative open items in their age bucket; they are not auto-applied to
  invoices.
- **Due dates:** printed due date → printed terms days → the contact's payment terms → the document date (due on
  receipt). Buckets count days past due: ≤0 current, 1–30, 31–60, 61–90, over 90.
- **Contacts** are keyed by TIN (branch ignored), else by the normalized name; same TIN = one contact, other names
  kept as aliases. A person's edits are remembered per field and never overwritten by sync. Manual merge points the
  source at the target (`merged_into_id`); documents of either key resolve to the target. Unmerge is out of scope.
- **Default account and ATC are not duplicated**: they live in the supplier databank (`aa_supplier_rules` by TIN),
  shown and edited from the contact page; a contact without a TIN can't have them.
- **Outgoing 2307 link**: a bill with EWT links to its quarter's latest generated version's 2307 ZIP
  (`/outputs/{id}/2307s`), or says "generate Qn" when none exists.
- **Acceptance fixture**: the plan has totals only, so per-document detail comes from the QBO import CSVs. QBO split
  the BOC import entry into three bills (Guangzhou FOB, BOC duty + VAT, R. Villanueva freight / brokerage); the fixture
  uses that split. How AutoAccounting splits one import document is the open landed-cost CPA question.
- **Contacts sync lazily**: the master is brought up to date from the documents whenever a contacts / aging / contact
  page is read and when a quarter is generated, not inside the extraction pipeline (no extra work or failure mode in
  the background job).
- **Merge is manager-only** (owner / manager), edits and 2307 marks are open to every firm member; all are audited
  (entity `contact`; 2307 marks as a `document` event `cwt_2307`).
- **Quarter versions** store the aging as of the quarter end in ledger tabs `ARAging` / `APAging` (one row per open
  item), so the version's aging PDF never changes after generation; the live aging (any date) is on the Customers /
  Suppliers pages.
