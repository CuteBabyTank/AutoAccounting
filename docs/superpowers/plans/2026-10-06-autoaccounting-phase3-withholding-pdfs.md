# AutoAccounting Phase 3 (Withholding and Return PDFs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the withholding side of a quarter (expanded withholding: 0619-E for months 1–2, 1601-EQ, the QAP alphalist and outgoing 2307s; compensation: 1601-C for each month) to the versioned output, and fill the official BIR PDFs for every return AutoAccounting produces (2551-Q, 1701-Q, 1702-Q, 0619-E, 1601-EQ, 1601-C, alongside the Phase 2 2550-Q).

**Architecture:** A pure `compute/ewt.py` decides each payment's ATC (the document's own choice, a remembered supplier choice, or a suggestion from the account, payee type and Top Withholding Agent flag) and computes base × rate. `compute/withholding.py` turns that and the payroll documents into the return items. The engine adds these forms and the QAP ledger to the same immutable snapshot as Phase 2, so versioning, diffs, yellow highlights and workbooks work unchanged. PDFs use a generic comb-cell overlay (`forms/overlay.py` + `services/accounting/pdf_overlay.py`) driven by one calibrated layout module per template. `pdf_returns.py` maps snapshot values and the company header onto each layout. Outgoing 2307s reuse the existing 2307 renderer, zipped one PDF per payee.

**Tech Stack:** Python `decimal`, PyMuPDF (fitz), openpyxl, FastAPI, async SQLAlchemy, Pydantic v2, pytest in the backend container; Next.js 15 / React 19 / Tailwind 4 frontend.

**Spec:** AutoAccounting spec sheet (Claude Doc) https://claude.ai/code/artifact/8dcfb05b-3f3e-4410-a082-da75a391cd21. The relevant sections are *Computation engine → Expanded withholding* and *Compensation*, *Filling the BIR forms*, *XLSX workbook* (0619E, 1601EQ, QAP, 1601C tabs) and the Phase 3 band of *Rollout*. Earlier plans: `docs/superpowers/plans/2026-10-05-autoaccounting-phase1-intake.md`, `docs/superpowers/plans/2026-10-05-autoaccounting-phase2-vat-itr.md`.

**Decisions taken with the user (2026-10-06):** one plan for all of Phase 3; 1601-C from payroll-register totals with the non-taxable breakdown entered per month; EWT ATC auto-suggested, editable per document and remembered per supplier; outgoing 2307s as a ZIP download.

## Global Constraints

- Stay inside the AutoAccounting module. New code goes under `backend/app/services/accounting/`, `backend/app/routers/accounting*.py`, `backend/app/models/accounting.py`, `backend/app/schemas/accounting.py`, `backend/app/forms/` (new layouts, `overlay.py`, templates), `frontend/src/{components,app}/accounting/`, `frontend/src/lib/accounting-*` and `frontend/src/types/accounting.ts`. The only edit outside these is one line in `startup_migrations._ensure_accounting_rls` to run the accounting column migrations. Reuse (import, never edit) `services/atc_codes.py`, `services/form_filler_service.py` and `schemas/form_filler.py`.
- Storage stays local, as in Phase 2. PDFs and ZIPs are rendered on demand from the stored snapshot and never written to disk.
- Money is `Decimal` end to end. Withholding returns round to centavos half-up (`c2`); income tax returns stay whole pesos.
- EWT tax = tax base × ATC rate. The base is the amount paid, net of VAT when VAT is shown (`gross − vat` if `vat > 0`, else `gross`). Rates come from `services/atc_codes.py`, plus `WC120` (contractors, corporate payee, 2%), which that table lacks.
- Expanded withholding returns (0619-E, 1601-EQ, QAP) are produced only for withholding agents (`is_withholding_agent` or `is_top_withholding_agent`), and only when the fiscal year-end month is 3, 6, 9 or 12, because these returns follow calendar quarters. 1601-C is produced when `has_employees` is set or the quarter has payroll documents.
- Snapshot form keys: `0619E-M1`, `0619E-M2`, `1601EQ`, `1601C-M1`, `1601C-M2`, `1601C-M3`. Item keys follow the official forms: 0619-E items 14–18, 1601-EQ items 19–31 plus schedule rows `S{i}_ATC/BASE/RATE/TAX`, and 1601-C items 14–36.
- Templates are the official BIR files, SHA-256 pinned:
  - 2551-Q `1f270ecf66d778836a14697863e420ff65d5ed0a5576a6cf58b97c9a8e8c9b24`
  - 1701-Q `c731d3f12556e6f19ab81f6113ca7c4a23f7ed099675c03451ac0074d96b85ed`
  - 1702-Q `589e22190b9211571cb8a0ba14c97c17dff250f3b8ee9f9e8f6cc3b37b1b1be4`
  - 0619-E `0418160d63d4e6f68c34f2bad553273a5d148c3686d8562d338d35fcdd0c5215`
  - 1601-EQ `5277addc6778c96a53fde99b8664b1a5213fcea638dea06033c9acf22ee73c25`
  - 1601-C `c8faaa71015337a73b4ceb96bfb265c539589ab5e10eb27899bb81f87f417397`
- PDF amounts are written one character per printed comb cell, right-aligned, with negatives in parentheses. An amount that doesn't fit is printed whole in red and listed in a footnote, never shrunk or cut.
- Pastel yellow `#FFF4B3` (RGB 1.0, 0.957, 0.702) marks changes, as in Phase 2.
- Gemini is not called in Phase 3.
- Backend tests: `docker compose exec -T backend python -m pytest -q`. Frontend: `cd frontend && npx tsc --noEmit && npx eslint src/components/accounting src/app/accounting src/lib/accounting-api.ts src/lib/accounting-format.ts src/types/accounting.ts` and `npm run build`. Restore `frontend/tsconfig.tsbuildinfo` after `tsc` (`git checkout -- frontend/tsconfig.tsbuildinfo`).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on branch `AutoAccounting` and never push.

## Review Focus

1. **A withholding agent with no payments that need withholding this quarter.** The 0619-E and 1601-EQ are still produced with zeros, "Any taxes withheld? No" is ticked, and nothing crashes. Pinned in Task 3 (`test_agent_with_no_payments_still_files_zero_returns`) and Task 5 (`test_0619e_fiscal_month_due_date_and_nothing_withheld`).
2. **A supplier invoice whose printed tax withheld differs from base × rate, or shows none.** The computed tax is reported and a warning counts the payments. Pinned in Task 1 (`test_missing_or_different_withholding_warns_but_reports_computed_tax`).
3. **A payment or payroll document dated outside the quarter's months** (moved by hand, or undated). It is counted in month 3 with a warning, never dropped. Pinned in Task 1 (`test_month_in_quarter_and_out_of_quarter_dates`) and Task 2 (`test_payroll_months_counts_out_of_quarter`).
4. **More than six ATCs in a quarter.** The workbook keeps every row. The 1601-EQ PDF prints the first six and says the rest go on an attachment. Pinned in Task 5 (`test_1601eq_schedule_caps_at_six_rows_with_a_note`).
5. **An amount too long for its comb** (e.g. ₱123,456,789 in the 8-cell 1701-Q boxes). It is printed whole in red and flagged in the footnote. Pinned in Task 4 (`test_too_long_amount_is_printed_whole_and_flagged`).

## Deviations from the spec (Phase 3 scope decisions)

- The returns report the EWT the client **owes** (base × rate), not the amount printed on the supplier's document. A mismatch or a missing withholding produces a warning (spec: EOPT RR 4-2024 keeps the expense deductible, but the tax is still due).
- ATC suggestions cover only these cases. Everything else needs the ATC set on the document; it is then remembered for that supplier.
  - Rent: WI/WC100.
  - Professional fees: WI010, or WI011 when the payee prints a VAT REG TIN; WC010 for corporate payees.
  - Repairs, as contractors: WI/WC120.
  - Top Withholding Agents also get goods WI/WC158 (purchases, raw materials, office supplies, capital goods) and services WI/WC160 (transportation, other).
- Payee type (individual vs corporate) comes from the payee name (Inc., Corp., Co., Ltd., OPC…), because documents don't state it.
- Supplier ATC choices apply at computation time to every document from that TIN that has no ATC of its own. Changing a supplier's ATC marks only the edited document's quarter stale.
- "BIR 2307 issued (copy)" documents stay support-only. The QAP and outgoing 2307s are built from the payments.
- 1601-C uses monthly register totals (gross pay and tax withheld from payroll documents). The non-taxable breakdown, taxable compensation not subject to withholding, adjustments and amended payments are entered per month. There is no per-employee check against the withholding table, and Part IV schedules are not filled.
- 0619-E, 1601-EQ and 1601-C amended-return credits other than those listed in the quarter inputs are 0.
- Due dates use the manual (eBIRForms) deadlines:
  - 0619-E and 1601-C: the 10th of the following month (1601-C for December: January 15).
  - 1601-EQ: the last day of the month after the quarter.
  - Weekends roll to Monday. eFPS staggered deadlines are not modelled.
- The PDFs leave some parts blank, because they are worksheets to copy into eBIRForms:
  - The page-2/3 header TIN and name on the new forms.
  - 1702-Q Schedule 1 (special rate).
  - The 1701-Q spouse column and Part II.
  - 2551-Q Schedule 1 rows 2–6.
  - Contact numbers, emails and Part III payment details on all forms.
- Outgoing 2307s carry no payee ZIP code (not captured), and the payee branch code is printed as 00000.
- Phase 2 minors still deferred: branch code on the 2550-Q PDF, company edits don't mark outputs stale, mark-as-filed doesn't record which version.

## File Structure

**Backend — create**
- `backend/app/services/accounting/compute/ewt.py`: `ATC_NONE`, `atc_info`, `rate_percent`, `is_corporate_name`, `is_agent`, `suggest_atc`, `effective_atc`, `tax_base`, `month_in_quarter`, `EwtRow`, `EwtResult`, `compute_ewt`.
- `backend/app/services/accounting/compute/withholding.py`: `form_0619e`, `atc_summary`, `form_1601eq`, `build_qap`, `payroll_months`, `form_1601c`.
- `backend/app/forms/overlay.py`: `Cell`, `comb`, `Cells`, `Check`, `Amount`, `FormLayout`.
- `backend/app/forms/bir2551q_layout.py`, `bir1701q_layout.py`, `bir1702q_layout.py`, `bir0619e_layout.py`, `bir1601eq_layout.py`, `bir1601c_layout.py`, with templates `backend/app/forms/templates/bir2551q_jan2018.pdf`, `bir1701q_jan2018.pdf`, `bir1702q_jan2018.pdf`, `bir0619e_jan2018.pdf`, `bir1601eq_jan2019.pdf`, `bir1601c_jan2018.pdf`.
- `backend/app/services/accounting/pdf_overlay.py`: `Rendered`, `amount_chars`, `render_form`.
- `backend/app/services/accounting/pdf_returns.py`: `LAYOUTS`, `ReturnHeader`, `header_from_snapshot`, `split_form`, `wrap`, `render_return`.
- `backend/app/services/accounting/outgoing_2307.py`: `payee_forms`, `build_zip`.
- `backend/app/services/accounting/schema.py`: `column_statements`.
- Tests:
  - `backend/tests/test_aa_ewt.py`
  - `backend/tests/test_aa_withholding.py`
  - `backend/tests/test_aa_engine_withholding.py`
  - `backend/tests/test_aa_pdf_overlay.py`
  - `backend/tests/test_aa_pdf_returns.py`
  - `backend/tests/test_aa_outgoing_2307.py`
  - `backend/tests/test_aa_wiring.py`

**Backend — modify (accounting module only)**
- `compute/inputs.py`:
  - `DocLine.ewt_atc` and `DocLine.counterparty_vat_registered`
  - `CompanyFacts` withholding flags
  - `PayrollMonth` and the new `PeriodInputs` fields
  - JSON round trip
- `compute/engine.py`: withholding forms, QAP, 1601-C, warnings, `expected_forms`.
- `compute/ledgers.py`: Transactions EWT columns.
- `compute/specs.py`: titles, items, notes, payables, QAP ledger, `PDF_FORMS`.
- `compute/due_dates.py`: monthly and 1601-EQ due dates.
- `diff.py`: columns new to a ledger are not changes.
- `models/accounting.py`: `ewt_atc` on `AADocument` and `AASupplierRule`.
- `schemas/accounting.py`:
  - `DocumentOut.ewt_atc` and `DocumentPatch.ewt_atc`
  - `PayrollMonthModel`
  - the new `PeriodInputsModel` fields
- `routers/accounting.py`: document `ewt_atc`, supplier-rule learning.
- `routers/accounting_periods.py`:
  - company flags and `doc_line` ATC
  - supplier ATC rules in `load_periods`
  - PDF for every form
  - the 2307 ZIP
- `startup_migrations.py`: one line in `_ensure_accounting_rls`.
- `tests/aa_factories.py`: nothing to change; new dataclass fields have defaults.
- Tests updated: `test_aa_diff.py`, `test_aa_compute_basics.py`, `test_accounting_schemas.py`.

**Frontend — modify**
- `frontend/src/types/accounting.ts`, `frontend/src/lib/accounting-api.ts`, `frontend/src/lib/accounting-format.ts`.
- `frontend/src/components/accounting/DocumentPanel.tsx`: the EWT ATC select.
- `frontend/src/components/accounting/PeriodPanel.tsx`: withholding inputs and the payroll grid.
- `frontend/src/components/accounting/OutputViewer.tsx`: the outgoing 2307s download.

---

### Task 1: Expanded withholding computation

**Files:**
- Modify: `backend/app/services/accounting/compute/inputs.py`
- Create: `backend/app/services/accounting/compute/ewt.py`
- Test: `backend/tests/test_aa_ewt.py`, `backend/tests/test_aa_compute_basics.py` (one new test)

**Interfaces:**
- Consumes: `quarter_start(fiscal_year, quarter, fye)` (due_dates), `lookup_atc(code) -> ATCEntry | None` (atc_codes, `entry.nature`, `entry.rate: float | None`), `c2`, `total`, `ZERO` (money).
- Produces:
  - `DocLine` gains `ewt_atc: str = ""` ("" = automatic, `"NONE"` = no withholding, else an ATC) and `counterparty_vat_registered: bool | None = None`.
  - `CompanyFacts` gains `is_withholding_agent: bool = False`, `is_top_withholding_agent: bool = False`, `has_employees: bool = False` (after `fiscal_year_end_month`).
  - `PayrollMonth(mwe_basic, mwe_premium, thirteenth_month, de_minimis, contributions, other_non_taxable, not_subject, adjustment, amended_paid)`, all `Decimal = ZERO`, frozen. `PAYROLL_FIELDS: tuple[str, ...]`.
  - `PeriodInputs` gains:
    - `ewt_remitted_m1: Decimal | None = None`
    - `ewt_remitted_m2: Decimal | None = None`
    - `ewt_over_remittance: Decimal = ZERO`
    - `amended_paid_withholding: Decimal = ZERO`
    - `payroll: tuple[PayrollMonth, PayrollMonth, PayrollMonth] = (PayrollMonth(),) * 3`
  - `inputs_to_json` writes `"payroll": [ {field: str, …} × 3 ]`, and `inputs_from_json` reads it back (padded to 3).
  - `ewt.ATC_NONE = "NONE"`
  - `ewt.atc_info(code) -> tuple[str, Decimal] | None` (nature, rate as a fraction)
  - `ewt.rate_percent(rate) -> Decimal` (0.15 → 15)
  - `ewt.is_corporate_name(name) -> bool`
  - `ewt.is_agent(company) -> bool`
  - `ewt.suggest_atc(line, company) -> str`
  - `ewt.effective_atc(line, company) -> str` ("" = none)
  - `ewt.tax_base(line) -> Decimal`
  - `ewt.month_in_quarter(day, year, quarter, fye) -> int | None`
  - `ewt.EwtRow(line_id, tin, name, address, atc, nature, rate, base, tax, withheld, month)` (frozen)
  - `ewt.EwtResult(rows: list[EwtRow], warnings: list[str])`, with `.month_tax(month) -> Decimal` and `.by_line() -> dict[str, tuple[str, Decimal]]`
  - `ewt.compute_ewt(lines, company, year, quarter) -> EwtResult`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_ewt.py`:

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.ewt import (
    ATC_NONE, atc_info, compute_ewt, effective_atc, is_corporate_name, month_in_quarter, rate_percent, suggest_atc,
    tax_base,
)
from tests.aa_factories import company, expense, purchase

D = Decimal
AGENT = dict(is_withholding_agent=True)


def test_payee_type_from_name():
    assert is_corporate_name("Cebu Fabric Supply Inc.") and is_corporate_name("ABC CORPORATION")
    assert is_corporate_name("SGV & Co.")
    assert not is_corporate_name("Maria Santos") and not is_corporate_name("")


def test_suggestions_follow_account_payee_and_top_agent():
    c = company(**AGENT)
    assert suggest_atc(expense(account="rent", counterparty_name="Ayala Land Inc."), c) == "WC100"
    assert suggest_atc(expense(account="rent", counterparty_name="Pedro Cruz"), c) == "WI100"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="Atty. Reyes"), c) == "WI010"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="Atty. Reyes",
                               counterparty_vat_registered=True), c) == "WI011"
    assert suggest_atc(expense(account="professional_fees", counterparty_name="SGV & Co."), c) == "WC010"
    assert suggest_atc(expense(account="repairs", counterparty_name="BuildRight Corp"), c) == "WC120"
    assert suggest_atc(purchase(counterparty_name="Cebu Fabric Supply Inc."), c) == ""
    top = company(is_top_withholding_agent=True)
    assert suggest_atc(purchase(counterparty_name="Cebu Fabric Supply Inc."), top) == "WC158"
    assert suggest_atc(expense(account="transportation", counterparty_name="Juan Dela Cruz"), top) == "WI160"
    assert suggest_atc(expense(account="utilities", counterparty_name="Meralco Inc."), top) == ""


def test_not_an_agent_withholds_nothing():
    r = compute_ewt([expense(account="rent", gross="10000")], company(), 2026, 3)
    assert r.rows == [] and r.warnings == []


def test_document_choice_overrides_suggestion():
    c = company(**AGENT)
    assert effective_atc(expense(account="rent", ewt_atc=ATC_NONE), c) == ""
    assert effective_atc(expense(account="office_supplies", ewt_atc="wi160"), c) == "WI160"
    assert effective_atc(expense(account="rent", ewt_atc="XX999"), c) == ""
    r = compute_ewt([expense(account="rent", ewt_atc="XX999")], c, 2026, 3)
    assert r.rows == [] and any("fixed rate" in w for w in r.warnings)


def test_tax_base_is_net_of_vat_and_tax_is_base_times_rate():
    l = expense(account="rent", counterparty_name="Ayala Land Inc.", gross="11200", vat="1200", withholding="500",
                doc_date=date(2026, 7, 5))
    assert tax_base(l) == D("10000.00")
    r = compute_ewt([l], company(**AGENT), 2026, 3)
    row = r.rows[0]
    assert (row.atc, row.rate, row.base, row.tax, row.month) == ("WC100", D("0.05"), D("10000.00"), D("500.00"), 1)
    assert r.warnings == []
    assert r.by_line() == {l.id: ("WC100", D("500.00"))}


def test_missing_or_different_withholding_warns_but_reports_computed_tax():
    c = company(**AGENT)
    none = expense(account="rent", gross="10000", doc_date=date(2026, 8, 3))
    off = expense(account="rent", gross="20000", withholding="300", doc_date=date(2026, 9, 3))
    r = compute_ewt([none, off], c, 2026, 3)
    assert [row.tax for row in r.rows] == [D("500.00"), D("1000.00")]
    assert r.month_tax(2) == D("500.00") and r.month_tax(3) == D("1000.00") and r.month_tax(1) == D("0.00")
    assert any("none was withheld" in w for w in r.warnings)
    assert any("differs" in w for w in r.warnings)


def test_withheld_without_atc_warns():
    r = compute_ewt([expense(account="office_supplies", withholding="50")], company(**AGENT), 2026, 3)
    assert r.rows == [] and any("no ATC" in w for w in r.warnings)


def test_month_in_quarter_and_out_of_quarter_dates():
    assert month_in_quarter(date(2026, 7, 31), 2026, 3, 12) == 1
    assert month_in_quarter(date(2026, 9, 1), 2026, 3, 12) == 3
    assert month_in_quarter(date(2026, 10, 1), 2026, 3, 12) is None
    assert month_in_quarter(None, 2026, 3, 12) is None
    assert month_in_quarter(date(2025, 8, 15), 2026, 1, 6) == 2  # June year-end: FY2026 Q1 is Jul–Sep 2025
    r = compute_ewt([expense(account="rent", gross="1000", doc_date=date(2026, 5, 2))], company(**AGENT), 2026, 3)
    assert r.rows[0].month == 3 and any("month 3" in w for w in r.warnings)


def test_rates():
    assert atc_info("WC120") == ("Contractors", D("0.02"))
    assert atc_info("wi158")[1] == D("0.01") and atc_info("nope") is None
    assert rate_percent(D("0.15")) == D("15") and format(rate_percent(D("0.10")), "f") == "10"
```

