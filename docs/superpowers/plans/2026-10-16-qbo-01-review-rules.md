# QBO 01: Review rules from the Q4 pack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the document review rules the Q4 test pack exposed (tendered < total, EWT expected, payment source
unknown, payment unverified, per-supplier invoice-number reuse, VAT-difference posting, personal purchases) to
extraction, classification, duplicates, the books and the review UI.

**Architecture:** Rules stay pure and live where their neighbours live: per-document rules in
`services/accounting/classify.py`, cross-document number reuse in `duplicates.py`, payment-evidence flags in a new
`services/accounting/review_rules.py` (so workstream 03 bank matching can call the same sync). Per-reason details
(suggested ATC, recomputed VAT, tendered amount) go in a new `aa_documents.review_notes` JSONB column. A reason can be
"soft" (`payment_unverified`): it is stored and shown but never sets `needs_review`, so it never blocks the queue or the
month close.

**Tech Stack:** FastAPI + SQLAlchemy async, pure-Python rules with pytest, Next.js/TS UI.

**Spec:** `docs/superpowers/plans/2026-10-16-quickbooks-parity-plan.md` §4 and §3 "Duplicate-number warnings";
working rules in `docs/superpowers/plans/2026-10-16-qbo-parity-program.md`.

## Global Constraints

- Branch `qbo-parity`; commit after each green task, message ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Additive columns go in the model **and** `services/accounting/schema.py`.
- Gemini schema/prompt changes are backward compatible: every new field optional, old `raw` dicts still load.
- Gates: `docker compose exec -T backend python -m pytest -q`, `docker compose exec -T backend ruff check app --select F,E9`,
  frontend `npm run lint && npx tsc --noEmit` (and `npm run build` at the end).
- Open CPA questions are not decided: Reyes Santos EWT stays a flag; the engine's existing EWT computation is untouched.
- Theme CSS vars only, no `dark:`.

## Review Focus

1. Old documents (no `review_notes`, `raw` without the new keys) must still serialise and post exactly as before —
   test: `test_old_raw_without_new_fields_has_no_new_reasons`.
2. A doc whose only reason is `payment_unverified` must not count as needing review (queue, month close) —
   test: `test_soft_reason_does_not_need_review`.
3. VAT shown *below* 12% must never claim more input VAT than printed — test: `test_vat_below_twelve_percent_claims_printed_vat`.
4. Monthly statements / support papers that repeat an account number must not trigger `duplicate_invoice_number` —
   test: `test_number_reuse_ignores_support_papers`.
5. A payment flag cleared by evidence comes back if the evidence is removed (receipt deleted, `paid_on` cleared), but
   is never re-added to a reviewed document — test: `test_payment_flags_follow_evidence`.

---

### Task 1: Extraction fields

**Files:** Modify `backend/app/services/accounting/extraction.py`; Test `backend/tests/test_accounting_extraction.py` (existing file; add tests).

**Produces:** `ExtractedDoc.cash_tendered: Decimal = 0`, `change_amount: Decimal = 0` (may be negative),
`payment_terms: str = ""` (`"cash" | "credit" | ""`), `marked_paid: bool = False`.

- [ ] Test `test_parse_payment_fields`: an item with `"cash_tendered": 500, "change": -60, "payment_terms": "credit", "marked_paid": true` parses to those values; `test_parse_payment_fields_missing` (old reply) gives the defaults.
- [ ] Prompt lines: `"cash_tendered"`, `"change"` (as printed, negative allowed), `"payment_terms"` (credit when terms/PDC/charge/balance due shown), `"marked_paid"` (true when it says PAID, RELEASED, RECEIVED). `parse_money` must keep negative change — check, else parse signed.
- [ ] Run, commit.

### Task 2: Soft reasons + per-document rules in classify

**Files:** Modify `classify.py`, `pipeline.company_profile`, `compute/ewt.py`; Test `backend/tests/test_accounting_review_rules.py` (new).

