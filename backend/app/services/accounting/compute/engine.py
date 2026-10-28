"""Assemble one quarter's returns, ledgers and warnings from documents (pure).

Everything is recomputed from documents: inventory and excess input VAT chain from
the company's first quarter on record; income tax is year-to-date from Q1.
"""

from dataclasses import dataclass, replace
from decimal import Decimal

from app.services.accounting.compute import withholding
from app.services.accounting.compute.cogs import CogsResult, cogs_form, compute_cogs, cost_base, is_capital_goods
from app.services.accounting.compute.deductions import (
    ExpenseBreakdown,
    expenses_form,
    quarter_expenses,
)
from app.services.accounting.compute.depreciation import Asset, depreciation_between
from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.ewt import compute_ewt, is_agent
from app.services.accounting.compute.inputs import CompanyFacts, PeriodData, PeriodInputs
from app.services.accounting.compute.itr import (
    PriorOverride,
    QuarterFigures,
    compute_1701q,
    compute_1702q,
)
from app.services.accounting.compute.ledgers import (
    build_sawt,
    build_slp,
    build_sls,
    build_transactions,
)
from app.services.accounting.compute.money import ZERO, c2, total
from app.services.accounting.compute.pt import compute_2551q
from app.services.accounting.compute.vat import VatResult, compute_2550q
from app.services.accounting.compute.withholding import (
    atc_summary,
    build_qap,
    form_0619e,
    form_1601c,
    form_1601eq,
    payroll_months,
)


@dataclass
class QuarterResult:
    forms: dict[str, dict]
    ledgers: dict[str, list[dict]]
    warnings: list[str]
    carry_out: dict[str, Decimal | None]
    review_open: int


VAT_THRESHOLD = Decimal("3000000")  # NIRC Sec. 109(BB) / 236(G): gross sales above this must register for VAT
MCIT_FROM_YEAR = 4                   # MCIT starts the 4th taxable year after operations began (Sec. 27(E))


def mcit_from_company(company: CompanyFacts, inputs: PeriodInputs, fiscal_year: int) -> PeriodInputs:
    """The company's start year decides MCIT when it's set, so the quarters and the annual return agree."""
    if company.operations_start_year is None:
        return inputs
    return replace(inputs, mcit_applies=fiscal_year >= company.operations_start_year + MCIT_FROM_YEAR)


def _peso_text(value: Decimal) -> str:
    return f"₱{value:,.2f}"


def _unsplit(line) -> bool:
    """A sale with a total but no VATable / zero-rated / exempt breakdown."""
    return line.category == "sales" and line.gross > 0 and line.vatable + line.zero_rated + line.exempt == 0


def split_vat_sales(lines) -> tuple:
    """A VAT-registered sale showing only a total and its VAT is VATable: total − VAT."""
    return tuple(replace(l, vatable=c2(l.gross - l.vat)) if _unsplit(l) and l.vat > 0 else l for l in lines)


def sales_base(lines, company: CompanyFacts) -> Decimal:
    sales = [l for l in lines if l.category == "sales"]
    if company.vat_registered:  # a sale with no split at all still counts for income tax, at its total
        return total(l.gross if _unsplit(l) else l.vatable + l.zero_rated + l.exempt for l in sales)
    return total(l.gross for l in sales)


def employer_contributions(p: PeriodData) -> Decimal:
    return total(m.employer_contributions for m in p.inputs.payroll)


def cwt_credits(lines) -> Decimal:
    return total(l.withholding for l in lines if l.category == "2307" and l.client_role == "seller")


def _calendar_quarters(company: CompanyFacts) -> bool:
    """Withholding returns follow calendar quarters; a fiscal year ending Mar/Jun/Sep/Dec lines up with them."""
    return company.fiscal_year_end_month % 3 == 0


