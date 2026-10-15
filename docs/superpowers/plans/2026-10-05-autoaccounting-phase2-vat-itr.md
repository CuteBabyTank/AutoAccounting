# AutoAccounting Phase 2 (VAT and ITR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From the documents filed in Phase 1, generate a quarter's BIR returns (2550-Q, 2551-Q, 1701-Q, 1702-Q), cost of sales, deductions and the SLS/SLP/SAWT lists as a versioned XLSX workbook with every change since the previous version highlighted pastel yellow, plus a filled 2550-Q PDF generated from that output.

**Architecture:** A pure computation package (`app/services/accounting/compute/`) turns plain `DocLine`s + per-quarter `PeriodInputs` into form values, ledgers and warnings; everything is recomputed from documents each time (VAT carry-over and inventory chain from the company's first quarter, income tax year-to-date from Q1 of the fiscal year). Each "Generate" stores an immutable `aa_outputs` version holding a string snapshot of all values, its diff against the previous version, and two XLSX files (highlighted and clean); the 2550-Q PDF is rendered on demand from the stored snapshot onto the official BIR template. A sub-router on `/api/accounting` exposes period inputs, generation and downloads; the Documents page gains a quarter panel, an output viewer and an "add to vN → vN+1?" prompt.

**Tech Stack:** Python `decimal`, openpyxl, PyMuPDF (fitz), FastAPI, async SQLAlchemy, pytest in the backend container; Next.js 15 / React 19 / Tailwind 4 frontend.

**Spec:** AutoAccounting spec sheet (Claude Doc) https://claude.ai/code/artifact/8dcfb05b-3f3e-4410-a082-da75a391cd21 — sections *Computation engine*, *Filling the BIR forms*, *XLSX workbook*, *Adding documents to a quarter that already has output*, and the Phase 2 band of *Rollout*. Phase 1 plan for context: `docs/superpowers/plans/2026-10-05-autoaccounting-phase1-intake.md`.

## Global Constraints

- Stay inside the AutoAccounting module: new code under `backend/app/services/accounting/`, `backend/app/routers/accounting*.py`, `backend/app/models/accounting.py`, `backend/app/schemas/accounting.py`, `backend/app/forms/` (new layout + template only), `frontend/src/{components,app}/accounting/`, `frontend/src/lib/accounting-*`, `frontend/src/types/accounting.ts`. No edits to other modules; new routes mount via `router.include_router` inside `routers/accounting.py` (no `main.py` change).
- Storage stays local: outputs go under `settings.accounting_root/accounting/outputs/…` (dev = `backend/uploads/accounting/outputs/`). No buckets, no Cloud Build changes.
- Money is `Decimal` end to end; VAT/percentage tax round to centavos half-up, income tax returns to whole pesos half-up ("DO NOT enter Centavos").
- VAT rate 12%; percentage tax 3% (ATC PT 010); 8% option = 8% × (cumulative gross sales + non-operating income − ₱250,000); graduated table = BIR Table 2 (2023 onwards); corporate rate 25% default, 20% selectable; MCIT 2% of gross income when enabled; OSD 40% (gross income for corporations, gross sales for individuals); representation cap 0.5% of net sales (trading/manufacturing) or 1% (services), year to date.
- Form item numbers follow the official PDFs: 2550-Q April 2024 (items 15–26, 31A–61B), 2551-Q January 2018 (Schedule 1, items 14–24), 1701-Q January 2018 (items 36–68), 1702-Q January 2018 (Schedules 2–4, items 14–25).
- Gemini is not called in Phase 2; every figure is computed in Python.
- Pastel yellow = `#FFF4B3`; highlighted text stays dark (`#1F1F1F`) in both themes.
- Outputs are immutable versions; regenerating creates v(n+1) and never overwrites.
- New tables carry `enterprise_id` and get the same FORCE RLS policy as the Phase 1 `aa_*` tables.
- Backend tests: `docker compose exec -T backend python -m pytest -q`; frontend: `cd frontend && npx tsc --noEmit && npx eslint src/components/accounting src/app/accounting src/lib/accounting-api.ts src/lib/accounting-format.ts src/types/accounting.ts` and `npm run build`. Restore `frontend/tsconfig.tsbuildinfo` after `tsc` (`git checkout -- frontend/tsconfig.tsbuildinfo`).
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; branch `AutoAccounting`; never push.

## Review Focus

1. **A quarter whose earlier quarters have no documents** (client onboarded mid-year) → income tax must not silently treat Q1–Q2 as zero without saying so; the user can enter prior totals. Pinned in Task 4 (`test_prior_override_replaces_missing_quarters`, `test_missing_earlier_quarters_warn`).
2. **Excess input VAT** (purchases VAT > output VAT) → item 61 negative, nothing payable, and the excess carries into the next quarter's item 38. Pinned in Task 2 (`test_excess_input_vat_carries_out`) and Task 4 (`test_vat_excess_chains_into_next_quarter`).
3. **Missing ending inventory** → cost of sales computed with ₱0 ending inventory and a visible warning, never a crash. Pinned in Task 1 (`test_cogs_without_ending_inventory`) and Task 4 (`test_missing_ending_inventory_warns`).
4. **Regenerating with no changes** → v(n+1) shows zero highlights; **a changed amount** → exactly that cell (and its totals) highlighted. Pinned in Task 5 (`test_identical_snapshots_have_no_changes`) and Task 6 (`test_changed_cell_is_yellow_with_comment`).
5. **Negative amounts on the PDF** (excess input tax / overpayment) → printed in parentheses inside the right box, not off the edge. Pinned in Task 7 (`test_negative_amount_in_parentheses`).

## Deviations from the spec (Phase 2 scope decisions)

- Workbook form tabs hold computed **values** with a "How it's computed" column instead of live Excel formulas, so version diffs compare real numbers.
- Carry-overs (excess input VAT, inventory, income-tax year to date) are **recomputed from documents** every time rather than stored in an `aa_carryovers` table; the first quarter on the platform takes opening values from its quarter inputs.
- PDFs: only the **2550-Q** overlay ships in Phase 2 (rollout). 2551-Q, 1701-Q and 1702-Q are in the workbook; their PDFs come with Phase 3.
- Not modelled yet (shown as 0 with the BIR item present): output VAT on uncollected receivables (35–36), capital goods > ₱1M deferral (39, 52), services by non-residents (45), penalties (22–25), special-rate income (1702-Q Schedule 1), spouse column (1701-Q B). Capital goods are excluded from deductions with a warning (no depreciation yet).
- VAT withheld by government on 2307s (2550-Q item 16) is a quarter input: Phase 1 does not extract 2307 ATCs, so all received 2307s are credited against income tax.
- Manufacturing uses the trading cost-of-sales formula (beginning + purchases − ending) with a warning; labour/overhead split comes later.
- Staleness is "any document in this or an earlier quarter of the company changed after the output was generated" (documents moved *out* of a quarter are not detected).

## File Structure

**Backend — create**
- `backend/app/services/accounting/compute/__init__.py` — package marker.
- `compute/money.py` — `d`, `c2`, `peso`, `total`, `ZERO`.
- `compute/inputs.py` — `DocLine`, `CompanyFacts`, `PeriodInputs`, `PeriodData`, `inputs_from_json`, `inputs_to_json`.
- `compute/cogs.py` — `claims_input_vat`, `cost_base`, `CogsResult`, `compute_cogs`, `cogs_form`.
- `compute/vat.py` — `VatResult`, `compute_2550q`.
- `compute/pt.py` — `compute_2551q`.
- `compute/itr.py` — `graduated_tax`, `QuarterFigures`, `PriorOverride`, `compute_1701q`, `compute_1702q`.
- `compute/deductions.py` — `ExpenseBreakdown`, `quarter_expenses`, `expenses_form`.
- `compute/ledgers.py` — `build_sls`, `build_slp`, `build_sawt`, `build_transactions`.
- `compute/specs.py` — form titles, item labels, ledger columns, payable item per form.
- `compute/due_dates.py` — `quarter_start`, `quarter_end`, `due_dates`.
- `compute/engine.py` — `QuarterResult`, `build_quarter`.
- `backend/app/services/accounting/diff.py` — `snapshot`, `diff_snapshots`, `count_changes`.
- `backend/app/services/accounting/render_xlsx.py` — `write_workbook`.
- `backend/app/forms/bir2550q_layout.py` + `backend/app/forms/templates/bir2550q_apr2024.pdf` — calibrated overlay map + official template.
- `backend/app/services/accounting/pdf_2550q.py` — `Header2550Q`, `render_2550q`.
- `backend/app/routers/accounting_periods.py` — period inputs, generate, outputs, downloads (sub-router).
- Tests: `backend/tests/aa_factories.py`, `test_aa_compute_basics.py`, `test_aa_vat.py`, `test_aa_itr.py`, `test_aa_engine.py`, `test_aa_diff.py`, `test_aa_xlsx.py`, `test_aa_pdf_2550q.py`, `test_aa_period_status.py`.

**Backend — modify (accounting module only)**
- `backend/app/models/accounting.py` — `AAPeriod`, `AAOutput`.
- `backend/app/services/accounting/rls.py` — add `aa_periods`, `aa_outputs`.
- `backend/app/services/accounting/tree.py` — `stale_periods`, quarter status in `build_tree`.
- `backend/app/schemas/accounting.py` — period/output models; 8% requires non-VAT; tree quarter status fields; upload `affected_periods`.
- `backend/app/routers/accounting.py` — include sub-router, tree status, `affected_periods` on finished uploads.
- Tests updated: `test_accounting_rls.py`, `test_accounting_tree.py`, `test_accounting_schemas.py`.

**Frontend — create / modify**
- Modify `frontend/src/types/accounting.ts`, `frontend/src/lib/accounting-api.ts`, `frontend/src/lib/accounting-format.ts`.
- Create `frontend/src/components/accounting/PeriodPanel.tsx`, `OutputViewer.tsx`, `AppendPrompt.tsx`.
- Modify `frontend/src/components/accounting/FolderTree.tsx` (status chips), `frontend/src/app/accounting/page.tsx` (panel + prompt).

---

### Task 1: Compute foundations — money, inputs, cost of sales

**Files:**
- Create: `backend/app/services/accounting/compute/__init__.py`, `compute/money.py`, `compute/inputs.py`, `compute/cogs.py`
- Test: `backend/tests/aa_factories.py`, `backend/tests/test_aa_compute_basics.py`

**Interfaces:**
- Produces:
  - `money.ZERO: Decimal`, `d(value) -> Decimal`, `c2(value) -> Decimal` (centavos, half-up), `peso(value) -> Decimal` (whole peso, half-up), `total(values) -> Decimal` (c2 of sum).
  - `inputs.DocLine(id, category, account, doc_type, client_role, doc_date, doc_number, counterparty_tin, counterparty_name, counterparty_address, gross, vatable, vat, exempt, zero_rated, withholding, input_vat_valid, open_review)` (frozen).
  - `inputs.CompanyFacts(registered_name, tin, branch_code, rdo_code, address, zip_code, taxpayer_type, vat_registered, income_tax_option, deduction_method, business_type, fiscal_year_end_month=12)` (frozen).
  - `inputs.PeriodInputs(ending_inventory=None, opening_inventory=None, opening_excess_input_vat=ZERO, vat_withheld=ZERO, advance_vat=ZERO, percentage_tax_withheld=ZERO, non_operating_income=ZERO, prior_year_excess_credits=ZERO, prior_taxable_income=None, prior_tax_paid=None, prior_cwt=None, cit_rate=25, mcit_applies=False)` (frozen).
  - `inputs.PeriodData(year, quarter, lines: tuple[DocLine, ...] = (), inputs: PeriodInputs = PeriodInputs())` (frozen).
  - `inputs.inputs_from_json(data: dict | None) -> PeriodInputs`, `inputs.inputs_to_json(inputs) -> dict` (decimals as strings, None kept).
  - `cogs.claims_input_vat(line, company_vat: bool) -> bool`, `cogs.cost_base(line, company_vat) -> Decimal`, `cogs.CogsResult(beginning_inventory, purchases, ending_inventory, cost_of_sales, ending_provided)`, `cogs.compute_cogs(lines, company, beginning: Decimal, ending: Decimal | None) -> CogsResult`, `cogs.cogs_form(result) -> dict[str, Decimal]`.
  - Test helpers `tests/aa_factories.py`: `line(**kw) -> DocLine`, `sale(**kw)`, `purchase(**kw)`, `expense(**kw)`, `company(**kw) -> CompanyFacts`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/aa_factories.py`:

```python
"""Builders for AutoAccounting computation tests."""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.inputs import CompanyFacts, DocLine

_MONEY = ("gross", "vatable", "vat", "exempt", "zero_rated", "withholding")
_counter = iter(range(1, 1_000_000))


def line(**kw) -> DocLine:
    values = dict(
        id=f"d{next(_counter)}", category="purchases", account="purchases", doc_type="invoice",
        client_role="buyer", doc_date=date(2026, 8, 1), doc_number="1", counterparty_tin="111222333",
        counterparty_name="Supplier", counterparty_address="", input_vat_valid=None, open_review=False,
    )
    for name in _MONEY:
        values[name] = Decimal("0.00")
    values.update(kw)
    for name in _MONEY:
        values[name] = Decimal(str(values[name]))
    return DocLine(**values)


def sale(**kw) -> DocLine:
    kw.setdefault("category", "sales")
    kw.setdefault("account", "sales")
    kw.setdefault("client_role", "seller")
    kw.setdefault("counterparty_name", "Customer")
    kw.setdefault("counterparty_tin", "555666777")
    return line(**kw)


def purchase(**kw) -> DocLine:
    kw.setdefault("category", "purchases")
    kw.setdefault("account", "purchases")
    return line(**kw)


def expense(**kw) -> DocLine:
    kw.setdefault("category", "expenses")
    kw.setdefault("account", "office_supplies")
    return line(**kw)


def company(**kw) -> CompanyFacts:
    values = dict(
        registered_name="Juan's Cloth Trading", tin="123456789", branch_code="00000", rdo_code="030",
        address="Quiapo, Manila", zip_code="1001", taxpayer_type="corporation", vat_registered=True,
        income_tax_option="graduated", deduction_method="itemized", business_type="trading",
        fiscal_year_end_month=12,
    )
    values.update(kw)
    return CompanyFacts(**values)
```

`backend/tests/test_aa_compute_basics.py`:

```python
from decimal import Decimal

from app.services.accounting.compute.cogs import claims_input_vat, cogs_form, compute_cogs, cost_base
from app.services.accounting.compute.inputs import PeriodInputs, inputs_from_json, inputs_to_json
from app.services.accounting.compute.money import c2, d, peso, total
from tests.aa_factories import company, purchase


def test_rounding_is_half_up():
    assert c2("2.345") == Decimal("2.35")
    assert c2("2.344") == Decimal("2.34")
    assert peso("1234.50") == Decimal("1235")
    assert peso("1234.49") == Decimal("1234")
    assert d(None) == Decimal("0") and d("") == Decimal("0")
    assert total(["1.005", "2"]) == Decimal("3.01")


def test_inputs_round_trip_through_json():
    original = PeriodInputs(ending_inventory=Decimal("5000.00"), vat_withheld=Decimal("120.50"), cit_rate=20,
                            mcit_applies=True, prior_taxable_income=Decimal("0.00"))
    data = inputs_to_json(original)
    assert data["ending_inventory"] == "5000.00" and data["opening_inventory"] is None
    assert inputs_from_json(data) == original


def test_inputs_from_json_ignores_junk():
    parsed = inputs_from_json({"ending_inventory": "", "cit_rate": 30, "vat_withheld": None})
    assert parsed == PeriodInputs()
    assert inputs_from_json(None) == PeriodInputs()


def test_cost_base_excludes_vat_only_when_claimed():
    claimed = purchase(gross="11200", vatable="10000", vat="1200", input_vat_valid=True)
    unclaimed = purchase(gross="1120", vatable="1000", vat="120", input_vat_valid=False)
    assert claims_input_vat(claimed, True) and not claims_input_vat(unclaimed, True)
    assert cost_base(claimed, True) == Decimal("10000.00")
    assert cost_base(unclaimed, True) == Decimal("1120.00")
    assert cost_base(claimed, False) == Decimal("11200.00")  # non-VAT company: VAT is part of cost


def test_trading_cost_of_sales():
    lines = [purchase(gross="11200", vat="1200", input_vat_valid=True), purchase(gross="500")]
    r = compute_cogs(lines, company(), Decimal("2000"), Decimal("3000"))
    assert (r.beginning_inventory, r.purchases, r.ending_inventory, r.cost_of_sales) == (
        Decimal("2000.00"), Decimal("10500.00"), Decimal("3000.00"), Decimal("9500.00"))
    assert r.ending_provided is True
    assert cogs_form(r)["goods_available"] == Decimal("12500.00")


def test_cogs_without_ending_inventory():
    r = compute_cogs([purchase(gross="500")], company(), Decimal("0"), None)
    assert r.ending_provided is False and r.ending_inventory == Decimal("0.00")
    assert r.cost_of_sales == Decimal("500.00")


def test_services_have_no_cost_of_sales():
    r = compute_cogs([purchase(gross="500")], company(business_type="services"), Decimal("100"), None)
    assert r.cost_of_sales == Decimal("0.00") and r.purchases == Decimal("0.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_compute_basics.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.accounting.compute'`.

- [ ] **Step 3: Implement**

`backend/app/services/accounting/compute/__init__.py`:

```python
"""AutoAccounting tax computation: documents + quarter inputs -> BIR form values (pure, no I/O)."""
```

`compute/money.py`:

```python
"""Decimal helpers for tax computation (pure)."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0.00")
_CENT = Decimal("0.01")
_PESO = Decimal("1")


def d(value) -> Decimal:
    """Coerce a number or numeric string to Decimal (None or '' -> 0)."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def c2(value) -> Decimal:
    """Round to centavos, half up (VAT and percentage tax returns)."""
    return d(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def peso(value) -> Decimal:
    """Round to whole pesos, half up (income tax returns: 'DO NOT enter Centavos')."""
    return d(value).quantize(_PESO, rounding=ROUND_HALF_UP)


def total(values: Iterable) -> Decimal:
    return c2(sum((d(v) for v in values), Decimal("0")))
```

`compute/inputs.py`:

```python
"""Plain inputs for the AutoAccounting computation engine (no ORM, no I/O)."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.money import ZERO, c2


@dataclass(frozen=True)
class DocLine:
    """One filed document, reduced to what the computations need."""

    id: str
    category: str          # sales | purchases | expenses | payroll | 2307 | unsorted
    account: str
    doc_type: str
    client_role: str       # seller | buyer
    doc_date: date | None
    doc_number: str
    counterparty_tin: str
    counterparty_name: str
    counterparty_address: str
    gross: Decimal = ZERO
    vatable: Decimal = ZERO
    vat: Decimal = ZERO
    exempt: Decimal = ZERO
    zero_rated: Decimal = ZERO
    withholding: Decimal = ZERO
    input_vat_valid: bool | None = None
    open_review: bool = False


@dataclass(frozen=True)
class CompanyFacts:
    registered_name: str
    tin: str
    branch_code: str
    rdo_code: str
    address: str
    zip_code: str
    taxpayer_type: str        # individual | corporation | partnership
    vat_registered: bool
    income_tax_option: str    # graduated | eight_percent
    deduction_method: str     # itemized | osd
    business_type: str        # trading | manufacturing | services
    fiscal_year_end_month: int = 12


@dataclass(frozen=True)
class PeriodInputs:
    """What documents can't tell us, entered per quarter."""

    ending_inventory: Decimal | None = None
    opening_inventory: Decimal | None = None          # first quarter on the platform only
    opening_excess_input_vat: Decimal = ZERO           # carried into the first quarter on the platform
    vat_withheld: Decimal = ZERO                       # 2550-Q item 16
    advance_vat: Decimal = ZERO                        # 2550-Q item 17
    percentage_tax_withheld: Decimal = ZERO            # 2551-Q item 15
    non_operating_income: Decimal = ZERO
    prior_year_excess_credits: Decimal = ZERO
    prior_taxable_income: Decimal | None = None        # earlier quarters filed outside the platform
    prior_tax_paid: Decimal | None = None
    prior_cwt: Decimal | None = None
    cit_rate: int = 25
    mcit_applies: bool = False


@dataclass(frozen=True)
class PeriodData:
    year: int
    quarter: int
    lines: tuple[DocLine, ...] = ()
    inputs: PeriodInputs = field(default_factory=PeriodInputs)


_DECIMALS = (
    "ending_inventory", "opening_inventory", "opening_excess_input_vat", "vat_withheld", "advance_vat",
    "percentage_tax_withheld", "non_operating_income", "prior_year_excess_credits",
    "prior_taxable_income", "prior_tax_paid", "prior_cwt",
)


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
    return PeriodInputs(**kwargs)


def inputs_to_json(inputs: PeriodInputs) -> dict:
    out: dict = {}
    for name in _DECIMALS:
        value = getattr(inputs, name)
        out[name] = None if value is None else str(value)
    out["cit_rate"] = inputs.cit_rate
    out["mcit_applies"] = inputs.mcit_applies
    return out
```

`compute/cogs.py`:

```python
"""Cost of goods sold (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.inputs import CompanyFacts, DocLine
from app.services.accounting.compute.money import ZERO, c2, total


def claims_input_vat(line: DocLine, company_vat: bool) -> bool:
    return company_vat and line.input_vat_valid is True and line.vat > 0


def cost_base(line: DocLine, company_vat: bool) -> Decimal:
    """What a purchase or expense costs the business: VAT-exclusive only when its input VAT is claimed."""
    if claims_input_vat(line, company_vat):
        return c2(line.gross - line.vat)
    return c2(line.gross)


@dataclass(frozen=True)
class CogsResult:
    beginning_inventory: Decimal
    purchases: Decimal
    ending_inventory: Decimal
    cost_of_sales: Decimal
    ending_provided: bool


def compute_cogs(lines, company: CompanyFacts, beginning: Decimal, ending: Decimal | None) -> CogsResult:
    """Beginning inventory + purchases − ending inventory (services carry no inventory)."""
    if company.business_type == "services":
        return CogsResult(ZERO, ZERO, ZERO, ZERO, True)
    purchases = total(cost_base(l, company.vat_registered) for l in lines if l.category == "purchases")
    end = c2(ending) if ending is not None else ZERO
    begin = c2(beginning)
    return CogsResult(begin, purchases, end, c2(begin + purchases - end), ending is not None)


def cogs_form(result: CogsResult) -> dict[str, Decimal]:
    return {
        "beginning_inventory": result.beginning_inventory,
        "purchases": result.purchases,
        "goods_available": c2(result.beginning_inventory + result.purchases),
        "ending_inventory": result.ending_inventory,
        "cost_of_sales": result.cost_of_sales,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_compute_basics.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute backend/tests/aa_factories.py backend/tests/test_aa_compute_basics.py
git commit -m "feat(accounting): compute foundations — money, period inputs, cost of sales

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: VAT — 2550-Q

**Files:**
- Create: `backend/app/services/accounting/compute/vat.py`
- Test: `backend/tests/test_aa_vat.py`

**Interfaces:**
- Consumes: `DocLine`, `PeriodInputs`, `claims_input_vat`, `c2`, `total`, `ZERO` (Task 1).
- Produces: `VAT_RATE = Decimal("0.12")`; `VatResult(items: dict[str, Decimal], excess_input_vat_out: Decimal)`; `compute_2550q(lines, inputs: PeriodInputs, carry_in: Decimal) -> VatResult`. Item keys exactly: `"15"`–`"26"`, `"31A"`, `"31B"`, `"32A"`, `"33A"`, `"34A"`, `"34B"`, `"35B"`–`"43B"`, `"44A"`, `"44B"`, `"45A"`, `"45B"`, `"46A"`, `"46B"`, `"47A"`, `"47B"`, `"48A"`, `"49A"`, `"50A"`, `"50B"`, `"51B"`–`"61B"`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_aa_vat.py`:

```python
from decimal import Decimal

from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.vat import compute_2550q
from tests.aa_factories import expense, purchase, sale

D = Decimal


def _quarter():
    return [
        sale(vatable="25000", vat="3000", gross="28000"),
        purchase(gross="11200", vatable="10000", vat="1200", input_vat_valid=True, account="raw_materials"),
        expense(gross="2240", vatable="2000", vat="240", input_vat_valid=True, account="transportation"),
        expense(gross="3360", vatable="3000", vat="360", input_vat_valid=True),
        expense(gross="1120", vatable="1000", vat="120", input_vat_valid=False, account="representation"),
    ]


def test_full_return_for_a_typical_quarter():
    r = compute_2550q(_quarter(), PeriodInputs(vat_withheld=D("100")), D("500"))
    i = r.items
    assert (i["31A"], i["31B"], i["34A"], i["34B"], i["37B"]) == (D("25000.00"), D("3000.00"), D("25000.00"), D("3000.00"), D("3000.00"))
    assert (i["38B"], i["43B"]) == (D("500.00"), D("500.00"))
    assert (i["44A"], i["44B"]) == (D("15000.00"), D("1800.00"))
    assert i["48A"] == D("1120.00")  # the receipt that fails input-VAT checks
    assert (i["50A"], i["50B"], i["51B"]) == (D("16120.00"), D("1800.00"), D("2300.00"))
    assert (i["60B"], i["61B"]) == (D("2300.00"), D("700.00"))
    assert (i["15"], i["16"], i["20"], i["21"], i["26"]) == (D("700.00"), D("100.00"), D("100.00"), D("600.00"), D("600.00"))
    assert r.excess_input_vat_out == D("0.00")


def test_excess_input_vat_carries_out():
    lines = [sale(vatable="1000", vat="120"), purchase(gross="5600", vat="600", input_vat_valid=True)]
    r = compute_2550q(lines, PeriodInputs(), D("0"))
    assert r.items["61B"] == D("-480.00") and r.items["26"] == D("-480.00")
    assert r.excess_input_vat_out == D("480.00")


def test_zero_rated_and_exempt_sales_and_ratable_input_tax():
    lines = [
        sale(vatable="60000", vat="7200"),
        sale(zero_rated="20000"),
        sale(exempt="20000"),
        purchase(gross="11200", vat="1200", input_vat_valid=True),
    ]
    i = compute_2550q(lines, PeriodInputs(), D("0")).items
    assert (i["32A"], i["33A"], i["34A"]) == (D("20000.00"), D("20000.00"), D("100000.00"))
    assert i["53B"] == D("240.00")  # 1200 × 20,000 / 100,000
    assert i["60B"] == D("960.00")


def test_importations_payroll_and_2307s():
    lines = [
        purchase(gross="56000", vat="6000", input_vat_valid=True, account="importation", doc_type="import"),
        purchase(gross="9000", input_vat_valid=False, account="importation"),
        expense(category="payroll", account="salaries", gross="50000"),
        sale(category="2307", account="2307_received", gross="10000", withholding="200"),
    ]
    i = compute_2550q(lines, PeriodInputs(), D("0")).items
    assert (i["46A"], i["46B"], i["49A"]) == (D("50000.00"), D("6000.00"), D("9000.00"))
    assert (i["44A"], i["48A"], i["31A"]) == (D("0.00"), D("0.00"), D("0.00"))


def test_all_items_present():
    keys = set(compute_2550q([], PeriodInputs(), D("0")).items)
    expected = {str(n) for n in range(15, 27)} | {"31A", "31B", "32A", "33A", "34A", "34B", "44A", "44B", "45A", "45B",
                                                   "46A", "46B", "47A", "47B", "48A", "49A", "50A", "50B"}
    expected |= {f"{n}B" for n in range(35, 44)} | {f"{n}B" for n in range(51, 62)}
    assert keys == expected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_vat.py -q`
Expected: FAIL with `ModuleNotFoundError: ... compute.vat`.

- [ ] **Step 3: Implement** — `compute/vat.py`:

```python
"""Quarterly VAT return, BIR Form 2550-Q (April 2024 ENCS) — pure."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.cogs import claims_input_vat
from app.services.accounting.compute.inputs import DocLine, PeriodInputs
from app.services.accounting.compute.money import ZERO, c2, total

VAT_RATE = Decimal("0.12")


@dataclass(frozen=True)
class VatResult:
    items: dict[str, Decimal]
    excess_input_vat_out: Decimal


def _is_import(line: DocLine) -> bool:
    return line.account == "importation" or line.doc_type == "import"


def compute_2550q(lines, inputs: PeriodInputs, carry_in: Decimal) -> VatResult:
    sales = [l for l in lines if l.category == "sales"]
    buys = [l for l in lines if l.category in ("purchases", "expenses") and l.client_role == "buyer"]
    claimed = [l for l in buys if claims_input_vat(l, True)]
    unclaimed = [l for l in buys if not claims_input_vat(l, True)]

    i: dict[str, Decimal] = {}
    # Part IV — sales and output tax
    i["31A"] = total(l.vatable for l in sales)
    i["31B"] = c2(i["31A"] * VAT_RATE)
    i["32A"] = total(l.zero_rated for l in sales)
    i["33A"] = total(l.exempt for l in sales)
    i["34A"] = total([i["31A"], i["32A"], i["33A"]])
    i["34B"] = i["31B"]
    i["35B"] = ZERO  # output VAT on uncollected receivables: not modelled yet
    i["36B"] = ZERO
    i["37B"] = c2(i["34B"] - i["35B"] + i["36B"])
    # Input tax brought forward
    i["38B"] = c2(carry_in)
    for key in ("39B", "40B", "41B", "42B"):
        i[key] = ZERO
    i["43B"] = total(i[k] for k in ("38B", "39B", "40B", "41B", "42B"))
    # Current transactions
    domestic = [l for l in claimed if not _is_import(l)]
    imported = [l for l in claimed if _is_import(l)]
    i["44A"] = total(l.gross - l.vat for l in domestic)
    i["44B"] = total(l.vat for l in domestic)
    i["45A"] = ZERO
    i["45B"] = ZERO
    i["46A"] = total(l.gross - l.vat for l in imported)
    i["46B"] = total(l.vat for l in imported)
    i["47A"] = ZERO
    i["47B"] = ZERO
    i["48A"] = total(l.gross for l in unclaimed if not _is_import(l))
    i["49A"] = total(l.gross for l in unclaimed if _is_import(l))
    i["50A"] = total(i[k] for k in ("44A", "45A", "46A", "47A", "48A", "49A"))
    i["50B"] = total(i[k] for k in ("44B", "45B", "46B", "47B"))
    i["51B"] = c2(i["43B"] + i["50B"])
    # Deductions from input tax
    i["52B"] = ZERO
    i["53B"] = c2(i["50B"] * i["33A"] / i["34A"]) if i["33A"] > 0 and i["34A"] > 0 else ZERO
    for key in ("54B", "55B", "56B"):
        i[key] = ZERO
    i["57B"] = total(i[k] for k in ("52B", "53B", "54B", "55B", "56B"))
    i["58B"] = ZERO
    i["59B"] = c2(i["57B"] + i["58B"])
    i["60B"] = c2(i["51B"] - i["59B"])
    i["61B"] = c2(i["37B"] - i["60B"])
    # Part II — total tax payable
    i["15"] = i["61B"]
    i["16"] = c2(inputs.vat_withheld)
    i["17"] = c2(inputs.advance_vat)
    i["18"] = ZERO
    i["19"] = ZERO
    i["20"] = total(i[k] for k in ("16", "17", "18", "19"))
    i["21"] = c2(i["15"] - i["20"])
    for key in ("22", "23", "24", "25"):
        i[key] = ZERO
    i["26"] = c2(i["21"] + i["25"])

    excess = c2(-i["61B"]) if i["61B"] < 0 else ZERO
    return VatResult(i, excess)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_vat.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/vat.py backend/tests/test_aa_vat.py
git commit -m "feat(accounting): 2550-Q quarterly VAT computation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Percentage tax and income tax — 2551-Q, 1701-Q, 1702-Q, deductions

**Files:**
- Create: `compute/pt.py`, `compute/itr.py`, `compute/deductions.py`
- Test: `backend/tests/test_aa_itr.py`

**Interfaces:**
- Consumes: Task 1 money/inputs/cogs.
- Produces:
  - `pt.PT_RATE = Decimal("0.03")`; `pt.compute_2551q(lines, inputs) -> dict[str, Decimal | str]` keys `S1_1_ATC` ("PT 010"), `S1_1_TAXABLE`, `S1_1_RATE`, `S1_1_DUE`, `S1_7`, `"14"`–`"24"`.
  - `itr.graduated_tax(income: Decimal) -> Decimal` (whole pesos, Table 2).
  - `itr.QuarterFigures(sales, cost_of_sales, deductions, non_operating_income, cwt)` (frozen, Decimals).
  - `itr.PriorOverride(taxable_income, tax_paid, cwt)` (frozen).
  - `itr.compute_1702q(quarters: list[QuarterFigures], company, inputs, prior: PriorOverride | None = None) -> dict[str, Decimal]` — `quarters` = Q1..current (current last); keys `S2_1`–`S2_13`, `S3_1`–`S3_6`, `S4_1`–`S4_7`, `"14"`–`"25"`.
  - `itr.compute_1701q(...)` same signature — graduated keys `"36"`–`"46"`, 8% keys `"47"`–`"54"`, credits `"55"`–`"62"`, `"63"`–`"68"`.
  - `deductions.ExpenseBreakdown(by_account: dict[str, Decimal], payroll, capital_goods, representation, representation_allowed, representation_disallowed_ytd, deductions)`; `deductions.quarter_expenses(lines, company, rep_ytd_before, allowed_ytd_before, sales_ytd) -> tuple[ExpenseBreakdown, Decimal, Decimal]` returning `(breakdown, rep_ytd_after, allowed_ytd_after)`; `deductions.expenses_form(breakdown) -> dict[str, Decimal]`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_aa_itr.py`:

```python
from decimal import Decimal

from app.services.accounting.compute.deductions import expenses_form, quarter_expenses
from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.itr import (
    PriorOverride, QuarterFigures, compute_1701q, compute_1702q, graduated_tax,
)
from app.services.accounting.compute.pt import compute_2551q
from tests.aa_factories import company, expense, line, sale

D = Decimal


def q(sales="0", cogs="0", deductions="0", nonop="0", cwt="0"):
    return QuarterFigures(D(sales), D(cogs), D(deductions), D(nonop), D(cwt))


def test_graduated_table_2023_onwards():
    assert graduated_tax(D("250000")) == D("0")
    assert graduated_tax(D("400000")) == D("22500")
    assert graduated_tax(D("500000")) == D("42500")
    assert graduated_tax(D("2000000")) == D("402500")
    assert graduated_tax(D("9000000")) == D("2552500")
    assert graduated_tax(D("-5")) == D("0")


def test_2551q_three_percent_of_gross_sales_less_withheld():
    lines = [sale(gross="100000"), sale(gross="50000"), expense(gross="999")]
    i = compute_2551q(lines, PeriodInputs(percentage_tax_withheld=D("300")))
    assert (i["S1_1_ATC"], i["S1_1_TAXABLE"], i["S1_1_DUE"]) == ("PT 010", D("150000.00"), D("4500.00"))
    assert (i["14"], i["15"], i["18"], i["19"], i["24"]) == (D("4500.00"), D("300.00"), D("300.00"), D("4200.00"), D("4200.00"))


def test_1702q_cumulative_with_prior_payments_and_cwt():
    corp = company()
    quarters = [q(sales="1000000", cogs="600000", deductions="100000", cwt="5000"),
                q(sales="800000", cogs="500000", deductions="80000", cwt="4000")]
    i = compute_1702q(quarters, corp, PeriodInputs())
    # Q1: taxable 300,000 → tax 75,000; paid 75,000 − 5,000 = 70,000
    assert (i["S2_1"], i["S2_2"], i["S2_3"], i["S2_5"], i["S2_6"], i["S2_7"]) == (D("800000"), D("500000"), D("300000"), D("300000"), D("80000"), D("220000"))
    assert (i["S2_8"], i["S2_9"], i["S2_10"], i["S2_11"]) == (D("300000"), D("520000"), D("25"), D("130000"))
    assert (i["S4_2"], i["S4_4"], i["S4_5"], i["S4_7"]) == (D("70000"), D("5000"), D("4000"), D("79000"))
    assert (i["14"], i["19"], i["20"], i["25"]) == (D("130000"), D("79000"), D("51000"), D("51000"))


def test_1702q_osd_and_mcit():
    corp = company(deduction_method="osd")
    quarters = [q(sales="1000000", cogs="990000")]
    i = compute_1702q(quarters, corp, PeriodInputs(mcit_applies=True))
    # gross income 10,000; OSD 4,000; taxable 6,000 → RCIT 1,500; MCIT 2% × 10,000 = 200
    assert (i["S2_6"], i["S2_11"], i["S3_6"], i["S2_13"]) == (D("4000"), D("1500"), D("200"), D("1500"))
    loss = compute_1702q([q(sales="1000000", cogs="999000", deductions="50000")], company(), PeriodInputs(mcit_applies=True))
    assert (loss["S2_11"], loss["S3_6"], loss["S2_13"]) == (D("0"), D("20"), D("20"))


def test_1702q_twenty_percent_rate():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(cit_rate=20))
    assert (i["S2_10"], i["S2_11"]) == (D("20"), D("20000"))


def test_1701q_graduated_itemized_and_osd():
    person = company(taxpayer_type="individual")
    i = compute_1701q([q(sales="900000", cogs="300000", deductions="100000", cwt="1000")], person, PeriodInputs())
    assert (i["36"], i["37"], i["38"], i["39"], i["41"], i["45"]) == (D("900000"), D("300000"), D("600000"), D("100000"), D("500000"), D("500000"))
    assert (i["46"], i["58"], i["62"], i["63"]) == (D("42500"), D("1000"), D("1000"), D("41500"))
    osd = compute_1701q([q(sales="900000", cogs="300000")], company(taxpayer_type="individual", deduction_method="osd"), PeriodInputs())
    assert (osd["37"], osd["40"], osd["41"]) == (D("0"), D("360000"), D("540000"))


def test_1701q_eight_percent_cumulative():
    person = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent")
    i = compute_1701q([q(sales="200000"), q(sales="300000", cwt="500")], person, PeriodInputs())
    assert (i["47"], i["49"], i["50"], i["51"], i["52"], i["53"], i["54"]) == (
        D("300000"), D("300000"), D("200000"), D("500000"), D("250000"), D("250000"), D("20000"))
    assert (i["56"], i["58"], i["63"]) == (D("0"), D("500"), D("19500"))


def test_prior_override_replaces_missing_quarters():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(),
                      PriorOverride(D("400000"), D("90000"), D("2000")))
    assert (i["S2_8"], i["S2_9"], i["S2_11"]) == (D("400000"), D("500000"), D("125000"))
    assert (i["S4_2"], i["S4_4"], i["20"]) == (D("90000"), D("2000"), D("33000"))


def test_prior_year_excess_credits_reduce_payable():
    i = compute_1702q([q(sales="100000")], company(), PeriodInputs(prior_year_excess_credits=D("5000")))
    assert (i["S4_1"], i["20"]) == (D("5000"), D("20000"))


def test_expenses_with_representation_cap_and_capital_goods():
    lines = [
        expense(gross="1120", vat="120", input_vat_valid=True, account="representation"),
        expense(gross="5000", account="rent"),
        expense(gross="80000", account="capital_goods"),
        line(category="payroll", account="salaries", gross="30000"),
    ]
    b, rep_ytd, allowed_ytd = quarter_expenses(lines, company(), D("0"), D("0"), D("100000"))
    # cap 0.5% × 100,000 = 500 of the 1,000 representation
    assert (b.representation, b.representation_allowed, b.representation_disallowed_ytd) == (D("1000.00"), D("500.00"), D("500.00"))
    assert (b.payroll, b.capital_goods, b.deductions) == (D("30000.00"), D("80000.00"), D("35500.00"))
    assert (rep_ytd, allowed_ytd) == (D("1000.00"), D("500.00"))
    form = expenses_form(b)
    assert form["rent"] == D("5000.00") and form["total_deductions"] == D("35500.00")
    # next quarter: sales YTD grows → more of the earlier representation becomes deductible
    b2, _, allowed2 = quarter_expenses([], company(), rep_ytd, allowed_ytd, D("300000"))
    assert (b2.representation_allowed, allowed2) == (D("500.00"), D("1000.00"))


def test_services_cap_is_one_percent():
    lines = [expense(gross="2000", account="representation")]
    b, _, _ = quarter_expenses(lines, company(business_type="services"), D("0"), D("0"), D("100000"))
    assert b.representation_allowed == D("1000.00")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_itr.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`compute/pt.py`:

```python
"""Quarterly percentage tax return, BIR Form 2551-Q (January 2018 ENCS) — pure."""

from decimal import Decimal

from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.money import ZERO, c2, total

PT_RATE = Decimal("0.03")  # ATC PT 010, persons exempt from VAT under Sec. 109(BB)


def compute_2551q(lines, inputs: PeriodInputs) -> dict[str, Decimal | str]:
    taxable = total(l.gross for l in lines if l.category == "sales")
    due = c2(taxable * PT_RATE)
    i: dict[str, Decimal | str] = {
        "S1_1_ATC": "PT 010",
        "S1_1_TAXABLE": taxable,
        "S1_1_RATE": Decimal("3"),
        "S1_1_DUE": due,
        "S1_7": due,
        "14": due,
        "15": c2(inputs.percentage_tax_withheld),
        "16": ZERO,
        "17": ZERO,
    }
    i["18"] = total([i["15"], i["16"], i["17"]])
    i["19"] = c2(i["14"] - i["18"])
    for key in ("20", "21", "22", "23"):
        i[key] = ZERO
    i["24"] = c2(i["19"] + i["23"])
    return i
```

`compute/deductions.py`:

```python
"""Itemized deductions for a quarter, with the representation cap applied year to date (pure)."""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.cogs import cost_base
from app.services.accounting.compute.inputs import CompanyFacts
from app.services.accounting.compute.money import ZERO, c2, total

_CAP_GOODS = Decimal("0.005")     # RR 10-2002: 0.5% of net sales
_CAP_SERVICES = Decimal("0.01")   # 1% of net revenue


@dataclass(frozen=True)
class ExpenseBreakdown:
    by_account: dict[str, Decimal]
    payroll: Decimal
    capital_goods: Decimal
    representation: Decimal
    representation_allowed: Decimal
    representation_disallowed_ytd: Decimal
    deductions: Decimal


def quarter_expenses(lines, company: CompanyFacts, rep_ytd_before: Decimal, allowed_ytd_before: Decimal,
                     sales_ytd: Decimal) -> tuple[ExpenseBreakdown, Decimal, Decimal]:
    by_account: dict[str, Decimal] = {}
    capital = ZERO
    for l in lines:
        if l.category != "expenses":
            continue
        amount = cost_base(l, company.vat_registered)
        if l.account == "capital_goods":
            capital = c2(capital + amount)
            continue
        by_account[l.account] = c2(by_account.get(l.account, ZERO) + amount)
    payroll = total(l.gross for l in lines if l.category == "payroll")
    representation = by_account.get("representation", ZERO)

    rep_ytd = c2(rep_ytd_before + representation)
    rate = _CAP_SERVICES if company.business_type == "services" else _CAP_GOODS
    allowed_ytd = min(rep_ytd, c2(sales_ytd * rate))
    allowed_q = c2(allowed_ytd - allowed_ytd_before)
    other = total(v for k, v in by_account.items() if k != "representation")
    breakdown = ExpenseBreakdown(
        by_account=dict(sorted(by_account.items())),
        payroll=payroll,
        capital_goods=capital,
        representation=representation,
        representation_allowed=allowed_q,
        representation_disallowed_ytd=c2(rep_ytd - allowed_ytd),
        deductions=c2(other + payroll + allowed_q),
    )
    return breakdown, rep_ytd, allowed_ytd


def expenses_form(b: ExpenseBreakdown) -> dict[str, Decimal]:
    form = {k: v for k, v in b.by_account.items() if k != "representation"}
    if b.payroll:
        form["payroll"] = b.payroll
    form["representation"] = b.representation
    form["representation_allowed"] = b.representation_allowed
    form["representation_disallowed_ytd"] = b.representation_disallowed_ytd
    form["capital_goods_not_expensed"] = b.capital_goods
    form["total_deductions"] = b.deductions
    return form
```

`compute/itr.py`:

```python
"""Quarterly income tax: 1701-Q (individuals) and 1702-Q (non-individuals), January 2018 ENCS — pure.

Both returns are cumulative within the fiscal year: each quarter reports this
quarter, adds the previous quarters, computes tax to date and subtracts what was
already paid or withheld. ``quarters`` is Q1..current with the current quarter last.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.inputs import CompanyFacts, PeriodInputs
from app.services.accounting.compute.money import ZERO, peso

OSD_RATE = Decimal("0.40")
MCIT_RATE = Decimal("0.02")
EIGHT_PERCENT = Decimal("0.08")
EIGHT_PERCENT_EXEMPTION = Decimal("250000")
_TABLE_2 = (  # (over, base tax, rate on the excess) — effective January 1, 2023
    (Decimal("8000000"), Decimal("2202500"), Decimal("0.35")),
    (Decimal("2000000"), Decimal("402500"), Decimal("0.30")),
    (Decimal("800000"), Decimal("102500"), Decimal("0.25")),
    (Decimal("400000"), Decimal("22500"), Decimal("0.20")),
    (Decimal("250000"), Decimal("0"), Decimal("0.15")),
)
_P0 = Decimal("0")


@dataclass(frozen=True)
class QuarterFigures:
    sales: Decimal
    cost_of_sales: Decimal
    deductions: Decimal
    non_operating_income: Decimal
    cwt: Decimal


@dataclass(frozen=True)
class PriorOverride:
    """Totals of earlier quarters of the year that were filed outside the platform."""

    taxable_income: Decimal
    tax_paid: Decimal
    cwt: Decimal


def graduated_tax(income: Decimal) -> Decimal:
    for over, base, rate in _TABLE_2:
        if income > over:
            return peso(base + (income - over) * rate)
    return _P0


def _credits(inputs: PeriodInputs, paid_before: Decimal, cwt_before: Decimal, cwt_now: Decimal) -> list[Decimal]:
    return [peso(inputs.prior_year_excess_credits), peso(paid_before), peso(cwt_before), peso(cwt_now)]


def compute_1702q(quarters: list[QuarterFigures], company: CompanyFacts, inputs: PeriodInputs,
                  prior: PriorOverride | None = None) -> dict[str, Decimal]:
    osd = company.deduction_method == "osd"
    rate = Decimal(inputs.cit_rate) / 100
    prev_taxable, paid, cwt_prev = _P0, _P0, _P0
    gross_by_quarter: list[Decimal] = []
    if prior is not None:
        quarters = quarters[-1:]
        prev_taxable, paid, cwt_prev = peso(prior.taxable_income), peso(prior.tax_paid), peso(prior.cwt)
    items: dict[str, Decimal] = {}
    for index, f in enumerate(quarters):
        s1, s2 = peso(f.sales), peso(f.cost_of_sales)
        s3 = s1 - s2
        s4 = peso(f.non_operating_income)
        s5 = s3 + s4
        s6 = peso(s5 * OSD_RATE) if osd else peso(f.deductions)
        s7 = s5 - s6
        s8 = prev_taxable
        s9 = s7 + s8
        s11 = peso(max(s9, _P0) * rate)
        gross_by_quarter.append(s5)
        mcit_base = sum(gross_by_quarter, _P0)
        s3_6 = peso(max(mcit_base, _P0) * MCIT_RATE) if inputs.mcit_applies else _P0
        s13 = max(s11, s3_6)
        c1, c2_, c4, c5 = _credits(inputs, paid, cwt_prev, f.cwt)
        s4_7 = c1 + c2_ + c4 + c5
        payable = s13 - s4_7
        if index < len(quarters) - 1:
            prev_taxable = s9
            paid = paid + max(payable, _P0)
            cwt_prev = cwt_prev + peso(f.cwt)
            continue
        items = {
            "S2_1": s1, "S2_2": s2, "S2_3": s3, "S2_4": s4, "S2_5": s5, "S2_6": s6, "S2_7": s7, "S2_8": s8,
            "S2_9": s9, "S2_10": Decimal(inputs.cit_rate), "S2_11": s11, "S2_12": s3_6, "S2_13": s13,
        }
        for n, gross in enumerate(gross_by_quarter[:3], start=1):
            items[f"S3_{n}"] = gross
        items.update({"S3_4": peso(mcit_base), "S3_5": Decimal("2"), "S3_6": s3_6})
        items.update({"S4_1": c1, "S4_2": c2_, "S4_3": _P0, "S4_4": c4, "S4_5": c5, "S4_6": _P0, "S4_7": s4_7})
        items.update({"14": s13, "15": _P0, "16": s13, "17": _P0, "18": s13, "19": s4_7, "20": payable,
                      "21": _P0, "22": _P0, "23": _P0, "24": _P0, "25": payable})
    return items


def compute_1701q(quarters: list[QuarterFigures], company: CompanyFacts, inputs: PeriodInputs,
                  prior: PriorOverride | None = None) -> dict[str, Decimal]:
    eight = company.income_tax_option == "eight_percent"
    osd = company.deduction_method == "osd"
    prev_cum, paid, cwt_prev = _P0, _P0, _P0
    if prior is not None:
        quarters = quarters[-1:]
        prev_cum, paid, cwt_prev = peso(prior.taxable_income), peso(prior.tax_paid), peso(prior.cwt)
    items: dict[str, Decimal] = {}
    for index, f in enumerate(quarters):
        if eight:
            i47, i48 = peso(f.sales), peso(f.non_operating_income)
            i49 = i47 + i48
            i50 = prev_cum
            i51 = i49 + i50
            i53 = max(i51 - EIGHT_PERCENT_EXEMPTION, _P0)
            due = peso(i53 * EIGHT_PERCENT)
            cumulative = i51
            schedule = {"47": i47, "48": i48, "49": i49, "50": i50, "51": i51, "52": EIGHT_PERCENT_EXEMPTION,
                        "53": i53, "54": due}
        else:
            i36 = peso(f.sales)
            i37 = _P0 if osd else peso(f.cost_of_sales)
            i38 = i36 - i37
            i39 = _P0 if osd else peso(f.deductions)
            i40 = peso(i36 * OSD_RATE) if osd else _P0
            i41 = i38 - (i40 if osd else i39)
            i42 = prev_cum
            i43 = peso(f.non_operating_income)
            i45 = i41 + i42 + i43
            due = graduated_tax(i45)
            cumulative = i45
            schedule = {"36": i36, "37": i37, "38": i38, "39": i39, "40": i40, "41": i41, "42": i42, "43": i43,
                        "44": _P0, "45": i45, "46": due}
        c55, c56, c57, c58 = _credits(inputs, paid, cwt_prev, f.cwt)
        i62 = c55 + c56 + c57 + c58
        payable = due - i62
        if index < len(quarters) - 1:
            prev_cum = cumulative
            paid = paid + max(payable, _P0)
            cwt_prev = cwt_prev + peso(f.cwt)
            continue
        items = dict(schedule)
        items.update({"55": c55, "56": c56, "57": c57, "58": c58, "59": _P0, "60": _P0, "61": _P0, "62": i62,
                      "63": payable, "64": _P0, "65": _P0, "66": _P0, "67": _P0, "68": payable})
    return items
```

Check `test_1702q_cumulative…`: Q1 s5=400,000, s6=100,000, s7=300,000, tax 75,000, credits cwt 5,000 → payable 70,000 → paid=70,000, cwt_prev=5,000; Q2 s3=300,000, s7=220,000, s9=520,000, s11=130,000, credits 70,000+5,000+4,000=79,000 → payable 51,000. ✓

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_itr.py -q`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/pt.py backend/app/services/accounting/compute/itr.py backend/app/services/accounting/compute/deductions.py backend/tests/test_aa_itr.py
git commit -m "feat(accounting): 2551-Q, 1701-Q, 1702-Q and itemized deductions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Ledgers, labels, due dates and the quarter engine

**Files:**
- Create: `compute/ledgers.py`, `compute/specs.py`, `compute/due_dates.py`, `compute/engine.py`
- Test: `backend/tests/test_aa_engine.py`

**Interfaces:**
- Consumes: Tasks 1–3; `app.services.accounting.matching.normalize_name`.
- Produces:
  - `ledgers.build_sls(lines) -> list[dict]` (keys `key, tin, name, address, exempt, zero_rated, taxable, gross_sales, output_tax`), `build_slp(lines, company_vat) -> list[dict]` (`key, tin, name, address, exempt, zero_rated, services, capital_goods, other_goods, gross_purchases, input_tax`), `build_sawt(lines)` (`key, doc_date, tin, name, income_payment, tax_withheld`), `build_transactions(lines, company_vat)` (`key, doc_date, doc_number, counterparty, tin, category, account, gross, vatable, vat, exempt, zero_rated, withholding, input_vat_claimed, needs_review`). Every row has a stable `key`.
  - `specs.FORM_TITLES`, `FORM_ORDER`, `PAYABLE_ITEM`, `WHOLE_PESO_FORMS`, `PDF_FORMS`, `FORM_ITEMS`, `FORM_NOTES`, `EXPENSE_LABELS`, `LEDGER_ORDER`, `LEDGER_TITLES`, `LEDGER_COLUMNS: dict[str, tuple[tuple[str, str, str], ...]]` (`(column, label, "money"|"text")`), `form_items(form, values) -> list[tuple[str, str]]`.
  - `due_dates.quarter_start(fiscal_year, quarter, fye) -> date`, `quarter_end(...) -> date`, `due_dates(forms, fiscal_year, quarter, fye) -> dict[str, date]` (weekends roll to Monday).
  - `engine.QuarterResult(forms: dict[str, dict], ledgers: dict[str, list[dict]], warnings: list[str], carry_out: dict, review_open: int)`; `engine.build_quarter(company, periods: list[PeriodData]) -> QuarterResult` — `periods` = every quarter on record for the company up to and including the target, oldest first, target last.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_aa_engine.py`:

```python
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import due_dates, quarter_end, quarter_start
from app.services.accounting.compute.engine import build_quarter
from app.services.accounting.compute.inputs import PeriodData, PeriodInputs
from app.services.accounting.compute.specs import form_items
from tests.aa_factories import company, expense, line, purchase, sale

D = Decimal


def P(year, quarter, *lines, **inputs):
    return PeriodData(year, quarter, tuple(lines), PeriodInputs(**inputs))


def test_vat_corporation_quarter_has_all_forms_and_ledgers():
    r = build_quarter(company(), [P(2026, 1, sale(vatable="100000", vat="12000", gross="112000"),
                                    purchase(gross="56000", vat="6000", input_vat_valid=True),
                                    opening_inventory=D("0"), ending_inventory=D("10000"))])
    assert set(r.forms) == {"2550Q", "1702Q", "COGS", "Expenses"}
    assert set(r.ledgers) == {"Transactions", "SLS", "SLP"}
    assert r.forms["COGS"]["cost_of_sales"] == D("40000.00")
    assert (r.forms["1702Q"]["S2_1"], r.forms["1702Q"]["S2_2"]) == (D("100000"), D("40000"))
    assert r.forms["2550Q"]["26"] == D("6000.00")
    assert r.warnings == [] and r.review_open == 0


def test_vat_excess_chains_into_next_quarter():
    periods = [P(2026, 1, sale(vatable="1000", vat="120"), purchase(gross="5600", vat="600", input_vat_valid=True),
                 opening_inventory=D("0"), ending_inventory=D("0")),
               P(2026, 2, sale(vatable="10000", vat="1200"), ending_inventory=D("0"))]
    r = build_quarter(company(), periods)
    assert r.forms["2550Q"]["38B"] == D("480.00") and r.forms["2550Q"]["61B"] == D("720.00")
    assert r.carry_out["excess_input_vat"] == D("0.00")


def test_inventory_chains_between_quarters():
    periods = [P(2026, 1, sale(vatable="1"), opening_inventory=D("0"), ending_inventory=D("3000")),
               P(2026, 2, purchase(gross="5000"), ending_inventory=D("1000"))]
    cogs = build_quarter(company(), periods).forms["COGS"]
    assert (cogs["beginning_inventory"], cogs["purchases"], cogs["cost_of_sales"]) == (D("3000.00"), D("5000.00"), D("7000.00"))


def test_missing_ending_inventory_warns():
    r = build_quarter(company(), [P(2026, 1, purchase(gross="500"), opening_inventory=D("0"))])
    assert any(w.startswith("Ending inventory was not provided") for w in r.warnings)


def test_missing_earlier_quarters_warn():
    r = build_quarter(company(), [P(2026, 3, sale(vatable="1000"), opening_inventory=D("0"), ending_inventory=D("0"))])
    assert any(w.startswith("No documents for Q1, Q2 of 2026") for w in r.warnings)


def test_prior_override_used_for_mid_year_start():
    r = build_quarter(company(), [P(2026, 3, sale(vatable="100000"), opening_inventory=D("0"), ending_inventory=D("0"),
                                    prior_taxable_income=D("200000"), prior_tax_paid=D("50000"))])
    assert r.forms["1702Q"]["S2_8"] == D("200000") and r.forms["1702Q"]["S4_2"] == D("50000")
    assert not any(w.startswith("No documents for") for w in r.warnings)


def test_eight_percent_individual_files_only_1701q():
    person = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent",
                     business_type="services")
    r = build_quarter(person, [P(2026, 1, sale(gross="300000"))])
    assert set(r.forms) == {"1701Q", "Expenses"} and set(r.ledgers) == {"Transactions"}
    assert r.forms["1701Q"]["54"] == D("4000")


def test_non_vat_corporation_files_2551q():
    r = build_quarter(company(vat_registered=False, business_type="services"), [P(2026, 1, sale(gross="100000"))])
    assert {"2551Q", "1702Q"} <= set(r.forms) and "2550Q" not in r.forms


def test_q4_has_no_quarterly_income_tax_return():
    r = build_quarter(company(business_type="services"), [P(2026, 4, sale(vatable="1000"))])
    assert "1702Q" not in r.forms
    assert any(w.startswith("Q4 has no quarterly income tax return") for w in r.warnings)


def test_draft_and_unsorted_warnings():
    lines = [sale(vatable="1000", open_review=True), line(category="unsorted")]
    r = build_quarter(company(business_type="services"), [P(2026, 1, *lines)])
    assert r.review_open == 1 and r.warnings[0].startswith("1 document(s) in this quarter still need review")
    assert any(w.startswith("1 unsorted document(s) were left out") for w in r.warnings)


def test_2307s_feed_sawt_and_income_tax_credit():
    cert = sale(category="2307", account="2307_received", gross="50000", withholding="1000",
                counterparty_name="Payor Inc", counterparty_tin="999888777")
    r = build_quarter(company(business_type="services"), [P(2026, 1, sale(vatable="50000"), cert)])
    assert r.ledgers["SAWT"] == [{"key": cert.id, "doc_date": "2026-08-01", "tin": "999888777", "name": "Payor Inc",
                                  "income_payment": D("50000.00"), "tax_withheld": D("1000.00")}]
    assert r.forms["1702Q"]["S4_5"] == D("1000")
    assert any("VAT withheld" in w for w in r.warnings)


def test_sls_and_slp_group_by_counterparty():
    lines = [sale(vatable="1000", counterparty_tin="555666777"), sale(vatable="2000", counterparty_tin="555666777"),
             purchase(gross="11200", vat="1200", input_vat_valid=True, counterparty_tin="111"),
             expense(gross="5600", vat="600", input_vat_valid=True, account="rent", counterparty_tin="222"),
             expense(gross="300", input_vat_valid=False, counterparty_tin="333", counterparty_name="Sari-sari")]
    r = build_quarter(company(business_type="services"), [P(2026, 1, *lines)])
    [sls] = r.ledgers["SLS"]
    assert (sls["taxable"], sls["output_tax"], sls["gross_sales"]) == (D("3000.00"), D("360.00"), D("3000.00"))
    slp = {row["key"]: row for row in r.ledgers["SLP"]}
    assert (slp["111"]["other_goods"], slp["111"]["input_tax"]) == (D("10000.00"), D("1200.00"))
    assert slp["222"]["services"] == D("5000.00")
    assert (slp["333"]["exempt"], slp["333"]["input_tax"]) == (D("300.00"), D("0.00"))


def test_quarter_bounds_and_due_dates_roll_off_weekends():
    assert (quarter_start(2026, 3, 12), quarter_end(2026, 3, 12)) == (date(2026, 7, 1), date(2026, 9, 30))
    assert (quarter_start(2027, 1, 6), quarter_end(2027, 1, 6)) == (date(2026, 7, 1), date(2026, 9, 30))
    due = due_dates(["2550Q", "1702Q", "1701Q", "2551Q"], 2026, 3, 12)
    assert due["2550Q"] == date(2026, 10, 26)   # Oct 25 is a Sunday
    assert due["2551Q"] == date(2026, 10, 26)
    assert due["1702Q"] == date(2026, 11, 30)   # 60 days → Sun Nov 29
    assert due["1701Q"] == date(2026, 11, 16)   # Nov 15 is a Sunday


def test_form_items_follow_spec_order_and_skip_absent_keys():
    items = form_items("2550Q", {"26": D("1"), "31A": D("2")})
    assert [k for k, _ in items] == ["31A", "26"]
    exp = form_items("Expenses", {"rent": D("1"), "total_deductions": D("1")})
    assert exp == [("rent", "Rent"), ("total_deductions", "Total deductions this quarter")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_engine.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`compute/ledgers.py`:

```python
"""SLS / SLP / SAWT and transaction ledgers for the workbook (pure)."""

from app.services.accounting.compute.cogs import claims_input_vat
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.compute.vat import VAT_RATE
from app.services.accounting.matching import normalize_name

GOODS_ACCOUNTS = frozenset({"purchases", "raw_materials", "importation", "office_supplies"})


def _party_key(line) -> str:
    return line.counterparty_tin or f"NAME:{normalize_name(line.counterparty_name)}"


def _new_row(key: str, line, money_columns) -> dict:
    row = {"key": key, "tin": line.counterparty_tin, "name": line.counterparty_name,
           "address": line.counterparty_address}
    row.update({column: ZERO for column in money_columns})
    return row


def _sorted(rows: dict[str, dict]) -> list[dict]:
    return sorted(rows.values(), key=lambda r: (r["name"].lower(), r["key"]))


def build_sls(lines) -> list[dict]:
    rows: dict[str, dict] = {}
    for l in lines:
        if l.category != "sales":
            continue
        key = _party_key(l)
        row = rows.setdefault(key, _new_row(key, l, ("exempt", "zero_rated", "taxable")))
        row["exempt"] = c2(row["exempt"] + l.exempt)
        row["zero_rated"] = c2(row["zero_rated"] + l.zero_rated)
        row["taxable"] = c2(row["taxable"] + l.vatable)
    for row in rows.values():
        row["gross_sales"] = total([row["exempt"], row["zero_rated"], row["taxable"]])
        row["output_tax"] = c2(row["taxable"] * VAT_RATE)
    return _sorted(rows)


def build_slp(lines, company_vat: bool) -> list[dict]:
    columns = ("exempt", "zero_rated", "services", "capital_goods", "other_goods", "input_tax")
    rows: dict[str, dict] = {}
    for l in lines:
        if l.category not in ("purchases", "expenses") or l.client_role != "buyer":
            continue
        key = _party_key(l)
        row = rows.setdefault(key, _new_row(key, l, columns))
        if claims_input_vat(l, company_vat):
            if l.account == "capital_goods":
                column = "capital_goods"
            elif l.account in GOODS_ACCOUNTS:
                column = "other_goods"
            else:
                column = "services"
            row[column] = c2(row[column] + l.gross - l.vat)
            row["input_tax"] = c2(row["input_tax"] + l.vat)
        else:
            row["exempt"] = c2(row["exempt"] + l.gross)
    for row in rows.values():
        row["gross_purchases"] = total(row[c] for c in columns if c != "input_tax")
    return _sorted(rows)


def build_sawt(lines) -> list[dict]:
    rows = [
        {"key": l.id, "doc_date": l.doc_date.isoformat() if l.doc_date else "", "tin": l.counterparty_tin,
         "name": l.counterparty_name, "income_payment": c2(l.gross), "tax_withheld": c2(l.withholding)}
        for l in lines if l.category == "2307" and l.client_role == "seller"
    ]
    return sorted(rows, key=lambda r: (r["doc_date"], r["name"], r["key"]))


def build_transactions(lines, company_vat: bool) -> list[dict]:
    rows = [
        {
            "key": l.id, "doc_date": l.doc_date.isoformat() if l.doc_date else "", "doc_number": l.doc_number,
            "counterparty": l.counterparty_name, "tin": l.counterparty_tin, "category": l.category,
            "account": l.account, "gross": c2(l.gross), "vatable": c2(l.vatable), "vat": c2(l.vat),
            "exempt": c2(l.exempt), "zero_rated": c2(l.zero_rated), "withholding": c2(l.withholding),
            "input_vat_claimed": "yes" if claims_input_vat(l, company_vat) else "no",
            "needs_review": "yes" if l.open_review else "no",
        }
        for l in lines
    ]
    return sorted(rows, key=lambda r: (r["doc_date"], r["doc_number"], r["key"]))
```

`compute/specs.py`:

```python
"""Titles, item labels and ledger columns for the workbook, the output viewer and the PDF (pure data)."""

FORM_TITLES = {
    "2550Q": "BIR Form 2550-Q — Quarterly Value-Added Tax Return",
    "2551Q": "BIR Form 2551-Q — Quarterly Percentage Tax Return",
    "1701Q": "BIR Form 1701-Q — Quarterly Income Tax Return (Individuals)",
    "1702Q": "BIR Form 1702-Q — Quarterly Income Tax Return (Non-Individuals)",
    "COGS": "Cost of goods sold",
    "Expenses": "Deductions",
}
FORM_ORDER = ("2550Q", "2551Q", "1701Q", "1702Q", "COGS", "Expenses")
PAYABLE_ITEM = {"2550Q": "26", "2551Q": "24", "1701Q": "68", "1702Q": "25"}
WHOLE_PESO_FORMS = frozenset({"1701Q", "1702Q"})
PDF_FORMS = frozenset({"2550Q"})

FORM_ITEMS: dict[str, tuple[tuple[str, str], ...]] = {
    "2550Q": (
        ("31A", "31A VATable sales"), ("31B", "31B Output tax on VATable sales"),
        ("32A", "32A Zero-rated sales"), ("33A", "33A Exempt sales"),
        ("34A", "34A Total sales"), ("34B", "34B Total output tax due"),
        ("35B", "35B Less: output VAT on uncollected receivables"),
        ("36B", "36B Add: output VAT on recovered uncollected receivables"),
        ("37B", "37B Total adjusted output tax due"),
        ("38B", "38B Input tax carried over from previous quarter"),
        ("39B", "39B Input tax deferred on capital goods over ₱1M"), ("40B", "40B Transitional input tax"),
        ("41B", "41B Presumptive input tax"), ("42B", "42B Others"), ("43B", "43B Total (38B to 42B)"),
        ("44A", "44A Domestic purchases"), ("44B", "44B Input tax on domestic purchases"),
        ("45A", "45A Services rendered by non-residents"), ("45B", "45B Input tax on services by non-residents"),
        ("46A", "46A Importations"), ("46B", "46B Input tax on importations"),
        ("47A", "47A Others"), ("47B", "47B Input tax on others"),
        ("48A", "48A Domestic purchases with no input tax"), ("49A", "49A VAT-exempt importations"),
        ("50A", "50A Total current purchases"), ("50B", "50B Total current input tax"),
        ("51B", "51B Total available input tax"),
        ("52B", "52B Input tax on capital goods over ₱1M deferred"),
        ("53B", "53B Input tax attributable to VAT-exempt sales"), ("54B", "54B VAT refund/TCC claimed"),
        ("55B", "55B Input VAT on unpaid payables"), ("56B", "56B Others"),
        ("57B", "57B Total deductions from input tax"), ("58B", "58B Add: input VAT on settled unpaid payables"),
        ("59B", "59B Adjusted deductions from input tax"), ("60B", "60B Total allowable input tax"),
        ("61B", "61B Net VAT payable/(excess input tax)"),
        ("15", "15 Net VAT payable/(excess input tax)"), ("16", "16 Creditable VAT withheld"),
        ("17", "17 Advance VAT payments"), ("18", "18 VAT paid in return previously filed"),
        ("19", "19 Other credits/payment"), ("20", "20 Total tax credits/payment"),
        ("21", "21 Tax still payable/(excess credits)"), ("22", "22 Surcharge"), ("23", "23 Interest"),
        ("24", "24 Compromise"), ("25", "25 Total penalties"), ("26", "26 TOTAL AMOUNT PAYABLE/(excess credits)"),
    ),
    "2551Q": (
        ("S1_1_ATC", "Schedule 1 · ATC"), ("S1_1_TAXABLE", "Schedule 1 · taxable amount"),
        ("S1_1_RATE", "Schedule 1 · tax rate (%)"), ("S1_1_DUE", "Schedule 1 · tax due"),
        ("S1_7", "Schedule 1 · 7 Total tax due"), ("14", "14 Total tax due"),
        ("15", "15 Creditable percentage tax withheld (2307)"), ("16", "16 Tax paid in return previously filed"),
        ("17", "17 Other tax credit/payment"), ("18", "18 Total tax credits/payments"),
        ("19", "19 Tax still payable/(overpayment)"), ("20", "20 Surcharge"), ("21", "21 Interest"),
        ("22", "22 Compromise"), ("23", "23 Total penalties"), ("24", "24 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "1702Q": (
        ("S2_1", "Sched 2 · 1 Sales/receipts/revenues/fees"), ("S2_2", "Sched 2 · 2 Less: cost of sales/services"),
        ("S2_3", "Sched 2 · 3 Gross income from operation"),
        ("S2_4", "Sched 2 · 4 Add: non-operating and other taxable income"),
        ("S2_5", "Sched 2 · 5 Total gross income"), ("S2_6", "Sched 2 · 6 Less: deductions"),
        ("S2_7", "Sched 2 · 7 Taxable income this quarter"),
        ("S2_8", "Sched 2 · 8 Add: taxable income previous quarter/s"),
        ("S2_9", "Sched 2 · 9 Total taxable income to date"), ("S2_10", "Sched 2 · 10 Applicable income tax rate (%)"),
        ("S2_11", "Sched 2 · 11 Income tax due other than MCIT"),
        ("S2_12", "Sched 2 · 12 Minimum corporate income tax (MCIT)"), ("S2_13", "Sched 2 · 13 Total income tax due"),
        ("S3_1", "Sched 3 · 1 Gross income — 1st quarter"), ("S3_2", "Sched 3 · 2 Gross income — 2nd quarter"),
        ("S3_3", "Sched 3 · 3 Gross income — 3rd quarter"), ("S3_4", "Sched 3 · 4 Total gross income"),
        ("S3_5", "Sched 3 · 5 MCIT rate (%)"), ("S3_6", "Sched 3 · 6 Minimum corporate income tax"),
        ("S4_1", "Sched 4 · 1 Prior year's excess credits"),
        ("S4_2", "Sched 4 · 2 Tax payments for previous quarters"),
        ("S4_3", "Sched 4 · 3 MCIT payments for previous quarters"),
        ("S4_4", "Sched 4 · 4 Creditable tax withheld — previous quarters"),
        ("S4_5", "Sched 4 · 5 Creditable tax withheld per 2307 — this quarter"),
        ("S4_6", "Sched 4 · 6 Tax paid in return previously filed"), ("S4_7", "Sched 4 · 7 Total tax credits/payments"),
        ("14", "14 Income tax due — regular rate"), ("15", "15 Less: unexpired excess MCIT"),
        ("16", "16 Balance/income tax still due"), ("17", "17 Add: income tax due — special rate"),
        ("18", "18 Aggregate income tax due"), ("19", "19 Less: total tax credits/payments"),
        ("20", "20 Net tax payable/(overpayment)"), ("21", "21 Surcharge"), ("22", "22 Interest"),
        ("23", "23 Compromise"), ("24", "24 Total penalties"), ("25", "25 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "1701Q": (
        ("36", "36 Sales/revenues/receipts/fees"), ("37", "37 Less: cost of sales/services"),
        ("38", "38 Gross income from operation"), ("39", "39 Total allowable itemized deductions"),
        ("40", "40 Optional standard deduction (40% of item 36)"), ("41", "41 Net income this quarter"),
        ("42", "42 Taxable income previous quarter/s"), ("43", "43 Non-operating income"),
        ("44", "44 Share in income from a general professional partnership"),
        ("45", "45 Total taxable income to date"), ("46", "46 TAX DUE (graduated rates)"),
        ("47", "47 Sales/revenues/receipts/fees"), ("48", "48 Add: non-operating income"),
        ("49", "49 Total income for the quarter"), ("50", "50 Add: total taxable income previous quarter"),
        ("51", "51 Cumulative taxable income as of this quarter"),
        ("52", "52 Less: allowable reduction (₱250,000)"), ("53", "53 Taxable income to date"),
        ("54", "54 TAX DUE (8%)"), ("55", "55 Prior year's excess credits"),
        ("56", "56 Tax payments for previous quarters"), ("57", "57 Creditable tax withheld — previous quarters"),
        ("58", "58 Creditable tax withheld per 2307 — this quarter"),
        ("59", "59 Tax paid in return previously filed"), ("60", "60 Foreign tax credits"),
        ("61", "61 Other tax credits/payments"), ("62", "62 Total tax credits/payments"),
        ("63", "63 Tax payable/(overpayment)"), ("64", "64 Surcharge"), ("65", "65 Interest"),
        ("66", "66 Compromise"), ("67", "67 Total penalties"), ("68", "68 TOTAL AMOUNT PAYABLE/(overpayment)"),
    ),
    "COGS": (
        ("beginning_inventory", "Beginning inventory"), ("purchases", "Add: purchases (incl. importation costs)"),
        ("goods_available", "Cost of goods available for sale"), ("ending_inventory", "Less: ending inventory"),
        ("cost_of_sales", "Cost of goods sold"),
    ),
}

FORM_NOTES: dict[str, dict[str, str]] = {
    "2550Q": {
        "31B": "12% × 31A", "34A": "31A + 32A + 33A", "37B": "34B − 35B + 36B", "43B": "Sum of 38B to 42B",
        "50A": "Sum of 44A to 49A", "50B": "Sum of 44B to 47B", "51B": "43B + 50B", "53B": "50B × 33A ÷ 34A",
        "57B": "Sum of 52B to 56B", "59B": "57B + 58B", "60B": "51B − 59B", "61B": "37B − 60B",
        "15": "Item 61B", "20": "Sum of 16 to 19", "21": "15 − 20", "26": "21 + 25",
    },
    "2551Q": {"S1_1_DUE": "3% × taxable amount", "18": "Sum of 15 to 17", "19": "14 − 18", "24": "19 + 23"},
    "1702Q": {
        "S2_3": "1 − 2", "S2_5": "3 + 4", "S2_7": "5 − 6", "S2_9": "7 + 8", "S2_11": "9 × 10",
        "S3_6": "2% × total gross income", "S2_13": "Higher of 11 and 12", "S4_7": "Sum of 1 to 6",
        "20": "18 − 19", "25": "20 + 24",
    },
    "1701Q": {
        "38": "36 − 37", "41": "38 − 39 (or 38 − 40 with OSD)", "45": "Sum of 41 to 44", "46": "Graduated table on 45",
        "49": "47 + 48", "51": "49 + 50", "53": "51 − 52", "54": "8% × 53", "62": "Sum of 55 to 61",
        "63": "46 or 54, less 62", "68": "63 + 67",
    },
    "COGS": {"goods_available": "Beginning + purchases", "cost_of_sales": "Available − ending inventory"},
}

EXPENSE_LABELS = {
    "purchases": "Purchases", "raw_materials": "Raw materials", "importation": "Importation",
    "capital_goods": "Capital goods", "salaries": "Salaries and wages", "rent": "Rent", "utilities": "Utilities",
    "professional_fees": "Professional fees", "office_supplies": "Office supplies",
    "transportation": "Transportation", "repairs": "Repairs and maintenance", "taxes_licenses": "Taxes and licenses",
    "other": "Other expenses", "payroll": "Salaries and wages (payroll)",
    "representation": "Representation — total this quarter",
    "representation_allowed": "Representation — deductible this quarter",
    "representation_disallowed_ytd": "Representation above the cap — year to date (not deductible)",
    "capital_goods_not_expensed": "Capital goods (not expensed — depreciation later)",
    "total_deductions": "Total deductions this quarter",
}

LEDGER_ORDER = ("SLS", "SLP", "SAWT", "Transactions")
LEDGER_TITLES = {
    "SLS": "Summary List of Sales", "SLP": "Summary List of Purchases",
    "SAWT": "SAWT — certificates (2307) received", "Transactions": "Transactions",
}
LEDGER_COLUMNS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "SLS": (("tin", "TIN", "text"), ("name", "Registered name", "text"), ("address", "Address", "text"),
            ("exempt", "Exempt sales", "money"), ("zero_rated", "Zero-rated sales", "money"),
            ("taxable", "Taxable sales", "money"), ("gross_sales", "Gross sales", "money"),
            ("output_tax", "Output tax", "money")),
    "SLP": (("tin", "TIN", "text"), ("name", "Registered name", "text"), ("address", "Address", "text"),
            ("exempt", "Exempt / no input tax", "money"), ("zero_rated", "Zero-rated", "money"),
            ("services", "Services", "money"), ("capital_goods", "Capital goods", "money"),
            ("other_goods", "Goods other than capital goods", "money"),
            ("gross_purchases", "Gross purchases", "money"), ("input_tax", "Input tax", "money")),
    "SAWT": (("doc_date", "Date", "text"), ("tin", "Payor TIN", "text"), ("name", "Payor name", "text"),
             ("income_payment", "Income payment", "money"), ("tax_withheld", "Tax withheld", "money")),
    "Transactions": (("doc_date", "Date", "text"), ("doc_number", "Document no.", "text"),
                     ("counterparty", "Counterparty", "text"), ("tin", "TIN", "text"),
                     ("category", "Folder", "text"), ("account", "Account", "text"), ("gross", "Total", "money"),
                     ("vatable", "VATable", "money"), ("vat", "VAT", "money"), ("exempt", "Exempt", "money"),
                     ("zero_rated", "Zero-rated", "money"), ("withholding", "Tax withheld", "money"),
                     ("input_vat_claimed", "Input VAT claimed", "text"), ("needs_review", "Needs review", "text")),
}


def form_items(form: str, values: dict) -> list[tuple[str, str]]:
    """(key, label) pairs in the form's own order, for keys present in ``values``."""
    if form in FORM_ITEMS:
        return [(key, label) for key, label in FORM_ITEMS[form] if key in values]
    return [(key, EXPENSE_LABELS.get(key, key)) for key in values]
```

`compute/due_dates.py`:

```python
"""Quarter bounds and BIR filing due dates (pure). Holidays are not modelled; weekends roll to Monday."""

import calendar
from datetime import date, timedelta


def _end_month(quarter: int, fye: int) -> int:
    return (fye + quarter * 3 - 1) % 12 + 1


def quarter_end(fiscal_year: int, quarter: int, fye: int = 12) -> date:
    month = _end_month(quarter, fye)
    year = fiscal_year if month <= fye else fiscal_year - 1
    return date(year, month, calendar.monthrange(year, month)[1])


def quarter_start(fiscal_year: int, quarter: int, fye: int = 12) -> date:
    end = quarter_end(fiscal_year, quarter, fye)
    month, year = end.month - 2, end.year
    if month < 1:
        month, year = month + 12, year - 1
    return date(year, month, 1)


def _next_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


_INDIVIDUAL_DUE = {1: (5, 15), 2: (8, 15), 3: (11, 15)}


def due_dates(forms, fiscal_year: int, quarter: int, fye: int = 12) -> dict[str, date]:
    end = quarter_end(fiscal_year, quarter, fye)
    out: dict[str, date] = {}
    for form in forms:
        if form in ("2550Q", "2551Q"):
            out[form] = _next_business_day(end + timedelta(days=25))
        elif form == "1702Q":
            out[form] = _next_business_day(end + timedelta(days=60))
        elif form == "1701Q" and quarter in _INDIVIDUAL_DUE:
            month, day = _INDIVIDUAL_DUE[quarter]
            out[form] = _next_business_day(date(end.year, month, day))
    return out
```

`compute/engine.py`:

```python
"""Assemble one quarter's returns, ledgers and warnings from documents (pure).

Everything is recomputed from documents: inventory and excess input VAT chain from
the company's first quarter on record; income tax is year-to-date from Q1.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.services.accounting.compute.cogs import CogsResult, cogs_form, compute_cogs
from app.services.accounting.compute.deductions import ExpenseBreakdown, expenses_form, quarter_expenses
from app.services.accounting.compute.inputs import CompanyFacts, PeriodData
from app.services.accounting.compute.itr import PriorOverride, QuarterFigures, compute_1701q, compute_1702q
from app.services.accounting.compute.ledgers import build_sawt, build_slp, build_sls, build_transactions
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.compute.pt import compute_2551q
from app.services.accounting.compute.vat import VatResult, compute_2550q


@dataclass
class QuarterResult:
    forms: dict[str, dict]
    ledgers: dict[str, list[dict]]
    warnings: list[str]
    carry_out: dict[str, Decimal | None]
    review_open: int


def _peso_text(value: Decimal) -> str:
    return f"₱{value:,.2f}"


def sales_base(lines, company: CompanyFacts) -> Decimal:
    sales = [l for l in lines if l.category == "sales"]
    if company.vat_registered:
        return total(l.vatable + l.zero_rated + l.exempt for l in sales)
    return total(l.gross for l in sales)


def _cwt(lines) -> Decimal:
    return total(l.withholding for l in lines if l.category == "2307" and l.client_role == "seller")


def build_quarter(company: CompanyFacts, periods: list[PeriodData]) -> QuarterResult:
    if not periods:
        raise ValueError("build_quarter needs at least the target quarter")
    target = periods[-1]
    warnings: list[str] = []
    keeps_inventory = company.business_type != "services"

    # 1. Chains across every quarter on record: inventory and excess input VAT.
    carry_vat = c2(periods[0].inputs.opening_excess_input_vat)
    previous_ending: Decimal | None = None
    cogs_by_period: dict[tuple[int, int], CogsResult] = {}
    vat: VatResult | None = None
    for index, p in enumerate(periods):
        if index > 0 and previous_ending is not None:
            beginning = previous_ending
        elif p.inputs.opening_inventory is not None:
            beginning = p.inputs.opening_inventory
        else:
            beginning = ZERO
            if p is target and keeps_inventory:
                warnings.append("Beginning inventory is unknown and was taken as ₱0. Enter last quarter's ending "
                                "inventory, or this quarter's opening inventory.")
        cogs_by_period[(p.year, p.quarter)] = compute_cogs(p.lines, company, beginning, p.inputs.ending_inventory)
        previous_ending = p.inputs.ending_inventory
        if company.vat_registered:
            vat = compute_2550q(p.lines, p.inputs, carry_vat)
            carry_vat = vat.excess_input_vat_out

    # 2. Income tax figures, Q1 to the target quarter of the fiscal year.
    by_quarter = {p.quarter: p for p in periods if p.year == target.year and p.quarter <= target.quarter}
    prior = None
    if target.quarter > 1 and target.inputs.prior_taxable_income is not None:
        prior = PriorOverride(target.inputs.prior_taxable_income, target.inputs.prior_tax_paid or ZERO,
                              target.inputs.prior_cwt or ZERO)
    else:
        missing = [q for q in range(1, target.quarter) if q not in by_quarter or not by_quarter[q].lines]
        if missing:
            names = ", ".join(f"Q{q}" for q in missing)
            warnings.append(f"No documents for {names} of {target.year}; income tax treats them as zero. If those "
                            "quarters were filed elsewhere, enter their totals in the quarter inputs.")
    figures: list[QuarterFigures] = []
    rep_ytd = allowed_ytd = sales_ytd = ZERO
    breakdown: ExpenseBreakdown | None = None
    for q in range(1, target.quarter + 1):
        p = by_quarter.get(q)
        lines = p.lines if p else ()
        sales_q = sales_base(lines, company)
        sales_ytd = c2(sales_ytd + sales_q)
        breakdown, rep_ytd, allowed_ytd = quarter_expenses(lines, company, rep_ytd, allowed_ytd, sales_ytd)
        cogs_q = cogs_by_period[(p.year, p.quarter)].cost_of_sales if p else ZERO
        figures.append(QuarterFigures(sales_q, cogs_q, breakdown.deductions,
                                      p.inputs.non_operating_income if p else ZERO, _cwt(lines)))

    # 3. Forms for the target quarter.
    forms: dict[str, dict] = {}
    individual = company.taxpayer_type == "individual"
    if company.vat_registered:
        forms["2550Q"] = vat.items
    elif not (individual and company.income_tax_option == "eight_percent"):
        forms["2551Q"] = compute_2551q(target.lines, target.inputs)
    if target.quarter <= 3:
        if individual:
            forms["1701Q"] = compute_1701q(figures, company, target.inputs, prior)
        else:
            forms["1702Q"] = compute_1702q(figures, company, target.inputs, prior)
    else:
        warnings.append("Q4 has no quarterly income tax return; the annual return (1701/1702) covers it and comes "
                        "in a later phase.")
    target_cogs = cogs_by_period[(target.year, target.quarter)]
    if keeps_inventory:
        forms["COGS"] = cogs_form(target_cogs)
    forms["Expenses"] = expenses_form(breakdown)

    # 4. Ledgers.
    ledgers: dict[str, list[dict]] = {"Transactions": build_transactions(target.lines, company.vat_registered)}
    if company.vat_registered:
        ledgers["SLS"] = build_sls(target.lines)
        ledgers["SLP"] = build_slp(target.lines, True)
    sawt = build_sawt(target.lines)
    if sawt:
        ledgers["SAWT"] = sawt

    # 5. Warnings.
    review_open = sum(1 for l in target.lines if l.open_review)
    if review_open:
        warnings.insert(0, f"{review_open} document(s) in this quarter still need review — this output is a DRAFT.")
    unsorted = sum(1 for l in target.lines if l.category == "unsorted")
    if unsorted:
        warnings.append(f"{unsorted} unsorted document(s) were left out. Move them to a folder to include them.")
    if keeps_inventory and not target_cogs.ending_provided:
        warnings.append("Ending inventory was not provided and was taken as ₱0, so cost of sales may be overstated.")
    if company.business_type == "manufacturing":
        warnings.append("Manufacturing cost of sales is simplified to beginning inventory + purchases − ending "
                        "inventory.")
    if breakdown.capital_goods > 0:
        warnings.append(f"{_peso_text(breakdown.capital_goods)} of capital goods were not expensed; depreciation is "
                        "not computed yet.")
    if breakdown.representation_disallowed_ytd > 0:
        cap = "1%" if company.business_type == "services" else "0.5%"
        warnings.append(f"Representation above the {cap} cap ({_peso_text(breakdown.representation_disallowed_ytd)} "
                        "so far this year) is not deductible.")
    if company.vat_registered and sawt and target.inputs.vat_withheld == 0:
        warnings.append("Received 2307s are credited against income tax. If any show VAT withheld (ATC WV…), enter "
                        "it as 'VAT withheld' in the quarter inputs.")

    carry_out = {"excess_input_vat": carry_vat if company.vat_registered else None,
                 "ending_inventory": target.inputs.ending_inventory}
    return QuarterResult(forms, ledgers, warnings, carry_out, review_open)
```

Check `test_eight_percent_individual_files_only_1701q`: services, non-VAT, 8% → no 2551Q, no 2550Q, no COGS; 1701Q 8%: sales 300,000 → 53 = 50,000 → 54 = 4,000 ✓.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_engine.py -q`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/compute/ledgers.py backend/app/services/accounting/compute/specs.py backend/app/services/accounting/compute/due_dates.py backend/app/services/accounting/compute/engine.py backend/tests/test_aa_engine.py
git commit -m "feat(accounting): quarter engine, SLS/SLP/SAWT ledgers, labels and due dates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Version snapshots and diffs

**Files:**
- Create: `backend/app/services/accounting/diff.py`
- Test: `backend/tests/test_aa_diff.py`

**Interfaces:**
- Consumes: `QuarterResult` (Task 4), `CompanyFacts` (Task 1).
- Produces: `snapshot(result, company) -> dict` (`{"company": {...}, "forms": {form: {key: str}}, "ledgers": {name: [row with str values]}}`, Decimals as plain strings via `format(v, "f")`); `diff_snapshots(old: dict | None, new: dict) -> dict` (`{"forms": {form: {key: [old, new]}}, "ledgers": {name: {"added": [key], "changed": {key: {column: [old, new]}}, "removed": [key]}}}`); `count_changes(diff: dict | None) -> int`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_aa_diff.py`:

```python
from decimal import Decimal

from app.services.accounting.compute.engine import QuarterResult
from app.services.accounting.diff import count_changes, diff_snapshots, snapshot
from tests.aa_factories import company


def _result(total="120.00", rows=None):
    rows = rows if rows is not None else [{"key": "555", "name": "A", "taxable": Decimal("1000.00")}]
    return QuarterResult(forms={"2550Q": {"26": Decimal(total), "31A": Decimal("1000.00")}},
                         ledgers={"SLS": rows}, warnings=[], carry_out={}, review_open=0)


def test_snapshot_is_plain_strings_with_company():
    snap = snapshot(_result(), company())
    assert snap["forms"]["2550Q"] == {"26": "120.00", "31A": "1000.00"}
    assert snap["ledgers"]["SLS"] == [{"key": "555", "name": "A", "taxable": "1000.00"}]
    assert snap["company"]["registered_name"] == "Juan's Cloth Trading"


def test_identical_snapshots_have_no_changes():
    a = snapshot(_result(), company())
    diff = diff_snapshots(a, snapshot(_result(), company()))
    assert diff == {"forms": {}, "ledgers": {}} and count_changes(diff) == 0


def test_changed_values_and_rows_are_reported():
    old = snapshot(_result(), company())
    new_rows = [{"key": "555", "name": "A", "taxable": Decimal("1500.00")},
                {"key": "777", "name": "B", "taxable": Decimal("10.00")}]
    new = snapshot(_result(total="180.00", rows=new_rows), company())
    diff = diff_snapshots(old, new)
    assert diff["forms"] == {"2550Q": {"26": ["120.00", "180.00"]}}
    assert diff["ledgers"]["SLS"] == {"added": ["777"], "changed": {"555": {"taxable": ["1000.00", "1500.00"]}},
                                      "removed": []}
    assert count_changes(diff) == 3


def test_removed_rows_and_new_forms():
    old = snapshot(_result(), company())
    new = snapshot(QuarterResult(forms={"2550Q": {"26": Decimal("120.00"), "31A": Decimal("1000.00")},
                                        "COGS": {"cost_of_sales": Decimal("5.00")}},
                                 ledgers={"SLS": []}, warnings=[], carry_out={}, review_open=0), company())
    diff = diff_snapshots(old, new)
    assert diff["forms"] == {"COGS": {"cost_of_sales": [None, "5.00"]}}
    assert diff["ledgers"]["SLS"]["removed"] == ["555"]
    assert count_changes(None) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_diff.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `backend/app/services/accounting/diff.py`:

```python
"""Immutable version snapshots and the differences between two versions (pure)."""

from dataclasses import asdict
from decimal import Decimal

from app.services.accounting.compute.engine import QuarterResult
from app.services.accounting.compute.inputs import CompanyFacts


def _text(value) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return "" if value is None else str(value)


def snapshot(result: QuarterResult, company: CompanyFacts) -> dict:
    return {
        "company": asdict(company),
        "forms": {form: {key: _text(v) for key, v in items.items()} for form, items in result.forms.items()},
        "ledgers": {name: [{col: _text(v) for col, v in row.items()} for row in rows]
                    for name, rows in result.ledgers.items()},
    }


def diff_snapshots(old: dict | None, new: dict) -> dict:
    """Every form value and ledger cell that is new or different in ``new``."""
    old = old or {}
    forms: dict[str, dict] = {}
    for form, items in new["forms"].items():
        before = old.get("forms", {}).get(form, {})
        changed = {key: [before.get(key), value] for key, value in items.items() if before.get(key) != value}
        if changed:
            forms[form] = changed
    ledgers: dict[str, dict] = {}
    for name, rows in new["ledgers"].items():
        before_rows = {row["key"]: row for row in old.get("ledgers", {}).get(name, [])}
        added: list[str] = []
        changed_rows: dict[str, dict] = {}
        for row in rows:
            previous = before_rows.get(row["key"])
            if previous is None:
                added.append(row["key"])
                continue
            columns = {col: [previous.get(col), value] for col, value in row.items()
                       if col != "key" and previous.get(col) != value}
            if columns:
                changed_rows[row["key"]] = columns
        current = {row["key"] for row in rows}
        removed = [key for key in before_rows if key not in current]
        if added or changed_rows or removed:
            ledgers[name] = {"added": added, "changed": changed_rows, "removed": removed}
    return {"forms": forms, "ledgers": ledgers}


def count_changes(diff: dict | None) -> int:
    if not diff:
        return 0
    n = sum(len(items) for items in diff["forms"].values())
    for change in diff["ledgers"].values():
        n += len(change["added"]) + len(change["changed"]) + len(change["removed"])
    return n
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_diff.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/diff.py backend/tests/test_aa_diff.py
git commit -m "feat(accounting): version snapshots and diffs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: XLSX workbook with pastel-yellow changes

**Files:**
- Create: `backend/app/services/accounting/render_xlsx.py`
- Test: `backend/tests/test_aa_xlsx.py`

**Interfaces:**
- Consumes: snapshot/diff shapes (Task 5); `specs` (Task 4).
- Produces: `write_workbook(path: Path, *, header: dict, snapshot: dict, warnings: list[str], review_open: int, due: dict[str, str], version: int, diff: dict | None = None, parent_version: int | None = None, clean: bool = False) -> None`. `header` keys: `company`, `tin`, `period`, `generated`. Sheets in order: `Summary`, present forms in `FORM_ORDER`, present ledgers in `LEDGER_ORDER`, then `Change log` (only when highlighting). Changed cells: fill `FFF4B3`, dark font, comment `"v{parent}: {before} → v{version}: {after}"` (blank shown as `blank`); new ledger rows filled across the row; removed rows listed in the Change log with strikethrough.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_aa_xlsx.py`:

```python
from openpyxl import load_workbook

from app.services.accounting.render_xlsx import write_workbook

HEADER = {"company": "Juan's Cloth Trading", "tin": "123-456-789-00000", "period": "2026 · Q3 (Jul–Sep)",
          "generated": "2026-10-05 21:00"}


def _snap(total="120.00", extra_row=False):
    rows = [{"key": "555", "tin": "555", "name": "A", "address": "", "exempt": "0.00", "zero_rated": "0.00",
             "taxable": "1000.00", "gross_sales": "1000.00", "output_tax": "120.00"}]
    if extra_row:
        rows.append({**rows[0], "key": "777", "tin": "777", "name": "B"})
    return {"company": {}, "forms": {"2550Q": {"31A": "1000.00", "26": total}, "1702Q": {"25": "5000"}},
            "ledgers": {"SLS": rows}}


def _write(tmp_path, name="out.xlsx", **kw):
    path = tmp_path / name
    write_workbook(path, header=HEADER, snapshot=kw.pop("snapshot", _snap()), warnings=kw.pop("warnings", []),
                   review_open=kw.pop("review_open", 0), due={"2550Q": "2026-10-26"}, version=kw.pop("version", 1), **kw)
    return load_workbook(path)


def _row(ws, key):
    return next(r for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value == key)


def _yellow(cell) -> bool:
    return cell.fill is not None and cell.fill.fill_type == "solid" and str(cell.fill.fgColor.rgb).endswith("FFF4B3")


def test_tabs_values_and_number_formats(tmp_path):
    wb = _write(tmp_path)
    assert wb.sheetnames == ["Summary", "2550Q", "1702Q", "SLS"]
    ws = wb["2550Q"]
    assert ws.cell(4, 1).value == "31A"  # spec order: Part IV first
    r = _row(ws, "31A")
    assert ws.cell(r, 3).value == 1000 and ws.cell(r, 3).number_format == "#,##0.00"
    assert ws.cell(_row(ws, "26"), 4).value == "21 + 25"
    assert wb["1702Q"].cell(_row(wb["1702Q"], "25"), 3).number_format == "#,##0"
    assert wb["SLS"].cell(2, 6).value == 1000
    assert not any(_yellow(c) for row in ws.iter_rows() for c in row)


def test_changed_cell_is_yellow_with_comment(tmp_path):
    diff = {"forms": {"2550Q": {"26": ["100.00", "120.00"]}},
            "ledgers": {"SLS": {"added": ["777"], "changed": {}, "removed": ["999"]}}}
    wb = _write(tmp_path, snapshot=_snap(extra_row=True), version=2, diff=diff, parent_version=1)
    ws = wb["2550Q"]
    cell = ws.cell(_row(ws, "26"), 3)
    assert _yellow(cell) and "v1: 100.00 → v2: 120.00" in cell.comment.text
    assert not _yellow(ws.cell(_row(ws, "31A"), 3))
    sls = wb["SLS"]
    new_row = next(r for r in range(2, sls.max_row + 1) if sls.cell(r, 1).value == "777")
    assert all(_yellow(sls.cell(new_row, c)) for c in range(1, 9))
    log = wb["Change log"]
    texts = [str(c.value) for row in log.iter_rows() for c in row if c.value is not None]
    assert "(row removed)" in texts and "(new row)" in texts


def test_clean_copy_has_no_highlights(tmp_path):
    diff = {"forms": {"2550Q": {"26": ["100.00", "120.00"]}}, "ledgers": {}}
    wb = _write(tmp_path, version=2, diff=diff, parent_version=1, clean=True)
    assert "Change log" not in wb.sheetnames
    ws = wb["2550Q"]
    assert not _yellow(ws.cell(_row(ws, "26"), 3)) and ws.cell(_row(ws, "26"), 3).comment is None


def test_summary_has_payables_draft_banner_and_warnings(tmp_path):
    wb = _write(tmp_path, review_open=2, warnings=["Ending inventory was not provided."])
    texts = [str(c.value) for row in wb["Summary"].iter_rows() for c in row if c.value is not None]
    assert "DRAFT — 2 document(s) still need review" in texts
    assert "• Ending inventory was not provided." in texts
    assert "2026-10-26" in texts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_xlsx.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `backend/app/services/accounting/render_xlsx.py`:

```python
"""Write a version's workbook: one tab per form and ledger; changes since the last version in pastel yellow."""

from decimal import Decimal, InvalidOperation
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.services.accounting.compute.specs import (
    FORM_NOTES, FORM_ORDER, FORM_TITLES, LEDGER_COLUMNS, LEDGER_ORDER, PAYABLE_ITEM, WHOLE_PESO_FORMS, form_items,
)

YELLOW = PatternFill("solid", fgColor="FFF4B3")
DARK = Font(color="1F1F1F")
STRUCK = Font(color="1F1F1F", strike=True)
BOLD = Font(bold=True)
TITLE = Font(bold=True, size=13)
RED = Font(bold=True, color="B42318")
MONEY = "#,##0.00"
WHOLE = "#,##0"
AUTHOR = "AutoAccounting"


def _number(text):
    if text is None or text == "":
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError):
        return text


def _shown(text) -> str:
    return "blank" if text in (None, "") else str(text)


def _mark(cell, before, after, parent: int, version: int) -> None:
    cell.fill = YELLOW
    cell.font = DARK
    cell.comment = Comment(f"v{parent}: {_shown(before)} → v{version}: {_shown(after)}", AUTHOR)


def _summary(wb, header, snapshot, warnings, review_open, due, version, parent_version, highlighting) -> None:
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = f"AutoAccounting — {header['company']}"
    ws["A1"].font = TITLE
    version_text = f"v{version}" + (f" — changes since v{parent_version} in yellow" if highlighting else "")
    row = 3
    for label, value in (("TIN", header["tin"]), ("Period", header["period"]), ("Version", version_text),
                         ("Generated", header["generated"])):
        ws.cell(row, 1, label).font = BOLD
        ws.cell(row, 2, value)
        row += 1
    if review_open:
        ws.cell(row, 1, f"DRAFT — {review_open} document(s) still need review").font = RED
        row += 1
    row += 1
    for col, text in enumerate(("Return", "Amount payable / (excess)", "Due date"), start=1):
        ws.cell(row, col, text).font = BOLD
    row += 1
    forms = snapshot["forms"]
    for form in FORM_ORDER:
        if form in PAYABLE_ITEM and form in forms:
            ws.cell(row, 1, FORM_TITLES[form])
            cell = ws.cell(row, 2, _number(forms[form].get(PAYABLE_ITEM[form])))
            cell.number_format = WHOLE if form in WHOLE_PESO_FORMS else MONEY
            ws.cell(row, 3, due.get(form, ""))
            row += 1
    if warnings:
        row += 1
        ws.cell(row, 1, "Warnings").font = BOLD
        row += 1
        for warning in warnings:
            ws.cell(row, 1, f"• {warning}")
            row += 1
    for col, width in (("A", 64), ("B", 30), ("C", 14)):
        ws.column_dimensions[col].width = width


def _form_sheet(wb, form, values, changes, version, parent_version) -> None:
    ws = wb.create_sheet(form)
    ws["A1"] = FORM_TITLES[form]
    ws["A1"].font = TITLE
    for col, text in enumerate(("Item", "Description", "Amount", "How it's computed"), start=1):
        ws.cell(3, col, text).font = BOLD
    notes = FORM_NOTES.get(form, {})
    for offset, (key, label) in enumerate(form_items(form, values)):
        row = 4 + offset
        ws.cell(row, 1, key)
        ws.cell(row, 2, label)
        cell = ws.cell(row, 3, _number(values[key]))
        if isinstance(cell.value, Decimal):
            cell.number_format = WHOLE if form in WHOLE_PESO_FORMS else MONEY
        ws.cell(row, 4, notes.get(key, ""))
        if key in changes:
            _mark(cell, changes[key][0], changes[key][1], parent_version, version)
    ws.freeze_panes = "A4"
    for col, width in (("A", 10), ("B", 60), ("C", 18), ("D", 30)):
        ws.column_dimensions[col].width = width


def _ledger_sheet(wb, name, rows, change, version, parent_version) -> None:
    ws = wb.create_sheet(name)
    columns = LEDGER_COLUMNS[name]
    for col, (_, label, _) in enumerate(columns, start=1):
        ws.cell(1, col, label).font = BOLD
    added = set(change["added"])
    for offset, row in enumerate(rows):
        r = 2 + offset
        changed = change["changed"].get(row["key"], {})
        for col, (key, _, kind) in enumerate(columns, start=1):
            cell = ws.cell(r, col, _number(row.get(key)) if kind == "money" else row.get(key, ""))
            if kind == "money":
                cell.number_format = MONEY
            if row["key"] in added:
                cell.fill = YELLOW
                cell.font = DARK
            elif key in changed:
                _mark(cell, changed[key][0], changed[key][1], parent_version, version)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(rows) + 1}"
    for col, (key, _, kind) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(col)].width = 16 if kind == "money" else (30 if key in ("name", "address", "counterparty") else 14)


