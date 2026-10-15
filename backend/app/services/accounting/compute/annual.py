"""Annual income tax return — 1702-RT (non-individuals), 1701 or 1701-A (individuals) — pure.

Built from the fiscal year's quarters of documents and inputs, the annual inputs, the asset
register, the NOLCO and excess MCIT carried in from earlier years, and the income tax paid
on the Q1–Q3 returns. Item keys follow the official forms (January 2018); amounts are whole pesos.
"""

from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.annual_inputs import AnnualInputs, QuarterSource, quarter_credits
from app.services.accounting.compute.carryover import (
    CarryResult, CarryRow, add_new, apply_carry, mcit_life, nolco_life, rows_from_json, rows_to_json,
)
from app.services.accounting.compute.cogs import CogsResult, cogs_form, cost_base, is_capital_goods
from app.services.accounting.compute.deductions import ExpenseBreakdown, expenses_form, quarter_expenses
from app.services.accounting.compute.depreciation import depreciation_between, fiscal_year_window, register_rows
from app.services.accounting.compute.due_dates import quarter_end
from app.services.accounting.compute.engine import (
    MCIT_FROM_YEAR, cogs_chain, cwt_credits, employer_contributions, sales_base, split_vat_sales,
)
from app.services.accounting.compute.inputs import CompanyFacts, PeriodData
from app.services.accounting.compute.itr import (
    EIGHT_PERCENT, EIGHT_PERCENT_EXEMPTION, OSD_RATE, graduated_tax, mcit_rate,
)
from app.services.accounting.compute.ledgers import build_sawt, build_transactions
from app.services.accounting.compute.money import ZERO, c2, peso, total

_P0 = Decimal("0")
CIT_SMALL_TAXABLE = Decimal("5000000")
CIT_SMALL_ASSETS = Decimal("100000000")
EIGHT_PERCENT_CEILING = Decimal("3000000")
PRIOR_ROWS_ON_FORM = 3
_MAPPED = {"rent": "11", "taxes_licenses": "15", "transportation": "16", "professional_fees": "17B"}


@dataclass(frozen=True)
class CarryIn:
    nolco: tuple[CarryRow, ...] = ()
    excess_mcit: tuple[CarryRow, ...] = ()
    excess_credits: Decimal | None = None


@dataclass
class AnnualResult:
    form: str
    forms: dict[str, dict]
    ledgers: dict[str, list[dict]]
    warnings: list[str]
    carry_out: dict
    review_open: int = 0


def annual_form(company: CompanyFacts) -> str:
    if company.taxpayer_type != "individual":
        return "1702RT"
    if company.has_compensation_income:  # 1701-A is only for income purely from business or profession
        return "1701"
    if company.income_tax_option == "eight_percent" or company.deduction_method == "osd":
        return "1701A"
    return "1701"


def carry_in_from_snapshot(carry: dict | None) -> CarryIn:
    """The closing schedules a previous year's annual version stored under ``snapshot['carry']``."""
    carry = carry if isinstance(carry, dict) else {}
    credits = carry.get("excess_credits")
    try:
        excess = c2(credits) if credits not in (None, "") else None
    except Exception:  # noqa: BLE001 — malformed stored value: no carried credit
        excess = None
    return CarryIn(rows_from_json(carry.get("nolco")), rows_from_json(carry.get("excess_mcit")), excess)


def _peso_text(value: Decimal) -> str:
    return f"₱{value:,.0f}"


def ordinary_schedule(b: ExpenseBreakdown, depreciation: Decimal) -> dict[str, Decimal]:
    """Ordinary allowable itemized deductions, by 1702-RT Schedule I / 1701 Schedule 4 item."""
    items = {key: _P0 for key in ("5", "6", "11", "13", "14", "15", "16", "17B", "17D")}
    items["5"] = peso(depreciation)
    items["6"] = peso(b.representation_allowed)
    items["13"] = peso(b.by_account.get("salaries", ZERO) + b.payroll)
    items["14"] = peso(b.contributions)
    for account, key in _MAPPED.items():
        items[key] = peso(b.by_account.get(account, ZERO))
    rest = total(v for k, v in b.by_account.items() if k not in _MAPPED and k not in ("salaries", "representation"))
    items["17D"] = peso(rest)
    items["18"] = sum(items.values(), _P0)
    return items


