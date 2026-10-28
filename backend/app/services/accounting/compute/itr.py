"""Quarterly income tax: 1701-Q (individuals) and 1702-Q (non-individuals), January 2018 ENCS. Pure.

Both returns are cumulative within the fiscal year: each quarter reports this
quarter, adds the previous quarters, computes tax to date and subtracts what was
already paid or withheld. ``quarters`` is Q1..current with the current quarter last.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.inputs import CompanyFacts, PeriodInputs
from app.services.accounting.compute.money import peso

OSD_RATE = Decimal("0.40")
MCIT_RATE = Decimal("0.02")
# CREATE Act (RA 11534) Sec. 27(E): MCIT was 1% from July 1, 2020 to June 30, 2023.
CREATE_RELIEF = (date(2020, 7, 1), date(2023, 6, 30))
MCIT_RELIEF_RATE = Decimal("0.01")
EIGHT_PERCENT = Decimal("0.08")
EIGHT_PERCENT_EXEMPTION = Decimal("250000")
_TABLE_1 = (  # TRAIN, taxable years 2018 to 2022
    (Decimal("8000000"), Decimal("2410000"), Decimal("0.35")),
    (Decimal("2000000"), Decimal("490000"), Decimal("0.32")),
    (Decimal("800000"), Decimal("130000"), Decimal("0.30")),
    (Decimal("400000"), Decimal("30000"), Decimal("0.25")),
    (Decimal("250000"), Decimal("0"), Decimal("0.20")),
)
_TABLE_2 = (  # (over, base tax, rate on the excess), effective January 1, 2023
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
    gross_income: Decimal | None = None  # for the MCIT base (1702-Q Schedule 3)


def graduated_tax(income: Decimal, year: int | None = None) -> Decimal:
    """Sec. 24(A)(2) tax on taxable income; ``year`` picks the TRAIN table (2022 and before) or the 2023 one."""
    for over, base, rate in (_TABLE_1 if year is not None and year < 2023 else _TABLE_2):
        if income > over:
            return peso(base + (income - over) * rate)
    return _P0


def mcit_rate(fiscal_year: int | None, fye: int = 12, through_quarter: int = 4) -> Decimal:
    """MCIT rate for the fiscal year up to the end of ``through_quarter``: 2%, or 1% for months in the CREATE relief
    period, weighted by month when the period straddles it (RMC 69-2023: calendar 2023 is 1.5%)."""
    if fiscal_year is None:
        return MCIT_RATE
    first, last = quarter_start(fiscal_year, 1, fye), quarter_end(fiscal_year, through_quarter, fye)
    months = relief = 0
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        months += 1
        relief += CREATE_RELIEF[0] <= date(year, month, 1) <= CREATE_RELIEF[1]
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return (MCIT_RELIEF_RATE * relief + MCIT_RATE * (months - relief)) / months


def _credits(inputs: PeriodInputs, paid_before: Decimal, cwt_before: Decimal, cwt_now: Decimal) -> list[Decimal]:
    return [peso(inputs.prior_year_excess_credits), peso(paid_before), peso(cwt_before), peso(cwt_now)]


def compute_1702q(quarters: list[QuarterFigures], company: CompanyFacts, inputs: PeriodInputs,
                  prior: PriorOverride | None = None, fiscal_year: int | None = None) -> dict[str, Decimal]:
    osd = company.deduction_method == "osd"
    rate = Decimal(inputs.cit_rate) / 100
    prev_taxable, paid, cwt_prev = _P0, _P0, _P0
    gross_by_quarter: list[Decimal] = []
    target_quarter = len(quarters)
    if prior is not None:
        quarters = quarters[-1:]
        prev_taxable, paid, cwt_prev = peso(prior.taxable_income), peso(prior.tax_paid), peso(prior.cwt)
        gross_by_quarter.append(peso(prior.gross_income or _P0))
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
        quarter_no = target_quarter - (len(quarters) - 1 - index)
        mcit = mcit_rate(fiscal_year, company.fiscal_year_end_month, quarter_no)
        s3_6 = peso(max(mcit_base, _P0) * mcit) if inputs.mcit_applies else _P0
        s13 = max(s11, s3_6)
        c1, c2_, c4, c5 = _credits(inputs, paid, cwt_prev, f.cwt)
        c6 = peso(inputs.amended_paid_income_tax) if index == len(quarters) - 1 else _P0  # this return only
        s4_7 = c1 + c2_ + c4 + c5 + c6
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
        if prior is not None:  # earlier quarters are one entered total, shown under the 1st quarter
            slots = {n: _P0 for n in range(1, 4)}
            slots[1] = gross_by_quarter[0]
            if target_quarter <= 3:
                slots[target_quarter] = gross_by_quarter[-1]
        else:
            slots = dict(enumerate(gross_by_quarter[:3], start=1))
        for n, gross in slots.items():
            items[f"S3_{n}"] = gross
        items.update({"S3_4": peso(mcit_base), "S3_5": (mcit * 100).normalize(), "S3_6": s3_6})
        items.update({"S4_1": c1, "S4_2": c2_, "S4_3": _P0, "S4_4": c4, "S4_5": c5, "S4_6": c6, "S4_7": s4_7})
        items.update({"14": s13, "15": _P0, "16": s13, "17": _P0, "18": s13, "19": s4_7, "20": payable,
                      "21": _P0, "22": _P0, "23": _P0, "24": _P0, "25": payable})
    return items


def compute_1701q(quarters: list[QuarterFigures], company: CompanyFacts, inputs: PeriodInputs,
                  prior: PriorOverride | None = None, year: int | None = None) -> dict[str, Decimal]:
    eight = company.income_tax_option == "eight_percent"
    osd = company.deduction_method == "osd"
    # The ₱250,000 reduction is for purely self-employed individuals, not mixed-income earners (RR 8-2018).
    reduction = _P0 if company.has_compensation_income else EIGHT_PERCENT_EXEMPTION
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
            i53 = max(i51 - reduction, _P0)
            due = peso(i53 * EIGHT_PERCENT)
            cumulative = i51
            schedule = {"47": i47, "48": i48, "49": i49, "50": i50, "51": i51, "52": reduction,
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
            due = graduated_tax(i45, year)
            cumulative = i45
            schedule = {"36": i36, "37": i37, "38": i38, "39": i39, "40": i40, "41": i41, "42": i42, "43": i43,
                        "44": _P0, "45": i45, "46": due}
        c55, c56, c57, c58 = _credits(inputs, paid, cwt_prev, f.cwt)
        i59 = peso(inputs.amended_paid_income_tax) if index == len(quarters) - 1 else _P0  # this return only
        i62 = c55 + c56 + c57 + c58 + i59
        payable = due - i62
        if index < len(quarters) - 1:
            prev_cum = cumulative
            paid = paid + max(payable, _P0)
            cwt_prev = cwt_prev + peso(f.cwt)
            continue
        items = dict(schedule)
        items.update({"55": c55, "56": c56, "57": c57, "58": c58, "59": i59, "60": _P0, "61": _P0, "62": i62,
                      "63": payable, "64": _P0, "65": _P0, "66": _P0, "67": _P0, "68": payable})
    return items