def _change_log(wb, diff, version, parent_version) -> None:
    ws = wb.create_sheet("Change log")
    ws["A1"] = f"Changes from v{parent_version} to v{version}"
    ws["A1"].font = TITLE
    for col, text in enumerate(("Tab", "Item / row", "Field", "Before", "After"), start=1):
        ws.cell(3, col, text).font = BOLD
    row = 4
    for form, items in diff["forms"].items():
        for key, (before, after) in items.items():
            for col, value in enumerate((form, key, "value", _shown(before), _shown(after)), start=1):
                ws.cell(row, col, value)
            row += 1
    for name, change in diff["ledgers"].items():
        for key in change["added"]:
            for col, value in enumerate((name, key, "(new row)", "", ""), start=1):
                ws.cell(row, col, value).fill = YELLOW
            row += 1
        for key, columns in change["changed"].items():
            for field, (before, after) in columns.items():
                for col, value in enumerate((name, key, field, _shown(before), _shown(after)), start=1):
                    ws.cell(row, col, value)
                row += 1
        for key in change["removed"]:
            for col, value in enumerate((name, key, "(row removed)", "", ""), start=1):
                cell = ws.cell(row, col, value)
                cell.fill = YELLOW
                cell.font = STRUCK
            row += 1
    for col, width in (("A", 14), ("B", 40), ("C", 18), ("D", 18), ("E", 18)):
        ws.column_dimensions[col].width = width