Add to `backend/tests/test_aa_compute_basics.py`:

```python
def test_withholding_inputs_round_trip():
    from app.services.accounting.compute.inputs import PayrollMonth

    original = PeriodInputs(ewt_remitted_m1=Decimal("500.00"), ewt_over_remittance=Decimal("10.00"),
                            payroll=(PayrollMonth(), PayrollMonth(contributions=Decimal("5000.00"),
                                                                  adjustment=Decimal("-25.00")), PayrollMonth()))
    data = inputs_to_json(original)
    assert data["ewt_remitted_m2"] is None and data["payroll"][1]["contributions"] == "5000.00"
    assert inputs_from_json(data) == original
    assert inputs_from_json({"payroll": [{"de_minimis": "x"}]}).payroll == (PayrollMonth(),) * 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_ewt.py tests/test_aa_compute_basics.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'app.services.accounting.compute.ewt'`, and `TypeError` on the `PeriodInputs`/`DocLine` keywords.

- [ ] **Step 3: Extend the inputs**

In `backend/app/services/accounting/compute/inputs.py`, change the import line to `from dataclasses import dataclass, field, fields`. Add to `DocLine`, after `open_review`:

```python
    ewt_atc: str = ""                                  # "" automatic | "NONE" | an ATC chosen on the document
    counterparty_vat_registered: bool | None = None    # supplier printed a VAT REG TIN
```

Add to `CompanyFacts`, after `fiscal_year_end_month`:

```python
    is_withholding_agent: bool = False
    is_top_withholding_agent: bool = False
    has_employees: bool = False
```

Add before `PeriodInputs`:

```python
@dataclass(frozen=True)
class PayrollMonth:
    """1601-C figures the payroll register doesn't give us, for one month of the quarter."""

    mwe_basic: Decimal = ZERO           # item 15
    mwe_premium: Decimal = ZERO         # item 16
    thirteenth_month: Decimal = ZERO    # item 17
    de_minimis: Decimal = ZERO          # item 18
    contributions: Decimal = ZERO       # item 19 (employee share)
    other_non_taxable: Decimal = ZERO   # item 20
    not_subject: Decimal = ZERO         # item 23
    adjustment: Decimal = ZERO          # item 26 (can be negative)
    amended_paid: Decimal = ZERO        # item 28


PAYROLL_FIELDS = tuple(f.name for f in fields(PayrollMonth))
_NO_PAYROLL = (PayrollMonth(), PayrollMonth(), PayrollMonth())
```

Add to `PeriodInputs`, after `mcit_applies`:

```python
    ewt_remitted_m1: Decimal | None = None             # 1601-EQ item 20 when it differs from the computed 0619-E
    ewt_remitted_m2: Decimal | None = None             # 1601-EQ item 21
    ewt_over_remittance: Decimal = ZERO                # 1601-EQ item 23
    amended_paid_withholding: Decimal = ZERO           # 1601-EQ item 22
    payroll: tuple[PayrollMonth, PayrollMonth, PayrollMonth] = _NO_PAYROLL
```

Extend `_DECIMALS` with `"ewt_remitted_m1", "ewt_remitted_m2", "ewt_over_remittance", "amended_paid_withholding"`, then replace the bodies of the two JSON helpers:

```python
def _payroll_from_json(raw) -> tuple[PayrollMonth, PayrollMonth, PayrollMonth]:
    months: list[PayrollMonth] = []
    for item in (raw if isinstance(raw, list) else [])[:3]:
        kwargs: dict = {}
        for name in PAYROLL_FIELDS:
            value = item.get(name) if isinstance(item, dict) else None
            if value is None or value == "":
                continue
            try:
                kwargs[name] = c2(value)
            except (InvalidOperation, ValueError):
                continue
        months.append(PayrollMonth(**kwargs))
    while len(months) < 3:
        months.append(PayrollMonth())
    return tuple(months)


def inputs_from_json(data: dict | None) -> PeriodInputs:
    """Parse stored inputs; unknown or malformed values fall back to defaults."""
    data = data if isinstance(data, dict) else {}
    kwargs: dict = {}
    for name in _DECIMALS:
        raw = data.get(name)
        if raw is None or raw == "":
            continue
        try:
            kwargs[name] = c2(raw)
        except (InvalidOperation, ValueError):
            continue
    if str(data.get("cit_rate")) in ("20", "25"):
        kwargs["cit_rate"] = int(data["cit_rate"])
    kwargs["mcit_applies"] = bool(data.get("mcit_applies", False))
    kwargs["payroll"] = _payroll_from_json(data.get("payroll"))
    return PeriodInputs(**kwargs)


def inputs_to_json(inputs: PeriodInputs) -> dict:
    out: dict = {}
    for name in _DECIMALS:
        value = getattr(inputs, name)
        out[name] = None if value is None else str(value)
    out["cit_rate"] = inputs.cit_rate
    out["mcit_applies"] = inputs.mcit_applies
    out["payroll"] = [{name: str(getattr(month, name)) for name in PAYROLL_FIELDS} for month in inputs.payroll]
    return out
```

- [ ] **Step 4: Implement the EWT computation**

`backend/app/services/accounting/compute/ewt.py`:

```python
"""Expanded withholding tax (EWT) on the client's payments: ATC, tax base and tax (pure).

The client, as withholding agent, owes base × ATC rate on each payment that needs
withholding whether or not it actually withheld (RR 4-2024 keeps the expense
deductible, but the tax is still due). Rates come from ``services/atc_codes.py``.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import quarter_start
from app.services.accounting.compute.inputs import CompanyFacts, DocLine
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.atc_codes import lookup_atc

ATC_NONE = "NONE"
_EXTRA = {"WC120": ("Contractors", Decimal("0.02"))}  # corporate contractors, missing from atc_codes.py
_CORPORATE_WORDS = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "OPC", "LLC",
    "COOPERATIVE", "COOP", "PARTNERSHIP", "PARTNERS",
})
_TWA_GOODS = frozenset({"purchases", "raw_materials", "office_supplies", "capital_goods"})
_TWA_SERVICES = frozenset({"transportation", "other"})
_PAYMENTS = ("purchases", "expenses")
_MISMATCH = Decimal("1.00")


def atc_info(code: str) -> tuple[str, Decimal] | None:
    """(nature, rate as a fraction) for an ATC with a fixed rate, else None."""
    code = (code or "").strip().upper()
    if code in _EXTRA:
        return _EXTRA[code]
    entry = lookup_atc(code)
    if entry is None or entry.rate is None:
        return None
    return entry.nature, Decimal(str(entry.rate))


def rate_percent(rate: Decimal) -> Decimal:
    """0.15 -> 15 (whole percentages without decimals)."""
    pct = rate * 100
    return pct.quantize(Decimal("1")) if pct == pct.to_integral_value() else pct.normalize()


def is_corporate_name(name: str) -> bool:
    return any(word in _CORPORATE_WORDS for word in re.findall(r"[A-Z]+", (name or "").upper()))


def is_agent(company: CompanyFacts) -> bool:
    return company.is_withholding_agent or company.is_top_withholding_agent


def _is_payment(line: DocLine) -> bool:
    return line.client_role == "buyer" and line.category in _PAYMENTS


def suggest_atc(line: DocLine, company: CompanyFacts) -> str:
    """The usual ATC for this payment, or "" when no withholding is expected."""
    if not is_agent(company) or not _is_payment(line):
        return ""
    prefix = "WC" if is_corporate_name(line.counterparty_name) else "WI"
    if line.account == "rent":
        return f"{prefix}100"
    if line.account == "professional_fees":
        if prefix == "WC":
            return "WC010"
        return "WI011" if line.counterparty_vat_registered else "WI010"
    if line.account == "repairs":
        return f"{prefix}120"
    if company.is_top_withholding_agent:
        if line.account in _TWA_GOODS:
            return f"{prefix}158"
        if line.account in _TWA_SERVICES:
            return f"{prefix}160"
    return ""


def effective_atc(line: DocLine, company: CompanyFacts) -> str:
    """The document's own ATC choice, else the suggestion ("" = no withholding)."""
    if not is_agent(company) or not _is_payment(line):
        return ""
    chosen = (line.ewt_atc or "").strip().upper()
    if chosen == ATC_NONE:
        return ""
    if chosen:
        return chosen if atc_info(chosen) else ""
    return suggest_atc(line, company)


def tax_base(line: DocLine) -> Decimal:
    """Amount paid, net of VAT when the document shows VAT."""
    return c2(line.gross - line.vat) if line.vat > 0 else c2(line.gross)


def month_in_quarter(day: date | None, year: int, quarter: int, fye: int) -> int | None:
    """1–3 for a date inside the quarter's months, else None."""
    if day is None:
        return None
    start = quarter_start(year, quarter, fye)
    index = (day.year - start.year) * 12 + day.month - start.month + 1
    return index if 1 <= index <= 3 else None


@dataclass(frozen=True)
class EwtRow:
    line_id: str
    tin: str
    name: str
    address: str
    atc: str
    nature: str
    rate: Decimal
    base: Decimal
    tax: Decimal
    withheld: Decimal
    month: int


@dataclass
class EwtResult:
    rows: list[EwtRow]
    warnings: list[str]

    def month_tax(self, month: int) -> Decimal:
        return total(r.tax for r in self.rows if r.month == month)

    def by_line(self) -> dict[str, tuple[str, Decimal]]:
        return {r.line_id: (r.atc, r.tax) for r in self.rows}


def compute_ewt(lines, company: CompanyFacts, year: int, quarter: int) -> EwtResult:
    if not is_agent(company):
        return EwtResult([], [])
    rows: list[EwtRow] = []
    outside = not_withheld = mismatched = no_atc = unknown = 0
    for l in lines:
        if not _is_payment(l):
            continue
        chosen = (l.ewt_atc or "").strip().upper()
        if chosen and chosen != ATC_NONE and atc_info(chosen) is None:
            unknown += 1
        atc = effective_atc(l, company)
        if not atc:
            if l.withholding > 0 and chosen != ATC_NONE:
                no_atc += 1
            continue
        nature, rate = atc_info(atc)
        base = tax_base(l)
        tax = c2(base * rate)
        month = month_in_quarter(l.doc_date, year, quarter, company.fiscal_year_end_month)
        if month is None:
            outside += 1
            month = 3
        if l.withholding == 0 and tax > 0:
            not_withheld += 1
        elif abs(l.withholding - tax) > _MISMATCH:
            mismatched += 1
        rows.append(EwtRow(l.id, l.counterparty_tin, l.counterparty_name, l.counterparty_address, atc, nature,
                           rate, base, tax, c2(l.withholding), month))
    warnings: list[str] = []
    if not_withheld:
        warnings.append(f"{not_withheld} payment(s) needed expanded withholding tax but none was withheld. The "
                        "tax is still due from the company and is included in the 0619-E / 1601-EQ.")
    if mismatched:
        warnings.append(f"{mismatched} payment(s) show tax withheld that differs from base × ATC rate; the "
                        "returns use the computed amount.")
    if no_atc:
        warnings.append(f"{no_atc} payment(s) show tax withheld but have no ATC. Set the ATC on the document to "
                        "include them.")
    if unknown:
        warnings.append(f"{unknown} document(s) have an ATC without a fixed rate in the ATC table and were left "
                        "out of the withholding returns.")
    if outside:
        warnings.append(f"{outside} payment(s) are dated outside this quarter's months and were counted in "
                        "month 3.")
    return EwtResult(rows, warnings)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_ewt.py tests/test_aa_compute_basics.py tests/test_aa_engine.py -q`
Expected: PASS. The existing engine tests are unaffected because the new fields have defaults.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/accounting/compute/inputs.py backend/app/services/accounting/compute/ewt.py backend/tests/test_aa_ewt.py backend/tests/test_aa_compute_basics.py
git commit -m "feat(accounting): expanded withholding computation and withholding inputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 2: Withholding return builders (0619-E, 1601-EQ, QAP, 1601-C)

**Files:**
- Create: `backend/app/services/accounting/compute/withholding.py`
- Test: `backend/tests/test_aa_withholding.py`

**Interfaces:**
- Consumes: `EwtResult`, `EwtRow`, `rate_percent`, `month_in_quarter` (Task 1); `PayrollMonth`, `PeriodInputs` (Task 1); `normalize_name` (`services/accounting/matching.py`).
- Produces:
  - `MAX_SCHEDULE_ROWS = 30`.
  - `form_0619e(amount: Decimal) -> dict[str, Decimal]`, with keys `14 15 16 17A 17B 17C 17D 18`.
  - `atc_summary(ewt) -> list[tuple[str, Decimal, Decimal, Decimal]]`, giving (atc, base, rate fraction, tax) sorted by ATC.
  - `form_1601eq(ewt, inputs) -> dict[str, Decimal | str]`:
    - schedule rows `S{i}_ATC` (str), `S{i}_BASE`, `S{i}_RATE` (percent) and `S{i}_TAX`, for i = 1…
    - items `19`–`31`.
  - `build_qap(ewt) -> list[dict]`. Each row has `key, tin, name, address, atc, nature, m1, m2, m3, base, rate (percent), tax`, sorted by name.
  - `payroll_months(lines, year, quarter, fye) -> tuple[dict[int, tuple[Decimal, Decimal]], int]`, giving month → (gross compensation, tax withheld) for `category == "payroll"` lines, and the count dated outside the quarter's months (those go to month 3).
  - `form_1601c(gross, withheld, month: PayrollMonth) -> dict[str, Decimal]`, with items `14`–`36`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_withholding.py`:

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import PayrollMonth, PeriodInputs
from app.services.accounting.compute.withholding import (
    atc_summary, build_qap, form_0619e, form_1601c, form_1601eq, payroll_months,
)
from tests.aa_factories import company, expense, line

D = Decimal
AGENT = company(is_withholding_agent=True)


def _ewt():
    return compute_ewt([
        expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333",
                gross="10000", doc_date=date(2026, 7, 5)),
        expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333",
                gross="10000", doc_date=date(2026, 9, 5)),
        expense(account="professional_fees", counterparty_name="Atty. Reyes", counterparty_tin="444555666",
                gross="20000", doc_date=date(2026, 8, 20)),
    ], AGENT, 2026, 3)


def test_0619e_is_the_month_total():
    f = form_0619e(D("1500"))
    assert f["14"] == f["16"] == f["18"] == D("1500.00") and f["15"] == f["17D"] == D("0.00")


def test_1601eq_schedule_totals_and_remittances():
    ewt = _ewt()
    assert atc_summary(ewt) == [("WC100", D("20000.00"), D("0.05"), D("1000.00")),
                                ("WI010", D("20000.00"), D("0.05"), D("1000.00"))]
    f = form_1601eq(ewt, PeriodInputs())
    assert (f["S1_ATC"], f["S1_BASE"], f["S1_RATE"], f["S1_TAX"]) == ("WC100", D("20000.00"), D("5"), D("1000.00"))
    assert f["S2_ATC"] == "WI010" and "S3_ATC" not in f
    assert f["19"] == D("2000.00")
    assert (f["20"], f["21"]) == (D("500.00"), D("1000.00"))   # computed 0619-E months 1 and 2
    assert f["25"] == D("1500.00") and f["26"] == D("500.00") and f["31"] == D("500.00")


def test_1601eq_uses_amounts_actually_remitted():
    f = form_1601eq(_ewt(), PeriodInputs(ewt_remitted_m1=D("0"), ewt_over_remittance=D("100")))
    assert f["20"] == D("0.00") and f["23"] == D("100.00")
    assert f["26"] == D("900.00")  # 2000 − (0 + 1000 + 100)


def test_qap_one_row_per_payee_and_atc_with_monthly_bases():
    rows = build_qap(_ewt())
    assert [r["name"] for r in rows] == ["Atty. Reyes", "Ayala Land Inc."]
    ayala = rows[1]
    assert ayala["key"] == "111222333|WC100" and ayala["nature"] == "Rentals"
    assert (ayala["m1"], ayala["m2"], ayala["m3"], ayala["base"]) == (D("10000.00"), D("0.00"), D("10000.00"),
                                                                       D("20000.00"))
    assert ayala["rate"] == D("5") and ayala["tax"] == D("1000.00")


def test_1601c_non_taxable_and_withheld():
    month = PayrollMonth(mwe_basic=D("20000"), thirteenth_month=D("5000"), contributions=D("3000"),
                         not_subject=D("12000"), adjustment=D("-50"))
    f = form_1601c(D("100000"), D("6000"), month)
    assert f["21"] == D("28000.00") and f["22"] == D("72000.00") and f["24"] == D("60000.00")
    assert f["25"] == D("6000.00") and f["27"] == D("5950.00") and f["31"] == D("5950.00")
    assert f["36"] == D("5950.00")


def test_payroll_months_counts_out_of_quarter():
    payroll = dict(category="payroll", account="salaries")
    months, outside = payroll_months([
        line(**payroll, gross="50000", withholding="4000", doc_date=date(2026, 7, 31)),
        line(**payroll, gross="50000", withholding="4000", doc_date=date(2026, 8, 31)),
        line(**payroll, gross="10000", withholding="500", doc_date=None),
        expense(gross="999", doc_date=date(2026, 7, 2)),
    ], 2026, 3, 12)
    assert months[1] == (D("50000.00"), D("4000.00"))
    assert months[3] == (D("10000.00"), D("500.00")) and outside == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_withholding.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.accounting.compute.withholding'`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/compute/withholding.py`:

```python
"""Withholding returns from computed EWT and payroll documents (pure): 0619-E, 1601-EQ, QAP and 1601-C."""

