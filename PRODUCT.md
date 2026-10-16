# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: Philippine accounting and bookkeeping firms (firm owner, managers, staff) who keep the books and file BIR returns for many client businesses. Their job is turning a constant inflow of client paperwork (sales invoices, receipts, BIR 2307s, payroll registers, import papers) into filed returns and BIR loose-leaf books of accounts.

## Product Purpose
AutoAccounting is an AI back office for Philippine accounting firms. Staff drop client documents; it matches each to the right client company by TIN and name, extracts and sorts it (sales, purchases, expenses, payroll, 2307s), checks VAT math and flags anything doubtful with a reason, then files everything Company → Year → Quarter. From that it fills the BIR returns as PDFs plus a versioned XLSX, and keeps the BIR loose-leaf books of accounts. Success is zero re-encoding, with every figure traceable to its source document.

## Positioning
Drop-and-done for PH compliance: one batch of mixed client papers becomes the month's, quarter's and year's BIR returns (0619-E, 1601-C, 2550-Q, 2551-Q, 1601-EQ, 1701-Q/1702-Q, 1701/1701-A/1702-RT, 1604-C alphalist with 2316s, outgoing 2307s) and the client's journals, GL, trial balance and financial statements, instead of staff encoding receipts into spreadsheets.

## Operating Context
- Inputs: sales/service invoices, official and collection receipts, BIR 2307s, payroll registers, import papers; photos and scans.
- Work happens per client company, in batches, against BIR monthly/quarterly/annual deadlines (moved to the next working day on weekends and PH holidays).
- Outputs: filled BIR return PDFs, a versioned workbook with changes highlighted, and BIR loose-leaf books (6 books for VAT-registered, 4 for non-VAT; printed months are closed; year-end binder with sworn declaration).
- Currency is peso (₱); VAT is 12%.

## Capabilities and Constraints
- Real review reasons the app raises include: possible duplicate, not addressed to the client, seller not VAT-registered, VAT math mismatch, another company's TIN, missing date/amount, low confidence.
- The marketing site is static HTML/CSS/JS in frontend/public/ (index.html, styles.css, app.js), served at /homepage; no build step. The hero headline and sorting demo are approved as-is. The main CTA is "Book a demo" (a demo sells better than self-serve trial); keep subheads out, or to one sentence.
- Billing is per extracted page (₱), opt-in per platform; pricing and free-tier terms are undecided.
- No e-filing integration: AutoAccounting fills returns; the firm submits them.

## Brand Commitments
- Name: AutoAccounting.
- Light mode; deep navy/slate ink with emerald green signalling accuracy/completion (from the founding brief).
- The interactive drag-and-drop sorting demo is a required part of the landing page.
- Headline from brief: "Drop Your Documents. Consider Your Books Done."

## Evidence on Hand
None. There are no real certifications (SOC 2 etc.), accuracy figures, usage numbers, customers, testimonials, or confirmed integrations. The user asked for all such claims to be removed for now; do not fabricate them. Demo data must be visibly illustrative.

## Product Principles
- Show the work being done, don't assert it.
- Every entry traces back to its source document.
- Built for people who process other people's paperwork at volume.