def write_workbook(path: Path, *, header: dict, snapshot: dict, warnings: list[str], review_open: int,
                   due: dict[str, str], version: int, diff: dict | None = None, parent_version: int | None = None,
                   clean: bool = False) -> None:
    highlighting = bool(diff) and not clean and parent_version is not None
    active = diff if highlighting else {"forms": {}, "ledgers": {}}
    wb = Workbook()
    _summary(wb, header, snapshot, warnings, review_open, due, version, parent_version, highlighting)
    for form in FORM_ORDER:
        if form in snapshot["forms"]:
            _form_sheet(wb, form, snapshot["forms"][form], active["forms"].get(form, {}), version, parent_version)
    for name in LEDGER_ORDER:
        if name in snapshot["ledgers"]:
            change = active["ledgers"].get(name, {"added": [], "changed": {}, "removed": []})
            _ledger_sheet(wb, name, snapshot["ledgers"][name], change, version, parent_version)
    if highlighting:
        _change_log(wb, diff, version, parent_version)
    wb.save(path)
```


- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_xlsx.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/accounting/render_xlsx.py backend/tests/test_aa_xlsx.py
git commit -m "feat(accounting): versioned XLSX workbook with pastel-yellow changes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 2550-Q PDF overlay

**Files:**
- Create: `backend/app/forms/templates/bir2550q_apr2024.pdf` (official BIR file), `backend/app/forms/bir2550q_layout.py`, `backend/app/services/accounting/pdf_2550q.py`
- Test: `backend/tests/test_aa_pdf_2550q.py`

**Interfaces:**
- Consumes: snapshot values (`dict[str, str]`) for form `2550Q`.
- Produces: `Header2550Q(tin, rdo_code, name, address, zip_code, fiscal_year_end_month, fiscal_year, quarter, period_from: date, period_to: date)`; `split_amount(text) -> tuple[str, str] | None`; `render_2550q(values, header, highlights: frozenset[str] = frozenset(), amended: bool = False, draft_reviews: int = 0) -> bytes`.

- [ ] **Step 1: Add the template**

```bash
curl -sSL -A "Mozilla/5.0" -o backend/app/forms/templates/bir2550q_apr2024.pdf "https://bir-cdn.bir.gov.ph/BIR/pdf/2550Q%20%20April%202024%20ENCS_Final.pdf"
shasum -a 256 backend/app/forms/templates/bir2550q_apr2024.pdf
```
Expected: `18eb16925010fdda820cef958221ba2c0d073066efa93a898113e39b31135a25`. (If the BIR has replaced the file, stop: the field map below is calibrated to this exact version.)

- [ ] **Step 2: Write the failing tests** — `backend/tests/test_aa_pdf_2550q.py`:

```python
import hashlib
from datetime import date