def cogs_chain(company: CompanyFacts, periods) -> tuple[dict[tuple[int, int], CogsResult], set[tuple[int, int]]]:
    """Cost of sales per quarter with inventory chained across every quarter on record.

    Also returns the quarters whose beginning inventory was unknown (taken as ₱0).
    """
    cogs_by_period: dict[tuple[int, int], CogsResult] = {}
    unknown: set[tuple[int, int]] = set()
    previous_ending: Decimal | None = None
    previous_beginning = ZERO
    for index, p in enumerate(periods):
        if index > 0 and previous_ending is not None:
            beginning = previous_ending
        elif p.inputs.opening_inventory is not None:
            beginning = p.inputs.opening_inventory
            if index > 0:  # the previous quarter closed with this stock; don't expense it twice
                prev = periods[index - 1]
                cogs_by_period[(prev.year, prev.quarter)] = compute_cogs(prev.lines, company, previous_beginning,
                                                                         beginning)
        else:
            beginning = ZERO
            unknown.add((p.year, p.quarter))
        cogs_by_period[(p.year, p.quarter)] = compute_cogs(p.lines, company, beginning, p.inputs.ending_inventory)
        previous_ending = p.inputs.ending_inventory
        previous_beginning = beginning
    return cogs_by_period, unknown


def quarter_depreciation(assets, year: int, quarter: int, fye: int) -> Decimal:
    start, end = quarter_start(year, quarter, fye), quarter_end(year, quarter, fye)
    return total(depreciation_between(a, start, end) for a in assets)


AMENDED_WARNING = ("This is an amended return. Enter what was paid on the original return in the quarter inputs, "
                   "or the full tax is asked for again.")


