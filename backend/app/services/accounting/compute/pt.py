"""Quarterly percentage tax return, BIR Form 2551-Q (January 2018 ENCS). Pure."""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.inputs import PeriodInputs
from app.services.accounting.compute.money import ZERO, c2, total

PT_RATE = Decimal("0.03")  # ATC PT 010, persons exempt from VAT under Sec. 109(BB)
# CREATE Act (RA 11534) Sec. 116: 1% from July 1, 2020 to June 30, 2023.
PT_RELIEF = (date(2020, 7, 1), date(2023, 6, 30))
PT_RELIEF_RATE = Decimal("0.01")


def pt_rate(day: date | None) -> Decimal:
    return PT_RELIEF_RATE if day is not None and PT_RELIEF[0] <= day <= PT_RELIEF[1] else PT_RATE


def compute_2551q(lines, inputs: PeriodInputs, period_end: date | None = None) -> dict[str, Decimal | str]:
    """Sales are taxed at the rate in force on their date (undated ones at the quarter end's); a quarter that
    straddles June 30, 2023 shows the blended rate."""
    sales = [l for l in lines if l.category == "sales"]
    taxable = total(l.gross for l in sales)
    due = c2(total(l.gross * pt_rate(l.doc_date or period_end) for l in sales))
    rate = (due / taxable * 100).quantize(Decimal("0.01")).normalize() if taxable else pt_rate(period_end) * 100
    i: dict[str, Decimal | str] = {
        "S1_1_ATC": "PT 010",
        "S1_1_TAXABLE": taxable,
        "S1_1_RATE": rate.normalize(),
        "S1_1_DUE": due,
        "S1_7": due,
        "14": due,
        "15": c2(inputs.percentage_tax_withheld),
        "16": c2(inputs.amended_paid_business_tax),
        "17": ZERO,
    }
    i["18"] = total([i["15"], i["16"], i["17"]])
    i["19"] = c2(i["14"] - i["18"])
    for key in ("20", "21", "22", "23"):
        i[key] = ZERO
    i["24"] = c2(i["19"] + i["23"])
    return i
