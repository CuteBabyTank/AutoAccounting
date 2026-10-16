# AutoAccounting × QuickBooks Online: what we learned and what to build

Date: 2026-10-16. Source: a full manual run of `AutoAccounting_Test_Pack_Q4_2026.pdf` (51 pages, Bayanihan Hardware
Trading Corp., Q4 2026) through QuickBooks Online Accountant (Advanced, PHP), followed by a tour of every QBO page.
QBO company: `MFS_Test`.

## 1. What happened when the pack went through QBO

### How it was entered

| Step | QBO tool | Result |
|---|---|---|
| Chart of accounts (+21: bank, cash on hand, card, Input VAT, Input VAT–Importation, CWT, Output VAT, EWT/WTC/SSS/PhilHealth/Pag-IBIG payables, Purchases, Taxes & licenses, Representation, Transportation, 13th month, Office equipment, Suspense) | Import → Chart of Accounts (CSV) | 17/19 first pass; 2 rejected for wrong type/detail-type names, re-imported |
| 18 products/services (incl. "Output VAT 12%" and "Creditable withholding tax" pseudo-items) | Batch import products | 14/18, then 4/4 on retry ("unexpected error") |
| Sales invoices 0005, 0006, 0008 | Import invoices | Negative line (1% CWT on 0006) **rejected**, both as negative rate and as negative qty |
| CWT on 0006 | Import credit notes, then Receive Payment to apply it | Credit note was **not auto-applied**; had to apply by hand |
| Cash sales 0007, 0009 | Import sales receipts | OK |
| 42 supplier documents (bills, receipts, OR, BOC entry) | Import bills (CSV, multi-line, add suppliers) | 42/42; VAT had to be pre-split into a separate Input VAT line per document |
| Sta. Elena rent with 5% EWT (−₱1,500 line) | Bill form, by hand | Import can't take negative lines |
| Opening bank balance, Dec payroll, 13th month | Hidden `/app/dataimport/journalentries` | OK |
| Payments | Bank-data CSV import into Cash on hand (31), Credit card (3), Bank (8), then match in the bank feed | New banking UI: Match buttons did nothing; had to switch to the old UI. 2 wrong auto-suggestions (see below) |

**Final trial balance (1/1–12/31/2026) balanced at ₱2,080,401.79.** A/R ₱467,623.82 · A/P ₱757,042.80 (8 open bills) ·
Input VAT ₱85,618.41 + import VAT ₱23,520 · Output VAT ₱62,558.52 · Sales ₱521,321 · Bank ₱330,854.85 (= statement
ending balance) · Cash on hand −₱155,639.87 (no opening balance or Oct–Nov bank statement in the pack).

### Where QBO needed a human (and AutoAccounting must not)

1. **No PH VAT model.** Sales tax was off. Every document needed a hand-split Input/Output VAT line, and every
   exempt/zero-rated/non-VAT/not-addressed case was a manual decision. QBO has no idea what a VATable vs VAT-exempt
   line on a POS receipt is.