def build_quarter(company: CompanyFacts, periods: list[PeriodData], amended: bool = False,
                  assets: tuple[Asset, ...] | list[Asset] = (),
                  filed_remittances: dict[int, tuple[Decimal, int]] | None = None) -> QuarterResult:
    if not periods:
        raise ValueError("build_quarter needs at least the target quarter")
    if company.vat_registered:
        periods = [replace(p, lines=split_vat_sales(p.lines)) for p in periods]
    target = periods[-1]
    itr_inputs = mcit_from_company(company, target.inputs, target.year)
    warnings: list[str] = []
    keeps_inventory = company.business_type != "services"

    # 1. Chains across every quarter on record: inventory and excess input VAT.
    cogs_by_period, beginning_unknown = cogs_chain(company, periods)
    if (target.year, target.quarter) in beginning_unknown and keeps_inventory:
        warnings.append("Beginning inventory is unknown and was taken as ₱0. Enter last quarter's ending "
                        "inventory, or this quarter's opening inventory.")
    carry_vat = ZERO
    vat: VatResult | None = None
    for p in periods:
        if p.inputs.opening_excess_input_vat > 0:  # entered carry-in wins over the chain
            carry_vat = c2(p.inputs.opening_excess_input_vat)
        if company.vat_registered:
            vat = compute_2550q(p.lines, p.inputs, carry_vat)
            carry_vat = vat.excess_input_vat_out

    # 2. Income tax figures, Q1 to the target quarter of the fiscal year.
    by_quarter = {p.quarter: p for p in periods if p.year == target.year and p.quarter <= target.quarter}
    prior = None
    if target.quarter > 1 and target.inputs.prior_taxable_income is not None:
        prior = PriorOverride(target.inputs.prior_taxable_income, target.inputs.prior_tax_paid or ZERO,
                              target.inputs.prior_cwt or ZERO, target.inputs.prior_gross_income)
        if (itr_inputs.mcit_applies and target.inputs.prior_gross_income is None
                and company.taxpayer_type != "individual"):
            warnings.append("MCIT needs earlier quarters' gross income. Enter it in the quarter inputs; until then "
                            "MCIT counts this quarter only.")
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
        breakdown, rep_ytd, allowed_ytd = quarter_expenses(lines, company, rep_ytd, allowed_ytd, sales_ytd,
                                                           employer_contributions(p) if p else ZERO)
        cogs_q = cogs_by_period[(p.year, p.quarter)].cost_of_sales if p else ZERO
        depreciation_q = quarter_depreciation(assets, target.year, q, company.fiscal_year_end_month)
        figures.append(QuarterFigures(sales_q, cogs_q, c2(breakdown.deductions + depreciation_q),
                                      p.inputs.non_operating_income if p else ZERO, cwt_credits(lines)))

    # 3. Forms for the target quarter.
    forms: dict[str, dict] = {}
    individual = company.taxpayer_type == "individual"
    if company.vat_registered:
        forms["2550Q"] = vat.items
    elif not (individual and company.income_tax_option == "eight_percent"):
        forms["2551Q"] = compute_2551q(target.lines, target.inputs,
                                       quarter_end(target.year, target.quarter, company.fiscal_year_end_month))
    if target.quarter <= 3:
        if individual:
            forms["1701Q"] = compute_1701q(figures, company, itr_inputs, prior, target.year)
        else:
            forms["1702Q"] = compute_1702q(figures, company, itr_inputs, prior, target.year)
    else:
        warnings.append("Q4 has no quarterly income tax return; the annual return (1702-RT / 1701 / 1701-A) "
                        "covers it. Generate it from the year's Annual return folder.")
    target_cogs = cogs_by_period[(target.year, target.quarter)]
    if keeps_inventory:
        forms["COGS"] = cogs_form(target_cogs)
    forms["Expenses"] = expenses_form(breakdown, depreciation_q)

    # 3b. Withholding returns.
    ewt = compute_ewt(target.lines, company, target.year, target.quarter)
    withholding_warnings = list(ewt.warnings)
    if is_agent(company):
        if _calendar_quarters(company):
            forms["0619E-M1"] = form_0619e(ewt.month_tax(1))
            forms["0619E-M2"] = form_0619e(ewt.month_tax(2))
            forms["1601EQ"] = form_1601eq(ewt, target.inputs, filed_remittances)
            for month, item in ((1, "20"), (2, "21")):
                if forms["1601EQ"][f"_SRC_{item}"] == "calculated":
                    withholding_warnings.append(
                        f"0619-E M{month} isn't marked filed; 1601-EQ item {item} uses the calculated "
                        f"{_peso_text(forms['1601EQ'][item])}. Mark it filed in Prepare returns once it's filed.")
            atc_count = len(atc_summary(ewt))
            if atc_count > withholding.MAX_SCHEDULE_ROWS:
                withholding_warnings.append(
                    f"This quarter has {atc_count} ATCs; the 1601-EQ tab lists the first "
                    f"{withholding.MAX_SCHEDULE_ROWS}. Item 19 and the QAP include them all."
                )
        else:
            withholding_warnings.append("Expanded withholding returns follow calendar quarters, which this fiscal "
                                        "year doesn't line up with; 0619-E and 1601-EQ were not prepared.")
    payroll_lines = [l for l in target.lines if l.category == "payroll"]
    if company.has_employees or payroll_lines:
        months, outside = payroll_months(payroll_lines, target.year, target.quarter, company.fiscal_year_end_month)
        for m in (1, 2, 3):
            gross, withheld = months.get(m, (ZERO, ZERO))
            forms[f"1601C-M{m}"] = form_1601c(gross, withheld, target.inputs.payroll[m - 1])
        nil_but_paid = [m for m in (1, 2, 3) if target.inputs.payroll[m - 1].no_payroll and m in months]
        if nil_but_paid:
            withholding_warnings.append(f"Month {', '.join(map(str, nil_but_paid))} is marked 'no payroll', but has "
                                        "payroll documents. Untick it, or move the documents.")
        if outside:
            withholding_warnings.append(f"{outside} payroll document(s) are dated outside this quarter's months and "
                                        "were counted in month 3 of the 1601-C.")
        if payroll_lines and not any(m.contributions or m.employer_contributions for m in target.inputs.payroll):
            withholding_warnings.append("Payroll was filed but no SSS / PhilHealth / Pag-IBIG was entered. Enter the "
                                        "employee and employer shares per month in the payroll inputs, so they're "
                                        "deducted and booked.")
        if payroll_lines and not company.has_employees:
            withholding_warnings.append("Payroll documents were found but the company isn't marked as having "
                                        "employees; the 1601-C was prepared anyway. Tick 'Has employees' on the "
                                        "company to enter the non-taxable amounts.")

    # 4. Ledgers.
    ledgers: dict[str, list[dict]] = {
        "Transactions": build_transactions(target.lines, company.vat_registered, ewt.by_line()),
    }
    if company.vat_registered:
        ledgers["SLS"] = build_sls(target.lines)
        ledgers["SLP"] = build_slp(target.lines, True)
    sawt = build_sawt(target.lines)
    if sawt:
        ledgers["SAWT"] = sawt
    if "1601EQ" in forms and ewt.rows:
        ledgers["QAP"] = build_qap(ewt)

    # 5. Warnings.
    review_open = sum(1 for l in target.lines if l.open_review)
    if review_open:
        warnings.insert(0, f"{review_open} document(s) in this quarter still need review, so this output is a DRAFT.")
    unsplit = sum(1 for l in target.lines if _unsplit(l)) if company.vat_registered else 0
    if unsplit:
        warnings.append(f"{unsplit} sales document(s) have a total but no VATable, zero-rated or exempt amount. "
                        "They count for income tax at their total but are left out of the 2550-Q; open them and "
                        "fill in the split.")
    if not company.vat_registered and sales_ytd > VAT_THRESHOLD:
        eight = individual and company.income_tax_option == "eight_percent"
        warnings.append(f"Gross sales so far this year are {_peso_text(sales_ytd)}, above the ₱3,000,000 VAT "
                        "threshold. The client must register for VAT and charge VAT from the following month"
                        + ("; the 8% option no longer applies this year, so income tax reverts to graduated rates."
                           if eight else "."))
    if amended and target.inputs.amended_paid_business_tax == 0 and target.inputs.amended_paid_income_tax == 0:
        warnings.append(AMENDED_WARNING)
    unsorted = sum(1 for l in target.lines if l.category == "unsorted")
    if unsorted:
        warnings.append(f"{unsorted} unsorted document(s) were left out. Move them to a folder to include them.")
    if keeps_inventory and not target_cogs.ending_provided:
        warnings.append("Ending inventory was not provided and was taken as ₱0, so cost of sales may be overstated.")
    if company.business_type == "manufacturing":
        warnings.append("Manufacturing cost of sales is simplified to beginning inventory + purchases − ending "
                        "inventory.")
    capital = total(cost_base(l, company.vat_registered) for l in target.lines if is_capital_goods(l))
    if capital > 0:
        warnings.append(f"{_peso_text(capital)} of capital goods bought this quarter are in the asset register and "
                        "depreciated over their useful life, not expensed. Check their useful life on each document.")
    if breakdown.representation_disallowed_ytd > 0:
        cap = "1%" if company.business_type == "services" else "0.5%"
        warnings.append(f"Representation above the {cap} cap ({_peso_text(breakdown.representation_disallowed_ytd)} "
                        "so far this year) is not deductible.")
    if company.vat_registered and sawt and target.inputs.vat_withheld == 0:
        warnings.append("Received 2307s are credited against income tax. If any show VAT withheld (ATC WV…), enter "
                        "it as 'VAT withheld' in the quarter inputs.")

    warnings.extend(withholding_warnings)

    carry_out = {"excess_input_vat": carry_vat if company.vat_registered else None,
                 "ending_inventory": target.inputs.ending_inventory}
    return QuarterResult(forms, ledgers, warnings, carry_out, review_open)


def expected_forms(company: CompanyFacts, quarter: int, has_payroll: bool = False) -> list[str]:
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
    if company.has_employees or has_payroll:
        forms += ["1601C-M1", "1601C-M2", "1601C-M3"]
    return forms