**Produces:**
- `REVIEW_REASONS` += `tendered_less_than_total`, `ewt_expected`, `payment_source_unknown`, `payment_unverified`, `duplicate_invoice_number`, `personal_purchase`.
- `SOFT_REASONS = frozenset({"payment_unverified"})`; `needs_review_for(reasons: list[str]) -> bool`.
- `CompanyProfile` gains `is_withholding_agent: bool = False`, `owner_names: tuple[str, ...] = ()` (defaults keep old call sites working).
- `ewt.expected_atc(account: str, counterparty_name: str, vat_registered: bool | None) -> str` (rent → `WC100`/`WI100`; professional fees → `WC010` / `WI011` if VAT-registered else `WI010`; else ""), used by `suggest_atc`.
- classify output gains `review_notes: dict` and `excluded: bool`.

Rules (each a test with pack values):
- `tendered_less_than_total`: `cash_tendered > 0 and cash_tendered < gross` or `change_amount < 0`. Gross unchanged. Note `{"tendered", "total"}`. Fixture p20 Tindahan 0048029 style: total 560, tendered 500, change −60.
- `ewt_expected`: profile is agent, role buyer, category expenses/purchases, account rent/professional_fees, `withholding_amount == 0`. Note `{"atc", "rate", "amount"}` = base (gross − VAT when VAT shown) × rate. Fixture p11 Reyes Santos RS-1048 professional fees ₱30,000 + ₱3,600 VAT → WI010 5% → ₱1,500. Not raised for non-agents.
- `payment_source_unknown`: category payroll and `marked_paid` (raw), no `paid_on` (always none at extraction). Fixture p43 13th month ₱120,000.
- `payment_unverified`: buyer purchases/expenses with `payment_terms == "credit"`. Soft.
- `vat_math_mismatch`: no longer invalidates input VAT on its own (other issues still do); note `{"expected", "difference"}` (expected = vatable × 12%, difference = printed − expected). Fixture p16 Golden: 20,000 / 2,600 → expected 2,400, difference 200, `input_vat_valid` True, treatment `vatable`.
- `personal_purchase`: when `not_addressed_to_client` fires and the buyer name matches an owner name (`name_similarity ≥ NAME_MATCH_THRESHOLD`) → add reason, `excluded=True`. Fixture p38 owner's name.
- `needs_review = needs_review_for(reasons)` everywhere `bool(reasons)` was used (classify, mark_duplicate, links.py, accounting.py ×2, duplicates.sync_flags).

### Task 3: VAT difference posting

**Files:** `books/chart.py`, `compute/cogs.py`, `compute/vat.py`, `compute/ledgers.py`, `compute/books.py`; Tests `test_accounting_review_rules.py`.

**Produces:** chart account `("1310", "VAT difference - for review", "asset", False, "vat_difference")` (seeded on existing charts by `ensure_chart` → `missing_standard`); `cogs.claimed_input_vat(line, company_vat) -> Decimal` (0 when not claimed; `min(vat, c2(vatable × 12%))` when they differ by > ₱1, else vat); `cogs.vat_difference(line, company_vat) -> Decimal` (vat − claimed when claimed, else 0).
- [ ] Golden purchase posts Dr Purchases 20,000 / Dr Input VAT 2,400 / Dr VAT difference 200 / Cr A/P 22,600; 2550-Q 44A 20,000, 44B 2,400.
- [ ] VAT below 12% (2,200 on 20,000) claims 2,200, no difference.
- [ ] `post_all` on a chart without `vat_difference` doesn't fail when no difference exists (line only emitted when > 0 … `chart.code` called lazily).

### Task 4: Per-supplier invoice-number reuse + regression fixtures

**Files:** `duplicates.py`, `schemas/accounting.py` (`DuplicatePairOut.reason` Literal += `number_reused`); Tests `test_accounting_review_rules.py`.

**Produces:** `NUMBER_REUSED = "number_reused"`, flag `duplicate_invoice_number`; `DupDoc.category: str = ""`.
- [ ] `duplicate_pairs` emits `number_reused` when buyer-side purchases/expenses, same supplier + number, but dates (or totals) differ and not cleared. `sync_flags` keeps each flag iff the doc is the copy (or original) of a pair of that kind.
- [ ] Regression: Luzon Paint SI 5838 scanned twice (same date, ₱ amount) → `same_number` pair, copy flagged `possible_duplicate` (both `duplicate_pairs` and per-file `mark_duplicates`).
- [ ] Support/statement docs with repeated numbers → no pair.

### Task 5: Payment-evidence flags (clearable)

**Files:** Create `services/accounting/review_rules.py`; call from `books/links.relink_receipts`; add `paid_on`, `paid_via` to the relink trigger set in `routers/accounting.patch_document`.