import fitz

from app.forms import bir2550q_layout as L
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q, split_amount

HEADER = Header2550Q("123456789", "030", "Juan's Cloth Trading", "Quiapo, Manila", "1001", 12, 2026, 3,
                     date(2026, 7, 1), date(2026, 9, 30))


def _words(pdf: bytes, page: int):
    return fitz.open("pdf", pdf)[page].get_text("words")


def test_template_is_the_calibrated_official_form():
    assert hashlib.sha256(L.TEMPLATE_PATH.read_bytes()).hexdigest() == L.TEMPLATE_SHA256


def test_split_amount():
    assert split_amount("1234.5") == ("1,234", "50")
    assert split_amount("-480.00") == ("(480", "00)")
    assert split_amount("") is None and split_amount("abc") is None


def test_amounts_land_in_their_boxes():
    pdf = render_2550q({"31A": "25000.00", "31B": "3000.00", "26": "600.00"}, HEADER)
    a = next(w for w in _words(pdf, 1) if w[4] == "25,000")
    assert 163 < a[0] and a[2] <= 331 and abs(a[3] - 141.4) < 3
    b = next(w for w in _words(pdf, 1) if w[4] == "3,000")
    assert 376 < b[0] and b[2] <= 545 and abs(b[3] - 141.4) < 3
    total = next(w for w in _words(pdf, 0) if w[4] == "600")
    assert 376 < total[0] and total[2] <= 545 and abs(total[3] - 566.6) < 3


