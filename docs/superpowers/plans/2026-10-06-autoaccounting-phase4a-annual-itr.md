# AutoAccounting Phase 4a (Annual ITR, Depreciation, NOLCO) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce each company's annual income tax return (1702-RT for non-individuals, 1701 or 1701-A for individuals) as a versioned output with workbook and filled PDF, backed by an asset register with straight-line depreciation (also used by the quarterly returns) and NOLCO / excess MCIT carried across years.

**Architecture:** A year-level `AAPeriod` (`quarter = 0`) holds the annual inputs and versions. Pure modules compute depreciation (`compute/depreciation.py`), carry-overs (`compute/carryover.py`), annual inputs (`compute/annual_inputs.py`) and the annual return (`compute/annual.py`) from the same `PeriodData` the quarters use. The router layer syncs the `aa_assets` register from capital-goods documents, gathers Q1–Q3 tax paid from quarterly versions and the previous year's closing schedules, then stores an ordinary snapshot, so diffs, yellow highlights and `write_workbook` work unchanged. PDFs reuse the Phase 3 comb overlay with three newly calibrated layouts.

**Tech Stack:** Python `decimal`, PyMuPDF, openpyxl, FastAPI, async SQLAlchemy, Pydantic v2, pytest (in the backend container); Next.js 15 / React 19 / Tailwind 4.