from decimal import Decimal

from app.services.accounting.compute.ewt import EwtResult, month_in_quarter, rate_percent
from app.services.accounting.compute.inputs import PayrollMonth, PeriodInputs
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.matching import normalize_name

MAX_SCHEDULE_ROWS = 30


def form_0619e(amount: Decimal) -> dict[str, Decimal]:
    """0619-E (January 2018): the month's expanded withholding tax; no penalties or prior remittance."""
    amount = c2(amount)
    return {"14": amount, "15": ZERO, "16": amount, "17A": ZERO, "17B": ZERO, "17C": ZERO, "17D": ZERO,
            "18": amount}


def atc_summary(ewt: EwtResult) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    groups: dict[str, list] = {}
    for r in ewt.rows:
        group = groups.setdefault(r.atc, [r.rate, ZERO, ZERO])
        group[1] += r.base
        group[2] += r.tax
    return [(atc, c2(base), rate, c2(tax)) for atc, (rate, base, tax) in sorted(groups.items())]


def form_1601eq(ewt: EwtResult, inputs: PeriodInputs) -> dict[str, Decimal | str]:
    """1601-EQ (January 2019): the quarter by ATC, less the two 0619-E remittances."""
    items: dict[str, Decimal | str] = {}
    for i, (atc, base, rate, tax) in enumerate(atc_summary(ewt)[:MAX_SCHEDULE_ROWS], start=1):
        items[f"S{i}_ATC"] = atc
        items[f"S{i}_BASE"] = base
        items[f"S{i}_RATE"] = rate_percent(rate)
        items[f"S{i}_TAX"] = tax
    items["19"] = total(r.tax for r in ewt.rows)
    items["20"] = c2(inputs.ewt_remitted_m1) if inputs.ewt_remitted_m1 is not None else ewt.month_tax(1)
    items["21"] = c2(inputs.ewt_remitted_m2) if inputs.ewt_remitted_m2 is not None else ewt.month_tax(2)
    items["22"] = c2(inputs.amended_paid_withholding)
    items["23"] = c2(inputs.ewt_over_remittance)
    items["24"] = ZERO
    items["25"] = total(items[key] for key in ("20", "21", "22", "23", "24"))
    items["26"] = c2(items["19"] - items["25"])
    for key in ("27", "28", "29", "30"):
        items[key] = ZERO
    items["31"] = c2(items["26"] + items["30"])
    return items


def build_qap(ewt: EwtResult) -> list[dict]:
    """Quarterly alphalist of payees: one row per payee and ATC, with each month's tax base."""
    rows: dict[str, dict] = {}
    for r in ewt.rows:
        party = r.tin or f"NAME:{normalize_name(r.name)}"
        key = f"{party}|{r.atc}"
        row = rows.setdefault(key, {
            "key": key, "tin": r.tin, "name": r.name, "address": r.address, "atc": r.atc, "nature": r.nature,
            "m1": ZERO, "m2": ZERO, "m3": ZERO, "base": ZERO, "rate": rate_percent(r.rate), "tax": ZERO,
        })
        row[f"m{r.month}"] = c2(row[f"m{r.month}"] + r.base)
        row["base"] = c2(row["base"] + r.base)
        row["tax"] = c2(row["tax"] + r.tax)
    return sorted(rows.values(), key=lambda row: (row["name"].lower(), row["key"]))


def payroll_months(lines, year: int, quarter: int, fye: int) -> tuple[dict[int, tuple[Decimal, Decimal]], int]:
    totals: dict[int, list[Decimal]] = {}
    outside = 0
    for l in lines:
        if l.category != "payroll":
            continue
        month = month_in_quarter(l.doc_date, year, quarter, fye)
        if month is None:
            outside += 1
            month = 3
        pair = totals.setdefault(month, [ZERO, ZERO])
        pair[0] += l.gross
        pair[1] += l.withholding
    return {month: (c2(gross), c2(tax)) for month, (gross, tax) in totals.items()}, outside


def form_1601c(gross: Decimal, withheld: Decimal, month: PayrollMonth) -> dict[str, Decimal]:
    """1601-C (January 2018): one month's compensation and tax withheld."""
    i: dict[str, Decimal] = {
        "14": c2(gross), "15": c2(month.mwe_basic), "16": c2(month.mwe_premium),
        "17": c2(month.thirteenth_month), "18": c2(month.de_minimis), "19": c2(month.contributions),
        "20": c2(month.other_non_taxable),
    }
    i["21"] = total(i[key] for key in ("15", "16", "17", "18", "19", "20"))
    i["22"] = c2(i["14"] - i["21"])
    i["23"] = c2(month.not_subject)
    i["24"] = c2(i["22"] - i["23"])
    i["25"] = c2(withheld)
    i["26"] = c2(month.adjustment)
    i["27"] = c2(i["25"] + i["26"])
    i["28"] = c2(month.amended_paid)
    i["29"] = ZERO
    i["30"] = c2(i["28"] + i["29"])
    i["31"] = c2(i["27"] - i["30"])
    for key in ("32", "33", "34", "35"):
        i[key] = ZERO
    i["36"] = c2(i["31"] + i["35"])
    return i
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_withholding.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/withholding.py backend/tests/test_aa_withholding.py
git commit -m "feat(accounting): 0619-E, 1601-EQ, QAP and 1601-C builders

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Engine, specs, due dates and diff

**Files:**
- Modify:
  - `backend/app/services/accounting/compute/engine.py`
  - `backend/app/services/accounting/compute/ledgers.py`
  - `backend/app/services/accounting/compute/specs.py`
  - `backend/app/services/accounting/compute/due_dates.py`
  - `backend/app/services/accounting/diff.py`
- Test:
  - `backend/tests/test_aa_engine_withholding.py`
  - `backend/tests/test_aa_diff.py` (one new test)

**Interfaces:**
- Consumes: `compute_ewt`, `is_agent` (Task 1); `form_0619e`, `form_1601eq`, `build_qap`, `payroll_months`, `form_1601c` (Task 2).
- Produces:
  - `build_quarter(...)` adds these forms:
    - for agents with a calendar-aligned year-end: `0619E-M1`, `0619E-M2` and `1601EQ`, plus the `QAP` ledger when there are payments;
    - for employers, or whenever payroll documents exist: `1601C-M1..M3`.
    - Transactions rows gain `ewt_atc` (str) and `ewt_due` (Decimal).
  - `expected_forms(company, quarter)` lists the new forms in the same order as `FORM_ORDER`.
  - `build_transactions(lines, company_vat, ewt_by_line=None)`.
  - `specs`:
    - `FORM_ORDER`, `FORM_TITLES`, `FORM_ITEMS`, `FORM_NOTES` and `PAYABLE_ITEM` cover the new forms;
    - `LEDGER_ORDER = ("SLS", "SLP", "SAWT", "QAP", "Transactions")`;
    - `PDF_FORMS` covers every return.
  - `due_dates(forms, fiscal_year, quarter, fye)` dates `0619E-Mn`, `1601C-Mn` and `1601EQ`.
  - `diff_snapshots` ignores a ledger column the previous version didn't have.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_engine_withholding.py`:

```python
from datetime import date
from decimal import Decimal

from openpyxl import load_workbook

from app.services.accounting.compute.due_dates import due_dates
from app.services.accounting.compute.engine import build_quarter, expected_forms
from app.services.accounting.compute.inputs import PayrollMonth, PeriodData, PeriodInputs
from app.services.accounting.diff import snapshot
from app.services.accounting.render_xlsx import write_workbook
from tests.aa_factories import company, expense, line, sale

D = Decimal


def P(year, quarter, *lines, **inputs):
    inputs.setdefault("opening_inventory", D("0"))
    inputs.setdefault("ending_inventory", D("0"))
    return PeriodData(year, quarter, tuple(lines), PeriodInputs(**inputs))


def _rent():
    return expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333", gross="11200",
                   vat="1200", vatable="10000", withholding="500", input_vat_valid=True, doc_date=date(2026, 7, 5))


def test_withholding_agent_gets_0619e_1601eq_and_qap():
    c = company(is_withholding_agent=True)
    rent = _rent()
    r = build_quarter(c, [P(2026, 3, rent)])
    assert {"0619E-M1", "0619E-M2", "1601EQ"} <= set(r.forms)
    assert r.forms["0619E-M1"]["18"] == D("500.00") and r.forms["0619E-M2"]["18"] == D("0.00")
    assert r.forms["1601EQ"]["S1_ATC"] == "WC100" and r.forms["1601EQ"]["26"] == D("0.00")
    assert r.ledgers["QAP"][0]["tax"] == D("500.00")
    tx = r.ledgers["Transactions"][0]
    assert tx["ewt_atc"] == "WC100" and tx["ewt_due"] == D("500.00")
    assert expected_forms(c, 3) == ["2550Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ"]


def test_agent_with_no_payments_still_files_zero_returns():
    r = build_quarter(company(is_withholding_agent=True), [P(2026, 3, sale(vatable="1000", vat="120"))])
    assert r.forms["0619E-M1"]["18"] == D("0.00") and r.forms["1601EQ"]["31"] == D("0.00")
    assert "QAP" not in r.ledgers


def test_non_agent_has_no_withholding_forms_but_transactions_show_blank_atc():
    r = build_quarter(company(), [P(2026, 3, _rent())])
    assert not any(form.startswith(("0619E", "1601")) for form in r.forms)
    assert r.ledgers["Transactions"][0]["ewt_atc"] == "" and r.ledgers["Transactions"][0]["ewt_due"] == D("0.00")


def test_fiscal_year_not_on_calendar_quarters_skips_ewt_returns():
    c = company(is_withholding_agent=True, fiscal_year_end_month=5)
    r = build_quarter(c, [P(2026, 1)])
    assert "1601EQ" not in r.forms and any("calendar quarters" in w for w in r.warnings)
    assert "1601EQ" not in expected_forms(c, 1)


def test_employer_gets_three_1601c_months():
    c = company(has_employees=True)
    payroll = line(category="payroll", account="salaries", gross="100000", withholding="8000",
                   doc_date=date(2026, 8, 31))
    months = (PayrollMonth(), PayrollMonth(contributions=D("5000")), PayrollMonth())
    r = build_quarter(c, [P(2026, 3, payroll, payroll=months)])
    assert r.forms["1601C-M2"]["14"] == D("100000.00") and r.forms["1601C-M2"]["22"] == D("95000.00")
    assert r.forms["1601C-M2"]["36"] == D("8000.00") and r.forms["1601C-M1"]["36"] == D("0.00")
    assert expected_forms(c, 4)[-3:] == ["1601C-M1", "1601C-M2", "1601C-M3"]


def test_payroll_without_employee_flag_still_files_1601c_with_warning():
    payroll = line(category="payroll", account="salaries", gross="1000", doc_date=date(2026, 7, 15))
    r = build_quarter(company(), [P(2026, 3, payroll)])
    assert "1601C-M1" in r.forms and any("having employees" in w for w in r.warnings)


def test_due_dates_for_withholding_forms():
    days = due_dates(["0619E-M1", "0619E-M2", "1601EQ", "1601C-M3"], 2026, 3, 12)
    assert days["0619E-M1"] == date(2026, 8, 10)
    assert days["0619E-M2"] == date(2026, 9, 10)
    assert days["1601EQ"] == date(2026, 11, 2)     # Oct 31 is a Saturday
    assert days["1601C-M3"] == date(2026, 10, 12)  # Oct 10 is a Saturday
    assert due_dates(["1601C-M3"], 2026, 4, 12)["1601C-M3"] == date(2027, 1, 15)


def test_workbook_has_withholding_tabs(tmp_path):
    c = company(is_withholding_agent=True, has_employees=True)
    r = build_quarter(c, [P(2026, 3, _rent())])
    path = tmp_path / "w.xlsx"
    write_workbook(path, header={"company": "Juan", "tin": "1", "period": "2026 Q3", "generated": "now"},
                   snapshot=snapshot(r, c), warnings=r.warnings, review_open=0, due={}, version=1)
    names = load_workbook(path).sheetnames
    assert {"0619E-M1", "0619E-M2", "1601EQ", "1601C-M1", "QAP"} <= set(names)
```

Add to `backend/tests/test_aa_diff.py`:

```python
def test_new_ledger_columns_are_not_changes():
    old = snapshot(_result(rows=[{"key": "555", "name": "A"}]), company())
    new = snapshot(_result(rows=[{"key": "555", "name": "A", "ewt_atc": ""}]), company())
    assert diff_snapshots(old, new)["ledgers"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_engine_withholding.py tests/test_aa_diff.py -q`
Expected: FAIL. `KeyError: '0619E-M1'`, a `ewt_atc` key error, missing due dates, and the new-column diff.

- [ ] **Step 3: Due dates**

In `backend/app/services/accounting/compute/due_dates.py`, add after `_next_business_day`:

```python
def _add_months(first: date, n: int) -> date:
    index = first.month - 1 + n
    return date(first.year + index // 12, index % 12 + 1, 1)


def month_start(fiscal_year: int, quarter: int, fye: int, month: int) -> date:
    """First day of month 1–3 of the quarter."""
    return _add_months(quarter_start(fiscal_year, quarter, fye), month - 1)
```

Then extend the `if/elif` chain inside the loop of `due_dates`, after the `elif form == "1701Q" …` branch:

```python
        elif form.startswith(("0619E-M", "1601C-M")):
            following = _add_months(month_start(fiscal_year, quarter, fye, int(form[-1])), 1)
            if form.startswith("1601C") and following.month == 1:
                out[form] = _next_business_day(date(following.year, 1, 15))
            else:
                out[form] = _next_business_day(date(following.year, following.month, 10))
        elif form == "1601EQ":
            following = _add_months(date(end.year, end.month, 1), 1)
            last = calendar.monthrange(following.year, following.month)[1]
            out[form] = _next_business_day(date(following.year, following.month, last))
```

- [ ] **Step 4: Specs**

In `backend/app/services/accounting/compute/specs.py`, replace `FORM_ORDER`, `PAYABLE_ITEM` and `PDF_FORMS`, and add the new titles, items and notes. Put these just after the existing `FORM_TITLES` dict:

```python
WITHHOLDING_MONTHLY = ("0619E-M1", "0619E-M2", "1601C-M1", "1601C-M2", "1601C-M3")
for _m in (1, 2):
    FORM_TITLES[f"0619E-M{_m}"] = (f"BIR Form 0619-E — Monthly Remittance of Expanded Withholding Tax "
                                   f"(month {_m} of the quarter)")
FORM_TITLES["1601EQ"] = "BIR Form 1601-EQ — Quarterly Remittance Return of Expanded Withholding Tax"
for _m in (1, 2, 3):
    FORM_TITLES[f"1601C-M{_m}"] = (f"BIR Form 1601-C — Monthly Remittance Return of Tax Withheld on Compensation "
                                   f"(month {_m} of the quarter)")

FORM_ORDER = ("2550Q", "2551Q", "1701Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ", "1601C-M1", "1601C-M2",
              "1601C-M3", "COGS", "Expenses")
PAYABLE_ITEM = {"2550Q": "26", "2551Q": "24", "1701Q": "68", "1702Q": "25", "0619E-M1": "18", "0619E-M2": "18",
                "1601EQ": "31", "1601C-M1": "36", "1601C-M2": "36", "1601C-M3": "36"}
PDF_FORMS = frozenset({"2550Q", "2551Q", "1701Q", "1702Q", "0619E-M1", "0619E-M2", "1601EQ", "1601C-M1",
                       "1601C-M2", "1601C-M3"})
```

Delete the old one-line definitions of `FORM_ORDER`, `PAYABLE_ITEM` and `PDF_FORMS` above it (keep `WHOLE_PESO_FORMS`). After the `FORM_ITEMS` dict literal, add:

```python
_0619E_ITEMS = (
    ("14", "14 Amount of remittance"), ("15", "15 Less: amount remitted from previously filed form"),
    ("16", "16 Net amount of remittance"), ("17A", "17A Surcharge"), ("17B", "17B Interest"),
    ("17C", "17C Compromise"), ("17D", "17D Total penalties"), ("18", "18 TOTAL AMOUNT OF REMITTANCE"),
)
_1601EQ_SCHEDULE = tuple(
    (f"S{i}_{part}", f"Row {i} · {label}")
    for i in range(1, 31)
    for part, label in (("ATC", "ATC"), ("BASE", "tax base"), ("RATE", "tax rate (%)"), ("TAX", "tax withheld"))
)
_1601EQ_ITEMS = _1601EQ_SCHEDULE + (
    ("19", "19 Total taxes withheld for the quarter"), ("20", "20 Less: remittance made — 1st month"),
    ("21", "21 Less: remittance made — 2nd month"), ("22", "22 Tax remitted in return previously filed"),
    ("23", "23 Over-remittance from previous quarter"), ("24", "24 Other payments made"),
    ("25", "25 Total remittances made"), ("26", "26 Tax still due/(over-remittance)"), ("27", "27 Surcharge"),
    ("28", "28 Interest"), ("29", "29 Compromise"), ("30", "30 Total penalties"),
    ("31", "31 TOTAL AMOUNT STILL DUE/(over-remittance)"),
)
_1601C_ITEMS = (
    ("14", "14 Total amount of compensation"), ("15", "15 Statutory minimum wage (MWEs)"),
    ("16", "16 Holiday, overtime, night shift and hazard pay (MWEs)"), ("17", "17 13th month pay and other benefits"),
    ("18", "18 De minimis benefits"), ("19", "19 SSS, GSIS, PHIC, HDMF contributions and union dues (employee share)"),
    ("20", "20 Other non-taxable compensation"), ("21", "21 Total non-taxable compensation"),
    ("22", "22 Total taxable compensation"), ("23", "23 Less: taxable compensation not subject to withholding"),
    ("24", "24 Net taxable compensation"), ("25", "25 Total taxes withheld"),
    ("26", "26 Add/(less): adjustment from previous months"), ("27", "27 Taxes withheld for remittance"),
    ("28", "28 Less: tax remitted in return previously filed"), ("29", "29 Other remittances made"),
    ("30", "30 Total tax remittances made"), ("31", "31 Tax still due/(over-remittance)"), ("32", "32 Surcharge"),
    ("33", "33 Interest"), ("34", "34 Compromise"), ("35", "35 Total penalties"),
    ("36", "36 TOTAL AMOUNT STILL DUE/(over-remittance)"),
)
for _m in (1, 2):
    FORM_ITEMS[f"0619E-M{_m}"] = _0619E_ITEMS
FORM_ITEMS["1601EQ"] = _1601EQ_ITEMS
for _m in (1, 2, 3):
    FORM_ITEMS[f"1601C-M{_m}"] = _1601C_ITEMS
```