2. **No withholding model.** 1% CWT withheld by a customer, 5% EWT withheld from a lessor: neither can be imported. It
   took a credit note, a manual bill and a manual credit application. There's no 2307 tracking, no ATC, and no
   "EWT expected but not on the invoice" warning (Reyes Santos professional fees, RS-1048, went in with no EWT
   because QBO can't know).
3. **No document-level validation.** The pack's traps all went straight through QBO's importers:
   - p7 duplicate scan of Luzon Paint SI 5838: import would have taken it (I left it out by hand).
   - p16 Golden Hardware VAT ₱2,600 on ₱20,000 (should be ₱2,400): no warning. Booked ₱200 to Suspense by hand.
   - p15 QuickFix and p27 Park-N-Go are **Official Receipts**, so no input VAT: manual.
   - p21, p28, p40: buyer block blank, and p38 personal purchase in the owner's name: manual.
   - p42 sari-sari acknowledgement receipt (no TIN, no serial): manual.
   - **New trap found:** p20, p22, p25, p28 and p37 show cash tendered *less than* the total (negative change). Neither
     QBO nor the answer key flags it.
4. **Bank matching on amount alone picks wrong.** The ₱150 bank service charge auto-matched to the Park-N-Go ₱150 bill.
   The ₱3,500 Petro Bayan POS had two candidates (the fuel bill and the City of Marikina permit). QBO matches on
   amount and date window, never on payee or document number in the narration.
5. **Imports are brittle.** Type/detail-type strings must match exactly, there are random "unexpected error" rows, no
   negative lines, no way to import a JE without knowing a hidden URL, and dates need a manual format pick on every
   import.
6. **AI suggestions are shallow.** QBO auto-drafted a **13-period prepaid-expense schedule** for the ₱1,515 prepaid
   phone-load receipt (p40), which is wrong. It also offers "Autofill this bill" from a PDF/photo, a "For review" tab on
   Bills, and PDF bank statements in bank import. It does the extraction, but not the PH judgement.

Takeaway: QBO is a strong **ledger, subledger, bank and reporting shell**. AutoAccounting's moat is the PH document
judgement and the BIR outputs. The gaps worth closing are the shell features firms will expect once the books live with
us: **bank reconciliation, AR/AP subledgers with aging, audit trail, a work queue, and reporting drill-down.**

## 2. QBO page inventory vs AutoAccounting

Full feature-by-feature detail (every page, form, setting, report and the 38 workflow templates) is in
`docs/superpowers/specs/2026-10-16-quickbooks-online-feature-catalog.md`. This table is the summary.

Legend: ✅ have · 🟡 partial · ❌ missing · ⛔ skip (out of scope for a PH compliance back office)

| QBO area / page | What it does | AutoAccounting today | Call |
|---|---|---|---|
| **Your practice → Clients** (`/app/clients`) | Firm's client list, books-review status per client | Companies page + folder tree | ✅ |
| **Your practice → Work** (`/app/work`) | Projects/tasks per client with due dates, templates, assignee | Due dates computed (`compute/due_dates.py`) but no work board | ❌ → **P2** |
| **Your practice → Team** (`/app/usermgt`) | Users, roles, SSO | Team page, roles | ✅ |
| Client overview (`/app/overview`) | Company setup, banking activity (unaccepted / unreconciled / reconciled-through per account), common issues | None | ❌ → **P2** (needs P1 bank) |
| Dashboards: Get things done / Business overview / Cash flow / Planner | Shortcuts, P&L tile, expense donut, bank balances, cash-flow projection | None | 🟡 → P3 (light) |
| Tasks (`/app/taskmanager`) | To-dos linked to invoices/bills | None | ❌ → P2 (fold into Work) |
| **Transactions → Bank transactions** (`/app/banking`) | Bank feed: categorise / match / transfer / exclude, batch accept | Bank statements extracted but kept as "support, never computed" (`classify.py:60`) | ❌ → **P1** |
| App transactions | Shopify/Amazon/etc. connectors | — | ⛔ |
| **Reconcile** (`/app/reconcile`) | Tick-off against statement, reconciliation reports | None | ❌ → **P1** |
| **Rules** (`/app/olbrules`) | Bank rules: description/amount → account/payee | Supplier → ATC/account databank (`accounting_atc.py`) | 🟡 → P1 (extend to bank lines) |
| Chart of accounts | Accounts, types, detail types, import | `ChartEditor.tsx`, seeded PH chart | ✅ |
| Recurring transactions (`/app/recurring`) | Templates on a schedule | None | ❌ → P3 |
| Advanced accounting → Revenue recognition | ASC 606 schedules | — | ⛔ |
| Advanced accounting → Fixed assets | Asset register + depreciation | `assets.py`, `compute/depreciation.py`, `AssetSection.tsx` | ✅ |
| Advanced accounting → Prepaid expenses (`/app/accruals`) | Amortisation schedules (auto-drafted) | None | ❌ → P3 (reviewed suggestions only, never auto-post) |
| **Sales: All sales / Invoices / Customers** | Open/partially paid/paid status, receive payment, customer balances | Sales documents exist; no customer master, no open-balance tracking | 🟡 → **P1** |
| Estimates / Sales orders | Pre-sale docs | — | ⛔ |
| Products & services | Item list | — (line items extracted, not mastered) | ⛔ (maybe later for inventory) |
| **Expenses: Expenses / Bills / Suppliers** | Bill status (For review / Unpaid / Paid), Pay bills, Mark as paid, supplier balances | Supplier TINs in ATC databank; payment links (`books/links.py`); no open-AP view | 🟡 → **P1** |
| Purchase orders | Procurement | — | ⛔ |
| **Reports** (`/app/standardreports`) | ~80 reports: BS/P&L (comparison, by month, detail), cash flows, AR/AP aging, GL, journal, TB, adjusted TB, transaction lists, audit log, reconciliation reports, tax liability | TB, FS, GL, journals in books + XLSX | 🟡 → **P2** (aging, by-month, comparison, drill-down) |
| Custom / Management reports / KPIs / Spreadsheet sync / Performance centre | Report builder, packaged management report, KPI tiles, Excel sync | XLSX workbook per period | 🟡 → P3 (management-report PDF pack) |
| Employees (payroll) | Paycheques, payroll tax filing | Payroll register import → 1601-C, alphalist, 2316 | ✅ (compliance side) / ⛔ (running payroll) |
| Time | Timesheets, approvals, scheduling | — | ⛔ |
| Inventory | Stock levels, item receipts, valuation | COGS from periodic inventory (`compute/cogs.py`) | 🟡 / ⛔ perpetual |
| Financial planning: Forecasts / Budgets | Forecast & budget vs actual | — | ⛔ (P3 at most) |
| **Workflow automation** (`/app/workflow-templates-approvals`) | Multi-condition approval routing for bills/invoices/estimates/POs | Manager role exists; no approval step | ❌ → P2 (approve-before-close) |
| Taxes (`/app/tax/home`) | Sales-tax setup (not PH-aware) | The whole BIR engine | ✅ (our moat) |
| **Accountant tools → Reclassify transactions** | Bulk change account/class across a date range | Edit one document at a time | ❌ → **P2** |
| Accountant tools → Write off invoices | Bulk write off old A/R | — | ❌ → P3 (needs P1 A/R) |
| Accountant tools → COA templates | Reusable charts across clients | One seeded PH chart | 🟡 → P2 (firm-level templates by industry) |
| **Accountant tools → Voided/deleted → Audit log** (`/app/auditlog`) | Who changed what, when, before/after | Auth events only (`auth.audit`) | ❌ → **P1** |
| Accountant tools → Close books (Settings → Advanced) | Lock date + password | Month close / reopen / bind (`books/closing.py`) | ✅ (stronger) |
| Import data (`/app/importdata`, hidden `/app/dataimport/journalentries`) | CSV import of COA, customers, suppliers, products, invoices, credit notes, sales receipts, bills, JEs, bank | Document upload only; JE form; employee import | 🟡 → P2 (opening TB + JE CSV import) |
| + New menu | ~30 transaction types | Upload + JE form | ✅ by design (documents in, not forms) |
| Bill "Autofill" / Bills "For review" | AI extract from PDF/photo into a draft bill | Core pipeline (`pipeline.py`, `extraction.py`, review reasons) | ✅ (stronger: PH rules + review reasons) |

## 3. Roadmap

Ordered by how much a firm would miss it once AutoAccounting is the system of record. Each item names the modules it
touches and the acceptance check. P1 items assume the books design (`2026-10-09-autoaccounting-books-design.md`) is
in place.

### P1 — Bank statements become ledger evidence, with reconciliation

**Why:** in the QBO run, the bank statement was the only thing that proved payments. Today we extract statements and
discard them (`classify.py:60`).

- **Parse statement lines.** Extend `extraction.py` for `kind == "statement"` to return `{date, description, debit,
  credit, balance, ref/check_no}` rows plus opening/closing balance. Validate that the running balance ties. Store them
  in a new `aa_bank_lines` table (company, account, statement doc, line no, date, amount, narration, check_no,
  match_status, matched_ref). Add `schema.py` columns and RLS like the other aa_* tables.
- **Bank accounts on the company.** `aa_accounts` of subtype `bank` carry the account number (match on the last 4
  digits from the statement header).
- **Matcher (`services/accounting/bank_match.py`, pure).** Candidates are open documents and payments for the company.
  Score = amount exact (required) + date window + **payee/number tokens in the narration** (e.g. "Check #000819 –
  Golden Hardware" → supplier Golden Hardware, doc 8098). Exactly one high-confidence candidate: link it. Several: review
  reason `bank_match_ambiguous` with the candidates (this fixes QBO's ₱3,500 Petro Bayan vs City permit). Narration
  disagrees with the payee: never auto-link (this fixes QBO's ₱150 service charge → parking bill).
- **Partial payments.** Allow one bank line to settle part of an invoice (Mabuhay ₱50,000 against SI 0008 ₱131,476.80).
  Open balances live in P1 A/R below.
- **Unmatched lines** become suggested postings: bank charges, interest, transfers. "Cash deposit – store sales" pairs
  with a cash-on-hand withdrawal. Payroll credit pairs with the payroll register's net pay. Anything else waits for
  review (`bank_line_unmatched`).
- **Bank rules.** Generalise the ATC databank to "narration contains X → account Y / payee Z". Learn them from
  confirmed matches.
- **Reconcile.** Per account per month: statement closing balance vs book balance, list of uncleared items, and a
  reconciliation report PDF in the month's books folder. A month can't be closed (`books/closing.py`) while a
  statement exists and is unreconciled (soft block with an override reason).
- **Opening balance prompt.** If the first statement's opening balance ≠ book balance on that date, raise
  `opening_balance_missing` on the company. QBO silently let Cash on hand go to −₱155,639.87.
- **UI.** Folder tree: Company → Year → Bank → account → month. Panel shows lines with match chips like the document
  panel, plus a Reconcile button and a "reconciled through" date.

**Acceptance:** the Q4 pack's December statement auto-links 7/8 lines (rent check, fuel POS, QuickFix, Golden,
payroll, Mabuhay partial, cash deposit as a transfer) and suggests Bank charges for the ₱150 line. Book bank balance =
₱330,854.85 = statement ending balance. December reconciles with zero uncleared items.

### P1 — Customer and supplier subledgers (A/R, A/P) with aging

**Why:** QBO's Customers/Suppliers/Invoices/Bills screens are where staff answer "who owes what". We have the
documents but no balances.

- **Contacts master** `aa_contacts` (company, role customer|supplier|both, TIN, registered name, address, VAT status,
  default account, default ATC). Auto-created and deduped by TIN from extracted documents. Name variants are merged by
  TIN. Feeds the 2307 issuer/payee data and the SLSP.
- **Open items.** Each credit sale/purchase has an open balance = total − linked payments − credits (CWT/EWT, credit
  memos). Payment links come from receipts (`books/links.py`) and bank lines (P1).
- **Withholding on the subledger.** Customer-withheld CWT reduces A/R and creates a **"2307 to receive"** item: Kalayaan
  SI 0006 owes ₱268,142.70 and a ₱2,415.70 2307 is expected. Supplier-withheld EWT reduces A/P and creates an
  **outgoing 2307** item (already generated by `outgoing_2307.py`; link it). No credit-note gymnastics as in QBO.
- **Aging.** A/R and A/P aging (current, 1–30, 31–60, 61–90, 90+) by contact, as of any date; XLSX + PDF in the period
  output.
- **Customer statement** PDF (for firms that send them for clients).
- **UI.** Company → Customers / Suppliers lists with open balance, overdue, 2307 pending. A contact page shows its
  documents, payments, open items and 2307s.

**Acceptance:** after the Q4 pack, A/R = ₱467,623.82 across 3 open invoices and A/P = ₱757,042.80 across 8 open bills,
matching QBO. Aging buckets as of 12/31/2026 are correct.

### P1 — Audit log

**Why:** QBO's audit log is the accountant's safety net. Ours exists only for auth.

- `aa_audit_events` (firm, company, user, at, entity, entity_id, action, before JSON, after JSON, reason). Written from
  the router layer for document edits, review-reason overrides, account/JE changes, close/reopen/bind and contact
  merges. Under RLS like everything else.
- Document panel "History" tab plus a company-level Audit log page with filters (user, date, entity).
- Every override of a review reason (e.g. "accept not_an_invoice anyway") records who did it and why.

**Acceptance:** editing an amount, overriding a flag and reopening a month each produce an event with a before/after
diff, visible to the firm only.

### P2 — Firm work board (deadlines, tasks, client health)

**Why:** QBO's Work, Tasks and Client overview are how a firm runs many clients. We already compute BIR due dates.

- **Work board** per firm: one card per client × filing (0619-E Oct, 2550-Q Q4, 1601-EQ Q4, 1604-C…), with due date
  (from `compute/due_dates.py`), status (no docs → docs in → needs review → generated → filed) and assignee (team
  members).
- **Client overview** tile per company: documents needing review by reason, unreconciled bank months (P1),
  unaccepted/unmatched bank lines, open 2307s to receive, months not closed.
- **Approve-before-close:** an optional firm setting so that only a manager can close a month or mark a return filed.
  This is the useful slice of QBO's approval workflows.
- **Tasks:** free-form tasks linked to a document or period ("ask client for Oct–Nov bank statement").

### P2 — Reporting depth and drill-down

- P&L **by month** and **comparison** (quarter vs prior quarter, year vs prior year), Balance Sheet comparison,
  **GL detail** and **transaction list by date** with filters, and an Adjusted TB (pre/post closing entries).
- **Every figure drills down** to the posting and then to the source document page (product principle: every entry
  traces back to its source document). QBO only drills to the transaction.
- **Management report pack** PDF (cover, P&L, BS, cash flow, aging, notes) per quarter.

### P2 — Bulk tools

- **Reclassify:** choose company, date range and account, select postings, then move them to another account or ATC.
  Re-runs the engine, keeps closed months intact via correcting entries, and writes audit events.
- **Bulk accept** in the review queue: select many documents with the same reason and resolve them in one action,
  like QBO's "Accept 30 items".
- **COA templates** at firm level (trading, services, manufacturing, non-VAT), applied when creating a company.

### P2 — Opening balances and CSV import

- **Opening TB import** (CSV/XLSX: account code/name, debit, credit, as-of) and **opening open items** (A/R/A/P
  invoices outstanding at books start). This avoids the negative cash-on-hand problem.
- **JE CSV import** (the hidden QBO importer was the only way to do payroll/opening entries in bulk).
- Make importers tolerant where QBO was brittle: map account names fuzzily to the chart with a confirm step, accept
  negative lines, auto-detect the date format.

### P2 — Smaller wins from the full QBO walk-through

Each of these is a page or setting QBO has that maps cleanly onto our flow (details in the catalogue).

- **Client health checks** (QBO Client overview → *Common issues*): per company, count uncategorised items, A/R and
  A/P older than 90 days, **negative asset/liability balances** (it caught our negative Cash on hand), opening-balance
  plugs still sitting in Suspense, unreconciled months and the "reconciled through" date. Show on the work board.
- **Adjusting-entry flag on JEs** plus an **Adjusted TB** (unadjusted → adjustments → adjusted) and an **Adjusting
  Journal Entries** report. Our books already separate closing entries. Add the flag to `aa_journal_entries` and
  `JournalEntryForm.tsx`.
- **Invalid Journal Transactions** report: a self-check listing any posting that doesn't balance or hits an inactive
  account. The engine already raises on unbalanced entries; surface it as a report instead of a 500.
- **Lock account** and **make inactive** on chart accounts (`ChartEditor.tsx`): block posting to an account without
  deleting it. Also the live "where this lands on the BS/P&L" preview when adding an account.
- **Duplicate-number warnings**: QBO warns on a repeated cheque no., bill no. per supplier, or journal no. We already
  detect duplicate documents. Add the cheap per-supplier invoice-number check as its own review reason.
- **Supplier defaults**: default expense account and terms per supplier (QBO's supplier form) feeding classification.
  This is our ATC databank, extended with terms so due dates and A/P aging work.
- **Report viewer upgrades**: cash/accrual toggle, *display columns by* month/quarter, *compare to* prior period/year
  with ₱ and % change, non-zero rows only, divide by 1000, and **drill-down** to the source document page.
- **KPI and ratio tiles** per company (from the QBO KPI scorecard and Performance centre): gross and net margin,
  opex ratio, current ratio, quick ratio, A/R and A/P ageing buckets. These are cheap once FS exist and useful in the
  management pack.
- **Management report pack** export as **PDF and DOCX** (QBO offers both), with cover, contents and notes.
- **Global search** across documents (number, TIN, payee, amount, date) and the review queue, with type-ahead like
  QBO's.
- **Notifications** inbox for the firm: deadline approaching, document needs review, statement unreconciled, 2307
  still missing.

### P3 — Nice to have

- **Recurring entries** (monthly rent accrual, retainer) as JE templates. The engine still prefers documents.
- **Prepaid expense schedules**, only as reviewed suggestions (QBO's auto-draft of a 13-month prepaid for a ₱1,515
  phone load shows the risk).
- **Write off invoices** in bulk (needs P1 A/R).
- **Cash-flow tile and projection** from open A/R/A/P due dates.
- **Export to QBO/Xero** (COA, contacts, JE CSV) for firms that keep a client's books elsewhere.
- **Customer statements** with QBO's three types (balance forward, open item, transaction) and an aging footer.
- **Privacy toggle** on dashboards (hide amounts while screen-sharing with a client).
- **Firm-level checklist templates** for the monthly close (QBO Work → Manage templates).
- **Report scheduling**: email a report or pack on a schedule (QBO workflow "Schedule and send a report").

### Skip

E-commerce connectors, estimates/sales orders/POs, perpetual inventory and item master, time tracking, running payroll
and payments, revenue recognition (ASC 606), forecasts/budgets.

## 4. Extraction and review rules the pack exposed

Add these to the pipeline and to `backend/tests` as fixtures from the Q4 pack. They are cheap and they are exactly what
QBO can't do.

| New / changed rule | Trigger (from the pack) | Behaviour |
|---|---|---|
| `tendered_less_than_total` (new review reason) | Cash < total, negative change: p20 Tindahan 0048029, p22 Botika 0012151, p25 Manok House, p28 Tindahan 0052607, p37 Tindahan 0061504 | Flag; post the invoice total. Ask whether there's another payment or the receipt was altered |
| `ewt_expected` (new) | Client is a withholding agent and the supplier invoice is for professional fees/rent with no EWT shown (p11 Reyes Santos RS-1048) | Flag and suggest the ATC (WI010/WC010 professional, WC100 rent) and amount; feeds 0619-E/1601-EQ and the outgoing 2307 |
| `payment_unverified` (new, low severity) | Credit terms with no matching receipt/bank line after the period (Pacific Steel PDC ×2, Luzon Paint, Meralco-type bill, Handaan 50% DP) | Show on the A/P aging; don't block |
| `payment_source_unknown` (new) | Payroll-type document says "released" but nothing matches in the bank (p43 13th month ₱120,000 on 12/15) | Flag for the client question list |
| Duplicate detection | p7 = p6 (Luzon Paint 5838) | Already `duplicates.py`. Add the pack as a regression fixture |
| `vat_math_mismatch` | p16 Golden ₱2,600 vs ₱2,400 | Already exists. Post input VAT at the recomputed 12% and send the excess to a "VAT difference – for review" account (what I did by hand in QBO) |
| `not_an_invoice` | p15 QuickFix OR, p27 Park-N-Go OR, p42 acknowledgement receipt | Already exists. Gross goes to expense, no input VAT |
| `not_addressed_to_client` | p21, p28, p40 (buyer block blank), p38 (owner's name) | Already exists. p38 should default to **exclude/drawings**, not expense |
| Import landed cost | p18 BOC entry: FOB + freight + duty + brokerage = landed cost ₱196,000; VAT ₱23,520 | Duty and VAT paid to BOC = one payment. FOB = payable to the foreign supplier. Freight/brokerage payee unknown → `payment_source_unknown`. Resolves the open "IEIRD landed cost → COGS" question: in QBO it all went to Purchases |
| Bank statement lines | p51 | P1 bank matching; acceptance test above |

## 5. Things left in the QBO test company (for whoever looks next)

- Suspense – for review holds ₱532,680.15: ₱412,880.15 opening-bank offset, ₱120,000 13th-month payment source, and
  ₱200 Golden excess VAT (a debit).
- Cash on hand is −₱155,639.87 because there's no opening balance or Oct–Nov bank data.
- Assumed payee for freight + brokerage on the import entry: "R. Villanueva (Customs Broker)".
- Payment-method mapping was assumed: CASH, GCash, debit card, fleet card, RFID and SakayPay all went to "Cash on hand".
  Only "CREDIT CARD ****4412" went to the card account.
- The bank-feed screen was switched to QBO's **previous** banking UI, because the new one's Match buttons didn't
  respond. Switch back with "Try new banking page".
- QBO added two zero-balance accounts by itself while pages were being opened: *Reconciliation Discrepancies*
  (10:07 pm) and *Inventory Shrinkage* (10:13 pm), shown as "System Administration" in the audit log.
- QBO auto-created a draft prepaid-expense schedule for the Sulit-Stop ₱1,515 bill (Advanced accounting → Prepaid
  expenses). It's a draft and wasn't approved.
- Import files used are in `docs/superpowers/research/2026-10-16-qbo-q4-run/` (`gen.py` generated them).
