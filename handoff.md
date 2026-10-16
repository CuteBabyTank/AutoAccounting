# Handoff: QuickBooks Online benchmark of the Q4 2026 test pack

Date: 2026-10-16. Nothing here is committed yet; all of it is new, untracked files.

## What was done

1. **Entered the whole Q4 test pack into QuickBooks Online by hand.** The pack is
   `~/Desktop/AutoAccounting_Test_Pack_Q4_2026.pdf` (51 pages, Bayanihan Hardware Trading Corp.). The QBO company is
   `MFS_Test` (Accountant view, Advanced, PHP). The aim was to see what a firm does today without AutoAccounting.
   - Trial balance 1/1–12/31/2026 balances at **₱2,080,401.79**. The bank account equals the statement ending balance
     (₱330,854.85). A/R is ₱467,623.82 (3 open invoices) and A/P is ₱757,042.80 (8 unpaid bills).
   - Left out on purpose: p7 (duplicate scan of Luzon Paint 5838) and p38 (owner's personal pharmacy purchase).
2. **Walked every page of QBO** and wrote a feature catalogue: each feature, what it does, and whether AutoAccounting
   has it.
3. **Wrote a plan** for which QBO features AutoAccounting should build, plus new review rules the pack exposed.

## Files

| File | What it is |
|---|---|
| `docs/superpowers/plans/2026-10-16-quickbooks-parity-plan.md` | **Start here.** What happened in QBO, a summary page map, and the roadmap: P1 bank statements → reconciliation, A/R/A/P subledgers with aging and 2307 tracking, audit log; P2 work board, reporting drill-down, bulk tools, opening TB import, smaller wins; P3; skip list. §4 lists the new review rules. §5 lists what's left in the QBO company. |
| `docs/superpowers/specs/2026-10-16-quickbooks-online-feature-catalog.md` | Detailed reference of every QBO page, form, setting, report (all ~100) and the 38 workflow templates. |
| `docs/superpowers/research/2026-10-16-qbo-q4-run/` | The CSVs imported into QBO and `gen.py`, which produced them from the pack (VAT already split per document). `gen.py` writes into a `qbo/` folder next to itself. The `*_fixed` / `01b` / `05_bills_import` files are the versions that actually imported. |

## Key findings (short)

- QBO has **no PH VAT or withholding model**. Every VAT split, the 1% CWT (needed a credit note) and the 5% EWT (needed
  a manual bill with a negative line) were done by hand. Importers reject negative lines.
- QBO **caught none of the pack's traps**: the duplicate, the VAT math error (Golden ₱2,600 vs ₱2,400), ORs posing as
  invoices, blank buyer blocks, the personal purchase, the acknowledgement receipt.
- **New trap the answer key misses:** five receipts (p20, p22, p25, p28, p37) show cash tendered *less than* the total
  (negative change). This is proposed as review reason `tendered_less_than_total`.
- Bank matching on amount alone picked wrong twice: the ₱150 service charge matched a parking bill, and ₱3,500 fuel
  had the city permit as a second candidate. The new bank-feed UI's Match buttons didn't respond, so the old UI was
  used.
- Best ideas to borrow: the bank feed, matching and reconcile; per-contact open balances and aging; the audit log;
  Client overview "common issues" (it flagged negative Cash on hand); the adjusting-JE flag with an Adjusted TB; report
  comparisons and drill-down.

## State of the QBO test company (`MFS_Test`)

- **Suspense – for review: ₱532,680.15.** That's the opening-bank offset (₱412,880.15), the 13th-month payment
  source not found on the statement (₱120,000), and the excess VAT Golden billed (₱200 debit).
- **Cash on hand is −₱155,639.87.** The pack has no opening balance and no Oct–Nov bank data.
- Assumptions made:
  - Every non-card payment method (cash, GCash, debit, fleet card, RFID, SakayPay) went to Cash on hand.
  - Freight and brokerage on the import entry are payable to "R. Villanueva (Customs Broker)".
  - Reyes Santos RS-1048 was booked with no EWT.
- The bank feed was switched to QBO's **previous** UI. Switch back with "Try new banking page".
- QBO added two zero-balance accounts by itself while pages were being opened: *Reconciliation Discrepancies*
  (10:07 pm) and *Inventory Shrinkage* (10:13 pm), shown as "System Administration" in the audit log.
- QBO auto-drafted a wrong 13-month prepaid schedule for the ₱1,515 Sulit-Stop bill (Advanced accounting → Prepaid
  expenses). It's a draft and wasn't approved.
- Sales tax is still off; VAT lives in custom accounts (Input VAT, Input VAT – Importation, Output VAT).

## Open questions for the user / CPA

- Was the 13th month (₱120,000, 12/15) paid in cash or from another account?
- What is the 12/15 ₱38,450 "cash deposit – store sales" made of? Only SI 0007 (₱21,616) is a cash sale before it.
- Were the Oct–Nov credit purchases (Pacific Steel PDCs, Luzon Paint, Metro Luzon Electric, Reyes Santos) paid? No
  evidence in the pack.
- Should the client have withheld EWT on Reyes Santos' professional fees?
- Does the import landed cost (freight, brokerage, duty) go to COGS? This was already an open item in `CLAUDE.md`. QBO
  run put it all in Purchases.

## Suggested next steps

1. Review and commit the three new docs (plus this file).
2. Turn the plan's §4 rules into pytest fixtures from the Q4 pack (`backend/tests`), starting with
   `tendered_less_than_total` and the duplicate and VAT-mismatch regressions.
3. Brainstorm, then spec, P1 "bank statements as ledger evidence" (`classify.py:60` currently drops statements),
   following the books design in `docs/superpowers/specs/2026-10-09-autoaccounting-books-design.md`.