def _mcit_applies(company: CompanyFacts, fiscal_year: int, q3: PeriodData | None) -> tuple[bool, str | None]:
    if company.operations_start_year:
        return fiscal_year >= company.operations_start_year + MCIT_FROM_YEAR, None
    if q3 is not None:
        return q3.inputs.mcit_applies, ("The year operations began isn't set on the company, so MCIT follows Q3's "
                                        "'MCIT applies' input. Set it on the company to decide MCIT by year.")
    return False, ("The year operations began isn't set on the company and there are no Q3 inputs, so MCIT was "
                   "not computed. Set the year on the company.")


def _nolco_slots(result: CarryResult, fiscal_year: int, prefix: str) -> tuple[dict, dict]:
    """Schedule IIIA (1702-RT) / 6.A.1 (1701) rows: three latest prior-year losses in rows 4–6, this year's in 7."""
    amounts: dict[str, Decimal] = {}
    years: dict[str, str] = {}
    prior = [row for row in result.schedule if int(row["year"]) < fiscal_year][-PRIOR_ROWS_ON_FORM:]
    current = [row for row in result.schedule if int(row["year"]) == fiscal_year]
    for slot, row in list(zip((4, 5, 6), prior)) + list(zip((7,), current)):
        years[f"{prefix}_{slot}_YEAR"] = row["year"]
        for column, key in (("A", "amount"), ("B", "used_before"), ("C", "expired_this_year"),
                            ("D", "used_this_year"), ("E", "remaining")):
            amounts[f"{prefix}_{slot}_{column}"] = peso(row[key])
    amounts[f"{prefix}_8"] = peso(result.applied)
    return amounts, years


def _reconciliation(inputs: AnnualInputs, keys: dict[str, str]) -> dict[str, Decimal]:
    """Net income per books against taxable income (1702-RT Schedule V / 1701 Part IX)."""
    if inputs.book_net_income is None:
        return {}
    other = c2(inputs.other_reconciling)
    add_other = peso(other) if other > 0 else _P0
    less_other = peso(-other) if other < 0 else _P0
    items = {keys["book"]: peso(inputs.book_net_income), keys["nondeductible"]: peso(inputs.nondeductible_expenses)}
    if add_other:
        items[keys["add_other"]] = add_other
    items[keys["add_total"]] = items[keys["book"]] + items[keys["nondeductible"]] + add_other
    items[keys["nontaxable"]] = peso(inputs.nontaxable_income)
    if less_other:
        items[keys["less_other"]] = less_other
    items[keys["less_total"]] = items[keys["nontaxable"]] + less_other
    items[keys["net"]] = items[keys["add_total"]] - items[keys["less_total"]]
    return items


_RECON_1702RT = {"book": "S5_1", "nondeductible": "S5_2", "add_other": "S5_3", "add_total": "S5_4",
                 "nontaxable": "S5_5", "less_other": "S5_7", "less_total": "S5_9", "net": "S5_10"}
_RECON_1701 = {"book": "P9_1", "nondeductible": "P9_2", "add_other": "P9_3", "add_total": "P9_5",
               "nontaxable": "P9_6", "less_other": "P9_8", "less_total": "P9_10", "net": "P9_11"}


def _balance_sheet(inputs: AnnualInputs, net_book_value: Decimal, warnings: list[str]) -> dict[str, Decimal] | None:
    fields = ("current_assets", "ppe_net", "other_noncurrent_assets", "current_liabilities",
              "noncurrent_liabilities", "equity")
    if all(getattr(inputs, name) is None for name in fields):
        return None
    value = {name: c2(getattr(inputs, name) or ZERO) for name in fields}
    if inputs.ppe_net is None:
        value["ppe_net"] = c2(net_book_value)
    sheet = {
        "current_assets": value["current_assets"], "ppe_net": value["ppe_net"],
        "other_noncurrent_assets": value["other_noncurrent_assets"],
        "total_assets": total([value["current_assets"], value["ppe_net"], value["other_noncurrent_assets"]]),
        "current_liabilities": value["current_liabilities"], "noncurrent_liabilities": value["noncurrent_liabilities"],
        "total_liabilities": total([value["current_liabilities"], value["noncurrent_liabilities"]]),
        "equity": value["equity"],
    }
    sheet["total_liabilities_equity"] = c2(sheet["total_liabilities"] + sheet["equity"])
    gap = c2(sheet["total_assets"] - sheet["total_liabilities_equity"])
    if abs(gap) > 1:
        warnings.append(f"The balance sheet doesn't balance: total assets {_peso_text(sheet['total_assets'])} vs "
                        f"liabilities and equity {_peso_text(sheet['total_liabilities_equity'])}. Check the "
                        "balance-sheet inputs.")
    return sheet