def test_negative_amount_in_parentheses():
    pdf = render_2550q({"61B": "-480.00"}, HEADER)
    words = _words(pdf, 1)
    whole = next(w for w in words if w[4] == "(480")
    cents = next(w for w in words if w[4] == "00)")
    assert whole[2] <= 545 and 560 < cents[0] and cents[2] <= 590


def test_header_boxes_are_filled():
    pdf = render_2550q({}, HEADER)
    page1 = _words(pdf, 0)
    xs = [w for w in page1 if w[4] == "X"]
    assert any(abs((w[0] + w[2]) / 2 - L.P1_QUARTER[3][0]) < 3 for w in xs)      # 3rd quarter
    assert any(abs((w[0] + w[2]) / 2 - L.P1_CALENDAR[0]) < 3 for w in xs)       # calendar year
    tin_digits = [w for w in page1 if w[4] in "123456789" and abs(w[3] - 184) < 4 and 233 < w[0] < 390]
    assert len(tin_digits) >= 9
    assert any(w[4] == "J" and w[0] < 40 and abs(w[3] - 213) < 4 for w in page1)  # name, first letter


def test_highlight_and_draft_banner():
    pdf = render_2550q({"31A": "1.00"}, HEADER, highlights=frozenset({"31A"}), draft_reviews=2)
    doc = fitz.open("pdf", pdf)
    fills = [d.get("fill") for d in doc[1].get_drawings() if d.get("fill")]
    assert any(abs(f[0] - 1.0) < 0.01 and abs(f[1] - 0.957) < 0.01 and abs(f[2] - 0.702) < 0.01 for f in fills)
    assert "DRAFT" in doc[0].get_text() and "Highlighted = changed" in doc[0].get_text()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_2550q.py -q`
Expected: FAIL with `ModuleNotFoundError: ... bir2550q_layout`.

- [ ] **Step 4: Implement**

`backend/app/forms/bir2550q_layout.py`:

```python
"""Overlay map for BIR Form 2550-Q (April 2024 ENCS).

Calibrated from the template's own vector boxes and item-number text positions
(PDF points, origin top-left as PyMuPDF uses; page 612 × 1008). Amount boxes are
split into pesos (right-aligned) and centavos (centred).
"""

from pathlib import Path

TEMPLATE_PATH = Path(__file__).parent / "templates" / "bir2550q_apr2024.pdf"
TEMPLATE_SHA256 = "18eb16925010fdda820cef958221ba2c0d073066efa93a898113e39b31135a25"
FONT_NAME = "helv"
FONT_SIZE = 8.0
CELL_FONT_SIZE = 9.0


def _centres(edges: list[float]) -> list[float]:
    return [round((a + b) / 2, 1) for a, b in zip(edges, edges[1:])]


# (page, column) -> (pesos right edge, centavos centre, highlight x0, highlight x1)
COLUMNS = {
    (0, "B"): (544.5, 577.0, 376.5, 591.0),
    (1, "A"): (330.0, 361.5, 163.5, 375.0),
    (1, "B"): (544.5, 575.5, 376.5, 589.5),
}

_P1 = {"15": 355.0, "16": 384.1, "17": 402.3, "18": 420.6, "19": 439.1, "20": 457.1, "21": 475.3, "22": 493.6,
       "23": 511.8, "24": 530.1, "25": 548.3, "26": 566.6}
_P2_ROWS = {"31": 141.4, "32": 157.3, "33": 173.3, "34": 186.6, "35": 206.9, "36": 222.9, "37": 238.8, "38": 265.1,
            "39": 281.0, "40": 297.0, "41": 312.9, "42": 328.9, "43": 344.8, "44": 375.1, "45": 390.9, "46": 407.0,
            "47": 422.9, "48": 438.9, "49": 454.8, "50": 468.2, "51": 489.1, "52": 512.2, "53": 532.5,
            "54": 548.4, "55": 564.4, "56": 580.3, "57": 596.3, "58": 612.2, "59": 628.2, "60": 644.1,
            "61": 660.1}
