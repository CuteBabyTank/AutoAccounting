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
