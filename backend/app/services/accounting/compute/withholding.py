"""Withholding returns from computed EWT and payroll documents (pure): 0619-E, 1601-EQ, QAP and 1601-C."""

from decimal import Decimal

from app.services.accounting.compute.ewt import (
    EwtResult,
    month_in_quarter,
    rate_percent,
)
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


def form_1601eq(ewt: EwtResult, inputs: PeriodInputs,
                filed: dict[int, tuple[Decimal, int]] | None = None) -> dict[str, Decimal | str]:
    """1601-EQ (January 2019): the quarter by ATC, less the two 0619-E remittances.

    Each month's remittance is what was entered, else the filed 0619-E, else the calculated month.
    """
    filed = filed or {}
    items: dict[str, Decimal | str] = {}
    for i, (atc, base, rate, tax) in enumerate(atc_summary(ewt)[:MAX_SCHEDULE_ROWS], start=1):
        items[f"S{i}_ATC"] = atc
        items[f"S{i}_BASE"] = base
        items[f"S{i}_RATE"] = rate_percent(rate)
        items[f"S{i}_TAX"] = tax
    items["19"] = total(r.tax for r in ewt.rows)
    for month, item, entered in ((1, "20", inputs.ewt_remitted_m1), (2, "21", inputs.ewt_remitted_m2)):
        if entered is not None:
            items[item], items[f"_SRC_{item}"] = c2(entered), "entered"
        elif month in filed:
            amount, version = filed[month]
            items[item], items[f"_SRC_{item}"] = c2(amount), f"filed:v{version}"
        else:
            items[item], items[f"_SRC_{item}"] = ewt.month_tax(month), "calculated"
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


NO_PAYROLL = "NO_PAYROLL"


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
    if month.no_payroll:
        i[NO_PAYROLL] = Decimal("1")  # marker, not a form item: a nil return needs no compensation
    return i
