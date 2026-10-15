# AutoAccounting Phase 4a — Annual income tax, depreciation and NOLCO

**Date:** 2026-10-06 · **Branch:** `AutoAccounting` · **Parent spec:** AutoAccounting spec sheet (Claude Doc) https://claude.ai/code/artifact/8dcfb05b-3f3e-4410-a082-da75a391cd21. This document covers the *Rollout → Phase 4 · Annual* band, split by the user on 2026-10-06 into 4a (this spec) and 4b.

Phase 4a produces the annual income tax return for each company and fiscal year (1702-RT for corporations, 1701 or 1701-A for individuals), with the same versioned output as the quarters: snapshot, yellow diffs, workbook, filled PDF, stale detection and mark-as-filed. It adds an asset register with straight-line depreciation, used by both the quarterly and the annual income tax, and carries net operating losses (NOLCO) and excess MCIT across years.

## Decisions taken with the user (2026-10-06)

| Topic | Decision |
|---|---|
| Scope | Annual ITR + NOLCO now. 1604-C, 1604-E, SLSP DAT export and the BIR template watcher are Phase 4b. |
| Depreciation | Asset register, straight-line, built from capital-goods documents. |
| Balance sheet and reconciliation | Typed into annual inputs; blank on the PDF with a warning when not entered. |
| Q1–Q3 income tax paid | From the version marked filed for each quarter, else the latest version; overridable per quarter in the annual inputs. |
| Storage of the annual output | A year-level period (approach A): `AAPeriod` row with `quarter = 0`, shown as "Annual" in the tree. |

## Out of scope

- 1604-C, 1604-E, SLSP/QAP/SAWT DAT export, template watcher (Phase 4b).
- Compensation income on the 1701 (mixed-income earners). The 1701 / 1701-A are prepared for business income only, and every one carries a warning saying so.
- 1702-EX (exempt) and 1702-MX (mixed rates), special-rate income, and the spouse column of the 1701.
- Asset disposals, gains on sale, and methods other than straight-line.
- Audited financial statements and their attachments.

## 1. Year-level period

- An annual period is `AAPeriod(year=<fiscal year>, quarter=0)`; its outputs are ordinary `AAOutput` rows. `uq_aa_period (company_id, year, quarter)` already allows it.
- Every quarterly query that orders or bounds by `(year, quarter)` excludes `quarter = 0`: `load_periods`, `_docs_up_to`, `_is_stale`'s input check, the tree, `stale_periods`. The annual loader reads all four quarters of the fiscal year and all earlier annual periods.
- Stale: an annual output is stale when any document of the fiscal year, any quarterly or annual input of the year or earlier, any asset row, or the company record changed after it was generated, or when a quarter's filed version changed.
- Mark-as-filed works on the annual period as on quarters. A new version after filing is an amended return.
- The tree shows an **Annual** node under each fiscal year that has documents, after Q4, with the same status badges as quarters.

## 2. Asset register and depreciation

**Table `aa_assets`** (enterprise-scoped, FORCE RLS like the other `aa_*` tables):

| Column | Type | Notes |
|---|---|---|
| `id`, `enterprise_id`, `company_id` | | as other tables |
| `document_id` | UUID, unique, FK `aa_documents` | one asset per capital-goods document |
| `description` | text | defaults to the seller name + document number |
| `cost` | NUMERIC(14,2) | document gross − VAT when the input VAT was claimed, else gross |
| `in_service` | date | defaults to the document date |
| `useful_life_months` | int | default 60, 1–600 |
| `end_date` | date, nullable | retired / sold; no depreciation after this month |
| `created_at`, `updated_at` | | |

- Rows are created or updated when generation runs (from documents whose account is `capital_goods` and are not excluded or deleted); edits to `description`, `in_service`, `useful_life_months` and `end_date` are kept. A deleted or re-filed document drops its asset from computation; the row is kept so the edits survive a restore.
- **Depreciation** (pure `compute/depreciation.py`): monthly = cost ÷ life, counting the month the asset goes into service as a full month, until the life or `end_date` runs out. The last month takes the remainder so the total equals cost. Amounts are centavos half-up per month, summed.
- **Quarterly ITR:** the year-to-date depreciation of the fiscal year's months up to the quarter end is added to the deductions (itemized only; OSD and 8% ignore it). This replaces the "capital goods were not expensed" warning. Expenses tab: new row `depreciation`.
- **Annual ITR:** the fiscal year's depreciation is a deduction (itemized only).
- **Workbook tab `Depreciation`:** one row per asset: description, document, in service, cost, life, accumulated at the start of the year, this year, accumulated at year end, net book value.

## 3. Annual computation

A pure `compute/annual.py` builds the annual result from the four quarters' document lines, their quarterly inputs, the annual inputs, the asset register and the carry-over schedules. It reuses the quarterly helpers (`sales_base`, `compute_cogs`, `quarter_expenses` with the representation cap year to date, `graduated_tax`).