**Produces:** `payment_flags(category: str, client_role: str, raw: dict | None) -> set[str]` (which of the two payment reasons a document qualifies for) and `sync_payment_flags(docs, paid_ids: set[str]) -> None` (adds/removes `payment_source_unknown` / `payment_unverified`: removed when the doc has `paid_on` or a receipt settles it; re-added when evidence goes, never on reviewed docs; recomputes `needs_review`). Workstream 03 adds bank-line ids to `paid_ids`.

### Task 6: Columns, owner names, API, UI

**Files:** `models/accounting.py` (`AADocument.review_notes` JSONB `{}`, `AACompany.owner_names` JSONB `[]`), `schema.py`, `schemas/accounting.py` (`DocumentOut.review_notes`, `CompanyIn.owner_names` cleaned like aliases), `routers/accounting.py` (`owner_names` in `_NOT_TAX_FACTS`), `pipeline.company_profile` (owner names + books_signatory, withholding agent flag), frontend `types/accounting.ts`, `lib/accounting-format.ts` (labels + `SOFT_REASONS` + `reasonDetail(reason, notes)`), `DocumentPanel.tsx` (details after labels; soft reasons in a neutral note box), `DuplicateCompare.tsx` (`number_reused` text), `CompanyForm.tsx` (owner names input), `FileGrid.tsx` if it badges duplicates.

### Task 7: Gates, docs, progress entry

`npm run build`, CLAUDE.md gotcha (soft reasons + `review_rules.sync_payment_flags` hook for bank matching), progress file.

## Decisions

1. **VAT difference claims the recomputed VAT.** On `vat_math_mismatch` (with no other input-VAT issue) the document now
   claims `min(printed VAT, VATable × 12%)` on the books *and* the 2550-Q, and the excess goes to the new
   `1310 VAT difference - for review` asset. VAT printed below 12% claims only what is printed (never more than the
   invoice supports). Documents already stored keep their old `input_vat_valid=False` (no re-classification).
   **Bug fix 2026-10-19:** older documents are now re-classified when a company's periods load
   (`books/vat_backfill.backfill_vat_difference`, pure rule `review_rules.legacy_vat_fix`): a buyer purchase / expense
   whose only input-VAT issue is `vat_math_mismatch` gets `input_vat_valid=True` (audited as "AutoAccounting (VAT
   difference rule)", books touched, the quarter's versions go stale; closed months correct through `apply_closes`).
   A document whose quarter is already filed keeps the disallowed VAT (the filed return didn't claim it) and gets a
   note (`review_notes.vat_math_mismatch.legacy = "filed"`).
2. **`payment_unverified` is soft.** Stored in `review_reasons`, shown as a note, but `needs_review` ignores it, so it
   never blocks the review queue or month close. It is raised at extraction when the document shows credit terms (not
   "after the period" — the period isn't known to have ended at extraction); evidence clears it.
3. **Payment evidence today** = `paid_on` set on the document, or a receipt linked to it (`settles_document_id`).
   Bank lines (workstream 03) plug in through `review_rules.sync_payment_flags(docs, paid_ids)`.
4. **`payment_source_unknown`** is raised only for payroll documents Gemini reads as paid/released; the BOC landed-cost
   freight/brokerage case is left to the open CPA landed-cost question.
5. **`ewt_expected` is only a flag + suggestion** (open CPA question on Reyes Santos). The returns engine's existing EWT
   computation is unchanged. ATC suggestion: corporate name → `WC010` / `WC100`; individual → `WI010` (`WI011` if the
   supplier is VAT-registered) / `WI100`; amount = VAT-exclusive base × rate.
6. **Personal purchases are detected by owner name.** New company field "Owner / officer names" (plus the books
   signatory). A document not addressed to the client whose buyer matches one of those names gets `personal_purchase`
   and is **excluded** by default (not posted as an expense); if the company paid for it, the reviewer records it as
   drawings by journal entry. No drawings auto-post (conservative).
7. **Invoice-number reuse** is its own reason `duplicate_invoice_number` (pair reason `number_reused`), only for
   supplier documents (buyer side, purchases/expenses) with the same supplier + number but a different date or total.
   Same number + same date stays `possible_duplicate`. "Keep both" in the compare view clears it like any pair.
8. **Tendered < total** posts the invoice total unchanged and flags.
