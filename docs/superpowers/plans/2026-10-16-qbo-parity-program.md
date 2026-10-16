# QBO parity program: build order and working rules

Date: 2026-10-16. The owner asked for everything in `2026-10-16-quickbooks-parity-plan.md` to be built, unattended,
overnight. The plan doc is the requirements source; the feature catalogue
(`../specs/2026-10-16-quickbooks-online-feature-catalog.md`) is background. This file is the order and the rules every
workstream follows.

## Order

Each workstream gets its own design note + implementation plan (`docs/superpowers/plans/2026-10-16-qbo-NN-<slug>.md`),
then implementation, then review. Later workstreams may depend on earlier ones.

| # | Workstream | Plan source |
|---|---|---|
| 01 | Review rules from the Q4 pack: `tendered_less_than_total`, `ewt_expected`, `payment_source_unknown`, `payment_unverified` (low severity), VAT-difference account on `vat_math_mismatch`, personal purchase (`not_addressed_to_client` in owner's name) → drawings/exclude default, per-supplier duplicate invoice-number check | Plan §4, §3 "Duplicate-number warnings" |
| 02 | Audit log (`aa_audit_events`, write helper, router hooks, document History tab, company Audit log page) | Plan §3 P1 Audit log |
| 03 | Bank statements as ledger evidence: statement line extraction + `aa_bank_lines`, bank accounts, matcher (`bank_match.py`), bank rules, reconcile + report, opening-balance prompt, close soft-block, UI | Plan §3 P1 Bank |
| 04 | Contacts master + A/R/A/P open items + aging + 2307-to-receive / outgoing 2307 links + customer statement + Customers/Suppliers UI | Plan §3 P1 subledgers |
| 05 | Firm work board (client × filing cards, status, assignee), client health checks, tasks, approve-before-close setting, notifications inbox | Plan §3 P2 Work board + smaller wins |
| 06 | Reporting depth: P&L by month / comparison, BS comparison, GL detail, transaction list, adjusting-JE flag + Adjusted TB + AJE report, Invalid Journal Transactions report, drill-down to source document page, KPI/ratio tiles, management report pack (PDF + DOCX) | Plan §3 P2 Reporting + smaller wins |
| 07 | Bulk + chart tools: reclassify, bulk-resolve review queue, firm COA templates, lock/inactive accounts + "where it lands" preview, supplier defaults (terms) | Plan §3 P2 Bulk + smaller wins |
| 08 | Opening TB import, opening open items, JE CSV import (tolerant: fuzzy account map with confirm, negative lines, date-format detection) | Plan §3 P2 Opening balances |
| 09 | Global search (documents by number/TIN/payee/amount/date + review queue, type-ahead) | Plan §3 smaller wins |
| 10 | P3 items that are cheap once the above exist: recurring JE templates, write-off invoices, cash-flow tile from open A/R/A/P, customer statement types, privacy toggle, close-checklist templates. Skip anything that turns out large. | Plan §3 P3 |

Skip list (do not build): e-commerce connectors, estimates/SOs/POs, perpetual inventory, time tracking, running
payroll, revenue recognition, forecasts/budgets, report email scheduling (no mail infra).

## Working rules (every workstream)

- Branch `qbo-parity`. Commit after each green task; message ends with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push, never touch `main`.
- Read `CLAUDE.md` first and obey its gotchas: FORCE RLS on aa_* (new tables get the same RLS policy as the others
  in `services/accounting/rls.py`), `enterprise_id` filter on every query, additive columns go in the model **and**
  `services/accounting/schema.py`, `csv_safe` on spreadsheet cells, theme CSS vars (no `dark:`), page roots
  `className="lp ..."`.
- TDD for backend logic: pure functions with tests in `backend/tests` (no DB, no Gemini, like the existing tests).
  Use the Q4 pack facts in the parity plan as fixtures where they apply.
- Gates before every commit: `docker compose exec -T backend python -m pytest -q`,
  `docker compose exec -T backend ruff check app --select F,E9`. For frontend changes also
  `cd frontend && npm run lint && npx tsc --noEmit`. Run `npm run build` at the end of each workstream.
- Gemini prompt changes: extend the existing extraction schema/prompt in `extraction.py`; keep it backward compatible
  so old documents still load.
- Open CPA questions (landed cost → COGS, 13th-month source, Reyes Santos EWT) are **not** decided here: make the
  behaviour a review flag or a setting, default to the current behaviour.
- When the plan is ambiguous, pick the conservative option (flag for review rather than auto-post; never
  auto-post bank matches that disagree with the narration) and record it under a **Decisions** heading in that
  workstream's plan file, so the owner can check it in the morning.
- Keep UI consistent with `components/accounting/*` (same panels, chips, page guides). Add a page-guide hint for each
  new page like the existing ones.
- Update `CLAUDE.md` (repo layout / gotchas) when a workstream adds something a future session must know.
- At the end of each workstream, append a short entry to `docs/superpowers/plans/2026-10-16-qbo-parity-progress.md`:
  what shipped, test count, decisions made, anything left undone and why.