def _overpayment(payable: Decimal, inputs: AnnualInputs) -> tuple[str, str | None]:
    if payable >= 0:
        return "", None
    if inputs.refund_overpayment:
        return "refund", None
    return "carry_over", str(-payable)


ANNUAL_AMENDED_WARNING = ("This is an amended return. Enter what was paid on the original return in the annual "
                          "inputs, or the full tax is asked for again.")


def build_annual(company: CompanyFacts, periods: list[PeriodData], fiscal_year: int, inputs: AnnualInputs, *,
                 assets=(), quarter_sources: dict[int, QuarterSource] | None = None, carry_in: CarryIn = CarryIn(),
                 amended: bool = False, books_start: date | None = None) -> AnnualResult:
    periods = [p for p in periods if p.quarter >= 1 and (p.year, p.quarter) <= (fiscal_year, 4)]
    if company.vat_registered:
        periods = [replace(p, lines=split_vat_sales(p.lines)) for p in periods]
    fy = [p for p in periods if p.year == fiscal_year]
    by_q = {p.quarter: p for p in fy}
    lines = tuple(l for p in fy for l in p.lines)
    warnings: list[str] = []
    form = annual_form(company)
    individual = company.taxpayer_type == "individual"
    eight = individual and company.income_tax_option == "eight_percent"
    osd = not eight and company.deduction_method == "osd"
    itemized = not eight and not osd
    keeps_inventory = company.business_type != "services"
    fye = company.fiscal_year_end_month

    before_books = [q for q in range(1, 5)
                    if books_start is not None and quarter_end(fiscal_year, q, fye) < books_start]
    pre_books = (inputs.pre_books_sales, inputs.pre_books_cost_of_sales, inputs.pre_books_deductions,
                 inputs.pre_books_cwt)
    if before_books and not any(pre_books):
        warnings.append(f"The books start {books_start:%d %b %Y}, so {', '.join(f'Q{q}' for q in before_books)} "
                        "aren't on AutoAccounting. Enter those months' sales, cost of sales, deductions and "
                        "creditable tax withheld under 'Before the books started' in the annual inputs, or the "
                        "return covers only part of the year.")
    missing = [q for q in range(1, 5) if q not in before_books and (q not in by_q or not by_q[q].lines)]
    if missing:
        warnings.append(f"No documents for {', '.join(f'Q{q}' for q in missing)} of FY {fiscal_year}; the annual "
                        "return treats them as zero.")

    # 1. Income and deductions for the whole fiscal year.
    sales = c2(total(sales_base(p.lines, company) for p in fy) + inputs.pre_books_sales)
    cogs = CogsResult(ZERO, ZERO, ZERO, ZERO, True)
    if keeps_inventory and fy:
        chain, unknown = cogs_chain(company, periods)
        first = (fy[0].year, fy[0].quarter)
        beginning = chain[first].beginning_inventory
        if first in unknown:
            warnings.append("Beginning inventory for the year is unknown and was taken as ₱0. Enter the opening "
                            "inventory in the first quarter's inputs.")
        purchases = total(chain[(p.year, p.quarter)].purchases for p in fy)
        q4 = by_q.get(4)
        ending = inputs.ending_inventory if inputs.ending_inventory is not None else (
            q4.inputs.ending_inventory if q4 else None)
        if ending is None:
            warnings.append("Ending inventory for the year wasn't entered (annual inputs or Q4) and was taken as ₱0, "
                            "so cost of sales may be overstated.")
        end = c2(ending or ZERO)
        purchases = c2(purchases + inputs.pre_books_cost_of_sales)  # the earlier months' cost, as purchases
        cogs = CogsResult(beginning, purchases, end, c2(beginning + purchases - end), ending is not None)
    non_operating = c2(inputs.non_operating_income if inputs.non_operating_income is not None
                       else total(p.inputs.non_operating_income for p in fy))
    breakdown, _, _ = quarter_expenses(lines, company, ZERO, ZERO, sales,
                                       total(employer_contributions(p) for p in fy))
    start, end_day = fiscal_year_window(fiscal_year, fye)
    depreciation = total(depreciation_between(a, start, end_day) for a in assets)
    register = register_rows(assets, start, end_day)
    schedule = ordinary_schedule(breakdown, depreciation)
    if inputs.pre_books_deductions:
        schedule["17D"] += peso(inputs.pre_books_deductions)
        schedule["18"] += peso(inputs.pre_books_deductions)

    # 2. Credits.
    cwt = {q: cwt_credits(p.lines) for q, p in by_q.items()}
    credit_rows, paid_q1_q3, credit_warnings = quarter_credits(quarter_sources or {}, inputs, cwt)
    cwt_prior = peso(sum((cwt.get(q, ZERO) for q in (1, 2, 3)), inputs.pre_books_cwt))
    cwt_q4 = peso(cwt.get(4, ZERO))
    prior_excess = peso(inputs.prior_year_excess_credits if inputs.prior_year_excess_credits is not None
                        else carry_in.excess_credits or ZERO)
    amended_paid = peso(inputs.amended_paid_income_tax)

    items: dict = {}
    carry_out: dict = {}
    ledgers: dict[str, list[dict]] = {}

    # 3. The return.
    if form == "1702RT":
        i = items
        i["27"] = peso(sales)
        i["28"] = _P0
        i["29"] = i["27"]
        i["30"] = peso(cogs.cost_of_sales)
        i["31"] = i["29"] - i["30"]
        i["32"] = peso(non_operating)
        i["33"] = i["31"] + i["32"]
        before_nolco = i["33"] - schedule["18"] if itemized else i["33"] - peso(i["33"] * OSD_RATE)
        nolco = apply_carry(carry_in.nolco, fiscal_year, max(i["33"] - schedule["18"], _P0), nolco_life,
                            deduct=itemized)
        loss = schedule["18"] - i["33"] if itemized and schedule["18"] > i["33"] else _P0
        nolco = add_new(nolco, fiscal_year, loss, nolco_life)
        if itemized:
            i.update({f"S1_{k}": v for k, v in schedule.items()})
            i["34"] = schedule["18"]
            i["35"] = _P0
            i["36"] = peso(nolco.applied)
            i["37"] = i["34"] + i["35"] + i["36"]
            i["38"] = _P0
            i["39"] = i["33"] - i["37"]
            i.update({"S3_1": i["33"], "S3_2": i["34"], "S3_3": loss})
            slots, years = _nolco_slots(nolco, fiscal_year, "S3")
            i.update(slots)
            i.update(years)
        else:
            i.update({"34": _P0, "35": _P0, "36": _P0, "37": _P0})
            i["38"] = peso(i["33"] * OSD_RATE)
            i["39"] = i["33"] - i["38"]
        rate = 25
        if inputs.cit_20_percent:
            if i["39"] <= CIT_SMALL_TAXABLE:
                rate = 20
            else:
                warnings.append("The 20% rate needs net taxable income of ₱5,000,000 or less; this year's is "
                                f"{_peso_text(i['39'])}, so 25% was used.")
        i["40"] = Decimal(rate)
        i["41"] = peso(max(i["39"], _P0) * rate / 100)
        mcit_on, mcit_note = _mcit_applies(company, fiscal_year, by_q.get(3))
        if mcit_note:
            warnings.append(mcit_note)
        i["42"] = peso(max(i["33"], _P0) * mcit_rate(fiscal_year, fye)) if mcit_on else _P0
        i["43"] = max(i["41"], i["42"])
        excess = apply_carry(carry_in.excess_mcit, fiscal_year, max(i["41"] - i["42"], _P0), mcit_life)
        new_excess = i["42"] - i["41"] if mcit_on and i["42"] > i["41"] else _P0
        excess = add_new(excess, fiscal_year, new_excess, mcit_life, normal_tax=i["41"], mcit=i["42"])
        prior_mcit = [row for row in excess.schedule if int(row["year"]) < fiscal_year][-PRIOR_ROWS_ON_FORM:]
        for slot, row in enumerate(prior_mcit, start=1):
            i[f"S4_{slot}_YEAR"] = row["year"]
            for column, key in (("A", "normal_tax"), ("B", "mcit"), ("C", "amount"), ("D", "used_before"),
                                ("E", "expired_this_year"), ("F", "used_this_year"), ("G", "remaining")):
                if row[key] != "":
                    i[f"S4_{slot}_{column}"] = peso(row[key])
        if prior_mcit:
            i["S4_4"] = peso(excess.applied)
        i.update({"44": prior_excess, "45": _P0, "46": peso(paid_q1_q3), "47": peso(excess.applied),
                  "48": cwt_prior, "49": cwt_q4, "50": _P0, "51": amended_paid, "52": _P0, "53": _P0, "54": _P0})
        i["55"] = sum((i[k] for k in ("44", "45", "46", "47", "48", "49", "50", "51", "52", "53", "54")), _P0)
        i["56"] = i["43"] - i["55"]
        i.update({"14": i["43"], "15": i["55"], "16": i["56"], "17": _P0, "18": _P0, "19": _P0, "20": _P0,
                  "21": i["56"]})
        i.update(_reconciliation(inputs, _RECON_1702RT))
        payable = i["21"]
        carry_out["excess_mcit"] = rows_to_json(excess.closing)
        if excess.schedule:
            ledgers["ExcessMCIT"] = excess.schedule
        if excess.expired:
            warnings.append(f"{_peso_text(excess.expired)} of excess MCIT from "
                            f"{', '.join(map(str, excess.expired_years))} expired unused this year.")
        if len(prior_mcit) < len([r for r in excess.schedule if int(r["year"]) < fiscal_year]):
            warnings.append("More excess MCIT years than the 1702-RT's three rows; the workbook's ExcessMCIT tab "
                            "lists them all.")
        recon_net, recon_key = i.get("S5_10"), "Schedule V"
        total_assets = sum((getattr(inputs, n) or ZERO for n in ("current_assets", "ppe_net",
                                                                  "other_noncurrent_assets")), ZERO)
        if inputs.cit_20_percent and total_assets > CIT_SMALL_ASSETS:
            warnings.append("The 20% rate also needs total assets (excluding land) of ₱100,000,000 or less; the "
                            "balance sheet entered is above that. Untick 20% if it doesn't qualify.")
    elif form == "1701":
        i = items
        mixed = company.has_compensation_income
        comp_taxable = _P0
        if mixed:  # Schedule 2: taxable compensation from the 2316
            comp_gross, comp_exempt = peso(inputs.compensation_income), peso(inputs.compensation_nontaxable)
            comp_taxable = max(comp_gross - comp_exempt, _P0)
            i.update({"S2_4": comp_gross, "S2_5": comp_exempt, "S2_6": comp_taxable})
            if comp_gross == 0:
                warnings.append("The client earns compensation income, but none was entered. Enter the gross, "
                                "non-taxable and tax-withheld amounts from their BIR 2316 in the annual inputs.")
        before_nolco = None
        if eight:  # Schedule 3.B: compensation at graduated rates plus 8% of business income
            nolco = apply_carry(carry_in.nolco, fiscal_year, _P0, nolco_life, deduct=False)
            i["S2_7"] = graduated_tax(comp_taxable, fiscal_year)
            i["S3_26"] = peso(sales)
            i["S3_27"] = peso(non_operating)
            i["S3_28"] = i["S3_26"] + i["S3_27"]
            i["S3_29"] = _P0 if mixed else peso(EIGHT_PERCENT_EXEMPTION)
            i["S3_30"] = max(i["S3_28"] - i["S3_29"], _P0)
            i["S3_31"] = peso(i["S3_30"] * EIGHT_PERCENT)
            i["S3_32"] = i["S2_7"] + i["S3_31"]
            tax_due = i["S3_32"]
            if i["S3_28"] > EIGHT_PERCENT_CEILING:
                warnings.append(f"Gross sales and other income are {_peso_text(i['S3_28'])}, above ₱3,000,000: the "
                                "8% option isn't available above that. Switch the company to graduated rates.")
        else:  # Schedule 3.A: business and compensation together at graduated rates
            i["S3_8"] = peso(sales)
            i["S3_9"] = _P0
            i["S3_10"] = i["S3_8"]
            i["S3_19"] = peso(non_operating)
            i["S3_20"] = _P0
            i["S3_21"] = _P0
            i["S3_22"] = i["S3_19"]
            if osd:  # an individual's OSD is 40% of net sales (item 10); cost of sales isn't deducted
                nolco = apply_carry(carry_in.nolco, fiscal_year, _P0, nolco_life, deduct=False)
                i.update({"S3_11": _P0, "S3_12": i["S3_10"], "S3_13": _P0, "S3_14": _P0, "S3_15": _P0, "S3_16": _P0})
                i["S3_17"] = peso(i["S3_10"] * OSD_RATE)
                i["S3_18"] = i["S3_10"] - i["S3_17"]
            else:
                i["S3_11"] = peso(cogs.cost_of_sales)
                i["S3_12"] = i["S3_10"] - i["S3_11"]
                gross = i["S3_12"] + i["S3_22"]
                nolco = apply_carry(carry_in.nolco, fiscal_year, max(gross - schedule["18"], _P0), nolco_life)
                loss = schedule["18"] - gross if schedule["18"] > gross else _P0
                nolco = add_new(nolco, fiscal_year, loss, nolco_life)
                i.update({f"S4_{k}": v for k, v in schedule.items()})
                i["S3_13"] = schedule["18"]
                i["S3_14"] = _P0
                i["S3_15"] = peso(nolco.applied)
                i["S3_16"] = i["S3_13"] + i["S3_14"] + i["S3_15"]
                i["S3_17"] = _P0
                i["S3_18"] = i["S3_12"] - i["S3_16"]
                i.update({"S6_1": gross, "S6_2": schedule["18"], "S6_3": loss})
                slots, years = _nolco_slots(nolco, fiscal_year, "S6")
                i.update(slots)
                i.update(years)
                before_nolco = gross - schedule["18"]
            i["S3_23"] = i["S3_18"] + i["S3_22"]
            i["S3_24"] = i["S3_23"] + comp_taxable
            i["S3_25"] = graduated_tax(max(i["S3_24"], _P0), fiscal_year)
            tax_due = i["S3_25"]
        i.update({"P6_1": tax_due, "P6_2": _P0, "P6_3": _P0, "P6_4": _P0, "P6_5": tax_due})
        i.update({"P7_1": prior_excess, "P7_2": peso(paid_q1_q3), "P7_3": cwt_prior, "P7_4": cwt_q4,
                  "P7_5": peso(inputs.compensation_tax_withheld) if mixed else _P0,
                  "P7_6": amended_paid, "P7_7": _P0, "P7_8": _P0, "P7_9": _P0})
        i["P7_10"] = sum((i[f"P7_{n}"] for n in range(1, 10)), _P0)
        i["22"] = i["P6_5"]
        i["23"] = i["P7_10"]
        i["24"] = i["22"] - i["23"]
        i["25"] = _P0
        i["26"] = i["24"] - i["25"]
        i.update({"27": _P0, "28": _P0, "29": _P0, "30": _P0})
        i["31"] = i["26"] + i["30"]
        i["32"] = i["31"]
        if itemized:
            i.update(_reconciliation(inputs, _RECON_1701))
        payable = i["31"]
        recon_net, recon_key = (i.get("P9_11"), "Part IX") if itemized else (None, None)
    else:  # 1701A
        i = items
        nolco = apply_carry(carry_in.nolco, fiscal_year, _P0, nolco_life, deduct=False)
        if eight:
            i["47"] = peso(sales)
            i["48"] = _P0
            i["49"] = i["47"]
            i["50"] = peso(non_operating)
            i["51"] = _P0
            i["52"] = i["50"] + i["51"]
            i["53"] = i["49"] + i["52"]
            i["54"] = peso(EIGHT_PERCENT_EXEMPTION)
            i["55"] = max(i["53"] - i["54"], _P0)
            i["56"] = peso(i["55"] * EIGHT_PERCENT)
            due = i["56"]
            if i["53"] > EIGHT_PERCENT_CEILING:
                warnings.append(f"Gross sales and other income are {_peso_text(i['53'])}, above ₱3,000,000: the 8% "
                                "option isn't available above that. Switch the company to graduated rates.")
        else:
            i["36"] = peso(sales)
            i["37"] = _P0
            i["38"] = i["36"]
            i["39"] = peso(i["38"] * OSD_RATE)
            i["40"] = i["38"] - i["39"]
            i["41"] = peso(non_operating)
            i["42"] = _P0
            i["43"] = _P0
            i["44"] = i["41"] + i["42"] + i["43"]
            i["45"] = i["40"] + i["44"]
            i["46"] = graduated_tax(max(i["45"], _P0), fiscal_year)
            due = i["46"]
        i.update({"57": prior_excess, "58": peso(paid_q1_q3), "59": cwt_prior, "60": cwt_q4, "61": amended_paid,
                  "62": _P0, "63": _P0})
        i["64"] = sum((i[str(n)] for n in range(57, 64)), _P0)
        i["65"] = due - i["64"]
        i.update({"20": due, "21": i["64"], "22": i["65"], "23": _P0})
        i["24"] = i["22"] - i["23"]
        i.update({"25": _P0, "26": _P0, "27": _P0, "28": _P0})
        i["29"] = i["24"] + i["28"]
        i["30"] = i["29"]
        before_nolco = None
        payable = i["29"]
        recon_net, recon_key = None, None

    option, carried = _overpayment(payable, inputs)
    items["OVERPAYMENT_OPTION"] = option
    carry_out["nolco"] = rows_to_json(nolco.closing)
    carry_out["excess_credits"] = carried
    if form != "1702RT":
        carry_out.pop("excess_mcit", None)

    # 4. Forms, ledgers and warnings.
    forms: dict[str, dict] = {form: items}
    if keeps_inventory:
        forms["COGS"] = cogs_form(cogs)
    forms["Expenses"] = expenses_form(breakdown, depreciation)
    sheet = _balance_sheet(inputs, sum((r["net_book_value"] for r in register), ZERO), warnings)
    if sheet is not None:
        forms["BalanceSheet"] = sheet
    if register:
        ledgers["Depreciation"] = register
    if nolco.schedule:
        ledgers["NOLCO"] = nolco.schedule
    ledgers["QuarterCredits"] = credit_rows
    sawt = build_sawt(lines)
    if sawt:
        ledgers["SAWT"] = sawt
    ledgers["Transactions"] = build_transactions(lines, company.vat_registered)

    review_open = sum(1 for l in lines if l.open_review)
    if review_open:
        warnings.insert(0, f"{review_open} document(s) in this fiscal year still need review — this output is a "
                           "DRAFT.")
    warnings.extend(credit_warnings)
    if nolco.expired:
        warnings.append(f"{_peso_text(nolco.expired)} of NOLCO from {', '.join(map(str, nolco.expired_years))} "
                        "expired unused this year.")
    if not itemized and any(r["year"] != str(fiscal_year) for r in nolco.schedule):
        warnings.append("Under the OSD or the 8% option no NOLCO is deducted, but its carry-over period keeps running.")
    prior_losses = [r for r in nolco.schedule if int(r["year"]) < fiscal_year]
    if form != "1701A" and len(prior_losses) > PRIOR_ROWS_ON_FORM:
        warnings.append("More NOLCO years than the form's rows; the workbook's NOLCO tab lists them all.")
    if recon_key and recon_net is None:
        warnings.append(f"Net income per books wasn't entered, so {recon_key} (reconciliation) is left blank.")
    elif recon_key and before_nolco is not None and recon_net != before_nolco:
        warnings.append(f"{recon_key} ends at {_peso_text(recon_net)}, but taxable income before NOLCO is "
                        f"{_peso_text(before_nolco)}. Add the difference to the reconciling items.")
    capital = total(cost_base(l, company.vat_registered) for l in lines if is_capital_goods(l))
    if capital > 0:
        warnings.append(f"₱{capital:,.2f} of capital goods bought this year are depreciated through the asset "
                        "register, not expensed.")
    if amended and inputs.amended_paid_income_tax == 0:
        warnings.append(ANNUAL_AMENDED_WARNING)
    unsorted = sum(1 for l in lines if l.category == "unsorted")
    if unsorted:
        warnings.append(f"{unsorted} unsorted document(s) were left out. Move them to a folder to include them.")

    return AnnualResult(form, forms, ledgers, warnings, carry_out, review_open)