After the `FORM_NOTES` dict literal, add:

```python
for _m in (1, 2):
    FORM_NOTES[f"0619E-M{_m}"] = {"14": "EWT on this month's payments (base × ATC rate)", "16": "14 − 15",
                                  "17D": "Sum of 17A to 17C", "18": "16 + 17D"}
FORM_NOTES["1601EQ"] = {"19": "Sum of the schedule's tax withheld", "20": "0619-E month 1 (or the amount remitted)",
                        "21": "0619-E month 2 (or the amount remitted)", "25": "Sum of 20 to 24", "26": "19 − 25",
                        "31": "26 + 30"}
for _m in (1, 2, 3):
    FORM_NOTES[f"1601C-M{_m}"] = {"14": "Gross pay on this month's payroll documents", "21": "Sum of 15 to 20",
                                  "22": "14 − 21", "24": "22 − 23", "25": "Tax withheld on the payroll documents",
                                  "27": "25 + 26", "30": "28 + 29", "31": "27 − 30", "36": "31 + 35"}
```

Change the ledger specs:

```python
LEDGER_ORDER = ("SLS", "SLP", "SAWT", "QAP", "Transactions")
```

Add `"QAP": "QAP — alphalist of payees (expanded withholding)"` to `LEDGER_TITLES`. Add to `LEDGER_COLUMNS`:

```python
    "QAP": (("tin", "TIN", "text"), ("name", "Payee", "text"), ("atc", "ATC", "text"),
            ("nature", "Nature of income payment", "text"), ("m1", "Month 1 tax base", "money"),
            ("m2", "Month 2 tax base", "money"), ("m3", "Month 3 tax base", "money"),
            ("base", "Total tax base", "money"), ("rate", "Rate (%)", "text"), ("tax", "Tax withheld", "money")),
```

Then append to the `"Transactions"` column tuple, after `("withholding", "Tax withheld", "money")`:

```python
                     ("ewt_atc", "EWT ATC", "text"), ("ewt_due", "EWT required", "money"),
```

- [ ] **Step 5: Ledgers, engine and diff**

In `backend/app/services/accounting/compute/ledgers.py`, replace `build_transactions`:

```python
def build_transactions(lines, company_vat: bool, ewt_by_line: dict | None = None) -> list[dict]:
    ewt_by_line = ewt_by_line or {}
    rows = []
    for l in lines:
        atc, due = ewt_by_line.get(l.id, ("", ZERO))
        rows.append({
            "key": l.id, "doc_date": l.doc_date.isoformat() if l.doc_date else "", "doc_number": l.doc_number,
            "counterparty": l.counterparty_name, "tin": l.counterparty_tin, "category": l.category,
            "account": l.account, "gross": c2(l.gross), "vatable": c2(l.vatable), "vat": c2(l.vat),
            "exempt": c2(l.exempt), "zero_rated": c2(l.zero_rated), "withholding": c2(l.withholding),
            "ewt_atc": atc, "ewt_due": c2(due),
            "input_vat_claimed": "yes" if claims_input_vat(l, company_vat) else "no",
            "needs_review": "yes" if l.open_review else "no",
        })
    return sorted(rows, key=lambda r: (r["doc_date"], r["doc_number"], r["key"]))
```

In `backend/app/services/accounting/compute/engine.py`, add the imports:

```python
from app.services.accounting.compute.ewt import compute_ewt, is_agent
from app.services.accounting.compute.withholding import (
    build_qap, form_0619e, form_1601c, form_1601eq, payroll_months,
)
```

Add a helper below `_cwt`:

```python
def _calendar_quarters(company: CompanyFacts) -> bool:
    """Withholding returns follow calendar quarters; a fiscal year ending Mar/Jun/Sep/Dec lines up with them."""
    return company.fiscal_year_end_month % 3 == 0
```

Insert this block right after section 3 (after `forms["Expenses"] = expenses_form(breakdown)`), before `# 4. Ledgers.`:

```python
    # 3b. Withholding returns.
    ewt = compute_ewt(target.lines, company, target.year, target.quarter)
    withholding_warnings = list(ewt.warnings)
    if is_agent(company):
        if _calendar_quarters(company):
            forms["0619E-M1"] = form_0619e(ewt.month_tax(1))
            forms["0619E-M2"] = form_0619e(ewt.month_tax(2))
            forms["1601EQ"] = form_1601eq(ewt, target.inputs)
        else:
            withholding_warnings.append("Expanded withholding returns follow calendar quarters, which this fiscal "
                                        "year doesn't line up with; 0619-E and 1601-EQ were not prepared.")
    payroll_lines = [l for l in target.lines if l.category == "payroll"]
    if company.has_employees or payroll_lines:
        months, outside = payroll_months(payroll_lines, target.year, target.quarter, company.fiscal_year_end_month)
        for m in (1, 2, 3):
            gross, withheld = months.get(m, (ZERO, ZERO))
            forms[f"1601C-M{m}"] = form_1601c(gross, withheld, target.inputs.payroll[m - 1])
        if outside:
            withholding_warnings.append(f"{outside} payroll document(s) are dated outside this quarter's months and "
                                        "were counted in month 3 of the 1601-C.")
        if payroll_lines and not company.has_employees:
            withholding_warnings.append("Payroll documents were found but the company isn't marked as having "
                                        "employees; the 1601-C was prepared anyway.")
```

In section 4, replace the first ledger line and add the QAP after SAWT:

```python
    ledgers: dict[str, list[dict]] = {
        "Transactions": build_transactions(target.lines, company.vat_registered, ewt.by_line()),
    }
```

```python
    if "1601EQ" in forms and ewt.rows:
        ledgers["QAP"] = build_qap(ewt)
```

At the end of section 5, just before `carry_out = …`, add:

```python
    warnings.extend(withholding_warnings)
```

Replace `expected_forms`:

```python
def expected_forms(company: CompanyFacts, quarter: int) -> list[str]:
    """The returns this taxpayer files for a quarter (same rules as build_quarter)."""
    individual = company.taxpayer_type == "individual"
    forms: list[str] = []
    if company.vat_registered:
        forms.append("2550Q")
    elif not (individual and company.income_tax_option == "eight_percent"):
        forms.append("2551Q")
    if quarter <= 3:
        forms.append("1701Q" if individual else "1702Q")
    if is_agent(company) and _calendar_quarters(company):
        forms += ["0619E-M1", "0619E-M2", "1601EQ"]
    if company.has_employees:
        forms += ["1601C-M1", "1601C-M2", "1601C-M3"]
    return forms
```

In `backend/app/services/accounting/diff.py`, in `diff_snapshots`, change the changed-columns comprehension so a column the previous row didn't have isn't a change:

```python
            columns = {col: [previous.get(col), value] for col, value in row.items()
                       if col != "key" and col in previous and previous.get(col) != value}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_engine_withholding.py tests/test_aa_diff.py tests/test_aa_engine.py tests/test_aa_xlsx.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/accounting/compute/ backend/app/services/accounting/diff.py backend/tests/test_aa_engine_withholding.py backend/tests/test_aa_diff.py
git commit -m "feat(accounting): withholding forms, QAP and 1601-C in quarter outputs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 4: Comb-cell PDF overlay and the six calibrated layouts

**Files:**
- Create: `backend/app/forms/overlay.py`, `backend/app/services/accounting/pdf_overlay.py`
- Create: `backend/app/forms/bir2551q_layout.py`, `bir1701q_layout.py`, `bir1702q_layout.py`, `bir0619e_layout.py`, `bir1601eq_layout.py`, `bir1601c_layout.py`
- Create: `backend/app/forms/templates/bir2551q_jan2018.pdf`, `bir1701q_jan2018.pdf`, `bir1702q_jan2018.pdf`, `bir0619e_jan2018.pdf`, `bir1601eq_jan2019.pdf`, `bir1601c_jan2018.pdf` (official BIR files)
- Test: `backend/tests/test_aa_pdf_overlay.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `overlay.Cell = tuple[float, float]` and `overlay.comb(x0, x1, n) -> tuple[Cell, ...]`.
  - `overlay.Cells(page, cells, baseline, align="left")`, `overlay.Check(page, x, baseline)` and `overlay.Amount(page, pesos, baseline, cents=())`.
  - `overlay.FormLayout(template: Path, sha256: str, cells: dict[str, Cells], checks: dict[str, Check], amounts: dict[str, Amount])`.
  - Each `bir*_layout.LAYOUT: FormLayout`. Amount keys equal the snapshot item keys (1701-Q also has `P3_26`…`P3_31` for Part III; 1601-EQ schedule rows are `S1_*`…`S6_*`).
  - `pdf_overlay.Rendered(pdf: bytes, overflow: tuple[str, ...])` and `pdf_overlay.amount_chars(text, whole) -> tuple[list[str], list[str]] | None`.
  - `pdf_overlay.render_form(layout, *, amounts, cells=None, checks=(), highlights=frozenset(), draft_reviews=0, notes=()) -> Rendered`.

The coordinates below were calibrated on 2026-10-06 from each template's comb tick marks (vector rectangles 4–9 pt tall), checkbox outlines and item-label positions. They were checked by rendering every box and inspecting the result. A comb is a run of equal cells; the baseline sits 2 pt above the comb's bottom ticks.

- [ ] **Step 1: Add the templates**

```bash
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir2551q_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/2551Q%20Jan%202018%20ENCS%20final%20rev%203_copy.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1701q_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1701Q%20Jan%202018%20final%20rev2_copy.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1702q_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1702Q%202018ENCS%20final2.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir0619e_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/0619-E%20Jan%202018%20rev%20final.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1601eq_jan2019.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1601-EQ%20January%202019%20ENCS%20final.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1601c_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1601C%20final%20Jan%202018%20with%20DPA.pdf"
shasum -a 256 backend/app/forms/templates/bir2551q_jan2018.pdf backend/app/forms/templates/bir1701q_jan2018.pdf backend/app/forms/templates/bir1702q_jan2018.pdf backend/app/forms/templates/bir0619e_jan2018.pdf backend/app/forms/templates/bir1601eq_jan2019.pdf backend/app/forms/templates/bir1601c_jan2018.pdf
```

Expected: the six SHA-256 values listed under Global Constraints. If any differs, the BIR has replaced that form. Stop and report it, because the field maps below are calibrated to these exact versions.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_aa_pdf_overlay.py`:

```python
import hashlib

import fitz
import pytest

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701q_layout, bir1702q_layout, bir2551q_layout,
)
from app.forms.overlay import comb
from app.services.accounting.pdf_overlay import amount_chars, render_form

LAYOUTS = {
    "2551Q": bir2551q_layout.LAYOUT, "1701Q": bir1701q_layout.LAYOUT, "1702Q": bir1702q_layout.LAYOUT,
    "0619E": bir0619e_layout.LAYOUT, "1601EQ": bir1601eq_layout.LAYOUT, "1601C": bir1601c_layout.LAYOUT,
}


def _pages(pdf: bytes):
    return [page.get_text("words") for page in fitz.open("pdf", pdf)]


def test_comb_splits_evenly():
    assert comb(0, 30, 3) == ((0, 10), (10, 20), (20, 30))


@pytest.mark.parametrize("name", LAYOUTS)
def test_templates_are_the_calibrated_official_forms(name):
    layout = LAYOUTS[name]
    assert hashlib.sha256(layout.template.read_bytes()).hexdigest() == layout.sha256


