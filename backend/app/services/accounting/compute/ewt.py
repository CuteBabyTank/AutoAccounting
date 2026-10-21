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
from app.services.accounting.compute.money import c2, total
from app.services.atc_codes import lookup_atc

ATC_NONE = "NONE"
_EXTRA = {"WC120": ("Contractors", Decimal("0.02"))}  # corporate contractors, missing from atc_codes.py
_CORPORATE_WORDS = frozenset({
    "INC", "INCORPORATED", "CORP", "CORPORATION", "COMPANY", "LTD", "LIMITED", "OPC", "LLC",
    "COOPERATIVE", "COOP", "PARTNERSHIP", "PARTNERS",
})
_TWA_GOODS = frozenset({"purchases", "raw_materials", "office_supplies", "capital_goods"})
_TWA_SERVICES = frozenset({"transportation", "other"})
_GOODS_NATURES = frozenset({"goods_for_resale", "raw_materials", "capital_goods", "other"})
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


_CO_ABBREVIATION = re.compile(r"\bCO\.|&\s*CO\b")  # "Co." or "& Co"; a bare "Co" is a common surname


def is_corporate_name(name: str) -> bool:
    upper = (name or "").upper()
    if _CO_ABBREVIATION.search(upper):
        return True
    return any(word in _CORPORATE_WORDS for word in re.findall(r"[A-Z]+", upper))


def is_agent(company: CompanyFacts) -> bool:
    return company.is_withholding_agent or company.is_top_withholding_agent


def _is_payment(line: DocLine) -> bool:
    return line.client_role == "buyer" and line.category in _PAYMENTS and line.account != "drawings"


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
        return "WI010"  # default suggestion; a higher-rate ATC requires the reviewer's choice
    goods = line.nature in _GOODS_NATURES  # e.g. parts or materials booked to repairs: not a contractor's fee
    if line.account == "repairs" and not goods:
        return f"{prefix}120"
    if company.is_top_withholding_agent:
        if line.account in _TWA_GOODS or (line.account == "repairs" and goods):
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
    return c2(line.gross - line.vat - line.vat_difference) if line.vat > 0 else c2(line.gross)


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
    outside = not_withheld = mismatched = no_atc = unknown = credits = 0
    for l in lines:
        if not _is_payment(l):
            continue
        chosen = (l.ewt_atc or "").strip().upper()
        if chosen and chosen != ATC_NONE and atc_info(chosen) is None:
            unknown += 1
            continue
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
        if tax < 0:
            credits += 1
        elif l.withholding == 0 and tax > 0:
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
    if credits:
        warnings.append(f"{credits} credit(s) with a negative amount reduce the expanded withholding tax for their "
                        "month.")
    if outside:
        warnings.append(f"{outside} payment(s) are dated outside this quarter's months and were counted in "
                        "month 3.")
    return EwtResult(rows, warnings)