### Corporations — 1702-RT (January 2018 ENCS)

- Gross sales (net of VAT) − cost of sales = gross income; + non-operating income (annual input, defaulting to the sum of the quarters').
- Deductions: itemized (expenses + depreciation) or OSD 40% of gross income.
- Taxable income before NOLCO; − NOLCO applied (itemized only, §4) = taxable income.
- RCIT = taxable income × 25%, or 20% when the annual input "qualifies for 20%" is set (taxable income ≤ ₱5M and total assets ≤ ₱100M excluding land; the platform checks the ₱5M part and warns if total assets were entered above ₱100M).
- MCIT = 2% × gross income, from the 4th taxable year after the year operations began (company field `operations_start_year`, new, optional; when blank MCIT follows the quarterly `mcit_applies` input of Q3, else off with a warning).
- Tax due = the higher of RCIT and MCIT. When MCIT is higher, the excess over RCIT is added to the excess-MCIT schedule (§4).
- Credits: prior year's excess credits, Q1–Q3 income tax paid (§5), 2307s received for the whole year (SAWT, all four quarters), and excess MCIT from the last 3 years. Excess MCIT is applied only in a year RCIT is the higher tax, and only up to RCIT − MCIT, so the tax after the credit never falls below that year's MCIT. (Conservative reading of RR 9-98; flagged for the CPA gate.)
- Tax payable/(overpayment). An overpayment is carried to next year's "prior year's excess credits" by default; the annual input "refund instead" switches the PDF option box.
- Balance-sheet part (Schedule 9 / Part IV per the form): from annual inputs; "property, plant and equipment, net" defaults to the register's net book value.
- Reconciliation of net income per books against taxable income: annual inputs for the non-deductible and non-taxable items; the platform supplies taxable income.

### Individuals — 1701-A or 1701 (January 2018)

- **1701-A** when the individual earns only from business/profession and uses the 8% option or OSD. **1701** when itemized.
- 8%: 8% × (gross sales + non-operating income − ₱250,000). OSD: graduated table on gross sales − 40% of gross sales + non-operating income, as the quarterly rules do. Itemized: graduated table on gross income − deductions − NOLCO.
- Credits as for corporations (no MCIT).
- 1701 balance-sheet section from annual inputs, as above.
- Warning on every 1701/1701-A: compensation income is not included.

### Due dates

- 1702-RT: the 15th day of the 4th month after fiscal year-end; weekends roll to Monday.
- 1701 / 1701-A: April 15 of the following year (individuals are calendar-year only); weekends roll to Monday.

### Snapshot

Forms keyed `1702RT`, `1701`, `1701A`, with item keys following the official item numbers, plus `COGS`, `Expenses` (annual) and the ledgers `Depreciation`, `NOLCO`, `QuarterCredits` and `SAWT` (all four quarters). Versioning, diffs and yellow highlights work unchanged.

## 4. NOLCO and excess MCIT

- **NOLCO** arises in a year with taxable income before NOLCO below zero under itemized deductions. The loss is available for the next 3 taxable years; losses of fiscal years 2020 and 2021 for the next 5 (RR 25-2020).
- Applied oldest first, up to taxable income before NOLCO.
- Under OSD or the 8% option no NOLCO is deducted, but the carry-over period keeps running (RR 16-2008).
- NOLCO deducted in computing RCIT counts as used even when MCIT turns out higher.
- **Excess MCIT** (MCIT − RCIT in a year MCIT applied) is creditable against RCIT in the next 3 years, oldest first.
- **Sources:** each annual output's snapshot carries its closing schedules. The next year's annual computation reads the closing schedules of the latest filed (else latest) annual version of the previous year; for years before the platform, the annual inputs hold an opening schedule: rows of (year incurred, amount, already used).
- Workbook tabs `NOLCO` and, for corporations, `ExcessMCIT`: year incurred, amount, used before, used this year, expired this year, remaining, expiry year.

## 5. Q1–Q3 income tax paid

- For each of Q1–Q3: the tax payable item of the quarterly ITR (`PAYABLE_ITEM`: 1702-Q item 25, 1701-Q item 68) in that quarter's **filed** version; else its latest version; else ₱0 with a warning naming the quarter. A negative payable (overpayment) counts as ₱0 paid.
- Mark-as-filed records the filed version: new column `aa_periods.filed_output_id` (nullable FK `aa_outputs`), set to the latest version when marking filed and cleared when unmarking. This fixes the Phase 2 minor "mark-as-filed doesn't record which version".
- Annual inputs `q1_paid`, `q2_paid`, `q3_paid` (nullable) override.
- Warning when a quarter has a newer version than the filed one.
- Workbook tab `QuarterCredits`: quarter, source (filed vN / latest vN / entered / none), tax paid, 2307 credits.

## 6. Annual inputs

Stored in the annual period's `inputs` JSON, parsed by `annual_inputs_from_json` (malformed values fall back to defaults, like `inputs_from_json`):

- `ending_inventory` (defaults to Q4's), `non_operating_income` (defaults to the quarters' sum), `prior_year_excess_credits`.
- `q1_paid`, `q2_paid`, `q3_paid` overrides; `amended_paid_income_tax`.
- `cit_20_percent`, `refund_overpayment`.
- Balance sheet: `current_assets`, `ppe_net` (default: register), `other_noncurrent_assets`, `current_liabilities`, `noncurrent_liabilities`, `equity`; checked to balance within ₱1 with a warning otherwise.
- Reconciliation: `book_net_income`, `nondeductible_expenses`, `nontaxable_income`, `other_reconciling` (signed).
- Opening schedules: `opening_nolco` and `opening_excess_mcit`, lists of `{year, amount, used}`.

## 7. PDFs

- Official templates, downloaded from the BIR CDN and SHA-256 pinned in the plan: 1702-RT January 2018 ENCS (spec sheet link), 1701 January 2018 (spec sheet link), 1701-A January 2018 (URL to confirm in planning).
- Comb-cell layouts in `forms/bir1702rt_layout.py`, `bir1701_layout.py`, `bir1701a_layout.py`, rendered through the Phase 3 overlay (`pdf_overlay.render_form`), filled by `pdf_returns.render_return`. Same rules: one character per comb cell, right-aligned whole pesos, negatives in parentheses, an amount that doesn't fit printed whole in red and footnoted, yellow highlights for changed items, DRAFT stamp when reviews are open, Amended box ticked on amended versions.
- Before the plan is written, every box is calibrated against the template and a prototype render is checked by eye, as in Phase 3; the plan carries the proven layout code.
- Pages and parts left blank: payment details, contact details, the 1701 spouse column and compensation parts, the 1702-RT special-rate and exempt schedules, and any balance-sheet/reconciliation items not entered.

## 8. Workbook

`<Company> <FY> Annual vN.xlsx`, written by the existing `write_workbook` with the annual snapshot: Summary, the return tab (`1702RT` / `1701` / `1701A`), `COGS`, `Expenses`, `Depreciation`, `NOLCO`, `ExcessMCIT` (corporations), `QuarterCredits`, `SAWT`, `Transactions` (whole year), Change log on v2+. Clean copy as for quarters.

## 9. API

Under `/api/accounting`, role-gated and enterprise-scoped like the period routes:

- `GET /periods/{company_id}/{year}/annual` → `PeriodOut` (forms_expected, due date, inputs, versions, stale, filed).
- `PUT /periods/{company_id}/{year}/annual/inputs`, `POST …/annual/generate`, `PUT …/annual/filed`.
- `GET /companies/{company_id}/assets?year=` → assets with this year's depreciation; `PATCH /assets/{id}` (description, in_service, useful_life_months, end_date).
- Output downloads reuse `/outputs/{id}`, `/outputs/{id}/xlsx`, `/outputs/{id}/pdf?form=`.

## 10. Frontend

- Tree: an **Annual** node per fiscal year after Q4.
- `AnnualPanel` built like `PeriodPanel`: annual inputs (grouped: income, credits and overrides, balance sheet, reconciliation, opening schedules), Generate, versions, `OutputViewer`.
- Document panel: on capital-goods documents, an **Asset** section (description, in service, useful life in years and months, end date) and this year's depreciation.
- Theme CSS variables only, as before.

## 11. Also in this phase (Phase 2 minors)

- 2550-Q PDF prints the company's branch code.
- Editing a company record marks its quarterly and annual outputs stale (`aa_companies.updated_at` joins the stale check).
- Mark-as-filed records the filed version (§5).

## 12. Testing

Pure pytest for: depreciation (month counting, end date, remainder month, fiscal-year windows), the annual engine for each taxpayer type and deduction method, RCIT vs MCIT and the excess-MCIT schedule, NOLCO (3- and 5-year expiry, OSD clock running, oldest first, MCIT years), Q1–Q3 credit sourcing (filed / latest / override / missing), annual input parsing, due dates, layouts against the pinned templates (every key lands on its page, overflow handling), and the annual snapshot through `write_workbook`. DB-bound routes are exercised by the scripted end-to-end check and a manual run, per the project's testing convention.

## Review focus (for the plan)

1. A loss year followed by profit years: NOLCO used oldest first, a 2020 loss lasting 5 years, expiry warnings.
2. A corporation where MCIT exceeds RCIT one year and RCIT is higher the next: the excess MCIT credit is capped at RCIT − MCIT of the later year.
3. A quarter re-generated after filing: the annual credit uses the filed version and warns.
4. A fiscal year ending in June: depreciation months, Q1–Q3 mapping and the 1702-RT due date follow the fiscal calendar.
5. An asset whose document is deleted or re-filed to another account mid-year: its depreciation disappears and the output goes stale.