**Spec:** `docs/superpowers/specs/2026-10-06-autoaccounting-phase4a-annual-itr-design.md` (parent: AutoAccounting spec sheet, https://claude.ai/code/artifact/8dcfb05b-3f3e-4410-a082-da75a391cd21). Earlier plans: `2026-10-05-autoaccounting-phase1-intake.md`, `2026-10-05-autoaccounting-phase2-vat-itr.md`, `2026-10-06-autoaccounting-phase3-withholding-pdfs.md`.

## Global Constraints

- Stay inside the AutoAccounting module: `backend/app/services/accounting/`, `backend/app/routers/accounting*.py`, `backend/app/models/accounting.py`, `backend/app/schemas/accounting.py`, `backend/app/forms/` (layouts, `overlay.py`, templates), `frontend/src/{components,app}/accounting/`, `frontend/src/lib/accounting-*`, `frontend/src/types/accounting.ts`. No edits elsewhere (the accounting RLS/column hooks in `startup_migrations` already call `rls_statements()` / `column_statements()`).
- Storage stays local. PDFs render on demand from the stored snapshot.
- Money is `Decimal`. Income tax returns are whole pesos (`peso`, half up); depreciation is centavos half up per month.
- Annual period = `AAPeriod(quarter=0)`. Every quarterly query excludes `quarter = 0`.
- Snapshot form keys `1702RT`, `1701`, `1701A`, plus `COGS`, `Expenses`, `BalanceSheet`; ledgers `Depreciation`, `NOLCO`, `ExcessMCIT`, `QuarterCredits`, `SAWT`, `Transactions`. Payable items: 1702RT `21`, 1701 `31`, 1701A `29`; quarterly payable read from 1702Q `25` / 1701Q `68`.
- NOLCO lasts 3 taxable years after the loss year, 5 for losses of fiscal years 2020 and 2021. Excess MCIT lasts 3 years. Both applied oldest first.
- MCIT = 2% of gross income (1702-RT item 33), from fiscal year `operations_start_year + 4`.
- Excess MCIT credit is applied only up to RCIT − MCIT (never below that year's MCIT); with MCIT not applicable, up to RCIT.
- Templates (official BIR, SHA-256 pinned):
  - 1702-RT Jan 2018 `https://bir-cdn.bir.gov.ph/local/pdf/1702-RT%20Jan%202018%20ENCS%20Final%20v3.pdf` → `d9a6a8a13e0114934261151c4eb269a1573042e7ce670eaf12b15f169d308d2d`
  - 1701 Jan 2018 `https://bir-cdn.bir.gov.ph/local/pdf/1701%20Jan%202018%20final%20with%20rates.pdf` → `19be91d78258eb7c255f2615610db2739f10c378f8ac97adc0887c1bf40d1b2e`
  - 1701-A Jan 2018 `https://bir-cdn.bir.gov.ph/local/pdf/1701A%20Jan%202018%20v5%20with%20rates.pdf` → `8d492eabc6da2088cf9a55084488b192def5cc415048f607142c8bce1b72bfb8` (URL confirmed in planning)
- Pastel yellow `#FFF4B3` for changes. Theme CSS variables only in the frontend.
- Backend tests: `docker compose exec -T backend python -m pytest -q`. Frontend: `cd frontend && npx tsc --noEmit && npx eslint src/components/accounting src/app/accounting src/lib/accounting-api.ts src/lib/accounting-format.ts src/types/accounting.ts && npm run build`; restore `frontend/tsconfig.tsbuildinfo` afterwards.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Branch `AutoAccounting`; never push.

## Review Focus

1. **A loss year followed by profit years** — NOLCO is used oldest first, a 2020 loss lasts until 2025, a 2022 loss expires after 2025 with a warning. Pinned in Task 3 (`test_nolco_oldest_first_and_expiry`, `test_2020_loss_lasts_five_years`) and Task 5 (`test_loss_year_then_profit_uses_nolco`).
2. **MCIT above RCIT one year, RCIT higher the next** — the excess MCIT credit is capped at RCIT − MCIT. Pinned in Task 3 (`test_excess_mcit_capped_at_rcit_minus_mcit`) and Task 5 (`test_mcit_year_then_rcit_year`).
3. **A quarter re-generated after filing** — the annual return credits the filed version and warns. Pinned in Task 4 (`test_quarter_credits_filed_latest_override_missing`).
4. **A fiscal year ending in June** — depreciation months, quarters and the 1702-RT due date follow the fiscal calendar. Pinned in Task 2 (`test_fiscal_year_window`) and Task 4 (`test_annual_due_dates`) and Task 5 (`test_june_fiscal_year`).
5. **An asset whose document is deleted or re-filed mid-year** — it drops out of the computation (the engine only receives assets of active capital-goods documents) and its quarter goes stale. Pinned in Task 7 (`test_active_assets_follow_documents`) and Task 7 (`test_annual_stale_rules`).

## Deviations from the spec (decided while planning)

- **The 1702-RT and 1701 (January 2018) have no balance-sheet part.** Balance-sheet inputs go to a `BalanceSheet` workbook tab (with the balance check warning) and are not printed. Reconciliation goes to 1702-RT Schedule V / 1701 Part IX.
- **1702-RT Part IV item 45/46:** all Q1–Q3 payments go to item 46 (regular rate); the quarterly snapshot doesn't say which part was MCIT.
- **NOLCO rows on the PDF:** 1702-RT Schedule IIIA rows 4–6 hold the three most recent prior-year losses and row 7 this year's loss (per the form: "To Schedule IIIA, Item 7A"); 1701 Schedule 6.A.1 the same. More prior years than rows → a note on the PDF; the workbook lists them all.
- **Staleness from company edits** uses a new `aa_companies.facts_updated_at`, set only when a tax-relevant field changes (not pin/aliases), instead of `updated_at`.
- **Asset edits mark stale** the quarters and years from the asset's in-service period onwards.
- **2550-Q branch code:** the template pre-prints `00000`; a non-head-office branch code is printed over a white patch on those cells.

---

### Task 1: Annual templates and calibrated layouts

**Files:**
- Create: `backend/app/forms/templates/bir1702rt_jan2018.pdf`, `bir1701_jan2018.pdf`, `bir1701a_jan2018.pdf`
- Create: `backend/app/forms/bir1702rt_layout.py`, `bir1701_layout.py`, `bir1701a_layout.py` (written during calibration, in the tree)
- Modify: `backend/app/forms/overlay.py` (add `ticks`)
- Test: `backend/tests/test_aa_pdf_overlay_annual.py`

**Interfaces:**
- Produces: `overlay.ticks(*xs) -> tuple[Cell, ...]` (cells between consecutive measured ticks). Each `LAYOUT: FormLayout`. Amount keys equal snapshot item keys:
  - 1702RT: `14`–`21`, `27`–`56` (except `40`, a cell), `S1_1`…`S1_18` (`S1_17A`–`S1_17F`), `S3_1`–`S3_3`, `S3_{4..7}_{A..E}`, `S3_8`, `S4_{1..3}_{A..G}`, `S4_4`, `S5_1`–`S5_10`. Cells: identity (`name`, `name_2`, `name_3`, `address`…`address_3`), `tin_p2..4`, `name_p2..4`, `40`, `S3_{4..7}_YEAR`, `S4_{1..3}_YEAR`, `S1_17{D,E,F}_DESC`, `S5_{2,3,5,6,7,8}_DESC`. Checks: `calendar`, `fiscal`, `amended_yes/no`, `short_no`, `atc_IC055`, `itemized`, `osd`, `refund`, `tcc`, `carry_over`.
  - 1701: `22`–`32`, `S3_8`–`S3_32`, `S4_1`…`S4_18`, `S6_1`–`S6_3`, `S6_{4..7}_{A..E}`, `S6_8`, `P6_1`–`P6_5`, `P7_1`–`P7_10`, `P9_1`–`P9_11`. Cells: `year`, identity, `tin_p2..4`, `name_p2..4`, `S6_{4..7}_YEAR`, `S3_19_DESC`, `S3_27_DESC`, `S4_17D_DESC`, `P9_{2,3,4,6,7,8,9}_DESC`. Checks: `amended_yes/no`, `short_no`, `single_proprietor`, `professional`, `atc_II012`, `atc_II015`, `foreign_credits_no`, `exempt_no`, `special_no`, `rate_graduated`, `rate_eight`, `itemized`, `osd`, `refund`, `tcc`, `carry_over`.
  - 1701A: `20`–`30`, `36`–`65`. Cells: `year_month`, `year`, identity, `tin_p2`, `name_p2`, `41_DESC`, `50_DESC`. Checks: `amended_yes/no`, `short_no`, `single_proprietor`, `professional`, `atc_II012/14/15/17`, `foreign_credits_no`, `rate_osd`, `rate_eight`, `refund`, `tcc`, `carry_over`.

Calibration (done 2026-10-06): comb rows found from vertical tick marks 3–10 pt tall; baselines 2 pt above the bottom ticks; checkbox X centred in the 13 pt box, 2.5 pt above its bottom edge. The 1701 and 1701-A combs are unevenly spaced, so their cells use the measured tick x positions (`ticks`). Open boxes (1701 NOLCO detail, description lines) use narrow even cells. A prototype render of every box was inspected page by page.

- [ ] **Step 1: Download the templates and check the hashes**

```bash
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1702rt_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1702-RT%20Jan%202018%20ENCS%20Final%20v3.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1701_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1701%20Jan%202018%20final%20with%20rates.pdf"
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir1701a_jan2018.pdf "https://bir-cdn.bir.gov.ph/local/pdf/1701A%20Jan%202018%20v5%20with%20rates.pdf"
shasum -a 256 backend/app/forms/templates/bir17*_jan2018.pdf
```
Expected: the three hashes under Global Constraints. A different hash means the BIR replaced the form; stop.

- [ ] **Step 2: Write the tests** — `backend/tests/test_aa_pdf_overlay_annual.py`:

```python
import hashlib

import fitz
import pytest

from app.forms import bir1701_layout, bir1701a_layout, bir1702rt_layout
from app.forms.overlay import ticks
from app.services.accounting.pdf_overlay import render_form

LAYOUTS = {"1702RT": bir1702rt_layout.LAYOUT, "1701": bir1701_layout.LAYOUT, "1701A": bir1701a_layout.LAYOUT}


def _pages(pdf: bytes):
    return [page.get_text("words") for page in fitz.open("pdf", pdf)]


def test_ticks_pairs_consecutive_marks():
    assert ticks(0, 10, 25) == ((0, 10), (10, 25))


@pytest.mark.parametrize("name", LAYOUTS)
def test_templates_are_the_calibrated_official_forms(name):
    layout = LAYOUTS[name]
    assert hashlib.sha256(layout.template.read_bytes()).hexdigest() == layout.sha256


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
def test_every_cell_and_check_lands_on_its_page(name):
    layout = LAYOUTS[name]
    out = render_form(layout, amounts={}, cells={key: "Q" * len(c.cells) for key, c in layout.cells.items()},
                      checks=list(layout.checks))
    pages = _pages(out.pdf)
    for key, spec in layout.cells.items():
        x0, x1 = spec.cells[0]
        assert any(w[4].startswith("Q") and x0 - 1 <= w[0] <= x1 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key
    for key, spec in layout.checks.items():
        assert any(w[4] == "X" and abs((w[0] + w[2]) / 2 - spec.x) < 3 and abs(w[3] - spec.baseline) < 4
                   for w in pages[spec.page]), key


def test_too_long_amount_is_printed_whole_in_red():
    layout = LAYOUTS["1701A"]  # 8-cell boxes
    out = render_form(layout, amounts={"20": "123456789"})
    assert out.overflow == ("20",)
    assert any(w[4] == "123456789" for w in _pages(out.pdf)[0])
```

- [ ] **Step 3: Add `ticks` to `overlay.py`** (above `Cells`):

```python
def ticks(*xs: float) -> tuple[Cell, ...]:
    """Cells between consecutive measured tick marks, for combs whose spacing is uneven."""
    return tuple(zip(xs, xs[1:]))
```

- [ ] **Step 4: The layout modules** are the calibrated files `bir1702rt_layout.py`, `bir1701_layout.py`, `bir1701a_layout.py` (tick-derived coordinates as listed in each module).
- [ ] **Step 5: Run** `docker compose exec -T backend python -m pytest -q tests/test_aa_pdf_overlay_annual.py` → PASS.
- [ ] **Step 6: Commit** `feat(accounting): annual ITR templates and calibrated overlay layouts`.

---

### Task 2: Straight-line depreciation (pure)

**Files:** Create `backend/app/services/accounting/compute/depreciation.py`; Test `backend/tests/test_aa_depreciation.py`.

**Interfaces — Produces:**
- `Asset(id, document_id, description, doc_number, cost: Decimal, in_service: date, life_months: int = 60, end_date: date | None = None)` (frozen).
- `monthly_amounts(asset) -> list[Decimal]` — one per month of life, in-service month first, sums to cost.
- `depreciation_between(asset, start: date, end: date) -> Decimal` — months whose month lies in [start, end], none after `end_date`'s month.
- `fiscal_year_window(fiscal_year, fye) -> tuple[date, date]`.
- `register_rows(assets, start, end) -> list[dict]` — ledger rows: `key, description, doc_number, in_service, cost, life_months, accumulated_start, this_year, accumulated_end, net_book_value`.
- `DEFAULT_LIFE_MONTHS = 60`.

- [ ] **Step 1: Tests**

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.depreciation import (
    Asset, depreciation_between, fiscal_year_window, monthly_amounts, register_rows,
)


def _asset(**kw):
    values = dict(id="a1", document_id="d1", description="Sewing machine", doc_number="SI-1",
                  cost=Decimal("100000.00"), in_service=date(2026, 3, 20), life_months=60)
    values.update(kw)
    return Asset(**values)


def test_in_service_month_counts_and_total_equals_cost():
    a = _asset(cost=Decimal("1000.00"), life_months=3)
    assert monthly_amounts(a) == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert depreciation_between(a, date(2026, 3, 1), date(2026, 3, 31)) == Decimal("333.33")
    assert depreciation_between(a, date(2026, 1, 1), date(2030, 12, 31)) == Decimal("1000.00")


def test_rounding_never_goes_negative():
    a = _asset(cost=Decimal("1.00"), life_months=199)
    amounts = monthly_amounts(a)
    assert all(x >= 0 for x in amounts) and sum(amounts) == Decimal("1.00")


def test_end_date_stops_depreciation_after_its_month():
    a = _asset(cost=Decimal("6000.00"), life_months=60, end_date=date(2026, 5, 10))
    assert depreciation_between(a, date(2026, 1, 1), date(2026, 12, 31)) == Decimal("300.00")  # Mar–May


def test_fiscal_year_window():
    assert fiscal_year_window(2026, 6) == (date(2025, 7, 1), date(2026, 6, 30))
    a = _asset(cost=Decimal("12000.00"), life_months=12, in_service=date(2025, 12, 5))
    start, end = fiscal_year_window(2026, 6)
    assert depreciation_between(a, start, end) == Decimal("7000.00")  # Dec 2025 – Jun 2026


def test_register_rows_for_a_year():
    a = _asset(cost=Decimal("12000.00"), life_months=24, in_service=date(2025, 7, 1))
    rows = register_rows([a, _asset(id="later", in_service=date(2027, 1, 1))], date(2026, 1, 1), date(2026, 12, 31))
    assert len(rows) == 1
    r = rows[0]
    assert (r["accumulated_start"], r["this_year"], r["accumulated_end"], r["net_book_value"]) == (
        Decimal("3000.00"), Decimal("6000.00"), Decimal("9000.00"), Decimal("3000.00"))
    assert r["key"] == "a1" and r["in_service"] == "2025-07-01" and r["life_months"] == "24"
```

- [ ] **Step 2: Implementation** — `compute/depreciation.py`:

```python
"""Straight-line depreciation from the asset register (pure).

The month an asset goes into service counts as a full month. Each month is cost ÷ life
rounded to centavos; the last month takes the remainder so the total equals cost.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.money import ZERO, c2, total

DEFAULT_LIFE_MONTHS = 60


@dataclass(frozen=True)
class Asset:
    id: str
    document_id: str
    description: str
    doc_number: str
    cost: Decimal
    in_service: date
    life_months: int = DEFAULT_LIFE_MONTHS
    end_date: date | None = None


def _month(d: date) -> int:
    return d.year * 12 + d.month - 1


def monthly_amounts(asset: Asset) -> list[Decimal]:
    months = max(int(asset.life_months), 1)
    cost = c2(asset.cost)
    if cost <= 0:
        return [ZERO] * months
    monthly = c2(cost / months)
    amounts: list[Decimal] = []
    booked = ZERO
    for index in range(months):
        left = c2(cost - booked)
        amount = left if index == months - 1 else min(monthly, left)
        amounts.append(amount)
        booked = c2(booked + amount)
    return amounts


def _booked(asset: Asset, first: int, last: int) -> Decimal:
    start = _month(asset.in_service)
    stop = _month(asset.end_date) if asset.end_date else None
    return total(amount for offset, amount in enumerate(monthly_amounts(asset))
                 if first <= start + offset <= last and (stop is None or start + offset <= stop))


def depreciation_between(asset: Asset, start: date, end: date) -> Decimal:
    return _booked(asset, _month(start), _month(end))


def fiscal_year_window(fiscal_year: int, fye: int = 12) -> tuple[date, date]:
    return quarter_start(fiscal_year, 1, fye), quarter_end(fiscal_year, 4, fye)


def register_rows(assets, start: date, end: date) -> list[dict]:
    rows = []
    for a in sorted(assets, key=lambda x: (x.in_service, x.description, x.id)):
        if a.in_service > end:
            continue
        before = _booked(a, 0, _month(start) - 1)
        this_year = depreciation_between(a, start, end)
        accumulated = c2(before + this_year)
        rows.append({
            "key": a.id, "description": a.description, "doc_number": a.doc_number,
            "in_service": a.in_service.isoformat(), "cost": c2(a.cost), "life_months": str(a.life_months),
            "end_date": a.end_date.isoformat() if a.end_date else "", "accumulated_start": before,
            "this_year": this_year, "accumulated_end": accumulated, "net_book_value": c2(c2(a.cost) - accumulated),
        })
    return rows
```

- [ ] **Step 3:** run `pytest tests/test_aa_depreciation.py` → PASS. **Step 4:** commit `feat(accounting): straight-line depreciation`.

---

### Task 3: Carry-overs — NOLCO and excess MCIT (pure)

**Files:** Create `backend/app/services/accounting/compute/carryover.py`; Test `backend/tests/test_aa_carryover.py`.

**Interfaces — Produces:**
- `CarryRow(year: int, amount: Decimal, used: Decimal = 0, normal_tax: Decimal | None = None, mcit: Decimal | None = None)`.
- `nolco_life(year) -> int` (5 for 2020/2021, else 3); `mcit_life(year) -> int` (3).
- `CarryResult(applied, expired, expired_years: tuple[int, ...], closing: tuple[CarryRow, ...], schedule: list[dict])`.
- `apply_carry(rows, fiscal_year, budget, life, *, deduct=True) -> CarryResult` — rows usable this year (incurred before it, not past `year + life`), oldest first; applied up to `budget` (none when `deduct=False`); in a row's last year its unapplied rest expires. Schedule rows: `key, year, amount, normal_tax, mcit, used_before, used_this_year, expired_this_year, remaining, expiry_year`.
- `add_new(result, year, amount, life, normal_tax=None, mcit=None) -> CarryResult` — this year's new loss / excess (amount > 0) appended to closing and schedule.
- `rows_from_json(raw) -> tuple[CarryRow, ...]` (ignores malformed rows, max 20), `rows_to_json(rows) -> list[dict]`.

- [ ] **Step 1: Tests**

```python
from decimal import Decimal as D

from app.services.accounting.compute.carryover import (
    CarryRow, add_new, apply_carry, mcit_life, nolco_life, rows_from_json, rows_to_json,
)


def test_nolco_oldest_first_and_expiry():
    rows = (CarryRow(2023, D("100")), CarryRow(2022, D("50"), D("10")))
    r = apply_carry(rows, 2025, D("60"), nolco_life)
    assert r.applied == D("60.00")
    assert [(s["year"], s["used_this_year"], s["expired_this_year"], s["remaining"]) for s in r.schedule] == [
        ("2022", D("40.00"), D("0.00"), D("0.00")), ("2023", D("20.00"), D("0.00"), D("80.00"))]
    assert r.closing == (CarryRow(2023, D("100.00"), D("20.00")),)
    r2026 = apply_carry(r.closing, 2026, D("0"), nolco_life)
    assert r2026.expired == D("80.00") and r2026.expired_years == (2023,) and r2026.closing == ()


def test_2020_loss_lasts_five_years():
    rows = (CarryRow(2020, D("500")),)
    assert apply_carry(rows, 2025, D("100"), nolco_life).applied == D("100.00")
    assert apply_carry(rows, 2025, D("100"), nolco_life).expired == D("400.00")
    assert apply_carry(rows, 2026, D("100"), nolco_life).schedule == []  # already gone


def test_osd_years_run_the_clock_without_deducting():
    r = apply_carry((CarryRow(2022, D("100")),), 2025, D("1000"), nolco_life, deduct=False)
    assert r.applied == D("0.00") and r.expired == D("100.00")


def test_excess_mcit_capped_at_rcit_minus_mcit():
    rows = (CarryRow(2024, D("30000"), normal_tax=D("10000"), mcit=D("40000")),)
    r = apply_carry(rows, 2025, D("12000"), mcit_life)   # RCIT 52,000 − MCIT 40,000
    assert r.applied == D("12000.00") and r.closing[0].used == D("12000.00")
    assert r.schedule[0]["normal_tax"] == D("10000.00") and r.schedule[0]["mcit"] == D("40000.00")


def test_add_new_and_json_round_trip():
    r = add_new(apply_carry((), 2025, D("0"), nolco_life), 2025, D("700"), nolco_life)
    assert r.closing == (CarryRow(2025, D("700.00")),) and r.schedule[-1]["expiry_year"] == "2028"
    raw = rows_to_json(r.closing) + [{"year": "x"}, {"year": 2024, "amount": "-5"}]
    assert rows_from_json(raw) == r.closing
```

- [ ] **Step 2: Implementation** — `compute/carryover.py`:

```python
"""NOLCO and excess MCIT carried across taxable years (pure).

A row is usable in the years after it arose, up to ``year + life``; whatever is still
unapplied in that last year expires. Rows are applied oldest first.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.money import ZERO, c2

MAX_ROWS = 20


@dataclass(frozen=True)
class CarryRow:
    year: int
    amount: Decimal
    used: Decimal = ZERO
    normal_tax: Decimal | None = None
    mcit: Decimal | None = None


@dataclass(frozen=True)
class CarryResult:
    applied: Decimal
    expired: Decimal
    expired_years: tuple[int, ...]
    closing: tuple[CarryRow, ...]
    schedule: list[dict]


def nolco_life(year: int) -> int:
    """RR 25-2020: losses of taxable years 2020 and 2021 carry over for 5 years, others for 3."""
    return 5 if year in (2020, 2021) else 3


def mcit_life(year: int) -> int:
    return 3


def _row_out(row: CarryRow, life, used_now: Decimal, expired: Decimal, left: Decimal) -> dict:
    return {"key": str(row.year), "year": str(row.year), "amount": c2(row.amount),
            "normal_tax": "" if row.normal_tax is None else c2(row.normal_tax),
            "mcit": "" if row.mcit is None else c2(row.mcit), "used_before": c2(row.used),
            "used_this_year": used_now, "expired_this_year": expired, "remaining": left,
            "expiry_year": str(row.year + life(row.year))}


def apply_carry(rows, fiscal_year: int, budget, life, *, deduct: bool = True) -> CarryResult:
    left_to_apply = max(c2(budget), ZERO) if deduct else ZERO
    applied = expired = ZERO
    expired_years: list[int] = []
    closing: list[CarryRow] = []
    schedule: list[dict] = []
    for row in sorted(rows, key=lambda r: r.year):
        last = row.year + life(row.year)
        if row.year >= fiscal_year or fiscal_year > last:
            continue
        remaining = max(c2(row.amount - row.used), ZERO)
        used_now = min(remaining, left_to_apply)
        left_to_apply = c2(left_to_apply - used_now)
        gone = c2(remaining - used_now) if fiscal_year == last else ZERO
        left = c2(remaining - used_now - gone)
        schedule.append(_row_out(row, life, used_now, gone, left))
        applied, expired = c2(applied + used_now), c2(expired + gone)
        if gone > 0:
            expired_years.append(row.year)
        if left > 0:
            closing.append(replace(row, amount=c2(row.amount), used=c2(row.used + used_now)))
    return CarryResult(applied, expired, tuple(expired_years), tuple(closing), schedule)


def add_new(result: CarryResult, year: int, amount, life, normal_tax=None, mcit=None) -> CarryResult:
    amount = c2(amount)
    if amount <= 0:
        return result
    row = CarryRow(year, amount, ZERO, normal_tax, mcit)
    return replace(result, closing=result.closing + (row,),
                   schedule=result.schedule + [_row_out(row, life, ZERO, ZERO, amount)])


def _money(value) -> Decimal | None:
    try:
        return c2(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def rows_from_json(raw) -> tuple[CarryRow, ...]:
    rows: list[CarryRow] = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_ROWS]:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            continue
        amount = _money(item.get("amount"))
        used = _money(item.get("used") or "0")
        if not 2000 <= year <= 2100 or amount is None or amount <= 0 or used is None or used < 0:
            continue
        rows.append(CarryRow(year, amount, used, _money(item["normal_tax"]) if item.get("normal_tax") else None,
                             _money(item["mcit"]) if item.get("mcit") else None))
    return tuple(rows)


def rows_to_json(rows) -> list[dict]:
    out = []
    for r in rows:
        item = {"year": r.year, "amount": str(c2(r.amount)), "used": str(c2(r.used))}
        if r.normal_tax is not None:
            item["normal_tax"] = str(c2(r.normal_tax))
        if r.mcit is not None:
            item["mcit"] = str(c2(r.mcit))
        out.append(item)
    return out
```

- [ ] **Step 3:** run tests → PASS. **Step 4:** commit `feat(accounting): NOLCO and excess MCIT carry-over schedules`.

---

### Task 4: Annual inputs, Q1–Q3 credits and annual due dates (pure)

**Files:** Create `backend/app/services/accounting/compute/annual_inputs.py`; Modify `compute/due_dates.py`; Test `backend/tests/test_aa_annual_inputs.py`.

**Interfaces — Produces:**
- `AnnualInputs` (frozen) with fields: `ending_inventory, non_operating_income, prior_year_excess_credits, q1_paid, q2_paid, q3_paid` (`Decimal | None`), `amended_paid_income_tax: Decimal = 0`, `cit_20_percent: bool`, `refund_overpayment: bool`, balance sheet `current_assets, ppe_net, other_noncurrent_assets, current_liabilities, noncurrent_liabilities, equity` (`Decimal | None`), `book_net_income: Decimal | None`, `nondeductible_expenses, nontaxable_income, other_reconciling: Decimal = 0`, `opening_nolco, opening_excess_mcit: tuple[CarryRow, ...]`.
- `annual_inputs_from_json(data) -> AnnualInputs`, `annual_inputs_to_json(inputs) -> dict` (opening rows as `{year, amount, used}`).
- `QuarterSource(quarter, payable: Decimal | None = None, version: int | None = None, filed: bool = False, latest_version: int | None = None)`.
- `quarter_credits(sources: dict[int, QuarterSource], inputs, cwt_by_quarter: dict[int, Decimal]) -> tuple[list[dict], Decimal, list[str]]` — QuarterCredits ledger rows (`key, quarter, source, tax_paid, cwt`; Q1–Q4), total Q1–Q3 paid, warnings.
- `due_dates.annual_due_date(form, fiscal_year, fye=12) -> date`.

- [ ] **Step 1: Tests**

```python
from datetime import date
from decimal import Decimal as D

from app.services.accounting.compute.annual_inputs import (
    AnnualInputs, QuarterSource, annual_inputs_from_json, annual_inputs_to_json, quarter_credits,
)
from app.services.accounting.compute.carryover import CarryRow
from app.services.accounting.compute.due_dates import annual_due_date


def test_parse_with_fallbacks_and_round_trip():
    raw = {"ending_inventory": "1200.5", "q2_paid": "abc", "cit_20_percent": True, "other_reconciling": "-300",
           "opening_nolco": [{"year": 2023, "amount": "5000", "used": "1000"}, {"year": "bad"}]}
    inputs = annual_inputs_from_json(raw)
    assert inputs.ending_inventory == D("1200.50") and inputs.q2_paid is None and inputs.cit_20_percent
    assert inputs.other_reconciling == D("-300.00")
    assert inputs.opening_nolco == (CarryRow(2023, D("5000.00"), D("1000.00")),)
    assert annual_inputs_from_json(annual_inputs_to_json(inputs)) == inputs
    assert annual_inputs_from_json(None) == AnnualInputs()


def test_quarter_credits_filed_latest_override_missing():
    sources = {1: QuarterSource(1, D("1000"), 2, True, 3), 2: QuarterSource(2, D("-50"), 1, False, 1)}
    rows, paid, warnings = quarter_credits(sources, AnnualInputs(q3_paid=D("700")), {1: D("10"), 4: D("40")})
    assert [(r["quarter"], r["source"], r["tax_paid"], r["cwt"]) for r in rows] == [
        ("Q1", "filed v2", D("1000.00"), D("10.00")), ("Q2", "latest v1", D("0.00"), D("0.00")),
        ("Q3", "entered", D("700.00"), D("0.00")), ("Q4", "this return", D("0.00"), D("40.00"))]
    assert paid == D("1700.00")
    assert any("Q1 has v3" in w for w in warnings) and not any("Q3" in w for w in warnings)
    _, _, missing = quarter_credits({}, AnnualInputs(), {})
    assert sum("taken as ₱0" in w for w in missing) == 3


def test_annual_due_dates():
    assert annual_due_date("1702RT", 2026, 12) == date(2027, 4, 15)
    assert annual_due_date("1702RT", 2026, 6) == date(2026, 10, 15)
    assert annual_due_date("1701", 2026) == date(2027, 4, 15)
    assert annual_due_date("1701A", 2025) == date(2026, 4, 15)
    assert annual_due_date("1702RT", 2027, 3) == date(2027, 7, 15)
```

- [ ] **Step 2: Implementation** — `compute/annual_inputs.py`:

```python
"""Annual return inputs and the Q1–Q3 income tax credit (pure)."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.carryover import CarryRow, rows_from_json
from app.services.accounting.compute.money import ZERO, c2

_OPTIONAL = ("ending_inventory", "non_operating_income", "prior_year_excess_credits", "q1_paid", "q2_paid",
             "q3_paid", "current_assets", "ppe_net", "other_noncurrent_assets", "current_liabilities",
             "noncurrent_liabilities", "equity", "book_net_income")
_AMOUNTS = ("amended_paid_income_tax", "nondeductible_expenses", "nontaxable_income", "other_reconciling")
_FLAGS = ("cit_20_percent", "refund_overpayment")


@dataclass(frozen=True)
class AnnualInputs:
    ending_inventory: Decimal | None = None
    non_operating_income: Decimal | None = None
    prior_year_excess_credits: Decimal | None = None
    q1_paid: Decimal | None = None
    q2_paid: Decimal | None = None
    q3_paid: Decimal | None = None
    amended_paid_income_tax: Decimal = ZERO
    cit_20_percent: bool = False
    refund_overpayment: bool = False
    current_assets: Decimal | None = None
    ppe_net: Decimal | None = None
    other_noncurrent_assets: Decimal | None = None
    current_liabilities: Decimal | None = None
    noncurrent_liabilities: Decimal | None = None
    equity: Decimal | None = None
    book_net_income: Decimal | None = None
    nondeductible_expenses: Decimal = ZERO
    nontaxable_income: Decimal = ZERO
    other_reconciling: Decimal = ZERO
    opening_nolco: tuple[CarryRow, ...] = field(default_factory=tuple)
    opening_excess_mcit: tuple[CarryRow, ...] = field(default_factory=tuple)


def _money(raw) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return c2(raw)
    except (InvalidOperation, TypeError, ValueError):
        return None


def annual_inputs_from_json(data: dict | None) -> AnnualInputs:
    data = data if isinstance(data, dict) else {}
    kwargs: dict = {}
    for name in _OPTIONAL + _AMOUNTS:
        value = _money(data.get(name))
        if value is not None:
            kwargs[name] = value
    for name in _FLAGS:
        kwargs[name] = bool(data.get(name, False))
    kwargs["opening_nolco"] = tuple(CarryRow(r.year, r.amount, r.used)
                                    for r in rows_from_json(data.get("opening_nolco")))
    kwargs["opening_excess_mcit"] = tuple(CarryRow(r.year, r.amount, r.used)
                                          for r in rows_from_json(data.get("opening_excess_mcit")))
    return AnnualInputs(**kwargs)


def _rows(rows) -> list[dict]:
    return [{"year": r.year, "amount": str(r.amount), "used": str(r.used)} for r in rows]


def annual_inputs_to_json(inputs: AnnualInputs) -> dict:
    out: dict = {}
    for name in _OPTIONAL + _AMOUNTS:
        value = getattr(inputs, name)
        out[name] = None if value is None else str(value)
    for name in _FLAGS:
        out[name] = getattr(inputs, name)
    out["opening_nolco"] = _rows(inputs.opening_nolco)
    out["opening_excess_mcit"] = _rows(inputs.opening_excess_mcit)
    return out


@dataclass(frozen=True)
class QuarterSource:
    """What a quarterly income tax return says was payable: its filed version, else its latest."""

    quarter: int
    payable: Decimal | None = None
    version: int | None = None
    filed: bool = False
    latest_version: int | None = None


def quarter_credits(sources: dict, inputs: AnnualInputs, cwt_by_quarter: dict) -> tuple[list[dict], Decimal, list[str]]:
    rows: list[dict] = []
    warnings: list[str] = []
    paid_total = ZERO
    overrides = {1: inputs.q1_paid, 2: inputs.q2_paid, 3: inputs.q3_paid}
    for q in (1, 2, 3):
        src = sources.get(q) or QuarterSource(q)
        if overrides[q] is not None:
            source, paid = "entered", c2(overrides[q])
        elif src.payable is not None and src.version is not None:
            source = f"{'filed' if src.filed else 'latest'} v{src.version}"
            paid = max(c2(src.payable), ZERO)  # an overpayment paid nothing
            if src.filed and src.latest_version and src.latest_version > src.version:
                warnings.append(f"Q{q} has v{src.latest_version}, newer than the filed v{src.version}. The annual "
                                "return credits the tax paid on the filed version.")
        else:
            source, paid = "none", ZERO
            warnings.append(f"There is no Q{q} income tax return on AutoAccounting, so Q{q} tax paid was taken as "
                            f"₱0. Enter it in the annual inputs if Q{q} was filed elsewhere.")
        paid_total = c2(paid_total + paid)
        rows.append({"key": f"Q{q}", "quarter": f"Q{q}", "source": source, "tax_paid": paid,
                     "cwt": c2(cwt_by_quarter.get(q, ZERO))})
    rows.append({"key": "Q4", "quarter": "Q4", "source": "this return", "tax_paid": ZERO,
                 "cwt": c2(cwt_by_quarter.get(4, ZERO))})
    return rows, paid_total, warnings
```

`due_dates.py` gains:

```python
def annual_due_date(form: str, fiscal_year: int, fye: int = 12) -> date:
    """1702-RT: the 15th day of the 4th month after year end. 1701 / 1701-A: April 15 of the next year."""
    if form == "1702RT":
        end = quarter_end(fiscal_year, 4, fye)
        due = _add_months(date(end.year, end.month, 1), 4)
        return _next_business_day(date(due.year, due.month, 15))
    return _next_business_day(date(fiscal_year + 1, 4, 15))
```

- [ ] **Step 3:** run tests → PASS. **Step 4:** commit `feat(accounting): annual inputs, Q1–Q3 credit sourcing and annual due dates`.

---

### Task 5: Annual engine, quarterly depreciation, specs and workbook

**Files:**
- Create: `backend/app/services/accounting/compute/annual.py`
- Modify: `compute/engine.py` (public `split_vat_sales`, `cwt_credits`, `cogs_chain`; `assets` parameter; depreciation in deductions; capital goods warning), `compute/cogs.py` (capital goods never in cost of sales), `compute/deductions.py` (`expenses_form(b, depreciation=ZERO)`), `compute/inputs.py` (`CompanyFacts.operations_start_year: int | None = None`), `compute/specs.py` (titles, items, notes, ledgers, payable items for the annual forms), `render_xlsx.py` (year cells not number-formatted).
- Test: `backend/tests/test_aa_annual.py`, additions to `test_aa_engine.py`, `test_aa_xlsx.py`.

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `build_quarter(company, periods, amended=False, assets=())` — `assets: Sequence[Asset]`.
  - `annual.annual_form(company) -> "1702RT" | "1701" | "1701A"` (individual: itemized → 1701, OSD or 8% → 1701A).
  - `annual.CarryIn(nolco=(), excess_mcit=(), excess_credits: Decimal | None = None)`; `annual.carry_in_from_snapshot(carry: dict | None) -> CarryIn`.
  - `annual.AnnualResult(form, forms, ledgers, warnings, carry_out: dict, review_open)`.
  - `annual.build_annual(company, periods, fiscal_year, inputs, *, assets=(), quarter_sources=None, carry_in=CarryIn(), amended=False) -> AnnualResult`.
  - `annual.ordinary_schedule(breakdown, depreciation) -> dict[str, Decimal]` with keys `5, 6, 11, 13, 15, 16, 17B, 17D, 18` (peso).
  - `carry_out = {"nolco": [...], "excess_mcit": [...], "excess_credits": "123" | None}` — stored as `snapshot["carry"]`.
  - Forms also carry `OVERPAYMENT_OPTION` (`"refund"`, `"carry_over"` or `""`) and year cells `S3_n_YEAR` / `S4_n_YEAR` / `S6_n_YEAR`.

**Computation rules (all whole pesos on the return):**
- Sales = Σ `sales_base` of the fiscal year's quarters (VAT sales split as in quarters). Cost of sales (not services) = beginning inventory of the first fiscal-year quarter in the chain + the year's purchases (capital goods excluded) − ending inventory (annual input, else Q4's input, else ₱0 with a warning).
- Ordinary deductions = `quarter_expenses` over the whole year (representation cap on the year's sales) + the year's depreciation, mapped by `ordinary_schedule`: depreciation → 5, representation allowed → 6, rent → 11, salaries + payroll → 13, taxes and licenses → 15, transportation → 16, professional fees → 17b, everything else → 17d ("OTHERS — SEE WORKBOOK").
- Non-operating income = annual input, else Σ quarter inputs.
- 1702-RT: 27 sales, 28 0, 29, 30 cost of sales, 31, 32 non-operating, 33; itemized: 34 = Sched I 18, 35 0, 36 NOLCO applied (budget 33 − 34), 37, 38 0, 39 = 33 − 37; OSD: 34–37 0, 38 = 40% × 33, 39 = 33 − 38 (NOLCO clock runs). 40 rate (20 when `cit_20_percent` and 39 ≤ ₱5M, else 25 with a warning), 41 = max(39, 0) × rate, 42 = 2% × max(33, 0) when MCIT applies, 43 = max(41, 42). Credits 44 prior excess (input, else previous year's carried overpayment), 45 0, 46 Q1–Q3 paid, 47 excess MCIT applied (cap max(41 − 42, 0)), 48 CWT Q1–Q3, 49 CWT Q4, 50 0, 51 amended paid, 52–54 0, 55 sum, 56 = 43 − 55. Part II 14 = 43, 15 = 55, 16 = 56, 17–20 0, 21 = 16. New excess MCIT = 42 − 41 when MCIT applies and is higher.
- MCIT applies when `operations_start_year` is set and fiscal year ≥ start + 4; when not set, follow Q3's `mcit_applies` input (warning); with no Q3 inputs, off (warning).
- 1701 (itemized): S3_8 sales … S3_11 cost of sales, S3_12, S3_13 = S4_18, S3_14 0, S3_15 NOLCO, S3_16, S3_17 0, S3_18 = 12 − 16, S3_19 non-operating, S3_20/21 0, S3_22, S3_23 = 18 + 22, S3_24 = 23, S3_25 = graduated(max(24, 0)). NOLCO budget = max(S3_12 + S3_22 − S3_13, 0). Schedule 6: S6_1 = 12 + 22, S6_2 = 13, S6_3 = loss. Part VI P6_1 = P6_5 = S3_25. Part VII P7_1 prior excess, P7_2 Q1–Q3 paid, P7_3 CWT Q1–Q3, P7_4 CWT Q4, P7_6 amended paid, P7_10 sum. Part II 22 = P6_5, 23 = P7_10, 24, 25 0, 26 = 24, 27–30 0, 31 = 26, 32 = 31.
- 1701-A OSD: 36 sales, 37 0, 38, 39 = 40% × 38, 40, 41 non-operating, 42/43 0, 44, 45 = 40 + 44, 46 = graduated(max(45, 0)). 8%: 47 sales, 48 0, 49, 50 non-operating, 51 0, 52, 53, 54 250,000, 55 = max(53 − 54, 0), 56 = 8% × 55; warning when 53 > ₱3M. Credits 57–65 like Part VII; Part II 20 = due, 21 = 64, 22 = 65, 23 0, 24 = 22, 25–28 0, 29 = 24, 30 = 29. NOLCO clock runs, nothing deducted.
- Reconciliation (when `book_net_income` is entered): 1702-RT S5_1 book income, S5_2 non-deductible, S5_3 positive other items, S5_4, S5_5 non-taxable, S5_7 negative other items (as positive), S5_9, S5_10 = 4 − 9; 1701 P9_1/P9_2/P9_3/P9_5/P9_6/P9_8/P9_10/P9_11 the same. Warning when S5_10 / P9_11 differs from taxable income before NOLCO. Not entered → warning, schedule blank.
- BalanceSheet tab when any balance input is entered: PPE net defaults to the register's net book value; warning when assets ≠ liabilities + equity by more than ₱1.
- Warnings also cover: open reviews (DRAFT, first), compensation income not included (individuals), expired NOLCO/MCIT, amended without amount paid, unsorted documents, quarters without documents.
- Quarterly: each quarter's depreciation (`depreciation_between` over the quarter's months) is added to `QuarterFigures.deductions` (1702-Q/1701-Q itemized; OSD/8% ignore deductions); the Expenses tab gains `depreciation` and its total includes it. The "capital goods were not expensed" warning becomes "₱X of capital goods bought this quarter are in the asset register and depreciated over their useful life, not expensed."

- [ ] **Step 1: Tests** (`test_aa_annual.py`) — scenarios, each asserting exact items:
  - `test_corporation_itemized_profit`: trading VAT corp FY2026, sales 1,000,000 VATable across Q1–Q4, purchases 400,000, ending inventory 100,000 (annual input), rent 120,000, one asset 60,000 / 60 months in service 2026-01-15 → 27 = 1,000,000; 30 = 300,000; 34 = 132,000 (S1_5 = 12,000, S1_11 = 120,000); 39 = 568,000; 41 = 142,000; 43 = 142,000; QuarterCredits Q1–Q3 from sources; 56 = 43 − 55; `Depreciation` ledger row this_year 12,000.
  - `test_loss_year_then_profit_uses_nolco`: FY2025 loss → `carry_out["nolco"] == [{"year": 2025, "amount": "...", "used": "0.00"}]`; FY2026 with `carry_in_from_snapshot` of that → 36 = min(loss, 33 − 34); NOLCO ledger rows.
  - `test_mcit_year_then_rcit_year`: `operations_start_year=2020`; FY2025 small gross income margin → 42 > 41, new excess row; FY2026 → 47 = min(excess, 41 − 42).
  - `test_mcit_off_without_start_year_warns`.
  - `test_cit_20_percent_only_up_to_5m`.
  - `test_individual_osd_1701a_and_eight_percent` (including 3M warning and compensation warning).
  - `test_individual_itemized_1701`.
  - `test_june_fiscal_year`: FYE 6, documents dated 2025-07 to 2026-06 in FY2026, asset in service 2025-12 → depreciation 7 months.
  - `test_reconciliation_and_balance_sheet_warnings`.
  - `test_overpayment_carried_unless_refund`: payable negative → `carry_out["excess_credits"]`, `OVERPAYMENT_OPTION`.
  - `test_snapshot_through_write_workbook` (tabs `1702RT`, `Depreciation`, `NOLCO`, `QuarterCredits`; year cells unformatted).
  - `test_engine.py`: `test_quarter_depreciation_reduces_itemized_income`, `test_capital_goods_purchases_stay_out_of_cogs`.
- [ ] **Step 2–3:** implement `compute/annual.py` per the rules above, engine/cogs/deductions/specs/render_xlsx changes; run the whole suite (Phase 2/3 expectations that relied on capital goods in COGS or on the old warning are updated).
- [ ] **Step 4:** commit `feat(accounting): annual income tax engine with depreciation, NOLCO and MCIT`.

---

### Task 6: Annual PDFs and the 2550-Q branch code

**Files:** Modify `backend/app/services/accounting/pdf_returns.py`, `pdf_2550q.py`, `forms/bir2550q_layout.py` (`P1_BRANCH`); Test `backend/tests/test_aa_pdf_annual.py`, addition to `test_aa_pdf_2550q.py`.

**Interfaces:**
- `LAYOUTS` gains `1702RT`, `1701`, `1701A`; `_identity` fills `name_3` / `address_3` when the layout has them.
- Fillers: `_fill_1702rt` (year ended MM + YY, `40` rate cell, calendar/fiscal, amended, `short_no`, `atc_IC055`, itemized/OSD, overpayment box from `OVERPAYMENT_OPTION`, `tin_p2..4`/`name_p2..4`, year cells, description cells for filled 17d / Schedule V rows; note when more than three prior NOLCO years); `_fill_1701` (year, amended, short_no, single proprietor, `atc_II012`, foreign/exempt/special no, graduated + itemized, overpayment, page headers, years, descriptions); `_fill_1701a` (`year_month` = FYE month, `year`, amended, short_no, single proprietor, ATC II012 or II015, foreign no, `rate_osd`/`rate_eight`, overpayment, page 2 header, descriptions).
- `Header2550Q` gains `branch_code: str = "00000"`; when not `00000`, the pre-printed zeros are covered white and the branch digits printed.

- [ ] Tests: each form renders with header cells, checks and a known amount at its box (word positions), `OVERPAYMENT_OPTION` → box, amended box on amended versions, highlight of a changed item, 2550-Q branch digits at the branch cells.
- [ ] Commit `feat(accounting): fill the 1702-RT, 1701 and 1701-A; branch code on the 2550-Q`.

---

### Task 7: Database — assets, filed version, company fields, staleness and the tree

**Files:** Modify `models/accounting.py` (`AAAsset`; `AACompany.operations_start_year`, `facts_updated_at`; `AAPeriod.filed_output_id`), `services/accounting/schema.py`, `services/accounting/rls.py`, `schemas/accounting.py` (`CompanyIn.operations_start_year`, tree annual node), `routers/accounting.py` (company update sets `facts_updated_at`; tree status for quarter 0, asset and company changes), `routers/accounting_periods.py` (quarterly queries exclude quarter 0; `_is_stale` adds company facts and assets; mark-as-filed records `filed_output_id`; generation syncs assets and passes them; `period_label` handles 0), `services/accounting/tree.py` (`stale_periods(changes, generated, *, always=None, annual_changes=None)`; `build_tree` adds `annual` per year); Create `services/accounting/assets.py` (`asset_from_document`, `sync_assets`, `active_assets`).
- Tests: `test_aa_period_status.py` (`test_annual_stale_rules`, quarter ignores annual inputs, company facts), `test_accounting_tree.py` (annual node), `test_aa_wiring.py` (columns, `test_active_assets_follow_documents` for the pure selection), `test_accounting_rls.py` (aa_assets policy).

**Interfaces:**
- `AAAsset(id, enterprise_id, company_id, document_id unique FK aa_documents CASCADE, description, cost NUMERIC(14,2), in_service date, useful_life_months int default 60, end_date date null, created_at, updated_at)`.
- `assets.asset_from_document(doc_line, vat_registered, period_start) -> tuple[str, Decimal, date]` (description, cost, in-service default), `assets.is_asset_document(category, account, client_role) -> bool`, `async sync_assets(db, company) -> list[Asset]` (creates missing rows, updates cost when the document changed, returns `Asset`s of active documents only).
- `stale_periods`: quarterly output (q ≥ 1) is stale when a change in a quarterly period ≤ it is newer; annual output (q = 0) when a change in any period of that year or earlier, any `annual_changes` entry of that year (quarterly versions generated / filed) or the previous year's annual, or `always` (company facts) is newer.

- [ ] Commit `feat(accounting): asset register, filed version, annual staleness and tree node`.

---

### Task 8: Annual and asset API

**Files:** Create `backend/app/routers/accounting_annual.py`; Modify `routers/accounting.py` (include it **before** `accounting_periods`), `schemas/accounting.py` (`AnnualInputsModel`, `OpeningRowModel`, `AnnualPeriodOut`, `AssetOut`, `AssetPatch`); Test `backend/tests/test_accounting_annual_routes.py` (route order: `/periods/{c}/{y}/annual` resolves to the annual handler; schema validation of opening rows and life 1–600).

**Routes (enterprise-scoped, `company_or_404`):**
- `GET /periods/{company_id}/{year}/annual` → `AnnualPeriodOut` (company, year, label `"{year} · Annual"`, inputs, filed_at, document_count, open_reviews, latest_version, stale, forms_expected `[annual_form]`, due_dates, outputs, `carry_source`).
- `PUT …/annual/inputs` (sets `inputs_updated_at`), `PUT …/annual/filed` (records `filed_output_id`), `POST …/annual/generate` → `OutputOut` (sync assets, load periods to Q4, quarter sources from Q1–Q3 periods' filed/latest outputs, carry-in from the previous year's annual filed/latest output else opening inputs, `build_annual`, snapshot + `carry`, workbook header period `"FY {year} · Annual"`, files under `outputs/{company}/{year}A/`).
- `GET /companies/{company_id}/assets?year=` → `list[AssetOut]` (syncs first; each with document number/date, active flag, this year's depreciation, accumulated to year end, net book value). `PATCH /assets/{asset_id}` (description, in_service, useful_life_months 1–600, end_date ≥ in_service).
- Output download names use `Annual` instead of `Q{n}` for quarter 0.

- [ ] Commit `feat(accounting): annual period and asset register API`.

---

### Task 9: Frontend — Annual node, AnnualPanel, asset section, company field

**Files:** Modify `frontend/src/types/accounting.ts`, `frontend/src/lib/accounting-api.ts`, `components/accounting/FolderTree.tsx` (Annual leaf, newest first above Q4, with status chip), `app/accounting/page.tsx` (quarter 0 → `AnnualPanel`, no folder fetch), `components/accounting/DocumentPanel.tsx` (Asset section for capital goods), `components/accounting/CompanyForm.tsx` (year operations began, non-individuals), `components/accounting/OutputViewer.tsx` (year cells shown raw; annual label); Create `components/accounting/AnnualPanel.tsx`.

- AnnualPanel groups: Income (ending inventory, non-operating income), Credits and overrides (prior year's excess credits, Q1–Q3 tax paid overrides, paid on the original return when filed, 20% CIT, refund instead), Balance sheet (6), Reconciliation (4), Opening schedules (NOLCO and, for non-individuals, excess MCIT: editable rows year/amount/used, shown when there is no previous annual output), then Generate, versions, filed toggle, `OutputViewer`, and a read-only asset list with this year's depreciation.
- [ ] `npx tsc --noEmit`, eslint, `npm run build` pass. Commit `feat(accounting): annual return panel, asset editing and annual tree node`.

---

### Task 10: Verification

- [ ] Full backend suite and frontend build.
- [ ] Scripted end-to-end in the running dev stack (feature toggle on): a corporation with documents in all four quarters, a capital-goods document, generate Q1–Q3, mark Q1 filed, regenerate Q1, generate Annual (warning about the filed version), download XLSX and all PDFs, edit the asset → Annual and later quarters stale.
- [ ] Update `autoaccounting-status` memory.