_P2_COLUMN_A = {"31", "32", "33", "34", "44", "45", "46", "47", "48", "49", "50"}
_P2_COLUMN_B = {"31", "34", "35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47", "50",
                "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "61"}

# item key -> (page index, column, baseline y)
ITEMS: dict[str, tuple[int, str, float]] = {key: (0, "B", y) for key, y in _P1.items()}
ITEMS.update({f"{n}A": (1, "A", y) for n, y in _P2_ROWS.items() if n in _P2_COLUMN_A})
ITEMS.update({f"{n}B": (1, "B", y) for n, y in _P2_ROWS.items() if n in _P2_COLUMN_B})

# Header (page 1 unless noted). Points are (x centre, baseline y); cell groups are (x centres, baseline y).
P1_CALENDAR = (80.9, 119.5)
P1_FISCAL = (148.0, 119.5)
P1_YEAR_ENDED = (_centres([304.9, 318.8, 332.8, 347.1, 361.4, 375.9, 389.8]), 120.0)      # MMYYYY
P1_QUARTER = {1: (441.5, 119.5), 2: (477.3, 119.5), 3: (519.4, 119.5), 4: (561.1, 119.5)}
P1_PERIOD_FROM = (_centres([64.4, 78.4, 92.4, 106.5, 120.6, 134.6, 148.6, 162.6, 176.4]), 150.0)   # MMDDYYYY
P1_PERIOD_TO = (_centres([204.7, 219.0, 233.2, 247.3, 261.6, 275.6, 289.9, 304.5, 318.6]), 150.0)
P1_AMENDED = {True: (354.0, 148.8), False: (396.5, 148.8)}
P1_SHORT_PERIOD_NO = (540.1, 148.8)
P1_TIN = (_centres([233.4, 247.3, 261.5, 275.4]) + _centres([290.0, 304.5, 318.6, 332.5])
          + _centres([347.2, 361.3, 375.8, 389.6]), 182.0)
P1_RDO = (_centres([547.1, 562.1, 576.3, 591.5]), 182.0)
_LINE = [22.8, 36.1, 50.2, 64.3, 78.4, 92.3, 106.5, 120.6, 134.6, 148.6, 162.6, 176.5, 190.6, 204.7, 219.0, 233.1,
         247.3, 261.5, 275.6, 289.9, 304.5, 318.6, 332.9, 347.0, 361.3, 375.8, 389.9, 404.4, 418.9, 433.0, 447.2,
         461.4, 475.6, 489.8, 504.0, 518.2, 532.4, 546.9, 562.1, 576.3, 591.5]
P1_NAME = (_centres(_LINE), 211.0)
P1_ADDRESS = (_centres(_LINE), 239.5)
P1_ZIP = (_centres([532.6, 546.9, 562.1, 576.3, 591.5]), 257.0)
P2_TIN = (_centres([22.8, 36.1, 50.2, 64.4, 78.4, 92.5, 106.6, 120.6, 134.7, 148.9]), 103.0)
P2_NAME = (_centres([219.4, 233.9, 248.1, 262.2, 276.4, 290.5, 305.0, 319.2, 333.5, 347.5, 361.8, 376.0, 390.2,
                     404.4, 418.6, 432.8, 447.0, 461.2, 475.4, 489.6, 503.8, 517.9, 532.1, 546.7, 561.4, 575.6,
                     589.7]), 103.0)
FOOTNOTE = (24.0, 985.0)
DRAFT_BANNER = (24.0, 970.0)
```

`backend/app/services/accounting/pdf_2550q.py`:

```python
"""Fill BIR Form 2550-Q from a version's stored values (PyMuPDF overlay on the official template)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import fitz  # PyMuPDF

from app.forms import bir2550q_layout as L

YELLOW_RGB = (1.0, 0.957, 0.702)
RED_RGB = (0.71, 0.14, 0.09)
BLACK = (0, 0, 0)


@dataclass(frozen=True)
class Header2550Q:
    tin: str
    rdo_code: str
    name: str
    address: str
    zip_code: str
    fiscal_year_end_month: int
    fiscal_year: int
    quarter: int
    period_from: date
    period_to: date


def split_amount(text: str) -> tuple[str, str] | None:
    """'-1234.5' -> ('(1,234', '50)'): pesos and centavos as printed in the two boxes."""
    try:
        value = Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return None
    whole, cents = f"{abs(value):,.2f}".split(".")
    return (f"({whole}", f"{cents})") if value < 0 else (whole, cents)


def _width(text: str, size: float) -> float:
    return fitz.get_text_length(text, fontname=L.FONT_NAME, fontsize=size)


def _centre(page, x: float, y: float, text: str, size: float) -> None:
    page.insert_text((x - _width(text, size) / 2, y), text, fontname=L.FONT_NAME, fontsize=size, color=BLACK)


def _right(page, x: float, y: float, text: str, size: float) -> None:
    page.insert_text((x - _width(text, size), y), text, fontname=L.FONT_NAME, fontsize=size, color=BLACK)


def _cells(page, cells: tuple[list[float], float], text: str) -> None:
    centres, y = cells
    for x, char in zip(centres, text):
        if char.strip():
            _centre(page, x, y, char, L.CELL_FONT_SIZE)


def render_2550q(values: dict[str, str], header: Header2550Q, highlights: frozenset[str] = frozenset(),
                 amended: bool = False, draft_reviews: int = 0) -> bytes:
    doc = fitz.open(L.TEMPLATE_PATH)
    try:
        p1, p2 = doc[0], doc[1]
        _centre(p1, *(L.P1_CALENDAR if header.fiscal_year_end_month == 12 else L.P1_FISCAL), "X", 9)
        _cells(p1, L.P1_YEAR_ENDED, f"{header.fiscal_year_end_month:02d}{header.fiscal_year}")
        _centre(p1, *L.P1_QUARTER[header.quarter], "X", 9)
        _cells(p1, L.P1_PERIOD_FROM, header.period_from.strftime("%m%d%Y"))
        _cells(p1, L.P1_PERIOD_TO, header.period_to.strftime("%m%d%Y"))
        _centre(p1, *L.P1_AMENDED[amended], "X", 9)
        _centre(p1, *L.P1_SHORT_PERIOD_NO, "X", 9)
        _cells(p1, L.P1_TIN, header.tin[:9])
        _cells(p1, L.P1_RDO, header.rdo_code[:3])
        _cells(p1, L.P1_NAME, header.name.upper())
        _cells(p1, L.P1_ADDRESS, header.address.upper())
        _cells(p1, L.P1_ZIP, header.zip_code[:4])
        _cells(p2, L.P2_TIN, header.tin[:9])
        _cells(p2, L.P2_NAME, header.name.upper())

        for key, (page_index, column, baseline) in L.ITEMS.items():
            parts = split_amount(values.get(key, ""))
            if parts is None:
                continue
            page = doc[page_index]
            right, cents_x, x0, x1 = L.COLUMNS[(page_index, column)]
            if key in highlights:
                page.draw_rect(fitz.Rect(x0, baseline - 8.5, x1, baseline + 2), color=None, fill=YELLOW_RGB,
                               overlay=True)
            _right(page, right, baseline, parts[0], L.FONT_SIZE)
            _centre(page, cents_x, baseline, parts[1], L.FONT_SIZE)

        if highlights:
            p1.insert_text(L.FOOTNOTE, "Highlighted = changed since the previous version", fontname=L.FONT_NAME,
                           fontsize=7, color=BLACK)
        if draft_reviews:
            for page in doc:
                page.insert_text(L.DRAFT_BANNER, f"DRAFT — {draft_reviews} document(s) unreviewed — not for filing",
                                 fontname=L.FONT_NAME, fontsize=11, color=RED_RGB)
        return doc.tobytes(garbage=3, deflate=True)
    finally:
        doc.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_aa_pdf_2550q.py -q`
Expected: PASS (6 tests).

- [ ] **Step 6: Look at it** — render a sample and inspect it visually; nudge constants in `bir2550q_layout.py` if any text sits outside its box (ledger each nudge as a ruling):

```bash
docker compose exec -T backend python -c "
from datetime import date; import fitz
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q
v={'31A':'25000.00','31B':'3000.00','32A':'0.00','33A':'0.00','34A':'25000.00','34B':'3000.00','37B':'3000.00','38B':'500.00','43B':'500.00','44A':'15000.00','44B':'1800.00','48A':'1120.00','50A':'16120.00','50B':'1800.00','51B':'2300.00','60B':'2300.00','61B':'700.00','15':'700.00','16':'100.00','20':'100.00','21':'600.00','26':'600.00'}
h=Header2550Q('123456789','030','Juans Cloth Trading','Quiapo Manila','1001',12,2026,3,date(2026,7,1),date(2026,9,30))
d=fitz.open('pdf',render_2550q(v,h,frozenset({'26','44B'}),draft_reviews=1))
for i in (0,1): d[i].get_pixmap(dpi=110).save(f'/app/uploads/2550q_p{i+1}.png')
"
```
Then open `backend/uploads/2550q_p1.png` and `backend/uploads/2550q_p2.png` (Read tool) and check every value sits inside its box. Delete the PNGs afterwards.

- [ ] **Step 7: Commit**

```bash
git add backend/app/forms/templates/bir2550q_apr2024.pdf backend/app/forms/bir2550q_layout.py backend/app/services/accounting/pdf_2550q.py backend/tests/test_aa_pdf_2550q.py
git commit -m "feat(accounting): fill BIR 2550-Q PDF from a version's values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Periods and outputs tables, RLS, quarter status in the tree

**Files:**
- Modify: `backend/app/models/accounting.py` (append), `backend/app/services/accounting/rls.py`, `backend/app/services/accounting/tree.py`
- Test: `backend/tests/test_accounting_rls.py`, `backend/tests/test_accounting_tree.py`, `backend/tests/test_aa_period_status.py`

**Interfaces:**
- Produces: `AAPeriod(id, enterprise_id, company_id, year, quarter, inputs: dict, inputs_updated_at, filed_at, created_at, updated_at)` (unique `company_id, year, quarter`); `AAOutput(id, enterprise_id, company_id, period_id, version, parent_version, snapshot, diff, warnings, review_open, amended, xlsx_path, xlsx_clean_path, created_by, created_at)` (unique `period_id, version`); `tree.stale_periods(changes: dict[tuple[int, int], datetime], generated: dict[tuple[int, int], datetime]) -> set[tuple[int, int]]`; `tree.build_tree(companies, rows, status=None)` where `status: dict[tuple[str, int, int], dict]` holds `latest_version`, `stale`, `filed`, and every quarter dict gains those three keys (defaults `None`, `False`, `False`).

- [ ] **Step 1: Write the failing tests**

Replace the `TABLES` line in `backend/tests/test_accounting_rls.py` and its import with:

```python
from app.models.accounting import AACompany, AADocument, AAFile, AAOutput, AAPeriod, AASupplierRule, AAUpload
from app.services.accounting.rls import rls_statements

TABLES = [m.__tablename__ for m in (AACompany, AAUpload, AAFile, AADocument, AASupplierRule, AAPeriod, AAOutput)]
```

In `backend/tests/test_accounting_tree.py`, change the expected quarter dict in `test_build_tree_nests_years_and_quarters_newest_first` to:

```python
    assert juan["years"][0]["quarters"][0] == {
        "year": 2026, "quarter": 3, "label": "Q3 (Jul–Sep)", "document_count": 48, "review_count": 5,
        "latest_version": None, "stale": False, "filed": False,
    }
```

…and append:

```python
def test_build_tree_merges_quarter_status():
    companies = [TreeCompanyInput(A, "Juan's Cloth Trading", "123456789", False, 12)]
    tree = build_tree(companies, [(uuid.UUID(A), 2026, 3, 4, 0)],
                      {(A, 2026, 3): {"latest_version": 2, "stale": True, "filed": True}})
    quarter = tree[0]["years"][0]["quarters"][0]
    assert (quarter["latest_version"], quarter["stale"], quarter["filed"]) == (2, True, True)
```

`backend/tests/test_aa_period_status.py`:

```python
from datetime import datetime, timedelta, timezone

from app.services.accounting.tree import stale_periods

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def test_change_in_same_or_earlier_quarter_makes_output_stale():
    generated = {(2026, 2): T0, (2026, 3): T0}
    changes = {(2026, 2): T0 + timedelta(minutes=5)}
    assert stale_periods(changes, generated) == {(2026, 2), (2026, 3)}


def test_later_or_older_changes_do_not():
    generated = {(2026, 2): T0}
    changes = {(2026, 3): T0 + timedelta(hours=1), (2026, 1): T0 - timedelta(hours=1)}
    assert stale_periods(changes, generated) == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_rls.py tests/test_accounting_tree.py tests/test_aa_period_status.py -q`
Expected: FAIL (`ImportError: cannot import name 'AAOutput'`, tree assertion, `stale_periods` missing).

- [ ] **Step 3: Implement**

Append to `backend/app/models/accounting.py`:

```python
class AAPeriod(Base):
    """A company's fiscal quarter: inputs the documents can't provide, and whether it was filed."""

    __tablename__ = "aa_periods"
    __table_args__ = (UniqueConstraint("company_id", "year", "quarter", name="uq_aa_period"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Set only when inputs are saved, so marking a quarter filed doesn't make its outputs stale.
    inputs_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class AAOutput(Base):
    """One immutable generated version of a quarter's returns and workbook."""

    __tablename__ = "aa_outputs"
    __table_args__ = (UniqueConstraint("period_id", "version", name="uq_aa_output_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aa_periods.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    review_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    amended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    xlsx_path: Mapped[str] = mapped_column(String(500), nullable=False)
    xlsx_clean_path: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = _created()
```

`backend/app/services/accounting/rls.py` — extend the firm-scoped tables:

```python
_FIRM_TABLES = ("aa_companies", "aa_uploads", "aa_files", "aa_documents", "aa_periods", "aa_outputs")
```

`backend/app/services/accounting/tree.py` — add the import `from datetime import datetime` at the top, give `build_tree` a `status` parameter and append `stale_periods`:

```python
def build_tree(companies: list[TreeCompanyInput], rows: list[tuple], status: dict | None = None) -> list[dict]:
```

…inside the quarter dict construction, after `"review_count": int(review or 0),` add:

```python
            **_status(status, node["company"].id, year, quarter),
```

…and add these module-level functions:

```python
def _status(status: dict | None, company_id: str, year: int, quarter: int) -> dict:
    found = (status or {}).get((company_id, year, quarter), {})
    return {
        "latest_version": found.get("latest_version"),
        "stale": bool(found.get("stale", False)),
        "filed": bool(found.get("filed", False)),
    }


def stale_periods(changes: dict[tuple[int, int], datetime],
                  generated: dict[tuple[int, int], datetime]) -> set[tuple[int, int]]:
    """Quarters whose latest output predates a change in that quarter or any earlier one.

    Earlier quarters count because carry-overs (excess input VAT, inventory, income tax
    year to date) flow forward into later returns.
    """
    stale: set[tuple[int, int]] = set()
    for period, generated_at in generated.items():
        if any(changed_at > generated_at for changed_period, changed_at in changes.items()
               if changed_period <= period):
            stale.add(period)
    return stale
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_rls.py tests/test_accounting_tree.py tests/test_aa_period_status.py -q`
Expected: PASS.

- [ ] **Step 5: Boot and check the tables**

Run: `docker compose restart backend && sleep 12 && docker compose logs --since 20s backend 2>&1 | grep -iE "traceback|startup complete"`
Expected: `Application startup complete.` and no traceback.
Run: `docker compose exec -T db psql -U snagstock -d snagstock -c "select relname, relforcerowsecurity from pg_class where relname in ('aa_periods','aa_outputs')"`
Expected: both rows with `t`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/accounting.py backend/app/services/accounting/rls.py backend/app/services/accounting/tree.py backend/tests/test_accounting_rls.py backend/tests/test_accounting_tree.py backend/tests/test_aa_period_status.py
git commit -m "feat(accounting): periods and output versions tables with RLS; stale detection

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: API — quarter inputs, generate versions, downloads, tree status, append detection

**Files:**
- Create: `backend/app/routers/accounting_scope.py`, `backend/app/routers/accounting_periods.py`
- Modify: `backend/app/routers/accounting.py` (use shared scope helpers, include sub-router, tree status, `affected_periods`), `backend/app/schemas/accounting.py`, `backend/app/services/accounting/compute/engine.py` (add `expected_forms`)
- Test: `backend/tests/test_accounting_schemas.py`, `backend/tests/test_aa_engine.py`

**Interfaces:**
- Consumes: everything above.
- Produces (pure): `engine.expected_forms(company, quarter) -> list[str]` (subset of `2550Q`, `2551Q`, `1701Q`, `1702Q`).
- Produces (schemas): `PeriodInputsModel`, `PeriodOut`, `OutputBrief`, `ItemOut`, `FormOut`, `OutputOut`, `FiledIn`, `AffectedPeriodOut`; `TreeQuarterOut` gains `latest_version: int | None`, `stale: bool`, `filed: bool`; `UploadOut` gains `affected_periods: list[AffectedPeriodOut]`; `CompanyIn` rejects 8% for VAT-registered taxpayers.
- Produces (HTTP, under `/api/accounting`): `GET /periods/{company_id}/{year}/{quarter}` → `PeriodOut`; `PUT …/inputs` (body `PeriodInputsModel`) → `PeriodOut`; `PUT …/filed` (body `{"filed": bool}`) → `PeriodOut`; `POST …/generate` → `OutputOut` (201; 409 on a concurrent duplicate version); `GET /outputs/{id}` → `OutputOut`; `GET /outputs/{id}/xlsx?clean=` → file; `GET /outputs/{id}/pdf?form=2550Q&clean=` → file (400 for forms without a PDF yet).
- Produces (scope helpers): `accounting_scope.scope_for(user) -> uuid.UUID`, `accounting_scope.company_or_404(db, ent, company_id) -> AACompany`, `MANAGER_ROLES`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_accounting_schemas.py`, change `test_eight_percent_only_for_individuals`'s second `CompanyIn` to pass `vat_status="non_vat"`, then append:

```python
def test_eight_percent_requires_non_vat():
    with pytest.raises(ValidationError):
        CompanyIn(registered_name="Juan", tin="123456789", taxpayer_type="individual", vat_status="vat",
                  income_tax_option="eight_percent")


def test_period_inputs_validation():
    from decimal import Decimal

    from app.schemas.accounting import PeriodInputsModel

    ok = PeriodInputsModel(ending_inventory="5000", prior_taxable_income="-1200.50", cit_rate=20)
    assert ok.ending_inventory == Decimal("5000") and ok.prior_taxable_income == Decimal("-1200.50")
    with pytest.raises(ValidationError):
        PeriodInputsModel(ending_inventory="-1")
    with pytest.raises(ValidationError):
        PeriodInputsModel(cit_rate=30)
    with pytest.raises(ValidationError):
        PeriodInputsModel(vat_withheld="1.234")
    with pytest.raises(ValidationError):
        PeriodInputsModel(unknown=1)
```

Append to `backend/tests/test_aa_engine.py`:

```python
def test_expected_forms_match_taxpayer_profile():
    from app.services.accounting.compute.engine import expected_forms

    assert expected_forms(company(), 3) == ["2550Q", "1702Q"]
    assert expected_forms(company(), 4) == ["2550Q"]
    assert expected_forms(company(vat_registered=False), 1) == ["2551Q", "1702Q"]
    eight = company(taxpayer_type="individual", vat_registered=False, income_tax_option="eight_percent")
    assert expected_forms(eight, 2) == ["1701Q"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_schemas.py tests/test_aa_engine.py -q`
Expected: FAIL (`test_eight_percent_requires_non_vat` does not raise; `PeriodInputsModel` / `expected_forms` import errors).

- [ ] **Step 3: Implement the pure pieces**

Append to `compute/engine.py`:

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
    return forms
```

In `backend/app/schemas/accounting.py`, extend `CompanyIn._eight_percent_individuals_only`:

```python
    @model_validator(mode="after")
    def _eight_percent_individuals_only(self):
        if self.income_tax_option == "eight_percent":
            if self.taxpayer_type != "individual":
                raise ValueError("The 8% income tax option is only for individuals")
            if self.vat_status == "vat":
                raise ValueError("The 8% income tax option is only for non-VAT taxpayers")
        return self
```

…add `latest_version: int | None = None`, `stale: bool = False`, `filed: bool = False` to `TreeQuarterOut`, and append:

```python
def _amount(default=None, minimum=0):
    if minimum is None:
        return Field(default=default, max_digits=14, decimal_places=2)
    return Field(default=default, ge=minimum, max_digits=14, decimal_places=2)


class PeriodInputsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ending_inventory: Decimal | None = _amount()
    opening_inventory: Decimal | None = _amount()
    opening_excess_input_vat: Decimal = _amount(Decimal("0"))
    vat_withheld: Decimal = _amount(Decimal("0"))
    advance_vat: Decimal = _amount(Decimal("0"))
    percentage_tax_withheld: Decimal = _amount(Decimal("0"))
    non_operating_income: Decimal = _amount(Decimal("0"))
    prior_year_excess_credits: Decimal = _amount(Decimal("0"))
    prior_taxable_income: Decimal | None = _amount(minimum=None)  # can be a loss
    prior_tax_paid: Decimal | None = _amount()
    prior_cwt: Decimal | None = _amount()
    cit_rate: Literal[20, 25] = 25
    mcit_applies: bool = False


class OutputBrief(BaseModel):
    id: uuid.UUID
    version: int
    created_at: datetime
    review_open: int
    changes: int
    amended: bool


class PeriodOut(BaseModel):
    company: CompanyBrief
    year: int
    quarter: int
    label: str
    inputs: PeriodInputsModel
    filed_at: datetime | None
    document_count: int
    open_reviews: int
    latest_version: int | None
    stale: bool
    forms_expected: list[str]
    due_dates: dict[str, date]
    outputs: list[OutputBrief]


class ItemOut(BaseModel):
    key: str
    label: str
    value: str
    changed: bool
    before: str | None


class FormOut(BaseModel):
    form: str
    title: str
    items: list[ItemOut]
    pdf: bool
    payable_item: str | None


class OutputOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    year: int
    quarter: int
    label: str
    version: int
    parent_version: int | None
    created_at: datetime
    review_open: int
    amended: bool
    changes: int
    warnings: list[str]
    forms: list[FormOut]
    ledgers: dict[str, int]


class FiledIn(BaseModel):
    filed: bool


class AffectedPeriodOut(BaseModel):
    company_id: uuid.UUID
    company_name: str
    year: int
    quarter: int
    label: str
    latest_version: int
    filed: bool
    new_documents: int
```

…and add to `UploadOut`: `affected_periods: list[AffectedPeriodOut] = Field(default_factory=list)` (move `AffectedPeriodOut` above `UploadOut` so it is defined first).

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_accounting_schemas.py tests/test_aa_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Shared scope helpers** — create `backend/app/routers/accounting_scope.py` by moving `_MANAGER_ROLES`, `_MEMBER_ROLES`, `_scope` and `_company_or_404` out of `routers/accounting.py` unchanged under public names:

```python
"""Firm scoping shared by the AutoAccounting routers."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounting import AACompany
from app.models.user import User, UserRole

MANAGER_ROLES = (UserRole.ADMIN, UserRole.ENTERPRISE, UserRole.MANAGER)
MEMBER_ROLES = MANAGER_ROLES + (UserRole.EMPLOYEE,)


def scope_for(user: User) -> uuid.UUID:
    """The firm (enterprise owner id) every AutoAccounting row is scoped to."""
    if user.role not in MEMBER_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account cannot use AutoAccounting")
    if user.role in (UserRole.ADMIN, UserRole.ENTERPRISE):
        return user.id
    if user.enterprise_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not part of a firm")
    return user.enterprise_id


async def company_or_404(db: AsyncSession, ent: uuid.UUID, company_id: uuid.UUID) -> AACompany:
    company = (await db.execute(
        select(AACompany).where(AACompany.id == company_id, AACompany.enterprise_id == ent)
    )).scalar_one_or_none()
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company
```

In `routers/accounting.py`, delete those four definitions and import them under their old names so the rest of the file is unchanged:

```python
from app.routers.accounting_scope import (
    MANAGER_ROLES as _MANAGER_ROLES, company_or_404 as _company_or_404, scope_for as _scope,
)
```

- [ ] **Step 6: The periods sub-router** — `backend/app/routers/accounting_periods.py`:

```python
"""AutoAccounting phase 2: quarter inputs, generating output versions, workbook and PDF downloads."""

import asyncio
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi import Path as PathParam
from fastapi.responses import Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.models.accounting import AACompany, AADocument, AAOutput, AAPeriod
from app.models.user import User
from app.routers.accounting_scope import company_or_404, scope_for
from app.schemas.accounting import (
    CompanyBrief, FiledIn, FormOut, ItemOut, OutputBrief, OutputOut, PeriodInputsModel, PeriodOut,
)
from app.services.accounting.compute.due_dates import due_dates, quarter_end, quarter_start
from app.services.accounting.compute.engine import build_quarter, expected_forms
from app.services.accounting.compute.inputs import (
    CompanyFacts, DocLine, PeriodData, PeriodInputs, inputs_from_json, inputs_to_json,
)
from app.services.accounting.compute.specs import FORM_ORDER, FORM_TITLES, PAYABLE_ITEM, PDF_FORMS, form_items
from app.services.accounting.diff import count_changes, diff_snapshots, snapshot
from app.services.accounting.pdf_2550q import Header2550Q, render_2550q
from app.services.accounting.periods import quarter_label
from app.services.accounting.render_xlsx import write_workbook
from app.services.accounting.storage import is_stored_path_safe

router = APIRouter()

_MANILA = ZoneInfo("Asia/Manila")
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def company_facts(c: AACompany) -> CompanyFacts:
    return CompanyFacts(c.registered_name, c.tin, c.branch_code, c.rdo_code, c.address, c.zip_code,
                        c.taxpayer_type, c.vat_status == "vat", c.income_tax_option, c.deduction_method,
                        c.business_type, c.fiscal_year_end_month)


def doc_line(doc: AADocument) -> DocLine:
    seller = doc.client_role == "seller"
    return DocLine(
        id=str(doc.id), category=doc.category, account=doc.account, doc_type=doc.doc_type,
        client_role=doc.client_role, doc_date=doc.doc_date, doc_number=doc.doc_number,
        counterparty_tin=doc.buyer_tin if seller else doc.seller_tin,
        counterparty_name=doc.buyer_name if seller else doc.seller_name,
        counterparty_address=doc.buyer_address if seller else doc.seller_address,
        gross=doc.gross_amount, vatable=doc.vatable_amount, vat=doc.vat_amount, exempt=doc.exempt_amount,
        zero_rated=doc.zero_rated_amount, withholding=doc.withholding_amount,
        input_vat_valid=doc.input_vat_valid, open_review=doc.needs_review and not doc.reviewed,
    )


def period_label(year: int, quarter: int, company: AACompany) -> str:
    return f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}"


def _docs_up_to(year: int, quarter: int):
    return or_(AADocument.period_year < year, and_(AADocument.period_year == year, AADocument.period_quarter <= quarter))


async def _get_period(db: AsyncSession, company_id: uuid.UUID, year: int, quarter: int) -> AAPeriod | None:
    return (await db.execute(select(AAPeriod).where(
        AAPeriod.company_id == company_id, AAPeriod.year == year, AAPeriod.quarter == quarter
    ))).scalar_one_or_none()


async def _ensure_period(db: AsyncSession, ent: uuid.UUID, company: AACompany, year: int, quarter: int) -> AAPeriod:
    period = await _get_period(db, company.id, year, quarter)
    if period is not None:
        return period
    db.add(AAPeriod(enterprise_id=ent, company_id=company.id, year=year, quarter=quarter, inputs={}))
    try:
        await db.commit()
    except IntegrityError:  # created by a concurrent request
        await db.rollback()
    return await _get_period(db, company.id, year, quarter)


async def load_periods(db: AsyncSession, company: AACompany, year: int, quarter: int) -> list[PeriodData]:
    docs = (await db.execute(select(AADocument).where(
        AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
        AADocument.period_year.is_not(None), _docs_up_to(year, quarter),
    ))).scalars().all()
    rows = (await db.execute(select(AAPeriod).where(AAPeriod.company_id == company.id))).scalars().all()
    lines: dict[tuple[int, int], list[DocLine]] = {}
    for doc in docs:
        lines.setdefault((doc.period_year, doc.period_quarter), []).append(doc_line(doc))
    inputs = {(p.year, p.quarter): inputs_from_json(p.inputs) for p in rows}
    keys = sorted({k for k in set(lines) | set(inputs) if k <= (year, quarter)} | {(year, quarter)})
    return [
        PeriodData(y, q, tuple(sorted(lines.get((y, q), []), key=lambda l: (l.doc_date or date.min, l.id))),
                   inputs.get((y, q), PeriodInputs()))
        for y, q in keys
    ]


async def _is_stale(db: AsyncSession, company_id: uuid.UUID, year: int, quarter: int, generated_at: datetime) -> bool:
    doc_change = (await db.execute(select(func.max(func.greatest(
        AADocument.created_at, AADocument.updated_at, func.coalesce(AADocument.deleted_at, AADocument.created_at)
    ))).where(AADocument.company_id == company_id, AADocument.period_year.is_not(None),
              _docs_up_to(year, quarter)))).scalar()
    input_change = (await db.execute(select(func.max(AAPeriod.inputs_updated_at)).where(
        AAPeriod.company_id == company_id,
        or_(AAPeriod.year < year, and_(AAPeriod.year == year, AAPeriod.quarter <= quarter)),
    ))).scalar()
    return any(t is not None and t > generated_at for t in (doc_change, input_change))


async def _period_out(db: AsyncSession, company: AACompany, year: int, quarter: int) -> PeriodOut:
    period = await _get_period(db, company.id, year, quarter)
    outputs = (await db.execute(select(AAOutput).where(AAOutput.period_id == period.id)
                                .order_by(AAOutput.version.desc()))).scalars().all() if period else []
    document_count, open_reviews = (await db.execute(select(
        func.count(AADocument.id),
        func.count(AADocument.id).filter(AADocument.needs_review.is_(True), AADocument.reviewed.is_(False)),
    ).where(AADocument.company_id == company.id, AADocument.deleted_at.is_(None), AADocument.excluded.is_(False),
            AADocument.period_year == year, AADocument.period_quarter == quarter))).one()
    latest = outputs[0] if outputs else None
    forms = expected_forms(company_facts(company), quarter)
    return PeriodOut(
        company=CompanyBrief.model_validate(company), year=year, quarter=quarter,
        label=period_label(year, quarter, company),
        inputs=PeriodInputsModel(**inputs_to_json(inputs_from_json(period.inputs if period else {}))),
        filed_at=period.filed_at if period else None, document_count=document_count, open_reviews=open_reviews,
        latest_version=latest.version if latest else None,
        stale=bool(latest) and await _is_stale(db, company.id, year, quarter, latest.created_at),
        forms_expected=forms, due_dates=due_dates(forms, year, quarter, company.fiscal_year_end_month),
        outputs=[OutputBrief(id=o.id, version=o.version, created_at=o.created_at, review_open=o.review_open,
                             changes=count_changes(o.diff), amended=o.amended) for o in outputs],
    )


def output_out(output: AAOutput, period: AAPeriod, company: AACompany) -> OutputOut:
    changes = (output.diff or {}).get("forms", {})
    forms: list[FormOut] = []
    for form in FORM_ORDER:
        values = output.snapshot["forms"].get(form)
        if values is None:
            continue
        changed = changes.get(form, {})
        items = [ItemOut(key=key, label=label, value=values[key], changed=key in changed,
                         before=changed[key][0] if key in changed else None)
                 for key, label in form_items(form, values)]
        forms.append(FormOut(form=form, title=FORM_TITLES[form], items=items, pdf=form in PDF_FORMS,
                             payable_item=PAYABLE_ITEM.get(form)))
    return OutputOut(
        id=output.id, company_id=company.id, year=period.year, quarter=period.quarter,
        label=period_label(period.year, period.quarter, company), version=output.version,
        parent_version=output.parent_version, created_at=output.created_at, review_open=output.review_open,
        amended=output.amended, changes=count_changes(output.diff), warnings=list(output.warnings or []),
        forms=forms, ledgers={name: len(rows) for name, rows in output.snapshot["ledgers"].items()},
    )


@router.get("/periods/{company_id}/{year}/{quarter}", response_model=PeriodOut)
async def get_period(
    company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    company = await company_or_404(db, scope_for(user), company_id)
    return await _period_out(db, company, year, quarter)


@router.put("/periods/{company_id}/{year}/{quarter}/inputs", response_model=PeriodOut)
async def save_period_inputs(
    body: PeriodInputsModel, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
    quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    period.inputs = inputs_to_json(inputs_from_json(body.model_dump(mode="json")))
    period.inputs_updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await _period_out(db, company, year, quarter)


@router.put("/periods/{company_id}/{year}/{quarter}/filed", response_model=PeriodOut)
async def set_period_filed(
    body: FiledIn, company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100),
    quarter: int = PathParam(ge=1, le=4), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    period.filed_at = datetime.now(timezone.utc) if body.filed else None
    await db.commit()
    return await _period_out(db, company, year, quarter)


@router.post("/periods/{company_id}/{year}/{quarter}/generate", response_model=OutputOut,
             status_code=status.HTTP_201_CREATED)
async def generate_output(
    company_id: uuid.UUID, year: int = PathParam(ge=2000, le=2100), quarter: int = PathParam(ge=1, le=4),
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    ent = scope_for(user)
    company = await company_or_404(db, ent, company_id)
    period = await _ensure_period(db, ent, company, year, quarter)
    facts = company_facts(company)
    result = build_quarter(facts, await load_periods(db, company, year, quarter))
    snap = snapshot(result, facts)
    previous = (await db.execute(select(AAOutput).where(AAOutput.period_id == period.id)
                                 .order_by(AAOutput.version.desc()).limit(1))).scalar_one_or_none()
    diff = diff_snapshots(previous.snapshot, snap) if previous else None
    version = previous.version + 1 if previous else 1
    parent = previous.version if previous else None

    out_dir = Path(settings.accounting_root) / "accounting" / "outputs" / str(company.id) / f"{year}Q{quarter}"
    stamp = uuid.uuid4().hex[:8]  # unique names: a losing concurrent request never touches the winner's files
    highlighted, clean = out_dir / f"v{version}-{stamp}.xlsx", out_dir / f"v{version}-{stamp}-clean.xlsx"
    tin = company.tin
    header = {
        "company": company.registered_name,
        "tin": f"{tin[:3]}-{tin[3:6]}-{tin[6:9]}-{company.branch_code}",
        "period": period_label(year, quarter, company),
        "generated": datetime.now(_MANILA).strftime("%Y-%m-%d %H:%M"),
    }
    due = {form: day.isoformat()
           for form, day in due_dates(list(snap["forms"]), year, quarter, company.fiscal_year_end_month).items()}

    def _write() -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        common = dict(header=header, snapshot=snap, warnings=result.warnings, review_open=result.review_open,
                      due=due, version=version, diff=diff, parent_version=parent)
        write_workbook(highlighted, **common)
        write_workbook(clean, clean=True, **common)

    await asyncio.get_running_loop().run_in_executor(None, _write)
    output = AAOutput(
        enterprise_id=ent, company_id=company.id, period_id=period.id, version=version, parent_version=parent,
        snapshot=snap, diff=diff, warnings=result.warnings, review_open=result.review_open,
        amended=period.filed_at is not None, xlsx_path=str(highlighted), xlsx_clean_path=str(clean),
        created_by=user.id,
    )
    db.add(output)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        highlighted.unlink(missing_ok=True)
        clean.unlink(missing_ok=True)
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Another version was generated at the same moment. Refresh and try again.")
    return output_out(output, period, company)


async def _output_context(db: AsyncSession, user: User, output_id: uuid.UUID):
    ent = scope_for(user)
    output = (await db.execute(select(AAOutput).where(AAOutput.id == output_id, AAOutput.enterprise_id == ent)
                               )).scalar_one_or_none()
    if output is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output not found")
    period = await db.get(AAPeriod, output.period_id)
    company = await company_or_404(db, ent, output.company_id)
    return output, period, company


def _file_name(company: AACompany, period: AAPeriod, output: AAOutput, what: str, clean: bool, ext: str) -> str:
    name = re.sub(r"[^A-Za-z0-9 ._-]+", "", company.registered_name).strip() or "company"
    return f"{name} {period.year} Q{period.quarter} {what} v{output.version}{' clean' if clean else ''}.{ext}"


@router.get("/outputs/{output_id}", response_model=OutputOut)
async def get_output(output_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    return output_out(output, period, company)


@router.get("/outputs/{output_id}/xlsx")
async def download_workbook(output_id: uuid.UUID, clean: bool = Query(default=False),
                            user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    path = Path(output.xlsx_clean_path if clean else output.xlsx_path)
    if not is_stored_path_safe(str(path)) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workbook file not found")
    data = await asyncio.get_running_loop().run_in_executor(None, path.read_bytes)
    name = _file_name(company, period, output, "workbook", clean, "xlsx")
    return Response(content=data, media_type=_XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/outputs/{output_id}/pdf")
async def download_pdf(output_id: uuid.UUID, form: str = Query(...), clean: bool = Query(default=False),
                       user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    output, period, company = await _output_context(db, user, output_id)
    if form not in PDF_FORMS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A PDF for this form comes in a later phase")
    values = output.snapshot["forms"].get(form)
    if values is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"This version has no {form}")
    c = output.snapshot["company"]
    fye = c["fiscal_year_end_month"]
    header = Header2550Q(
        tin=c["tin"], rdo_code=c["rdo_code"], name=c["registered_name"], address=c["address"],
        zip_code=c["zip_code"], fiscal_year_end_month=fye, fiscal_year=period.year, quarter=period.quarter,
        period_from=quarter_start(period.year, period.quarter, fye),
        period_to=quarter_end(period.year, period.quarter, fye),
    )
    highlights = frozenset() if clean else frozenset((output.diff or {}).get("forms", {}).get(form, {}))
    data = await asyncio.get_running_loop().run_in_executor(
        None, lambda: render_2550q(values, header, highlights, output.amended, output.review_open)
    )
    name = _file_name(company, period, output, form, clean, "pdf")
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
```

- [ ] **Step 7: Wire it into `routers/accounting.py`**

(a) Add imports (merge with existing lines):

```python
from app.models.accounting import AAOutput, AAPeriod
from app.routers import accounting_periods
from app.schemas.accounting import AffectedPeriodOut
from app.services.accounting.tree import stale_periods
```

(b) At the very end of the file:

```python
router.include_router(accounting_periods.router)
```

(c) Add this helper above `get_tree`:

```python
def _quarter_status(outputs, filed, doc_changes, input_changes) -> dict:
    """(company_id, year, quarter) -> latest_version / stale / filed for the folder tree."""
    changes: dict[str, dict] = {}
    for company_id, year, quarter, at in [*doc_changes, *input_changes]:
        if at is None:
            continue
        per_company = changes.setdefault(str(company_id), {})
        per_company[(year, quarter)] = max(per_company.get((year, quarter), at), at)
    generated: dict[str, dict] = {}
    versions: dict[tuple[str, int, int], int] = {}
    for company_id, year, quarter, version, at in outputs:
        generated.setdefault(str(company_id), {})[(year, quarter)] = at
        versions[(str(company_id), year, quarter)] = version
    status_map: dict[tuple[str, int, int], dict] = {}
    for company_id, periods in generated.items():
        stale = stale_periods(changes.get(company_id, {}), periods)
        for year, quarter in periods:
            key = (company_id, year, quarter)
            status_map[key] = {"latest_version": versions[key], "stale": (year, quarter) in stale,
                               "filed": key in filed}
    for key in filed:
        status_map.setdefault(key, {"latest_version": None, "stale": False, "filed": True})
    return status_map
```

(d) In `get_tree`, before `return build_tree(...)`, add the four queries and pass the status:

```python
    outputs = (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, func.max(AAOutput.version),
               func.max(AAOutput.created_at))
        .join(AAOutput, AAOutput.period_id == AAPeriod.id)
        .where(AAPeriod.enterprise_id == ent)
        .group_by(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter)
    )).all()
    filed = {(str(c), y, q) for c, y, q in (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter)
        .where(AAPeriod.enterprise_id == ent, AAPeriod.filed_at.is_not(None))
    )).all()}
    doc_changes = (await db.execute(
        select(AADocument.company_id, AADocument.period_year, AADocument.period_quarter,
               func.max(func.greatest(AADocument.created_at, AADocument.updated_at,
                                      func.coalesce(AADocument.deleted_at, AADocument.created_at))))
        .where(AADocument.enterprise_id == ent, AADocument.period_year.is_not(None))
        .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
    )).all()
    input_changes = (await db.execute(
        select(AAPeriod.company_id, AAPeriod.year, AAPeriod.quarter, AAPeriod.inputs_updated_at)
        .where(AAPeriod.enterprise_id == ent, AAPeriod.inputs_updated_at.is_not(None))
    )).all()
    status_map = _quarter_status(outputs, filed, doc_changes, input_changes)
    return build_tree(inputs, [tuple(r) for r in rows], status_map)
```

(e) In `_upload_out`, before `return UploadOut(...)`, compute the quarters that already had outputs and pass `affected_periods=affected`:

```python
    affected: list[AffectedPeriodOut] = []
    if upload.status == "done":
        landed = (await db.execute(
            select(AADocument.company_id, AADocument.period_year, AADocument.period_quarter, func.count(AADocument.id))
            .join(AAFile, AAFile.id == AADocument.file_id)
            .where(AAFile.upload_id == upload_id, AADocument.deleted_at.is_(None),
                   AADocument.period_year.is_not(None))
            .group_by(AADocument.company_id, AADocument.period_year, AADocument.period_quarter)
        )).all()
        for company_id, year, quarter, count in landed:
            period = (await db.execute(select(AAPeriod).where(
                AAPeriod.company_id == company_id, AAPeriod.year == year, AAPeriod.quarter == quarter
            ))).scalar_one_or_none()
            if period is None:
                continue
            latest = (await db.execute(select(func.max(AAOutput.version))
                                       .where(AAOutput.period_id == period.id))).scalar()
            if latest is None:
                continue
            company = await db.get(AACompany, company_id)
            affected.append(AffectedPeriodOut(
                company_id=company_id, company_name=company.registered_name, year=year, quarter=quarter,
                label=f"{year} · {quarter_label(quarter, company.fiscal_year_end_month)}",
                latest_version=latest, filed=period.filed_at is not None, new_documents=count,
            ))
```

(`quarter_label` is already imported in `routers/accounting.py`.)

- [ ] **Step 8: Verify live (no Gemini needed — Phase 1 documents exist in dev)**

```bash
docker compose restart backend && sleep 12 && docker compose logs --since 20s backend 2>&1 | grep -iE "traceback|startup complete"
docker compose exec -T backend python -m pytest -q 2>&1 | tail -1
```
Expected: startup complete, suite green.

Mint a local dev token for the enterprise user (as in Phase 1 verification) and call, for Juan's Cloth Trading 2026 Q3 (`C` = its company id):
```bash
T=<dev token>; B=http://localhost:8000/api/accounting; A=(-s -A dev-check -H "Authorization: Bearer $T")
curl "${A[@]}" $B/periods/$C/2026/3 | python3 -m json.tool | head -40
curl "${A[@]}" -X PUT -H 'Content-Type: application/json' -d '{"opening_inventory":"0","ending_inventory":"5000","vat_withheld":"0"}' $B/periods/$C/2026/3/inputs | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['inputs']['ending_inventory'], d['stale'])"
curl "${A[@]}" -X POST $B/periods/$C/2026/3/generate | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['version'], [f['form'] for f in d['forms']], d['warnings'])"
```
Expected: v1 with forms `['2550Q', '1702Q', 'COGS', 'Expenses']`. Cross-check 2550-Q against SQL — `31A` must equal `select sum(vatable_amount) from aa_documents where company_id='$C' and period_year=2026 and period_quarter=3 and category='sales' and deleted_at is null and not excluded`, and `44B` the sum of `vat_amount` over non-import purchases/expenses with `input_vat_valid`.
Download both XLSX files and the PDF (`?form=2550Q`), open them (`openpyxl` / Read tool on a PNG render) and confirm values. Then PATCH one document's amount, check `GET /periods/…` shows `stale: true`, generate v2, and confirm the workbook highlights exactly the changed cells and the PDF shows the yellow boxes.

- [ ] **Step 9: Commit**

```bash
git add backend/app/routers/accounting_scope.py backend/app/routers/accounting_periods.py backend/app/routers/accounting.py backend/app/schemas/accounting.py backend/app/services/accounting/compute/engine.py backend/tests/test_accounting_schemas.py backend/tests/test_aa_engine.py
git commit -m "feat(accounting): quarter inputs, versioned generation, workbook/PDF downloads, tree status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Frontend — quarter panel, output viewer, append prompt, tree chips

**Files:**
- Modify: `frontend/src/types/accounting.ts`, `frontend/src/lib/accounting-api.ts`, `frontend/src/lib/accounting-format.ts`, `frontend/src/components/accounting/FolderTree.tsx`, `frontend/src/app/accounting/page.tsx`
- Create: `frontend/src/components/accounting/PeriodPanel.tsx`, `OutputViewer.tsx`, `AppendPrompt.tsx`

**Interfaces:**
- Consumes: Task 9 HTTP API.
- Produces: TS types `PeriodInputs`, `Period`, `OutputBrief`, `OutputItem`, `OutputForm`, `Output`, `AffectedPeriod`; `TreeQuarter` + `latest_version/stale/filed`; `Upload.affected_periods`; API methods `period`, `savePeriodInputs`, `setFiled`, `generate`, `output`, `outputFile`; helpers `saveBlob`, `formatAmount`; components `<PeriodPanel companyId year quarter refreshKey onChanged />`, `<OutputViewer outputId />`, `<AppendPrompt periods onGenerate onReview onClose />`.

- [ ] **Step 1: Types** — append to `frontend/src/types/accounting.ts`:

```ts
export interface PeriodInputs {
  ending_inventory: string | null;
  opening_inventory: string | null;
  opening_excess_input_vat: string;
  vat_withheld: string;
  advance_vat: string;
  percentage_tax_withheld: string;
  non_operating_income: string;
  prior_year_excess_credits: string;
  prior_taxable_income: string | null;
  prior_tax_paid: string | null;
  prior_cwt: string | null;
  cit_rate: 20 | 25;
  mcit_applies: boolean;
}

export interface OutputBrief {
  id: string;
  version: number;
  created_at: string;
  review_open: number;
  changes: number;
  amended: boolean;
}

export interface Period {
  company: CompanyBrief;
  year: number;
  quarter: number;
  label: string;
  inputs: PeriodInputs;
  filed_at: string | null;
  document_count: number;
  open_reviews: number;
  latest_version: number | null;
  stale: boolean;
  forms_expected: string[];
  due_dates: Record<string, string>;
  outputs: OutputBrief[];
}

export interface OutputItem {
  key: string;
  label: string;
  value: string;
  changed: boolean;
  before: string | null;
}

export interface OutputForm {
  form: string;
  title: string;
  items: OutputItem[];
  pdf: boolean;
  payable_item: string | null;
}

export interface Output {
  id: string;
  company_id: string;
  year: number;
  quarter: number;
  label: string;
  version: number;
  parent_version: number | null;
  created_at: string;
  review_open: number;
  amended: boolean;
  changes: number;
  warnings: string[];
  forms: OutputForm[];
  ledgers: Record<string, number>;
}

export interface AffectedPeriod {
  company_id: string;
  company_name: string;
  year: number;
  quarter: number;
  label: string;
  latest_version: number;
  filed: boolean;
  new_documents: number;
}
```

…and add `latest_version: number | null; stale: boolean; filed: boolean;` to `TreeQuarter` and `affected_periods: AffectedPeriod[];` to `Upload`.

- [ ] **Step 2: API + helpers**

Add `Output`, `Period`, `PeriodInputs` to the type import in `frontend/src/lib/accounting-api.ts` and these methods to `accountingApi`:

```ts
  period: (companyId: string, year: number, quarter: number) =>
    api.get<Period>(`/accounting/periods/${companyId}/${year}/${quarter}`).then((r) => r.data),
  savePeriodInputs: (companyId: string, year: number, quarter: number, inputs: PeriodInputs) =>
    api.put<Period>(`/accounting/periods/${companyId}/${year}/${quarter}/inputs`, inputs).then((r) => r.data),
  setFiled: (companyId: string, year: number, quarter: number, filed: boolean) =>
    api.put<Period>(`/accounting/periods/${companyId}/${year}/${quarter}/filed`, { filed }).then((r) => r.data),
  generate: (companyId: string, year: number, quarter: number) =>
    api.post<Output>(`/accounting/periods/${companyId}/${year}/${quarter}/generate`).then((r) => r.data),
  output: (id: string) => api.get<Output>(`/accounting/outputs/${id}`).then((r) => r.data),
  outputFile: (id: string, kind: "xlsx" | "pdf", opts: { clean?: boolean; form?: string } = {}) =>
    api
      .get<Blob>(`/accounting/outputs/${id}/${kind}`, {
        params: { clean: opts.clean ?? false, ...(opts.form ? { form: opts.form } : {}) },
        responseType: "blob",
      })
      .then((r) => r.data),
```

Append to `frontend/src/lib/accounting-format.ts`:

```ts
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Money for display: thousands separators, negatives in parentheses like the BIR forms. */
export function formatAmount(value: string, whole = false): string {
  const n = Number(value);
  if (value === "" || !Number.isFinite(n)) return value;
  const digits = whole ? 0 : 2;
  const text = Math.abs(n).toLocaleString("en-PH", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return n < 0 ? `(${text})` : text;
}

/** Pastel yellow used for "changed since the previous version" everywhere. */
export const CHANGED_STYLE = { backgroundColor: "#FFF4B3", color: "#1F1F1F" } as const;
```

- [ ] **Step 3: `frontend/src/components/accounting/OutputViewer.tsx`**

```tsx
"use client";

import { useEffect, useState } from "react";
import { DownloadSimple, FilePdf } from "@phosphor-icons/react";
import { accountingApi } from "@/lib/accounting-api";
import { CHANGED_STYLE, apiErrorMessage, formatAmount, saveBlob } from "@/lib/accounting-format";
import type { Output } from "@/types/accounting";

const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const WHOLE = new Set(["1701Q", "1702Q"]);

export default function OutputViewer({ outputId }: { outputId: string }) {
  const [output, setOutput] = useState<Output | null>(null);
  const [tab, setTab] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setOutput(null);
    setError("");
    accountingApi
      .output(outputId)
      .then((o) => {
        if (cancelled) return;
        setOutput(o);
        setTab(o.forms[0]?.form ?? null);
      })
      .catch((e) => {
        if (!cancelled) setError(apiErrorMessage(e, "Couldn't load this version"));
      });
    return () => {
      cancelled = true;
    };
  }, [outputId]);

  async function download(kind: "xlsx" | "pdf", clean: boolean, form?: string) {
    if (!output) return;
    const id = `${kind}-${clean}-${form ?? ""}`;
    setBusy(id);
    setError("");
    try {
      const blob = await accountingApi.outputFile(output.id, kind, { clean, form });
      const what = form ?? "workbook";
      saveBlob(blob, `${output.label} ${what} v${output.version}${clean ? " clean" : ""}.${kind}`);
    } catch (e) {
      setError(apiErrorMessage(e, "Download failed"));
    } finally {
      setBusy(null);
    }
  }

  if (error && !output) return <p className="text-sm text-[var(--alert-error-text)]">{error}</p>;
  if (!output) return <div className="h-24 animate-pulse rounded-lg bg-[var(--bg-primary)]" />;
  const current = output.forms.find((f) => f.form === tab) ?? null;

  return (
    <div className="rounded-lg border border-[var(--border)] p-3">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold text-[var(--text-primary)]">v{output.version}</span>
        {output.parent_version && (
          <span className="rounded px-1.5 text-xs" style={output.changes ? CHANGED_STYLE : undefined}>
            {output.changes} change{output.changes === 1 ? "" : "s"} since v{output.parent_version}
          </span>
        )}
        {output.review_open > 0 && (
          <span className="rounded-full bg-[var(--badge-yellow-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-yellow-text)]">DRAFT</span>
        )}
        {output.amended && (
          <span className="rounded-full bg-[var(--badge-blue-bg)] px-2 py-0.5 text-xs font-medium text-[var(--badge-blue-text)]">Amended</span>
        )}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className={BTN} disabled={busy !== null} onClick={() => download("xlsx", false)}>
            <DownloadSimple size={16} /> Workbook
          </button>
          <button className={BTN} disabled={busy !== null} onClick={() => download("xlsx", true)}>
            Clean copy
          </button>
        </div>
      </div>

      {output.warnings.length > 0 && (
        <ul className="mb-3 space-y-1 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] p-3 text-sm text-[var(--alert-warning-text)]">
          {output.warnings.map((w) => (
            <li key={w}>• {w}</li>
          ))}
        </ul>
      )}

      <div className="mb-2 flex flex-wrap gap-1.5">
        {output.forms.map((f) => (
          <button
            key={f.form}
            onClick={() => setTab(f.form)}
            className={`rounded-md px-2.5 py-1 text-xs font-medium ${f.form === tab ? "bg-[var(--accent-subtle)] text-[var(--text-primary)]" : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
          >
            {f.form}
            {f.items.some((i) => i.changed) && <span className="ml-1 inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: "#E5C200" }} />}
          </button>
        ))}
      </div>

      {current && (
        <>
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium text-[var(--text-primary)]">{current.title}</p>
            {current.pdf && (
              <div className="ml-auto flex gap-2">
                <button className={BTN} disabled={busy !== null} onClick={() => download("pdf", false, current.form)}>
                  <FilePdf size={16} /> Generate PDF
                </button>
                <button className={BTN} disabled={busy !== null} onClick={() => download("pdf", true, current.form)}>
                  Clean PDF
                </button>
              </div>
            )}
          </div>
          <div className="max-h-[420px] overflow-y-auto">
            <table className="w-full text-sm">
              <tbody>
                {current.items.map((item) => (
                  <tr
                    key={item.key}
                    className="border-t border-[var(--border)] text-[var(--text-primary)]"
                    style={item.changed ? CHANGED_STYLE : undefined}
                    title={item.changed ? `Was ${item.before ? formatAmount(item.before, WHOLE.has(current.form)) : "blank"}` : undefined}
                  >
                    <td className={`py-1.5 pr-3 ${item.key === current.payable_item ? "font-semibold" : ""}`}>{item.label}</td>
                    <td className={`py-1.5 text-right tabular-nums ${item.key === current.payable_item ? "font-semibold" : ""}`}>
                      {formatAmount(item.value, WHOLE.has(current.form))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <p className="mt-3 text-xs text-[var(--text-secondary)]">
        In the workbook:{" "}
        {Object.entries(output.ledgers)
          .map(([name, n]) => `${name} (${n} row${n === 1 ? "" : "s"})`)
          .join(" · ")}
      </p>
      {error && <p className="mt-2 text-sm text-[var(--alert-error-text)]">{error}</p>}
    </div>
  );
}
```

- [ ] **Step 4: `frontend/src/components/accounting/PeriodPanel.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import { CaretDown, CaretRight, FileXls, Spinner } from "@phosphor-icons/react";
import OutputViewer from "@/components/accounting/OutputViewer";
import { accountingApi } from "@/lib/accounting-api";
import { apiErrorMessage } from "@/lib/accounting-format";
import type { Period, PeriodInputs } from "@/types/accounting";

type FieldKey = Exclude<keyof PeriodInputs, "cit_rate" | "mcit_applies">;
interface Field {
  key: FieldKey;
  label: string;
  hint: string;
  optional?: boolean;
  show: (p: Period) => boolean;
}

const always = () => true;
const vat = (p: Period) => p.forms_expected.includes("2550Q");
const FIELDS: Field[] = [
  { key: "ending_inventory", label: "Ending inventory", hint: "Stock on hand at quarter end", optional: true, show: always },
  { key: "opening_inventory", label: "Opening inventory", hint: "First quarter on AutoAccounting only", optional: true, show: always },
  { key: "opening_excess_input_vat", label: "Excess input VAT carried in", hint: "First quarter only — excess from the last return filed", show: vat },
  { key: "vat_withheld", label: "VAT withheld (2307, ATC WV…)", hint: "2550-Q item 16", show: vat },
  { key: "advance_vat", label: "Advance VAT payments", hint: "2550-Q item 17", show: vat },
  { key: "percentage_tax_withheld", label: "Percentage tax withheld", hint: "2551-Q item 15", show: (p) => p.forms_expected.includes("2551Q") },
  { key: "non_operating_income", label: "Non-operating income", hint: "Interest, gains and other income this quarter", show: always },
  { key: "prior_year_excess_credits", label: "Prior year's excess credits", hint: "Income tax credit carried from last year", show: always },
  { key: "prior_taxable_income", label: "Earlier quarters: taxable income", hint: "Only if earlier quarters were filed outside AutoAccounting", optional: true, show: (p) => p.quarter > 1 },
  { key: "prior_tax_paid", label: "Earlier quarters: tax paid", hint: "", optional: true, show: (p) => p.quarter > 1 },
  { key: "prior_cwt", label: "Earlier quarters: tax withheld (2307)", hint: "", optional: true, show: (p) => p.quarter > 1 },
];

const CHIP = {
  filed: "bg-[var(--badge-green-bg)] text-[var(--badge-green-text)]",
  stale: "bg-[var(--badge-yellow-bg)] text-[var(--badge-yellow-text)]",
  generated: "bg-[var(--badge-blue-bg)] text-[var(--badge-blue-text)]",
  collecting: "bg-[var(--bg-primary)] text-[var(--text-secondary)]",
};
const INPUT = "w-full px-2.5 py-1.5 rounded-md border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent)]";
const BTN = "inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)] disabled:opacity-60";
const PRIMARY = "inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60";

interface Props {
  companyId: string;
  year: number;
  quarter: number;
  refreshKey: number;
  onChanged: () => void;
}

export default function PeriodPanel({ companyId, year, quarter, refreshKey, onChanged }: Props) {
  const [period, setPeriod] = useState<Period | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [citRate, setCitRate] = useState<20 | 25>(25);
  const [mcit, setMcit] = useState(false);
  const [showInputs, setShowInputs] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const apply = useCallback((p: Period) => {
    setPeriod(p);
    const next: Record<string, string> = {};
    for (const f of FIELDS) next[f.key] = p.inputs[f.key] ?? "";
    setDraft(next);
    setCitRate(p.inputs.cit_rate);
    setMcit(p.inputs.mcit_applies);
    setSelected((current) => (current && p.outputs.some((o) => o.id === current) ? current : p.outputs[0]?.id ?? null));
  }, []);

  useEffect(() => {
    setError("");
    accountingApi.period(companyId, year, quarter).then(apply).catch((e) => setError(apiErrorMessage(e, "Couldn't load this quarter")));
  }, [companyId, year, quarter, refreshKey, apply]);

  async function act(task: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(apiErrorMessage(e, fallback));
    } finally {
      setBusy(false);
    }
  }

  const saveInputs = () =>
    act(async () => {
      const inputs: Record<string, string | number | boolean | null> = { cit_rate: citRate, mcit_applies: mcit };
      for (const f of FIELDS) {
        const value = (draft[f.key] ?? "").replace(/,/g, "").trim();
        inputs[f.key] = value === "" ? (f.optional ? null : "0") : value;
      }
      apply(await accountingApi.savePeriodInputs(companyId, year, quarter, inputs as unknown as PeriodInputs));
      onChanged();
    }, "Couldn't save the inputs");

  const generate = () =>
    act(async () => {
      const output = await accountingApi.generate(companyId, year, quarter);
      setSelected(output.id);
      apply(await accountingApi.period(companyId, year, quarter));
      onChanged();
    }, "Couldn't generate the returns");

  const toggleFiled = () =>
    act(async () => {
      apply(await accountingApi.setFiled(companyId, year, quarter, !period?.filed_at));
      onChanged();
    }, "Couldn't update the filed status");

  if (!period) return error ? <p className="mb-4 text-sm text-[var(--alert-error-text)]">{error}</p> : null;

  const next = (period.latest_version ?? 0) + 1;
  const chip = period.filed_at
    ? { text: "Filed", cls: CHIP.filed }
    : period.stale
      ? { text: `Stale — new changes since v${period.latest_version}`, cls: CHIP.stale }
      : period.latest_version
        ? { text: `Generated v${period.latest_version}`, cls: CHIP.generated }
        : { text: "Collecting", cls: CHIP.collecting };
  const due = Object.entries(period.due_dates)
    .map(([form, day]) => `${form} due ${new Date(`${day}T00:00:00`).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}`)
    .join(" · ");
  const corporate = period.forms_expected.includes("1702Q");

  return (
    <div className="mb-5 rounded-xl border border-[var(--border)] p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${chip.cls}`}>{chip.text}</span>
        {due && <span className="text-xs text-[var(--text-secondary)]">{due}</span>}
        <div className="ml-auto flex flex-wrap gap-2">
          <button className={BTN} onClick={() => setShowInputs((s) => !s)}>
            {showInputs ? <CaretDown size={14} /> : <CaretRight size={14} />} Quarter inputs
          </button>
          {period.latest_version && (
            <button className={BTN} disabled={busy} onClick={toggleFiled}>
              {period.filed_at ? "Unmark filed" : "Mark as filed"}
            </button>
          )}
          <button className={PRIMARY} disabled={busy} onClick={generate}>
            {busy ? <Spinner size={16} className="animate-spin" /> : <FileXls size={16} />} Generate v{next}
          </button>
        </div>
      </div>

      {period.open_reviews > 0 && (
        <p className="mt-2 text-xs text-[var(--alert-warning-text)]">
          {period.open_reviews} document(s) still need review — new versions will be marked DRAFT.
        </p>
      )}
      {period.filed_at && (
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Marked filed on {new Date(period.filed_at).toLocaleDateString("en-PH")}. A new version will be an amended return.
        </p>
      )}

      {showInputs && (
        <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {FIELDS.filter((f) => f.show(period)).map((f) => (
              <label key={f.key} className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">{f.label}</span>
                <input
                  inputMode="decimal"
                  className={INPUT}
                  value={draft[f.key] ?? ""}
                  placeholder={f.optional ? "Not provided" : "0.00"}
                  onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
                />
                {f.hint && <span className="mt-0.5 block text-[11px] text-[var(--text-secondary)]">{f.hint}</span>}
              </label>
            ))}
            {corporate && (
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-[var(--text-secondary)]">Corporate income tax rate</span>
                <select className={INPUT} value={citRate} onChange={(e) => setCitRate(Number(e.target.value) as 20 | 25)}>
                  <option value={25}>25% (regular)</option>
                  <option value={20}>20% (net taxable income ≤ ₱5M and assets ≤ ₱100M)</option>
                </select>
              </label>
            )}
            {corporate && (
              <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                <input type="checkbox" checked={mcit} onChange={(e) => setMcit(e.target.checked)} />
                MCIT applies (4th year of operations onwards)
              </label>
            )}
          </div>
          <div className="mt-3 flex justify-end">
            <button className={PRIMARY} disabled={busy} onClick={saveInputs}>Save inputs</button>
          </div>
        </div>
      )}

      {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}

      {period.outputs.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {period.outputs.map((o) => (
              <button
                key={o.id}
                onClick={() => setSelected(o.id)}
                className={`rounded-md border px-2.5 py-1 text-xs ${o.id === selected ? "border-[var(--accent)] text-[var(--text-primary)]" : "border-[var(--border)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"}`}
              >
                v{o.version} · {new Date(o.created_at).toLocaleDateString("en-PH", { month: "short", day: "numeric" })}
                {o.version > 1 && ` · ${o.changes} change${o.changes === 1 ? "" : "s"}`}
                {o.review_open > 0 && " · DRAFT"}
                {o.amended && " · amended"}
              </button>
            ))}
          </div>
          {selected && <OutputViewer outputId={selected} />}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: `frontend/src/components/accounting/AppendPrompt.tsx`**

```tsx
"use client";

import { useState } from "react";
import { CheckCircle, X } from "@phosphor-icons/react";
import { CHANGED_STYLE, apiErrorMessage } from "@/lib/accounting-format";
import type { AffectedPeriod } from "@/types/accounting";

interface Props {
  periods: AffectedPeriod[];
  onGenerate: (period: AffectedPeriod) => Promise<void>;
  onReview: (period: AffectedPeriod) => void;
  onClose: () => void;
}

const keyOf = (p: AffectedPeriod) => `${p.company_id}:${p.year}:${p.quarter}`;

export default function AppendPrompt({ periods, onGenerate, onReview, onClose }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  async function add(p: AffectedPeriod) {
    setBusy(keyOf(p));
    setError("");
    try {
      await onGenerate(p);
      setDone((prev) => new Set(prev).add(keyOf(p)));
    } catch (e) {
      setError(apiErrorMessage(e, "Couldn't create the new version"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">Add to an existing quarter?</h2>
          <button onClick={onClose} className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]" aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="space-y-4">
          {periods.map((p) => {
            const next = p.latest_version + 1;
            const finished = done.has(keyOf(p));
            return (
              <div key={keyOf(p)} className="rounded-xl border border-[var(--border)] p-4 text-sm text-[var(--text-primary)]">
                <p className="font-semibold">Add to {p.company_name} — {p.label}?</p>
                <p className="mt-1">
                  This quarter already has output <strong>v{p.latest_version}</strong>. {p.new_documents} new document
                  {p.new_documents === 1 ? "" : "s"} will be <strong>added to v{p.latest_version}</strong> and saved as{" "}
                  <strong>v{next}</strong>. Changed values will be <span className="rounded px-1" style={CHANGED_STYLE}>highlighted in yellow</span>.
                </p>
                {p.filed && (
                  <p className="mt-2 rounded-lg border border-[var(--alert-warning-border)] bg-[var(--alert-warning-bg)] px-3 py-2 text-[var(--alert-warning-text)]">
                    {p.label} was marked filed. v{next} will be an amended return (the Amended Return box will be ticked).
                  </p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  {finished ? (
                    <span className="flex items-center gap-1.5 font-medium text-[var(--accent)]">
                      <CheckCircle size={16} weight="fill" /> Saved as v{next}
                    </span>
                  ) : (
                    <>
                      <button
                        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 font-medium text-white hover:bg-[var(--accent-hover)] disabled:opacity-60"
                        disabled={busy !== null}
                        onClick={() => add(p)}
                      >
                        {busy === keyOf(p) ? "Creating…" : `Add and create v${next}`}
                      </button>
                      <button
                        className="rounded-lg border border-[var(--border)] px-3 py-1.5 font-medium hover:bg-[var(--bg-hover)]"
                        onClick={() => onReview(p)}
                      >
                        Review files first
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
        {error && <p className="mt-3 text-sm text-[var(--alert-error-text)]">{error}</p>}
        <div className="mt-5 flex justify-end">
          <button className="rounded-lg border border-[var(--border)] px-4 py-2 text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-hover)]" onClick={onClose}>
            {done.size === periods.length ? "Done" : "Cancel"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Tree chips** — in `frontend/src/components/accounting/FolderTree.tsx`, change `leaf` to take an optional status and render it after the count:

```tsx
  const leaf = (ref: FolderRef, label: string, count: number, review: number, status?: TreeQuarter) => (
```

…import `TreeQuarter` from `@/types/accounting`, and inside the button, after the review badge, add:

```tsx
      {status?.filed ? (
        <span className="rounded-full bg-[var(--badge-green-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-green-text)]">Filed</span>
      ) : status?.stale ? (
        <span className="rounded-full bg-[var(--badge-yellow-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-yellow-text)]">Stale</span>
      ) : status?.latest_version ? (
        <span className="rounded-full bg-[var(--badge-blue-bg)] px-1.5 text-[11px] font-medium text-[var(--badge-blue-text)]">v{status.latest_version}</span>
      ) : null}
```

…and pass `q` as the fifth argument where quarter leaves are rendered: `leaf({ companyId: c.id, year: q.year, quarter: q.quarter }, q.label, q.document_count, q.review_count, q)`.

- [ ] **Step 7: Page wiring** — in `frontend/src/app/accounting/page.tsx`:

(a) imports: `import PeriodPanel from "@/components/accounting/PeriodPanel";`, `import AppendPrompt from "@/components/accounting/AppendPrompt";`, and `AffectedPeriod` in the type import.

(b) state:

```tsx
  const [append, setAppend] = useState<AffectedPeriod[] | null>(null);
  const [periodRefresh, setPeriodRefresh] = useState(0);
```

(c) in the status-transition effect's `done` branch, after `setNotice(...)`:

```tsx
      if (upload.affected_periods?.length) setAppend(upload.affected_periods);
      setPeriodRefresh((n) => n + 1);
```

(d) `refreshAfterDocChange` also bumps the panel:

```tsx
  const refreshAfterDocChange = () => {
    loadFolder(selected).catch(() => undefined);
    loadTree().catch(() => undefined);
    setPeriodRefresh((n) => n + 1);
  };
```

(e) inside the `<section>`, directly above `{folder ? (<FileGrid …`:

```tsx
            {folder && folder.year !== null && folder.quarter !== null && (
              <PeriodPanel
                companyId={folder.company.id}
                year={folder.year}
                quarter={folder.quarter}
                refreshKey={periodRefresh}
                onChanged={() => loadTree().catch(() => undefined)}
              />
            )}
```

(f) before the closing `</div>` of the page root:

```tsx
      {append && (
        <AppendPrompt
          periods={append}
          onGenerate={async (p) => {
            await accountingApi.generate(p.company_id, p.year, p.quarter);
            await loadTree();
            setSelected({ companyId: p.company_id, year: p.year, quarter: p.quarter });
            setPeriodRefresh((n) => n + 1);
          }}
          onReview={(p) => {
            setAppend(null);
            setSelected({ companyId: p.company_id, year: p.year, quarter: p.quarter });
          }}
          onClose={() => setAppend(null)}
        />
      )}
```

- [ ] **Step 8: Verify**

Run: `cd frontend && npx tsc --noEmit && npx eslint src/components/accounting src/app/accounting src/lib/accounting-api.ts src/lib/accounting-format.ts src/types/accounting.ts && npm run build; git checkout -- tsconfig.tsbuildinfo`
Expected: no type or lint errors; build lists `/accounting` and `/accounting/companies`.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/types/accounting.ts frontend/src/lib/accounting-api.ts frontend/src/lib/accounting-format.ts frontend/src/components/accounting frontend/src/app/accounting/page.tsx
git commit -m "feat(accounting): quarter panel, output viewer with yellow changes, append prompt, tree status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: End-to-end verification

**Files:** none (fixes found here are committed with a ruling each).

- [ ] **Step 1:** `docker compose up --build -d frontend` and reinstall dev deps in the backend container if needed (`docker compose exec -T backend pip install -q -e ".[dev]"`). Mint a local dev token for the enterprise user and inject it in the browser as in Phase 1.
- [ ] **Step 2: Juan's Cloth Trading 2026 Q3 in the UI** — open the quarter: the panel shows "Collecting" and due dates (2550-Q Oct 26, 1702-Q Nov 30). Open *Quarter inputs*, enter opening inventory 0 and ending inventory 5,000, save. Click *Generate v1*. Check: output viewer tabs 2550Q / 1702Q / COGS / Expenses; 2550-Q item 31A equals the sum of the quarter's VATable sales and 44B the claimed input VAT (cross-check with SQL as in Task 9 Step 8); warnings list the documents still under review (DRAFT).
- [ ] **Step 3: Downloads** — *Workbook*, *Clean copy*, *Generate PDF* all download; open the XLSX (tabs, numbers, Summary due dates) and the PDF (values in boxes, quarter 3 and calendar ticked, TIN/name in cells).
- [ ] **Step 4: Append flow** — drop one more purchase invoice for Juan's dated within Q3 (Gemini quota permitting; otherwise PATCH a document amount). After it files, the "Add to Juan's Cloth Trading — 2026 · Q3 (Jul–Sep)?" prompt appears with "v1 → v2"; *Add and create v2*. In v2: exactly the affected items are yellow in the viewer with "Was …" tooltips, the workbook has yellow cells with comments and a Change log tab, the clean copy has none, and the PDF shows yellow boxes on the changed items.
- [ ] **Step 5: Filed → amended** — *Mark as filed*, change a document, generate v3: the prompt/panel says amended; the PDF ticks Amended Return = Yes; the tree shows the *Filed* chip.
- [ ] **Step 6: Other taxpayer types** — edit Maria's Bakery to non-VAT and generate its Q3: 2551-Q appears instead of 2550-Q; then individual + non-VAT + 8%: only 1701-Q (Schedule II).
- [ ] **Step 7:** Full backend suite green; frontend build green; dark mode readable. Report results.