def test_amount_chars():
    assert amount_chars("1234.5", whole=False) == (["1", "2", "3", "4"], ["5", "0"])
    assert amount_chars("-480.00", whole=False) == (["(", "4", "8", "0"], ["0", "0)"])
    assert amount_chars("-1234.6", whole=True) == (["(", "1", "2", "3", "5", ")"], [])
    assert amount_chars("0", whole=True) == (["0"], [])
    assert amount_chars("abc", whole=False) is None


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_amount_box_takes_its_digits(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={key: "7" for key in layout.amounts})
    assert out.overflow == ()
    pages = _pages(out.pdf)
    for key, spec in layout.amounts.items():
        x0, x1 = spec.pesos[-1]
        assert any(w[4] == "7" and x0 <= (w[0] + w[2]) / 2 <= x1 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key


@pytest.mark.parametrize("name", LAYOUTS)
def test_every_check_and_cell_lands_on_its_page(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={}, cells={key: "8" * len(spec.cells) for key, spec in layout.cells.items()},
                      checks=list(layout.checks))
    pages = _pages(out.pdf)
    for key, spec in layout.checks.items():
        assert any(w[4] == "X" and abs((w[0] + w[2]) / 2 - spec.x) < 3 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key
    for key, spec in layout.cells.items():
        x0, x1 = spec.cells[0]
        assert any("8" in w[4] and x0 - 1 <= w[0] and abs(w[3] - spec.baseline) < 4 for w in pages[spec.page]), key


def test_too_long_amount_is_printed_whole_and_flagged():
    out = render_form(bir1701q_layout.LAYOUT, amounts={"36": "123456789"})
    assert out.overflow == ("36",)
    doc = fitz.open("pdf", out.pdf)
    assert "123456789" in doc[1].get_text()
    assert "Too long for the boxes" in doc[0].get_text() and "36" in doc[0].get_text()


def test_cells_checks_highlight_draft_and_notes():
    layout = bir2551q_layout.LAYOUT
    out = render_form(layout, amounts={"14": "-480.00"}, cells={"tin": "12345678900000", "S1_1_RATE": "3"},
                      checks=["q3"], highlights=frozenset({"14"}), draft_reviews=2, notes=["Extra note"])
    doc = fitz.open("pdf", out.pdf)
    words = doc[0].get_text("words")
    assert any(w[4] == "(" for w in words) and any(w[4] == "0)" for w in words)
    tin = layout.cells["tin"]
    digits = sorted((w for w in words if w[4].isdigit() and abs(w[3] - tin.baseline) < 4
                     and tin.cells[0][0] <= w[0] <= tin.cells[-1][1]), key=lambda w: w[0])
    assert "".join(w[4] for w in digits) == "12345678900000"
    rate = layout.cells["S1_1_RATE"]
    assert any(w[4] == "3" and rate.cells[1][0] <= (w[0] + w[2]) / 2 <= rate.cells[1][1]
               for w in doc[1].get_text("words"))  # right-aligned into the second cell
    fills = [d.get("fill") for d in doc[0].get_drawings() if d.get("fill")]
    assert any(abs(f[0] - 1.0) < 0.01 and abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)
    assert "DRAFT" in doc[1].get_text()
    footer = doc[0].get_text()
    assert "Highlighted = changed" in footer and "Extra note" in footer
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_overlay.py -q`
Expected: FAIL with `ImportError: cannot import name 'bir0619e_layout' from 'app.forms'`.

- [ ] **Step 4: Implement the overlay shapes and renderer**

`backend/app/forms/overlay.py`:

```python
"""Shared shapes for BIR "comb" form overlays: one character per printed cell.

Coordinates are PDF points, origin top-left (PyMuPDF). A cell is an (x0, x1)
pair; ``comb`` splits a run of equal cells, and runs are joined with ``+`` where
a box has printed separators (a TIN's dashes, an amount's decimal point).
"""

from dataclasses import dataclass
from pathlib import Path

Cell = tuple[float, float]


def comb(x0: float, x1: float, n: int) -> tuple[Cell, ...]:
    """``n`` equal cells across [x0, x1]."""
    step = (x1 - x0) / n
    return tuple((round(x0 + step * i, 2), round(x0 + step * (i + 1), 2)) for i in range(n))


@dataclass(frozen=True)
class Cells:
    """Text written one character per cell; a single cell takes the whole text, centred."""

    page: int
    cells: tuple[Cell, ...]
    baseline: float
    align: str = "left"  # left | right


@dataclass(frozen=True)
class Check:
    page: int
    x: float
    baseline: float


@dataclass(frozen=True)
class Amount:
    """Digits one per cell, right-aligned; ``cents=()`` for whole-peso returns."""

    page: int
    pesos: tuple[Cell, ...]
    baseline: float
    cents: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class FormLayout:
    template: Path
    sha256: str
    cells: dict[str, Cells]
    checks: dict[str, Check]
    amounts: dict[str, Amount]
```

`backend/app/services/accounting/pdf_overlay.py`:

```python
"""Fill a flat BIR form from a ``FormLayout`` (PyMuPDF overlay, one character per comb cell)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import fitz  # PyMuPDF

from app.forms.overlay import Amount, Cells, FormLayout

FONT = "helv"
CELL_SIZE = 9.0
CHECK_SIZE = 9.0
YELLOW_RGB = (1.0, 0.957, 0.702)
RED_RGB = (0.71, 0.14, 0.09)
BLACK = (0, 0, 0)


@dataclass(frozen=True)
class Rendered:
    pdf: bytes
    overflow: tuple[str, ...]  # amount keys whose digits did not fit their cells


def amount_chars(text: str, whole: bool) -> tuple[list[str], list[str]] | None:
    """'-1234.5' -> (['(', '1', '2', '3', '4'], ['5', '0)']); whole pesos -> (['(', '1', '2', '3', '5', ')'], [])."""
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    negative = value < 0
    if whole:
        digits = list(str(abs(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        return (["("] + digits + [")"] if negative else digits), []
    pesos, cents = f"{abs(value):.2f}".split(".")
    cents_chars = list(cents)
    if negative:
        cents_chars[-1] += ")"
        return ["("] + list(pesos), cents_chars
    return list(pesos), cents_chars


def _width(text: str, size: float) -> float:
    return fitz.get_text_length(text, fontname=FONT, fontsize=size)


def _centre(page, x: float, y: float, text: str, size: float = CELL_SIZE) -> None:
    page.insert_text((x - _width(text, size) / 2, y), text, fontname=FONT, fontsize=size, color=BLACK)


def _in_cells(page, cells, baseline: float, chars: list[str]) -> None:
    for (x0, x1), char in zip(cells, chars):
        if char.strip():
            _centre(page, (x0 + x1) / 2, baseline, char)


def _write_cells(page, spec: Cells, text: str) -> None:
    if len(spec.cells) == 1:
        x0, x1 = spec.cells[0]
        _centre(page, (x0 + x1) / 2, spec.baseline, text)
        return
    chars = list(text[: len(spec.cells)])
    cells = spec.cells[len(spec.cells) - len(chars):] if spec.align == "right" else spec.cells
    _in_cells(page, cells, spec.baseline, chars)


def _write_amount(page, spec: Amount, text: str) -> bool:
    """Write an amount; False when its digits overflow the pesos cells (then printed right-aligned, uncut)."""
    parts = amount_chars(text, whole=not spec.cents)
    if parts is None:
        return True
    pesos, cents = parts
    _in_cells(page, spec.cents, spec.baseline, cents)
    if len(pesos) <= len(spec.pesos):
        _in_cells(page, spec.pesos[len(spec.pesos) - len(pesos):], spec.baseline, pesos)
        return True
    right = spec.pesos[-1][1] - 1
    joined = "".join(pesos)
    page.insert_text((right - _width(joined, CELL_SIZE), spec.baseline), joined, fontname=FONT,
                     fontsize=CELL_SIZE, color=RED_RGB)
    return False


def _highlight(page, spec: Amount) -> None:
    x0 = spec.pesos[0][0]
    x1 = (spec.cents or spec.pesos)[-1][1]
    page.draw_rect(fitz.Rect(x0, spec.baseline - 9, x1, spec.baseline + 2.5), color=None, fill=YELLOW_RGB,
                   fill_opacity=0.85, overlay=True)


def render_form(layout: FormLayout, *, amounts: dict[str, str], cells: dict[str, str] | None = None,
                checks: Iterable[str] = (), highlights: frozenset[str] = frozenset(),
                draft_reviews: int = 0, notes: Sequence[str] = ()) -> Rendered:
    doc = fitz.open(layout.template)
    overflow: list[str] = []
    try:
        for key, text in (cells or {}).items():
            spec = layout.cells.get(key)
            if spec is not None and text:
                _write_cells(doc[spec.page], spec, text)
        for key in checks:
            spec = layout.checks.get(key)
            if spec is not None:
                _centre(doc[spec.page], spec.x, spec.baseline, "X", CHECK_SIZE)
        for key, text in amounts.items():
            spec = layout.amounts.get(key)
            if spec is None or text in (None, ""):
                continue
            page = doc[spec.page]
            if key in highlights:
                _highlight(page, spec)
            if not _write_amount(page, spec, text):
                overflow.append(key)

        notes = list(notes)
        if any(key in layout.amounts for key in highlights):
            notes.append("Highlighted = changed since the previous version")
        if overflow:
            notes.append("Too long for the boxes (printed in red): " + ", ".join(overflow))
        if notes:
            first = doc[0]
            first.insert_text((24, first.rect.height - 3), " · ".join(notes), fontname=FONT, fontsize=7,
                              color=BLACK)
        if draft_reviews:
            for page in doc:
                page.insert_text((24, 10), f"DRAFT — {draft_reviews} document(s) unreviewed — not for filing",
                                 fontname=FONT, fontsize=9, color=RED_RGB)
        return Rendered(doc.tobytes(garbage=3, deflate=True), tuple(overflow))
    finally:
        doc.close()
```

- [ ] **Step 5: Add the six layouts**

`backend/app/forms/bir2551q_layout.py`:

```python
"""Overlay map for BIR Form 2551-Q (January 2018 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.2 pt wide) and box
outlines; baselines sit 2 pt above each comb's bottom ticks.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_P1_PESOS, _P1_CENTS = comb(376.9, 547.4, 12), comb(561.7, 590.1, 2)
_P1_ROWS = {"14": 377.8, "15": 407.5, "16": 425.9, "17": 444.1, "18": 462.4, "19": 480.6, "20": 510.2,
            "21": 528.5, "22": 546.7, "23": 565.0, "24": 583.7}
_DUE_PESOS, _DUE_CENTS = comb(363.3, 533.5, 12), comb(547.5, 576.0, 2)

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir2551q_jan2018.pdf",
    sha256="1f270ecf66d778836a14697863e420ff65d5ed0a5576a6cf58b97c9a8e8c9b24",
    cells={
        "year_ended": Cells(0, comb(136.3, 164.7, 2) + comb(164.7, 221.5, 4), 142.4),
        "tin": Cells(0, comb(220.8, 263.3, 3) + comb(277.5, 320.1, 3) + comb(334.4, 377.0, 3)
                     + comb(391.1, 462.1, 5), 175.9),
        "rdo": Cells(0, comb(547.4, 590.1, 3), 175.9),
        "name": Cells(0, comb(23.0, 590.1, 40), 205.0),
        "address": Cells(0, comb(23.0, 590.1, 40), 234.2),
        "address_2": Cells(0, comb(23.0, 462.1, 31), 252.4),
        "zip": Cells(0, comb(533.1, 590.1, 4), 252.4),
        "S1_1_ATC": Cells(1, comb(37.2, 108.1, 5), 178.3),
        "S1_1_RATE": Cells(1, comb(320.7, 349.1, 2), 178.3, align="right"),
    },
    checks={
        "calendar": Check(0, 91.8, 122.5), "fiscal": Check(0, 164.1, 122.5),
        "q1": Check(0, 251.1, 135.9), "q2": Check(0, 293.4, 136.2), "q3": Check(0, 335.8, 135.9),
        "q4": Check(0, 377.9, 135.6),
        "amended_yes": Check(0, 432.4, 136.7), "amended_no": Check(0, 474.1, 137.3),
        "relief_no": Check(0, 241.7, 297.0),
        "rate_graduated": Check(0, 187.9, 337.5), "rate_eight": Check(0, 355.2, 337.7),
    },
    amounts={
        **{key: Amount(0, _P1_PESOS, y, _P1_CENTS) for key, y in _P1_ROWS.items()},
        "S1_1_TAXABLE": Amount(1, comb(108.1, 278.2, 12), 178.3, comb(292.4, 320.7, 2)),
        "S1_1_DUE": Amount(1, _DUE_PESOS, 178.3, _DUE_CENTS),
        "S1_7": Amount(1, _DUE_PESOS, 287.8, _DUE_CENTS),
    },
)
```

`backend/app/forms/bir1701q_layout.py`:

```python
"""Overlay map for BIR Form 1701-Q (January 2018 ENCS), page 612 × 936.

Whole pesos only. Column A (taxpayer) is filled; column B (spouse) is not
modelled. Calibrated from the template's comb tick marks; baselines sit 2 pt
above the bottom ticks. Part III items 26–31 summarise Part V (keys ``P3_*``).
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_PART_III = comb(362.3, 479.3, 8)
_PART_V = comb(355.6, 476.3, 8)
_P2_ROWS = {"36": 174.9, "37": 190.9, "38": 206.8, "39": 233.7, "40": 260.5, "41": 276.5, "42": 292.4,
            "43": 308.4, "44": 325.3, "45": 341.2, "46": 357.2, "47": 388.7, "48": 404.6, "49": 420.6,
            "50": 436.4, "51": 452.5, "52": 469.5, "53": 485.5, "54": 502.5, "55": 533.9, "56": 549.8,
            "57": 565.8, "58": 581.8, "59": 597.7, "60": 613.7, "61": 629.7, "62": 645.6, "63": 665.2,
            "64": 696.6, "65": 712.6, "66": 728.5, "67": 744.6, "68": 764.2}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1701q_jan2018.pdf",
    sha256="c731d3f12556e6f19ab81f6113ca7c4a23f7ed099675c03451ac0074d96b85ed",
    cells={
        "year": Cells(0, comb(87.6, 145.6, 4), 108.8),
        "tin": Cells(0, comb(198.5, 242.1, 3) + comb(256.2, 299.9, 3) + comb(314.0, 357.5, 3), 140.2),
        "rdo": Cells(0, comb(532.9, 580.9, 3), 140.2),
        "name": Cells(0, comb(15.6, 595.6, 40), 216.2),
        "address": Cells(0, comb(15.6, 595.6, 40), 243.7),
        "address_2": Cells(0, comb(15.6, 475.5, 32), 260.8),
        "zip": Cells(0, comb(532.9, 595.6, 4), 260.8),
    },
    checks={
        "q1": Check(0, 195.2, 104.9), "q2": Check(0, 239.3, 104.9), "q3": Check(0, 297.1, 103.8),
        "amended_yes": Check(0, 428.9, 104.9), "amended_no": Check(0, 470.5, 105.8),
        "single_proprietor": Check(0, 119.6, 154.5),
        "atc_II012": Check(0, 163.6, 171.6), "atc_II015": Check(0, 163.7, 185.5),
        "foreign_credits_no": Check(0, 556.9, 313.5),
        "rate_graduated": Check(0, 66.5, 339.9), "rate_eight": Check(0, 67.2, 361.4),
        "itemized": Check(0, 233.9, 339.6), "osd": Check(0, 364.7, 339.5),
    },
    amounts={
        "P3_26": Amount(0, _PART_III, 600.1), "P3_27": Amount(0, _PART_III, 616.1),
        "P3_28": Amount(0, _PART_III, 632.1), "P3_29": Amount(0, _PART_III, 648.0),
        "P3_30": Amount(0, _PART_III, 664.0), "P3_31": Amount(0, comb(420.9, 536.9, 8), 679.9),
        **{key: Amount(1, _PART_V, y) for key, y in _P2_ROWS.items()},
    },
)
```

`backend/app/forms/bir1702q_layout.py`:

```python
"""Overlay map for BIR Form 1702-Q (January 2018 ENCS), page 612 × 936.

Whole pesos only ("DO NOT enter Centavos"). Calibrated from the template's comb
tick marks (cells are 15.2 pt wide); baselines sit 2 pt above the bottom ticks.
Schedule 1 (special-rate income) is not filled: AutoAccounting does not model it.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_PESOS = comb(412.2, 594.2, 12)
_PART_II = {"14": 395.0, "15": 414.3, "16": 433.8, "17": 453.2, "18": 472.5, "19": 492.0, "20": 511.4,
            "21": 530.8, "22": 550.2, "23": 569.6, "24": 589.0, "25": 609.5}
_SCHEDULES = {"S2_1": 393.6, "S2_2": 410.7, "S2_3": 427.8, "S2_4": 444.9, "S2_5": 462.0, "S2_6": 479.0,
              "S2_7": 496.2, "S2_8": 513.2, "S2_9": 530.4, "S2_11": 564.6, "S2_12": 581.6, "S2_13": 599.5,
              "S3_1": 633.3, "S3_2": 650.3, "S3_3": 667.5, "S3_4": 684.5, "S3_6": 720.9,
              "S4_1": 754.6, "S4_2": 771.7, "S4_3": 788.8, "S4_4": 805.9, "S4_5": 823.0, "S4_6": 840.2,
              "S4_7": 903.5}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1702q_jan2018.pdf",
    sha256="589e22190b9211571cb8a0ba14c97c17dff250f3b8ee9f9e8f6cc3b37b1b1be4",
    cells={
        "year_month": Cells(0, comb(33.8, 60.6, 2), 158.3),
        "year_yy": Cells(0, comb(82.6, 108.7, 2), 158.3),
        "tin": Cells(0, comb(215.1, 260.6, 3) + comb(275.8, 321.3, 3) + comb(336.4, 381.9, 3), 193.4),
        "rdo": Cells(0, comb(533.5, 579.0, 3), 193.4),
        "name": Cells(0, comb(18.0, 594.2, 38), 223.6),
        "name_2": Cells(0, comb(18.0, 594.2, 38), 241.9),
        "address": Cells(0, comb(18.0, 594.2, 38), 272.1),
        "address_2": Cells(0, comb(18.0, 472.9, 30), 290.4),
        "zip": Cells(0, comb(533.5, 594.2, 4), 290.4),
        "S2_10": Cells(1, comb(548.7, 579.0, 2), 547.4, align="right"),
    },
    checks={
        "calendar": Check(0, 56.5, 132.5), "fiscal": Check(0, 112.8, 132.1),
        "q1": Check(0, 162.1, 147.9), "q2": Check(0, 189.5, 148.1), "q3": Check(0, 218.5, 147.7),
        "amended_yes": Check(0, 262.7, 149.5), "amended_no": Check(0, 306.1, 149.5),
        "itemized": Check(0, 142.4, 335.4), "osd": Check(0, 358.7, 335.8),
        "relief_no": Check(0, 227.5, 353.8),
    },
    amounts={
        **{key: Amount(0, _PESOS, y) for key, y in _PART_II.items()},
        **{key: Amount(1, _PESOS, y) for key, y in _SCHEDULES.items()},
    },
)
```

`backend/app/forms/bir0619e_layout.py`:

```python
"""Overlay map for BIR Form 0619-E (January 2018), page 612 × 792.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_PESOS, _CENTS = comb(391.9, 550.5, 11), comb(564.9, 593.8, 2)
_ROWS = {"14": 337.3, "15": 355.5, "16": 373.8, "17A": 402.8, "17B": 421.0, "17C": 439.3, "17D": 457.5,
         "18": 475.8}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir0619e_jan2018.pdf",
    sha256="0418160d63d4e6f68c34f2bad553273a5d148c3686d8562d338d35fcdd0c5215",
    cells={
        "month": Cells(0, comb(46.1, 131.5, 6), 147.4),
        "due_date": Cells(0, comb(145.9, 260.8, 8), 147.4),
        "tin": Cells(0, comb(218.1, 261.3, 3) + comb(276.0, 319.3, 3) + comb(334.0, 377.2, 3)
                     + comb(392.1, 464.1, 5), 181.1),
        "rdo": Cells(0, comb(536.1, 579.3, 3), 181.1),
        "name": Cells(0, comb(17.6, 593.8, 40), 209.8),
        "address": Cells(0, comb(17.6, 593.8, 40), 238.4),
        "address_2": Cells(0, comb(17.6, 464.1, 31), 256.7),
        "zip": Cells(0, comb(536.1, 593.8, 4), 256.7),
    },
    checks={
        "amended_yes": Check(0, 282.4, 143.5), "amended_no": Check(0, 325.9, 143.6),
        "withheld_yes": Check(0, 383.5, 143.7), "withheld_no": Check(0, 427.3, 143.9),
        "private": Check(0, 452.1, 271.4),
    },
    amounts={key: Amount(0, _PESOS, y, _CENTS) for key, y in _ROWS.items()},
)
```

`backend/app/forms/bir1601eq_layout.py`:

```python
"""Overlay map for BIR Form 1601-EQ (January 2019 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks. Part II has six ATC rows (items 13–18), keyed S1_*…S6_*.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_TAX_PESOS, _TAX_CENTS = comb(390.7, 549.1, 11), comb(564.2, 594.5, 2)
_SCHEDULE_Y = {1: 310.9, 2: 328.4, 3: 345.8, 4: 363.3, 5: 380.7, 6: 398.2}  # schedule row i is form item 12 + i
_TOTALS = {"19": 415.7, "20": 433.0, "21": 450.6, "22": 468.0, "23": 485.5, "24": 502.9, "25": 520.4,
           "26": 537.8, "27": 555.3, "28": 572.8, "29": 590.2, "30": 607.7, "31": 625.1}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1601eq_jan2019.pdf",
    sha256="5277addc6778c96a53fde99b8664b1a5213fcea638dea06033c9acf22ee73c25",
    cells={
        "year": Cells(0, comb(32.0, 89.7, 4), 126.1),
        "tin": Cells(0, comb(233.1, 276.0, 3) + comb(290.4, 333.4, 3) + comb(347.8, 390.8, 3)
                     + comb(405.2, 476.9, 5), 159.8),
        "rdo": Cells(0, comb(549.1, 594.5, 3), 159.8),
        "name": Cells(0, comb(17.6, 594.5, 40), 187.3),
        "address": Cells(0, comb(17.6, 594.5, 40), 214.6),
        "address_2": Cells(0, comb(17.6, 462.5, 31), 231.8),
        "zip": Cells(0, comb(534.1, 594.5, 4), 231.8),
        **{f"S{i}_ATC": Cells(0, comb(32.6, 104.2, 5), y) for i, y in _SCHEDULE_Y.items()},
        **{f"S{i}_RATE": Cells(0, ((319.0, 390.7),), y) for i, y in _SCHEDULE_Y.items()},
    },
    checks={
        "q1": Check(0, 124.3, 123.3), "q2": Check(0, 168.4, 123.7), "q3": Check(0, 211.3, 123.7),
        "q4": Check(0, 255.4, 123.3),
        "amended_yes": Check(0, 312.4, 123.7), "amended_no": Check(0, 356.3, 123.6),
        "withheld_yes": Check(0, 413.3, 123.3), "withheld_no": Check(0, 456.3, 123.5),
        "private": Check(0, 454.1, 247.3),
    },
    amounts={
        **{f"S{i}_BASE": Amount(0, comb(104.2, 275.9, 12), y, comb(290.3, 319.0, 2))
           for i, y in _SCHEDULE_Y.items()},
        **{f"S{i}_TAX": Amount(0, _TAX_PESOS, y, _TAX_CENTS) for i, y in _SCHEDULE_Y.items()},
        **{key: Amount(0, _TAX_PESOS, y, _TAX_CENTS) for key, y in _TOTALS.items()},
    },
)
```

`backend/app/forms/bir1601c_layout.py`:

```python
"""Overlay map for BIR Form 1601-C (January 2018 ENCS), page 612 × 936.

Calibrated from the template's comb tick marks (cells are 14.4 pt wide);
baselines sit 2 pt above the bottom ticks. Part IV (adjustment schedules) is not filled.
"""

from pathlib import Path

from app.forms.overlay import Amount, Cells, Check, FormLayout, comb

_PESOS, _CENTS = comb(390.8, 549.1, 11), comb(564.2, 594.5, 2)
_ROWS = {"14": 307.4, "15": 333.1, "16": 349.0, "17": 364.9, "18": 380.8, "19": 396.8, "20": 412.8,
         "21": 428.7, "22": 444.7, "23": 460.7, "24": 476.6, "25": 492.6, "26": 508.5, "27": 524.5,
         "28": 540.3, "29": 556.3, "30": 573.0, "31": 589.0, "32": 604.8, "33": 620.8, "34": 636.7,
         "35": 652.7, "36": 668.7}

LAYOUT = FormLayout(
    template=Path(__file__).parent / "templates" / "bir1601c_jan2018.pdf",
    sha256="c8faaa71015337a73b4ceb96bfb265c539589ab5e10eb27899bb81f87f417397",
    cells={
        "month": Cells(0, comb(46.4, 132.3, 6), 125.2),
        "tin": Cells(0, comb(233.1, 276.0, 3) + comb(290.4, 333.4, 3) + comb(347.8, 390.8, 3)
                     + comb(405.2, 476.9, 5), 155.5),
        "rdo": Cells(0, comb(549.1, 594.5, 3), 155.5),
        "name": Cells(0, comb(17.6, 594.5, 40), 181.9),
        "address": Cells(0, comb(17.6, 594.5, 40), 208.1),
        "address_2": Cells(0, comb(17.6, 462.5, 31), 224.1),
        "zip": Cells(0, comb(534.1, 594.5, 4), 224.1),
    },
    checks={
        "amended_yes": Check(0, 190.3, 122.0), "amended_no": Check(0, 238.1, 122.3),
        "withheld_yes": Check(0, 311.3, 122.4), "withheld_no": Check(0, 351.9, 121.8),
        "private": Check(0, 454.1, 239.6), "relief_no": Check(0, 225.4, 275.0),
    },
    amounts={key: Amount(0, _PESOS, y, _CENTS) for key, y in _ROWS.items()},
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_overlay.py tests/test_aa_pdf_2550q.py -q`
Expected: PASS (22 overlay tests; the 2550-Q tests are untouched).

- [ ] **Step 7: Commit**

```bash
git add backend/app/forms/overlay.py backend/app/forms/bir2551q_layout.py backend/app/forms/bir1701q_layout.py backend/app/forms/bir1702q_layout.py backend/app/forms/bir0619e_layout.py backend/app/forms/bir1601eq_layout.py backend/app/forms/bir1601c_layout.py backend/app/forms/templates/bir2551q_jan2018.pdf backend/app/forms/templates/bir1701q_jan2018.pdf backend/app/forms/templates/bir1702q_jan2018.pdf backend/app/forms/templates/bir0619e_jan2018.pdf backend/app/forms/templates/bir1601eq_jan2019.pdf backend/app/forms/templates/bir1601c_jan2018.pdf backend/app/services/accounting/pdf_overlay.py backend/tests/test_aa_pdf_overlay.py
git commit -m "feat(accounting): comb-cell PDF overlay and calibrated BIR layouts

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Fill each return from a version

**Files:**
- Create: `backend/app/services/accounting/pdf_returns.py`
- Test: `backend/tests/test_aa_pdf_returns.py`

**Interfaces:**
- Consumes: `LAYOUT`s and `render_form` (Task 4); `due_dates`, `month_start`, `quarter_start`, `quarter_end` (Task 3 / Phase 2).
- Produces:
  - `LAYOUTS: dict[str, FormLayout]` keyed by base form (`2551Q 1701Q 1702Q 0619E 1601EQ 1601C`).
  - `ReturnHeader(tin, branch_code, rdo_code, name, address, zip_code, taxpayer_type, income_tax_option, deduction_method, fiscal_year_end_month, fiscal_year, quarter)`, with `.period_from` and `.period_to`.
  - `header_from_snapshot(company: dict, fiscal_year, quarter) -> ReturnHeader`.
  - `split_form(form) -> tuple[str, int | None]` and `wrap(text, widths) -> list[str]`.
  - `render_return(form, values: dict[str, str], header, *, highlights=frozenset(), amended=False, draft_reviews=0) -> Rendered`. It raises `ValueError` for a form without a layout (the 2550-Q keeps its Phase 2 renderer).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_pdf_returns.py`:

```python
import fitz
import pytest

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701q_layout, bir1702q_layout, bir2551q_layout,
)
from app.services.accounting.pdf_returns import header_from_snapshot, render_return, split_form, wrap

COMPANY = {
    "registered_name": "Juan's Cloth Trading Corporation", "tin": "123456789", "branch_code": "00000",
    "rdo_code": "030", "address": "123 Rizal Avenue, Quiapo, Manila", "zip_code": "1001",
    "taxpayer_type": "corporation", "income_tax_option": "graduated", "deduction_method": "itemized",
    "fiscal_year_end_month": 12,
}


def H(year=2026, quarter=3, **company):
    return header_from_snapshot({**COMPANY, **company}, year, quarter)


def _words(pdf: bytes, page: int = 0):
    return fitz.open("pdf", pdf)[page].get_text("words")


def _ticked(words, check) -> bool:
    return any(w[4] == "X" and abs((w[0] + w[2]) / 2 - check.x) < 3 and abs(w[3] - check.baseline) < 4
               for w in words)


_PRINTED = {"-", "/", ".", "●", "%"}  # separators printed on the template itself


def _text_in(words, cells, baseline) -> str:
    inside = [w for w in words if w[4] not in _PRINTED and abs(w[3] - baseline) < 4
              and cells[0][0] - 1 <= (w[0] + w[2]) / 2 <= cells[-1][1] + 1]
    return "".join(w[4] for w in sorted(inside, key=lambda w: w[0]))


def _amount(words, spec) -> str:
    return _text_in(words, spec.pesos + spec.cents, spec.baseline)


def test_split_form_and_wrap():
    assert split_form("0619E-M2") == ("0619E", 2) and split_form("1601EQ") == ("1601EQ", None)
    assert wrap("Juan's Cloth Trading", [8, 8]) == ["JUAN'S", "CLOTH"]
    assert wrap("Supercalifragilistic", [5, 5]) == ["SUPER", "CALIF"]
    assert wrap("", [3]) == [""]


def test_header_from_an_older_snapshot_uses_defaults():
    h = header_from_snapshot({"registered_name": "A", "tin": "123456789"}, 2026, 2)
    assert (h.branch_code, h.fiscal_year_end_month, h.taxpayer_type) == ("00000", 12, "corporation")
    assert (h.period_from.isoformat(), h.period_to.isoformat()) == ("2026-04-01", "2026-06-30")


def test_unknown_form_is_rejected():
    with pytest.raises(ValueError):
        render_return("2550Q", {}, H())


def test_2551q_header_and_amounts():
    L = bir2551q_layout.LAYOUT
    values = {"S1_1_ATC": "PT 010", "S1_1_TAXABLE": "100000.00", "S1_1_RATE": "3", "S1_1_DUE": "3000.00",
              "S1_7": "3000.00", "14": "3000.00", "24": "3000.00"}
    pdf = render_return("2551Q", values, H()).pdf
    p1, p2 = _words(pdf, 0), _words(pdf, 1)
    for check in ("q3", "calendar", "amended_no", "relief_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _text_in(p1, L.cells["tin"].cells, L.cells["tin"].baseline) == "12345678900000"
    assert _text_in(p1, L.cells["year_ended"].cells, L.cells["year_ended"].baseline) == "122026"
    assert _text_in(p1, L.cells["name"].cells, L.cells["name"].baseline) == "JUAN'SCLOTHTRADINGCORPORATION"
    assert _amount(p1, L.amounts["14"]) == "300000"
    assert _text_in(p2, L.cells["S1_1_ATC"].cells, L.cells["S1_1_ATC"].baseline) == "PT010"


def test_1701q_graduated_and_eight_percent_choices():
    L = bir1701q_layout.LAYOUT
    graduated = {"36": "500000", "46": "22500", "62": "0", "63": "22500", "67": "0", "68": "22500"}
    pdf = render_return("1701Q", graduated, H(quarter=2, taxpayer_type="individual"),
                        highlights=frozenset({"46"})).pdf
    p1 = _words(pdf, 0)
    for check in ("q2", "atc_II012", "rate_graduated", "itemized", "single_proprietor", "foreign_credits_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _amount(p1, L.amounts["P3_26"]) == "22500" and _amount(p1, L.amounts["P3_31"]) == "22500"
    assert _amount(_words(pdf, 1), L.amounts["36"]) == "500000"
    fills = [d.get("fill") for d in fitz.open("pdf", pdf)[0].get_drawings() if d.get("fill")]
    assert any(abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)  # Part III mirrors item 46

    eight = {"47": "900000", "53": "650000", "54": "52000", "62": "0", "63": "52000", "68": "52000"}
    p1 = _words(render_return("1701Q", eight, H(quarter=1, taxpayer_type="individual",
                                                  income_tax_option="eight_percent")).pdf, 0)
    assert _ticked(p1, L.checks["atc_II015"]) and _ticked(p1, L.checks["rate_eight"])
    assert not _ticked(p1, L.checks["itemized"]) and _amount(p1, L.amounts["P3_26"]) == "52000"


def test_1702q_fiscal_year_rate_and_osd():
    L = bir1702q_layout.LAYOUT
    pdf = render_return("1702Q", {"S2_10": "25", "S2_1": "1000000", "25": "-1500"},
                        H(year=2027, quarter=1, fiscal_year_end_month=6, deduction_method="osd")).pdf
    p1, p2 = _words(pdf, 0), _words(pdf, 1)
    for check in ("fiscal", "q1", "osd", "relief_no"):
        assert _ticked(p1, L.checks[check]), check
    assert _text_in(p1, L.cells["year_month"].cells, L.cells["year_month"].baseline) == "06"
    assert _text_in(p1, L.cells["year_yy"].cells, L.cells["year_yy"].baseline) == "27"
    assert _text_in(p1, L.cells["tin"].cells, L.cells["tin"].baseline) == "123456789"  # branch is pre-printed
    assert _amount(p1, L.amounts["25"]) == "(1500)"
    assert _text_in(p2, L.cells["S2_10"].cells, L.cells["S2_10"].baseline) == "25"
    assert _amount(p2, L.amounts["S2_1"]) == "1000000"


def test_0619e_fiscal_month_due_date_and_nothing_withheld():
    L = bir0619e_layout.LAYOUT
    zero = {"14": "0.00", "16": "0.00", "18": "0.00"}
    p1 = _words(render_return("0619E-M1", zero, H(year=2027, quarter=1, fiscal_year_end_month=6)).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "072026"
    assert _text_in(p1, L.cells["due_date"].cells, L.cells["due_date"].baseline) == "08102026"
    assert _ticked(p1, L.checks["withheld_no"]) and _ticked(p1, L.checks["private"])
    p1 = _words(render_return("0619E-M2", {"14": "500.00", "18": "500.00"}, H(), amended=True).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "082026"
    assert _ticked(p1, L.checks["withheld_yes"]) and _ticked(p1, L.checks["amended_yes"])
    assert _amount(p1, L.amounts["18"]) == "50000"


def test_1601eq_schedule_caps_at_six_rows_with_a_note():
    L = bir1601eq_layout.LAYOUT
    values = {"19": "1000.00", "31": "0.00"}
    for i in range(1, 8):
        values.update({f"S{i}_ATC": f"WC{100 + i}", f"S{i}_BASE": "1000.00", f"S{i}_RATE": "5", f"S{i}_TAX": "50.00"})
    pdf = render_return("1601EQ", values, H(quarter=4))
    p1 = _words(pdf.pdf)
    assert _ticked(p1, L.checks["q4"]) and _ticked(p1, L.checks["withheld_yes"])
    assert _text_in(p1, L.cells["year"].cells, L.cells["year"].baseline) == "2026"
    assert _text_in(p1, L.cells["S6_ATC"].cells, L.cells["S6_ATC"].baseline) == "WC106"
    assert "WC107" not in fitz.open("pdf", pdf.pdf)[0].get_text()
    assert "More than six ATCs" in fitz.open("pdf", pdf.pdf)[0].get_text()
    assert _text_in(p1, L.cells["S1_RATE"].cells, L.cells["S1_RATE"].baseline) == "5"


def test_1601c_month_and_withheld():
    L = bir1601c_layout.LAYOUT
    p1 = _words(render_return("1601C-M3", {"14": "100000.00", "25": "8000.00", "36": "8000.00"}, H()).pdf)
    assert _text_in(p1, L.cells["month"].cells, L.cells["month"].baseline) == "092026"
    assert _ticked(p1, L.checks["withheld_yes"]) and _ticked(p1, L.checks["relief_no"])
    assert _amount(p1, L.amounts["36"]) == "800000"
    assert _text_in(p1, L.cells["address"].cells, L.cells["address"].baseline) == "123RIZALAVENUE,QUIAPO,MANILA"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_returns.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.accounting.pdf_returns'`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/pdf_returns.py`:

```python
"""Fill the official BIR returns (other than the 2550-Q) from a version's stored values."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701q_layout, bir1702q_layout, bir2551q_layout,
)
from app.forms.overlay import FormLayout
from app.services.accounting.compute.due_dates import due_dates, month_start, quarter_end, quarter_start
from app.services.accounting.pdf_overlay import Rendered, render_form

LAYOUTS: dict[str, FormLayout] = {
    "2551Q": bir2551q_layout.LAYOUT, "1701Q": bir1701q_layout.LAYOUT, "1702Q": bir1702q_layout.LAYOUT,
    "0619E": bir0619e_layout.LAYOUT, "1601EQ": bir1601eq_layout.LAYOUT, "1601C": bir1601c_layout.LAYOUT,
}
SCHEDULE_ROWS_ON_PDF = 6


@dataclass(frozen=True)
class ReturnHeader:
    tin: str
    branch_code: str
    rdo_code: str
    name: str
    address: str
    zip_code: str
    taxpayer_type: str
    income_tax_option: str
    deduction_method: str
    fiscal_year_end_month: int
    fiscal_year: int
    quarter: int

    @property
    def period_from(self) -> date:
        return quarter_start(self.fiscal_year, self.quarter, self.fiscal_year_end_month)

    @property
    def period_to(self) -> date:
        return quarter_end(self.fiscal_year, self.quarter, self.fiscal_year_end_month)


def header_from_snapshot(company: dict, fiscal_year: int, quarter: int) -> ReturnHeader:
    """The company as it was when the version was generated (older snapshots lack newer keys)."""
    return ReturnHeader(
        tin=str(company.get("tin") or ""), branch_code=str(company.get("branch_code") or "00000"),
        rdo_code=str(company.get("rdo_code") or ""), name=str(company.get("registered_name") or ""),
        address=str(company.get("address") or ""), zip_code=str(company.get("zip_code") or ""),
        taxpayer_type=str(company.get("taxpayer_type") or "corporation"),
        income_tax_option=str(company.get("income_tax_option") or "graduated"),
        deduction_method=str(company.get("deduction_method") or "itemized"),
        fiscal_year_end_month=int(company.get("fiscal_year_end_month") or 12),
        fiscal_year=fiscal_year, quarter=quarter,
    )


def split_form(form: str) -> tuple[str, int | None]:
    """'0619E-M2' -> ('0619E', 2); '1601EQ' -> ('1601EQ', None)."""
    base, _, month = form.partition("-M")
    return base, int(month) if month.isdigit() else None


def wrap(text: str, widths: list[int]) -> list[str]:
    """Upper-case ``text`` broken at spaces into lines of the given cell counts (overflow is cut)."""
    words = text.upper().split()
    lines: list[str] = []
    for width in widths:
        line = ""
        while words:
            candidate = f"{line} {words[0]}".strip()
            if len(candidate) <= width:
                line = candidate
                words.pop(0)
            elif not line:  # one word longer than the whole line
                line, words[0] = words[0][:width], words[0][width:]
            else:
                break
        lines.append(line)
    return lines


@dataclass
class _Fill:
    cells: dict[str, str] = field(default_factory=dict)
    checks: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)       # values the form shows twice (1701-Q Part III)
    sources: dict[str, str] = field(default_factory=dict)     # extra key -> snapshot key it copies
    notes: list[str] = field(default_factory=list)


def _positive(values: dict[str, str], key: str) -> bool:
    try:
        return Decimal(values.get(key) or "0") > 0
    except InvalidOperation:
        return False


def _identity(layout: FormLayout, h: ReturnHeader) -> dict[str, str]:
    cells: dict[str, str] = {}
    tin = h.tin[:9]
    cells["tin"] = tin + h.branch_code[:5] if len(layout.cells["tin"].cells) > 9 else tin
    cells["rdo"] = h.rdo_code[:3]
    for keys, text in ((("name", "name_2"), h.name), (("address", "address_2"), h.address)):
        present = [k for k in keys if k in layout.cells]
        for key, part in zip(present, wrap(text, [len(layout.cells[k].cells) for k in present])):
            cells[key] = part
    cells["zip"] = h.zip_code[:4]
    return cells


def _amended(amended: bool) -> str:
    return "amended_yes" if amended else "amended_no"


def _fill_2551q(values, h, amended, month) -> _Fill:
    fill = _Fill(cells={"year_ended": f"{h.fiscal_year_end_month:02d}{h.fiscal_year}",
                        "S1_1_ATC": values.get("S1_1_ATC", "").replace(" ", ""),
                        "S1_1_RATE": values.get("S1_1_RATE", "")},
                 checks=["calendar" if h.fiscal_year_end_month == 12 else "fiscal", f"q{h.quarter}",
                         _amended(amended), "relief_no"])
    if h.taxpayer_type == "individual":
        fill.checks.append("rate_graduated")
    return fill


def _fill_1701q(values, h, amended, month) -> _Fill:
    eight = h.income_tax_option == "eight_percent"
    fill = _Fill(cells={"year": str(h.fiscal_year)},
                 checks=[f"q{h.quarter}", _amended(amended), "single_proprietor", "foreign_credits_no",
                         "atc_II015" if eight else "atc_II012", "rate_eight" if eight else "rate_graduated"])
    if not eight:
        fill.checks.append("osd" if h.deduction_method == "osd" else "itemized")
    fill.sources = {"P3_26": "54" if eight else "46", "P3_27": "62", "P3_28": "63", "P3_29": "67", "P3_30": "68",
                    "P3_31": "68"}
    fill.extra = {key: values.get(source, "") for key, source in fill.sources.items()}
    return fill


def _fill_1702q(values, h, amended, month) -> _Fill:
    return _Fill(cells={"year_month": f"{h.fiscal_year_end_month:02d}", "year_yy": f"{h.fiscal_year % 100:02d}",
                        "S2_10": values.get("S2_10", "")},
                 checks=["calendar" if h.fiscal_year_end_month == 12 else "fiscal", f"q{h.quarter}",
                         _amended(amended), "osd" if h.deduction_method == "osd" else "itemized", "relief_no"])


def _fill_0619e(values, h, amended, month) -> _Fill:
    form = f"0619E-M{month}"
    due = due_dates([form], h.fiscal_year, h.quarter, h.fiscal_year_end_month)[form]
    first = month_start(h.fiscal_year, h.quarter, h.fiscal_year_end_month, month)
    return _Fill(cells={"month": first.strftime("%m%Y"), "due_date": due.strftime("%m%d%Y")},
                 checks=[_amended(amended), "withheld_yes" if _positive(values, "14") else "withheld_no", "private"])


def _fill_1601eq(values, h, amended, month) -> _Fill:
    end = h.period_to
    fill = _Fill(cells={"year": str(end.year)},
                 checks=[f"q{(end.month - 1) // 3 + 1}", _amended(amended),
                         "withheld_yes" if _positive(values, "19") else "withheld_no", "private"])
    for i in range(1, SCHEDULE_ROWS_ON_PDF + 1):
        fill.cells[f"S{i}_ATC"] = values.get(f"S{i}_ATC", "")
        fill.cells[f"S{i}_RATE"] = values.get(f"S{i}_RATE", "")
    if f"S{SCHEDULE_ROWS_ON_PDF + 1}_ATC" in values:
        fill.notes.append("More than six ATCs: rows 7 onwards are in the workbook's 1601EQ tab; attach them as an "
                          "additional sheet.")
    return fill


def _fill_1601c(values, h, amended, month) -> _Fill:
    first = month_start(h.fiscal_year, h.quarter, h.fiscal_year_end_month, month)
    return _Fill(cells={"month": first.strftime("%m%Y")},
                 checks=[_amended(amended), "withheld_yes" if _positive(values, "25") else "withheld_no",
                         "private", "relief_no"])


_FILLERS = {"2551Q": _fill_2551q, "1701Q": _fill_1701q, "1702Q": _fill_1702q, "0619E": _fill_0619e,
            "1601EQ": _fill_1601eq, "1601C": _fill_1601c}


def render_return(form: str, values: dict[str, str], header: ReturnHeader, *,
                  highlights: frozenset[str] = frozenset(), amended: bool = False,
                  draft_reviews: int = 0) -> Rendered:
    base, month = split_form(form)
    if base not in _FILLERS:
        raise ValueError(f"No PDF layout for {form}")
    layout = LAYOUTS[base]
    fill = _FILLERS[base](values, header, amended, month)
    cells = {**_identity(layout, header), **fill.cells}
    marked = set(highlights) | {key for key, source in fill.sources.items() if source in highlights}
    return render_form(layout, amounts={**values, **fill.extra}, cells=cells, checks=fill.checks,
                       highlights=frozenset(marked), draft_reviews=draft_reviews, notes=fill.notes)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_returns.py tests/test_aa_pdf_overlay.py -q`
Expected: PASS (31 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/pdf_returns.py backend/tests/test_aa_pdf_returns.py
git commit -m "feat(accounting): fill 2551-Q, 1701-Q, 1702-Q, 0619-E, 1601-EQ and 1601-C PDFs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 6: Outgoing 2307s

**Files:**
- Create: `backend/app/services/accounting/outgoing_2307.py`
- Test: `backend/tests/test_aa_outgoing_2307.py`

**Interfaces:**
- Consumes:
  - QAP ledger rows from the snapshot (Task 3): string values for `tin, name, address, atc, nature, m1, m2, m3, base, rate, tax`.
  - From the existing module, imported and not edited: `FilledForm`, `LineItem`, `Payee`, `Payor` (`app.schemas.form_filler`) and `generate_merged_pdf`, `MAX_LINE_ITEMS_PER_BLOCK` (`app.services.form_filler_service`).
- Produces:
  - `payee_forms(rows, company: dict, period_from: date, period_to: date) -> list[tuple[str, FilledForm]]`. There is one form per payee; a payee with more than 10 ATCs gets more copies.
  - `build_zip(rows, company, period_from, period_to) -> bytes`. The ZIP holds one PDF per form, named `<payee> 2307.pdf`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_outgoing_2307.py`:

```python
import io
import zipfile
from datetime import date

import fitz

from app.services.accounting.outgoing_2307 import build_zip, payee_forms

COMPANY = {"registered_name": "Juan's Cloth Trading", "tin": "123456789", "branch_code": "00000",
           "address": "Quiapo, Manila", "zip_code": "1001"}
Q3 = (date(2026, 7, 1), date(2026, 9, 30))


def _row(tin, name, atc, nature, m1, m3, base, tax):
    return {"key": f"{tin or name}|{atc}", "tin": tin, "name": name, "address": "Makati", "atc": atc,
            "nature": nature, "m1": m1, "m2": "0.00", "m3": m3, "base": base, "rate": "5", "tax": tax}


ROWS = [
    _row("111222333", "Ayala Land Inc.", "WC100", "Rentals", "10000.00", "10000.00", "20000.00", "1000.00"),
    _row("111222333", "Ayala Land Inc.", "WC158", "Supplier of goods", "5000.00", "0.00", "5000.00", "50.00"),
    _row("", "Pedro Cruz", "WI100", "Rentals", "0.00", "3000.00", "3000.00", "150.00"),
]


def test_one_certificate_per_payee_with_monthly_amounts():
    forms = payee_forms(ROWS, COMPANY, *Q3)
    assert [name for name, _ in forms] == ["Ayala Land Inc.", "Pedro Cruz"]
    ayala = forms[0][1]
    assert ayala.payee.tin == "11122233300000" and ayala.payor.tin == "12345678900000"
    assert (ayala.period_from, ayala.period_to) == ("07/01/2026", "09/30/2026")
    assert [(i.atc, i.m1, i.m3, i.total, i.tax_withheld) for i in ayala.ewt] == [
        ("WC100", 10000.0, 10000.0, 20000.0, 1000.0), ("WC158", 5000.0, 0.0, 5000.0, 50.0)]
    assert forms[1][1].payee.tin == ""


def test_more_atcs_than_rows_continue_on_another_copy():
    rows = [_row("111222333", "Ayala Land Inc.", f"WC{100 + i}", "Rentals", "1.00", "0.00", "1.00", "0.05")
            for i in range(12)]
    forms = payee_forms(rows, COMPANY, *Q3)
    assert [len(form.ewt) for _, form in forms] == [10, 2]


def test_zip_has_one_pdf_per_payee():
    with zipfile.ZipFile(io.BytesIO(build_zip(ROWS, COMPANY, *Q3))) as archive:
        names = archive.namelist()
        assert names == ["Ayala Land Inc. 2307.pdf", "Pedro Cruz 2307.pdf"]
        pdf = fitz.open("pdf", archive.read(names[0]))
        assert pdf.page_count == 1 and "WC100" in pdf[0].get_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_outgoing_2307.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.accounting.outgoing_2307'`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/outgoing_2307.py`:

```python
"""Outgoing BIR 2307s: one certificate per payee for the quarter, built from a version's QAP rows."""

import io
import re
import zipfile
from datetime import date
from decimal import Decimal, InvalidOperation

from app.schemas.form_filler import FilledForm, LineItem, Payee, Payor
from app.services.form_filler_service import MAX_LINE_ITEMS_PER_BLOCK, generate_merged_pdf


def _amount(text) -> float:
    try:
        return float(Decimal(str(text)))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def payee_forms(rows: list[dict], company: dict, period_from: date, period_to: date) -> list[tuple[str, FilledForm]]:
    """(payee name, filled 2307) per payee, a payee with more ATCs than the form's rows getting extra copies."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row.get("tin") or f"NAME:{row.get('name', '')}", []).append(row)
    payor = Payor(tin=f"{company.get('tin', '')}{company.get('branch_code') or '00000'}",
                  name=company.get("registered_name", ""), registered_address=company.get("address", ""),
                  zip_code=company.get("zip_code", ""))
    forms: list[tuple[str, FilledForm]] = []
    for party in sorted(groups.values(), key=lambda rs: (rs[0].get("name", "").lower(), rs[0].get("tin", ""))):
        first = party[0]
        payee = Payee(tin=f"{first['tin']}00000" if first.get("tin") else "", name=first.get("name", ""),
                      registered_address=first.get("address", ""), zip_code="")
        items = [LineItem(description=row.get("nature", ""), atc=row.get("atc", ""), m1=_amount(row.get("m1")),
                          m2=_amount(row.get("m2")), m3=_amount(row.get("m3")), total=_amount(row.get("base")),
                          tax_withheld=_amount(row.get("tax")))
                 for row in party]
        for start in range(0, len(items), MAX_LINE_ITEMS_PER_BLOCK):
            forms.append((first.get("name") or first.get("tin") or "payee", FilledForm(
                excel_row=0, payee=payee, payor=payor, period_from=period_from.strftime("%m/%d/%Y"),
                period_to=period_to.strftime("%m/%d/%Y"), ewt=items[start:start + MAX_LINE_ITEMS_PER_BLOCK],
            )))
    return forms


def _file_name(name: str, used: set[str]) -> str:
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "", name).strip() or "payee"
    candidate, n = f"{stem} 2307.pdf", 2
    while candidate in used:
        candidate, n = f"{stem} 2307 ({n}).pdf", n + 1
    used.add(candidate)
    return candidate


def build_zip(rows: list[dict], company: dict, period_from: date, period_to: date) -> bytes:
    buffer = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, form in payee_forms(rows, company, period_from, period_to):
            archive.writestr(_file_name(name, used), generate_merged_pdf([form]))
    return buffer.getvalue()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_outgoing_2307.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/outgoing_2307.py backend/tests/test_aa_outgoing_2307.py
git commit -m "feat(accounting): outgoing 2307s per payee from the QAP

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Database columns, schemas and API wiring

**Files:**
- Create: `backend/app/services/accounting/schema.py`
- Modify:
  - `backend/app/models/accounting.py`
  - `backend/app/schemas/accounting.py`
  - `backend/app/routers/accounting.py`
  - `backend/app/routers/accounting_periods.py`
  - `backend/app/startup_migrations.py` (the accounting stage only)
- Test:
  - `backend/tests/test_aa_wiring.py`
  - `backend/tests/test_accounting_schemas.py` (two new tests)

**Interfaces:**
- Consumes: `ATC_NONE`, `atc_info` (Task 1); `render_return`, `header_from_snapshot` (Task 5); `build_zip` (Task 6); `PDF_FORMS` (Task 3).
- Produces:
  - `AADocument.ewt_atc` and `AASupplierRule.ewt_atc`: `String(10)`, not null, default `""`.
  - `schema.column_statements() -> list[str]`.
  - `DocumentOut.ewt_atc: str` and `DocumentPatch.ewt_atc: str | None`. The patch value is upper-cased and must be `""`, `"NONE"` or an ATC with a fixed rate.
  - `PayrollMonthModel` and `PeriodInputsModel` with `ewt_remitted_m1`, `ewt_remitted_m2`, `ewt_over_remittance`, `amended_paid_withholding` and `payroll: list[PayrollMonthModel]` (exactly 3).
  - `doc_line(doc, atc_rules=None)`. `company_facts(c)` carries the withholding flags.
  - `GET /api/accounting/outputs/{id}/pdf?form=<any PDF_FORMS>&clean=` and `GET /api/accounting/outputs/{id}/2307s` (`application/zip`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aa_wiring.py`:

```python
import uuid
from datetime import date
from decimal import Decimal

from app.models.accounting import AACompany, AADocument
from app.routers.accounting_periods import company_facts, doc_line
from app.services.accounting.schema import column_statements


def _doc(**kw) -> AADocument:
    values = dict(
        id=uuid.uuid4(), client_role="buyer", category="expenses", account="rent", doc_type="invoice",
        doc_number="1", doc_date=date(2026, 7, 1), seller_name="Ayala Land Inc.", seller_tin="111222333",
        seller_address="Makati", seller_vat_registered=True, buyer_name="Juan", buyer_tin="123456789",
        buyer_address="", gross_amount=Decimal("11200.00"), vatable_amount=Decimal("10000.00"),
        vat_amount=Decimal("1200.00"), exempt_amount=Decimal("0.00"), zero_rated_amount=Decimal("0.00"),
        withholding_amount=Decimal("500.00"), input_vat_valid=True, needs_review=False, reviewed=False, ewt_atc="",
    )
    values.update(kw)
    return AADocument(**values)


def test_doc_line_carries_atc_choice_and_supplier_rule():
    plain = doc_line(_doc())
    assert plain.ewt_atc == "" and plain.counterparty_vat_registered is True
    assert doc_line(_doc(), {"111222333": "WC158"}).ewt_atc == "WC158"
    assert doc_line(_doc(ewt_atc="NONE"), {"111222333": "WC158"}).ewt_atc == "NONE"
    sale = doc_line(_doc(client_role="seller", category="sales"), {"123456789": "WC100"})
    assert sale.counterparty_tin == "123456789" and sale.ewt_atc == "" and sale.counterparty_vat_registered is None


def test_company_facts_carry_withholding_flags():
    c = AACompany(registered_name="Juan", tin="123456789", branch_code="00000", rdo_code="030", address="",
                  zip_code="", taxpayer_type="corporation", vat_status="vat", income_tax_option="graduated",
                  deduction_method="itemized", business_type="trading", fiscal_year_end_month=12,
                  is_withholding_agent=True, is_top_withholding_agent=False, has_employees=True)
    facts = company_facts(c)
    assert facts.is_withholding_agent and facts.has_employees and not facts.is_top_withholding_agent


def test_column_migrations_are_additive_and_idempotent():
    statements = column_statements()
    assert all("ADD COLUMN IF NOT EXISTS ewt_atc" in s for s in statements)
    assert {s.split()[2] for s in statements} == {"aa_documents", "aa_supplier_rules"}
```

Add to `backend/tests/test_accounting_schemas.py`:

```python
def test_document_patch_ewt_atc():
    assert DocumentPatch(ewt_atc=" wc158 ").ewt_atc == "WC158"
    assert DocumentPatch(ewt_atc="none").ewt_atc == "NONE"
    assert DocumentPatch(ewt_atc="").ewt_atc == ""
    with pytest.raises(ValidationError):
        DocumentPatch(ewt_atc="ZZ999")


def test_period_inputs_payroll_months():
    from app.schemas.accounting import PeriodInputsModel
    from app.services.accounting.compute.inputs import inputs_from_json

    default = PeriodInputsModel()
    assert len(default.payroll) == 3 and default.payroll[0].contributions == Decimal("0")
    ok = PeriodInputsModel(payroll=[{}, {"contributions": "5000", "adjustment": "-25.50"}, {}], ewt_remitted_m1="0")
    assert ok.payroll[1].adjustment == Decimal("-25.50") and ok.ewt_remitted_m1 == Decimal("0")
    assert inputs_from_json(ok.model_dump(mode="json")).payroll[1].contributions == Decimal("5000.00")
    with pytest.raises(ValidationError):
        PeriodInputsModel(payroll=[{}, {}])
    with pytest.raises(ValidationError):
        PeriodInputsModel(payroll=[{"de_minimis": "-1"}, {}, {}])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_wiring.py tests/test_accounting_schemas.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'app.services.accounting.schema'`, a `TypeError` for `ewt_atc` on `AADocument`, and validation failures on the new schema fields.

- [ ] **Step 3: Columns and their migration**

In `backend/app/models/accounting.py`, add to `AADocument` after `withholding_amount`:

```python
    ewt_atc: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
```

and to `AASupplierRule` after `account`:

```python
    ewt_atc: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
```

`backend/app/services/accounting/schema.py`:

```python
"""Additive column migrations for existing aa_* tables (idempotent; run at startup after create_all).

New databases get these columns from the models via create_all; existing ones get them here.
"""


def column_statements() -> list[str]:
    return [
        "ALTER TABLE aa_documents ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
        "ALTER TABLE aa_supplier_rules ADD COLUMN IF NOT EXISTS ewt_atc VARCHAR(10) NOT NULL DEFAULT ''",
    ]
```

In `backend/app/startup_migrations.py`, replace the body of `_ensure_accounting_rls`:

```python
async def _ensure_accounting_rls(conn) -> None:
    """AutoAccounting: additive aa_* columns, then row-level security (idempotent; tables exist after create_all)."""
    from app.services.accounting.rls import rls_statements
    from app.services.accounting.schema import column_statements
    for statement in column_statements() + rls_statements():
        await conn.execute(text(statement))
```

- [ ] **Step 4: Schemas**

In `backend/app/schemas/accounting.py`, add the import `from app.services.accounting.compute.ewt import ATC_NONE, atc_info`. Add `ewt_atc: str` to `DocumentOut` after `withholding_amount`. Add to `DocumentPatch`, after `withholding_amount`:

```python
    ewt_atc: str | None = Field(default=None, max_length=10)
```

with this validator inside `DocumentPatch`:

```python
    @field_validator("ewt_atc")
    @classmethod
    def _ewt_atc(cls, v: str | None) -> str | None:
        if v is None:
            return None
        code = v.strip().upper()
        if code and code != ATC_NONE and atc_info(code) is None:
            raise ValueError("Unknown ATC, or one without a fixed rate")
        return code
```

Add before `PeriodInputsModel`:

```python
class PayrollMonthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mwe_basic: Decimal = _amount(Decimal("0"))
    mwe_premium: Decimal = _amount(Decimal("0"))
    thirteenth_month: Decimal = _amount(Decimal("0"))
    de_minimis: Decimal = _amount(Decimal("0"))
    contributions: Decimal = _amount(Decimal("0"))
    other_non_taxable: Decimal = _amount(Decimal("0"))
    not_subject: Decimal = _amount(Decimal("0"))
    adjustment: Decimal = _amount(Decimal("0"), minimum=None)
    amended_paid: Decimal = _amount(Decimal("0"))
```

Add to `PeriodInputsModel` after `mcit_applies`:

```python
    ewt_remitted_m1: Decimal | None = _amount()
    ewt_remitted_m2: Decimal | None = _amount()
    ewt_over_remittance: Decimal = _amount(Decimal("0"))
    amended_paid_withholding: Decimal = _amount(Decimal("0"))
    payroll: list[PayrollMonthModel] = Field(default_factory=lambda: [PayrollMonthModel() for _ in range(3)],
                                             min_length=3, max_length=3)
```

- [ ] **Step 5: Document ATC and supplier learning**

In `backend/app/routers/accounting.py`, add `"ewt_atc"` to the end of `_PLAIN_FIELDS`. Replace `_learn_supplier_rule`:

```python
async def _learn_supplier_rule(db: AsyncSession, doc: AADocument, learn_atc: bool = False) -> None:
    tin = doc.buyer_tin if doc.client_role == "seller" else doc.seller_tin
    if not tin or doc.category not in ("purchases", "expenses"):
        return
    # Atomic upsert: two people correcting the same supplier at once must not 500.
    stmt = pg_insert(AASupplierRule).values(
        id=uuid.uuid4(), company_id=doc.company_id, counterparty_tin=tin, category=doc.category,
        account=doc.account, ewt_atc=doc.ewt_atc if learn_atc else "", updated_at=datetime.now(timezone.utc),
    )
    learned = {"category": stmt.excluded.category, "account": stmt.excluded.account,
               "updated_at": stmt.excluded.updated_at}
    if learn_atc:
        learned["ewt_atc"] = stmt.excluded.ewt_atc
    await db.execute(stmt.on_conflict_do_update(constraint="uq_aa_supplier_rule", set_=learned))
```

In `patch_document`, replace the learning call:

```python
    if sent & {"category", "account", "ewt_atc"}:
        await _learn_supplier_rule(db, doc, learn_atc="ewt_atc" in sent)
```

- [ ] **Step 6: Periods router**

In `backend/app/routers/accounting_periods.py`, update the imports:
- add `AASupplierRule` to the `app.models.accounting` import;
- add `from app.services.accounting.outgoing_2307 import build_zip`;
- add `from app.services.accounting.pdf_returns import header_from_snapshot, render_return`.

Then replace `company_facts` and `doc_line`:

```python
def company_facts(c: AACompany) -> CompanyFacts:
    return CompanyFacts(c.registered_name, c.tin, c.branch_code, c.rdo_code, c.address, c.zip_code,
                        c.taxpayer_type, c.vat_status == "vat", c.income_tax_option, c.deduction_method,
                        c.business_type, c.fiscal_year_end_month, is_withholding_agent=c.is_withholding_agent,
                        is_top_withholding_agent=c.is_top_withholding_agent, has_employees=c.has_employees)


def doc_line(doc: AADocument, atc_rules: dict[str, str] | None = None) -> DocLine:
    """A document as the engine sees it; a supplier's remembered ATC fills in when the document has none."""
    seller = doc.client_role == "seller"
    counterparty_tin = doc.buyer_tin if seller else doc.seller_tin
    remembered = "" if seller else (atc_rules or {}).get(counterparty_tin, "")
    return DocLine(
        id=str(doc.id), category=doc.category, account=doc.account, doc_type=doc.doc_type,
        client_role=doc.client_role, doc_date=doc.doc_date, doc_number=doc.doc_number,
        counterparty_tin=counterparty_tin,
        counterparty_name=doc.buyer_name if seller else doc.seller_name,
        counterparty_address=doc.buyer_address if seller else doc.seller_address,
        gross=doc.gross_amount, vatable=doc.vatable_amount, vat=doc.vat_amount, exempt=doc.exempt_amount,
        zero_rated=doc.zero_rated_amount, withholding=doc.withholding_amount,
        input_vat_valid=doc.input_vat_valid, open_review=doc.needs_review and not doc.reviewed,
        ewt_atc=doc.ewt_atc or remembered,
        counterparty_vat_registered=None if seller else doc.seller_vat_registered,
    )
```

In `load_periods`, load the supplier ATC rules after the `rows = …` query, and pass them to `doc_line`:

```python
    atc_rules = dict((await db.execute(select(AASupplierRule.counterparty_tin, AASupplierRule.ewt_atc).where(
        AASupplierRule.company_id == company.id, AASupplierRule.ewt_atc != "",
    ))).all())
```

```python
        lines.setdefault((doc.period_year, doc.period_quarter), []).append(doc_line(doc, atc_rules))
```

Replace `download_pdf` and add the 2307 download after it:

```python
@router.get("/outputs/{output_id}/pdf")
async def download_pdf(output_id: uuid.UUID, form: str = Query(...), clean: bool = Query(default=False),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    if form not in PDF_FORMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There is no PDF for this form")
    values = output.snapshot["forms"].get(form)
    if values is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This version has no {form}")
    c = output.snapshot["company"]
    highlights = frozenset() if clean else frozenset((output.diff or {}).get("forms", {}).get(form, {}))
    if form == "2550Q":
        fye = c["fiscal_year_end_month"]
        header = Header2550Q(
            tin=c["tin"], rdo_code=c["rdo_code"], name=c["registered_name"], address=c["address"],
            zip_code=c["zip_code"], fiscal_year_end_month=fye, fiscal_year=period.year, quarter=period.quarter,
            period_from=quarter_start(period.year, period.quarter, fye),
            period_to=quarter_end(period.year, period.quarter, fye),
        )

        def render() -> bytes:
            return render_2550q(values, header, highlights, output.amended, output.review_open)
    else:
        return_header = header_from_snapshot(c, period.year, period.quarter)

        def render() -> bytes:
            return render_return(form, values, return_header, highlights=highlights, amended=output.amended,
                                 draft_reviews=output.review_open).pdf
    data = await asyncio.get_running_loop().run_in_executor(None, render)
    name = _file_name(company, period, output, form, clean, "pdf")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/outputs/{output_id}/2307s")
async def download_2307s(output_id: uuid.UUID, user: User = Depends(get_current_user),
                         db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    rows = output.snapshot["ledgers"].get("QAP")
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This version has no payments with expanded withholding")
    c = output.snapshot["company"]
    fye = int(c.get("fiscal_year_end_month") or 12)
    start, end = quarter_start(period.year, period.quarter, fye), quarter_end(period.year, period.quarter, fye)
    data = await asyncio.get_running_loop().run_in_executor(None, lambda: build_zip(rows, c, start, end))
    name = _file_name(company, period, output, "2307s", False, "zip")
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
```

- [ ] **Step 7: Run tests to verify they pass, then the whole backend suite**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_wiring.py tests/test_accounting_schemas.py -q`
Expected: PASS.

Run: `docker compose exec -T backend python -m pytest -q`
Expected: PASS (all suites).

- [ ] **Step 8: Apply the column migration to the dev database and check the routes**

Run: `docker compose restart backend && sleep 8 && docker compose logs --tail=40 backend | grep -iE "error|traceback|ewt_atc" ; docker compose exec -T db psql -U snagstock -d snagstock -c "\d aa_documents" | grep ewt_atc`
Expected: no errors in the log, and the `ewt_atc | character varying(10)` column is listed.

Run: `docker compose exec -T backend python -c "from app.main import app; print(sorted(r.path for r in app.routes if '/outputs/' in r.path))"`
Expected: the list includes `/api/accounting/outputs/{output_id}/2307s` and `/api/accounting/outputs/{output_id}/pdf`.

- [ ] **Step 9: Commit**

```bash
git add backend/app/models/accounting.py backend/app/schemas/accounting.py backend/app/routers/accounting.py backend/app/routers/accounting_periods.py backend/app/services/accounting/schema.py backend/app/startup_migrations.py backend/tests/test_aa_wiring.py backend/tests/test_accounting_schemas.py
git commit -m "feat(accounting): EWT ATC per document and supplier, return PDFs and 2307 ZIP endpoints

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Frontend — ATC on documents, withholding and payroll inputs, 2307 download

**Files:**
- Modify:
  - `frontend/src/types/accounting.ts`
  - `frontend/src/lib/accounting-api.ts`
  - `frontend/src/lib/accounting-format.ts`
  - `frontend/src/components/accounting/DocumentPanel.tsx`
  - `frontend/src/components/accounting/PeriodPanel.tsx`
  - `frontend/src/components/accounting/OutputViewer.tsx`

**Interfaces:**
- Consumes:
  - `DocumentOut.ewt_atc`, `PATCH /documents/{id}` with `ewt_atc` (Task 7).
  - `PeriodInputsModel` with `payroll` (3 months) and the four EWT fields.
  - `GET /outputs/{id}/2307s` and `GET /outputs/{id}/pdf?form=` for every return.
- Produces: the UI only.

Use theme CSS variables (`var(--…)`), not Tailwind `dark:`; this app's `dark:` follows the OS.

- [ ] **Step 1: Types and API client**

In `frontend/src/types/accounting.ts`, add `ewt_atc: string;` to `AADocument` after `withholding_amount`. Add before `PeriodInputs`:

```ts
export interface PayrollMonth {
  mwe_basic: string;
  mwe_premium: string;
  thirteenth_month: string;
  de_minimis: string;
  contributions: string;
  other_non_taxable: string;
  not_subject: string;
  adjustment: string;
  amended_paid: string;
}
```

and add to `PeriodInputs` after `mcit_applies`:

```ts
  ewt_remitted_m1: string | null;
  ewt_remitted_m2: string | null;
  ewt_over_remittance: string;
  amended_paid_withholding: string;
  payroll: PayrollMonth[];
```

In `frontend/src/lib/accounting-api.ts`, add to `accountingApi` after `outputFile`:

```ts
  outgoing2307s: (id: string) =>
    api.get<Blob>(`/accounting/outputs/${id}/2307s`, { responseType: "blob" }).then((r) => r.data),
```

In `frontend/src/lib/accounting-format.ts`, add:

```ts
/** EWT ATCs offered on a payment; "" lets AutoAccounting suggest one, NONE means no withholding. */
export const EWT_ATC_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Automatic (suggested from the account and supplier)" },
  { value: "NONE", label: "No withholding" },
  { value: "WI010", label: "WI010 Professional fees, individual ≤ ₱3M (5%)" },
  { value: "WI011", label: "WI011 Professional fees, individual > ₱3M or VAT-registered (10%)" },
  { value: "WC010", label: "WC010 Professional fees, corporate ≤ ₱720k (10%)" },
  { value: "WC011", label: "WC011 Professional fees, corporate > ₱720k (15%)" },
  { value: "WI100", label: "WI100 Rentals, individual (5%)" },
  { value: "WC100", label: "WC100 Rentals, corporate (5%)" },
  { value: "WI120", label: "WI120 Contractors, individual (2%)" },
  { value: "WC120", label: "WC120 Contractors, corporate (2%)" },
  { value: "WI158", label: "WI158 Goods from a Top Withholding Agent, individual (1%)" },
  { value: "WC158", label: "WC158 Goods from a Top Withholding Agent, corporate (1%)" },
  { value: "WI160", label: "WI160 Services from a Top Withholding Agent, individual (2%)" },
  { value: "WC160", label: "WC160 Services from a Top Withholding Agent, corporate (2%)" },
];
```

- [ ] **Step 2: ATC select on the document panel**

In `frontend/src/components/accounting/DocumentPanel.tsx`:
- add `EWT_ATC_OPTIONS` to the `@/lib/accounting-format` import;
- add `ewt_atc: doc.ewt_atc,` to the object returned by `toDraft`;
- in the fields grid, right after the Account `<div>`, add:

```tsx
          {(draft.category === "purchases" || draft.category === "expenses") && (
            <div className="col-span-2">
              <label className={LABEL}>Expanded withholding (ATC)</label>
              <select className={INPUT} value={draft.ewt_atc} onChange={(e) => setDraft((d) => ({ ...d, ewt_atc: e.target.value }))}>
                {EWT_ATC_OPTIONS.map((o) => (
                  <option key={o.value || "auto"} value={o.value}>{o.label}</option>
                ))}
                {draft.ewt_atc && !EWT_ATC_OPTIONS.some((o) => o.value === draft.ewt_atc) && (
                  <option value={draft.ewt_atc}>{draft.ewt_atc}</option>
                )}
              </select>
              <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">
                Applies to this supplier&apos;s other documents too, unless they have their own.
              </span>
            </div>
          )}
```

(`save()` already sends every changed non-amount draft field as-is, so `ewt_atc` needs no other change.)

- [ ] **Step 3: Withholding and payroll inputs on the quarter panel**

In `frontend/src/components/accounting/PeriodPanel.tsx`:

1. Change the type import to `import type { PayrollMonth, Period, PeriodInputs } from "@/types/accounting";` and the field key type to `type FieldKey = Exclude<keyof PeriodInputs, "cit_rate" | "mcit_applies" | "payroll">;`.
2. Below `const vat = …`, add `const ewt = (p: Period) => p.forms_expected.includes("1601EQ");` and append to `FIELDS`:

```tsx
  { key: "ewt_remitted_m1", label: "EWT actually remitted — month 1", hint: "Only if the 0619-E paid differs from the computed amount", optional: true, show: ewt },
  { key: "ewt_remitted_m2", label: "EWT actually remitted — month 2", hint: "Only if the 0619-E paid differs from the computed amount", optional: true, show: ewt },
  { key: "ewt_over_remittance", label: "EWT over-remitted last quarter", hint: "1601-EQ item 23", show: ewt },
  { key: "amended_paid_withholding", label: "Paid on the original 1601-EQ", hint: "Amended returns only (1601-EQ item 22)", show: (p) => ewt(p) && p.filed_at !== null },
```

3. Below `FIELDS`, add:

```tsx
const PAYROLL_FIELDS: [keyof PayrollMonth, string][] = [
  ["mwe_basic", "Statutory minimum wage (MWEs)"],
  ["mwe_premium", "Holiday, overtime, night shift, hazard pay (MWEs)"],
  ["thirteenth_month", "13th month pay and other benefits (up to ₱90,000)"],
  ["de_minimis", "De minimis benefits"],
  ["contributions", "SSS, PhilHealth, Pag-IBIG, union dues (employee share)"],
  ["other_non_taxable", "Other non-taxable compensation"],
  ["not_subject", "Taxable compensation not subject to withholding"],
  ["adjustment", "Adjustment from previous months (+/−)"],
  ["amended_paid", "Paid on the original 1601-C (amended only)"],
];
```

4. Add state `const [payroll, setPayroll] = useState<PayrollMonth[]>([]);`, and in `apply` add `setPayroll(p.inputs.payroll.map((m) => ({ ...m })));`.
5. In `saveInputs`, change the declaration to `const inputs: Record<string, unknown> = { cit_rate: citRate, mcit_applies: mcit };` and, after the `for (const f of FIELDS)` loop, add:

```tsx
      inputs.payroll = payroll.map((month) =>
        Object.fromEntries(PAYROLL_FIELDS.map(([key]) => [key, (month[key] ?? "").replace(/,/g, "").trim() || "0"])),
      );
```

6. Inside the `showInputs` block, after the closing `</div>` of the field grid and before the "Save inputs" row, add:

```tsx
          {period.forms_expected.includes("1601C-M1") && payroll.length === 3 && (
            <div className="mt-4">
              <p className="mb-2 text-xs font-medium text-[var(--text-secondary)]">
                1601-C — amounts the payroll register doesn&apos;t show (gross pay and tax withheld come from the payroll documents)
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-xs text-[var(--text-secondary)]">
                      <th className="py-1 pr-3 font-medium">Item</th>
                      {[1, 2, 3].map((m) => (
                        <th key={m} className="py-1 pr-2 font-medium">Month {m}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {PAYROLL_FIELDS.map(([key, label]) => (
                      <tr key={key} className="border-t border-[var(--border)]">
                        <td className="py-1 pr-3 text-[var(--text-primary)]">{label}</td>
                        {payroll.map((month, i) => (
                          <td key={i} className="py-1 pr-2">
                            <input
                              inputMode="decimal"
                              className={INPUT}
                              aria-label={`${label}, month ${i + 1}`}
                              value={month[key]}
                              onChange={(e) =>
                                setPayroll((all) => all.map((m, j) => (j === i ? { ...m, [key]: e.target.value } : m)))
                              }
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
```

- [ ] **Step 4: Outgoing 2307s on the output viewer**

In `frontend/src/components/accounting/OutputViewer.tsx`, add `FileZip` to the phosphor import, and add below `download`:

```tsx
  async function download2307s() {
    if (!output) return;
    setBusy("2307s");
    setError("");
    try {
      saveBlob(await accountingApi.outgoing2307s(output.id), `${output.label} 2307s v${output.version}.zip`);
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  }
```

Add this button after the "Clean copy" button:

```tsx
          {(output.ledgers.QAP ?? 0) > 0 && (
            <button className={BTN} disabled={busy !== null} onClick={download2307s}>
              <FileZip size={16} /> Outgoing 2307s
            </button>
          )}
```

- [ ] **Step 5: Verify**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/accounting src/app/accounting src/lib/accounting-api.ts src/lib/accounting-format.ts src/types/accounting.ts && npm run build; git checkout -- tsconfig.tsbuildinfo`
Expected: no type errors, no lint errors, build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/accounting.ts frontend/src/lib/accounting-api.ts frontend/src/lib/accounting-format.ts frontend/src/components/accounting/DocumentPanel.tsx frontend/src/components/accounting/PeriodPanel.tsx frontend/src/components/accounting/OutputViewer.tsx
git commit -m "feat(accounting): ATC on documents, withholding and payroll inputs, 2307 download

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end check

**Files:** none (verification only).

- [ ] **Step 1: Full backend suite and a scripted end-to-end render**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: PASS.

Then run this script. It goes engine → snapshot → every PDF → workbook → 2307 ZIP for a withholding-agent employer, without a database:

```bash
docker compose exec -T backend python - <<'PY'
from datetime import date
from decimal import Decimal as D
from pathlib import Path
import io, zipfile, fitz
from app.services.accounting.compute.engine import build_quarter
from app.services.accounting.compute.inputs import CompanyFacts, DocLine, PeriodData, PeriodInputs
from app.services.accounting.diff import snapshot
from app.services.accounting.outgoing_2307 import build_zip
from app.services.accounting.pdf_returns import header_from_snapshot, render_return
from app.services.accounting.render_xlsx import write_workbook

c = CompanyFacts("Juan's Cloth Trading Corp", "123456789", "00000", "030", "Quiapo, Manila", "1001", "corporation",
                 True, "graduated", "itemized", "trading", 12, is_withholding_agent=True, has_employees=True)
def L(**kw):
    base = dict(id=kw.pop("id"), category="expenses", account="rent", doc_type="invoice", client_role="buyer",
                doc_date=date(2026, 7, 5), doc_number="1", counterparty_tin="111222333",
                counterparty_name="Ayala Land Inc.", counterparty_address="Makati")
    base.update(kw)
    return DocLine(**base)
lines = (L(id="a", gross=D("11200"), vat=D("1200"), vatable=D("10000"), input_vat_valid=True),
         L(id="b", category="sales", account="sales", client_role="seller", vatable=D("200000"), vat=D("24000"),
           gross=D("224000"), counterparty_name="Customer", counterparty_tin="555666777"),
         L(id="c", category="payroll", account="salaries", gross=D("80000"), withholding=D("4000"),
           doc_date=date(2026, 8, 31)))
r = build_quarter(c, [PeriodData(2026, 3, lines, PeriodInputs(opening_inventory=D("0"), ending_inventory=D("0")))])
snap = snapshot(r, c)
h = header_from_snapshot(snap["company"], 2026, 3)
for form in snap["forms"]:
    if form in ("2550Q", "COGS", "Expenses"):
        continue
    out = render_return(form, snap["forms"][form], h)
    assert fitz.open("pdf", out.pdf).page_count >= 1 and out.overflow == (), form
    print("pdf ok", form)
write_workbook(Path("/tmp/aa_phase3.xlsx"), header={"company": "Juan", "tin": "1", "period": "Q3", "generated": "now"},
               snapshot=snap, warnings=r.warnings, review_open=0, due={}, version=1)
z = zipfile.ZipFile(io.BytesIO(build_zip(snap["ledgers"]["QAP"], snap["company"], date(2026, 7, 1), date(2026, 9, 30))))
print("zip", z.namelist(), "warnings", r.warnings)
PY
```

Expected: `pdf ok` for 1702Q, 0619E-M1, 0619E-M2, 1601EQ, 1601C-M1, 1601C-M2 and 1601C-M3; `zip ['Ayala Land Inc. 2307.pdf']`; and warnings that name the missing Q1/Q2 documents and the rent payment with no tax withheld. (The 1702-Q is the corporation's ITR; the 2550-Q keeps its Phase 2 renderer.)

- [ ] **Step 2: Frontend checks**

Run: `cd frontend && npx tsc --noEmit && npm run build; git checkout -- tsconfig.tsbuildinfo`
Expected: PASS.

- [ ] **Step 3: Manual check in the running app (feature toggle `accounting` on in dev)**

1. On a company, tick "Withholding agent" and "Has employees" in Companies.
2. Open a quarter that has a rent invoice and a payroll register, then Generate. Expect:
   - tabs 0619E-M1, 0619E-M2, 1601EQ and 1601C-M1..M3;
   - an "Outgoing 2307s" button;
   - "Generate PDF" on each return downloads a filled form.
3. On the rent invoice, set the ATC to WC160 and Generate again. Expect the 1601-EQ row to change and be highlighted yellow.
4. Fill a payroll month in Quarter inputs, Save, and Generate. Expect 1601-C items 15–24 to change.

There is no commit for this task.
