"""Fill the official BIR returns (other than the 2550-Q) from a version's stored values."""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from app.forms import (
    bir0619e_layout, bir1601c_layout, bir1601eq_layout, bir1701_layout, bir1701a_layout, bir1701q_layout,
    bir1702q_layout, bir1702rt_layout, bir2551q_layout,
)
from app.forms.overlay import FormLayout
from app.services.accounting.compute.due_dates import due_dates, month_start, quarter_end, quarter_start
from app.services.accounting.pdf_overlay import Rendered, render_form

LAYOUTS: dict[str, FormLayout] = {
    "2551Q": bir2551q_layout.LAYOUT, "1701Q": bir1701q_layout.LAYOUT, "1702Q": bir1702q_layout.LAYOUT,
    "0619E": bir0619e_layout.LAYOUT, "1601EQ": bir1601eq_layout.LAYOUT, "1601C": bir1601c_layout.LAYOUT,
    "1702RT": bir1702rt_layout.LAYOUT, "1701": bir1701_layout.LAYOUT, "1701A": bir1701a_layout.LAYOUT,
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
    contact_number: str = ""
    email: str = ""
    has_compensation_income: bool = False

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
        contact_number=str(company.get("contact_number") or ""), email=str(company.get("email") or ""),
        has_compensation_income=bool(company.get("has_compensation_income", False)),
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


def _nonzero(values: dict[str, str], key: str) -> bool:
    try:
        return Decimal(values.get(key) or "0") != 0
    except InvalidOperation:
        return False


def _identity(layout: FormLayout, h: ReturnHeader) -> dict[str, str]:
    cells: dict[str, str] = {}
    tin = h.tin[:9]
    cells["tin"] = tin + h.branch_code[:5] if len(layout.cells["tin"].cells) > 9 else tin
    cells["rdo"] = h.rdo_code[:3]
    for keys, text in ((("name", "name_2", "name_3"), h.name), (("address", "address_2", "address_3"), h.address)):
        present = [k for k in keys if k in layout.cells]
        for key, part in zip(present, wrap(text, [len(layout.cells[k].cells) for k in present])):
            cells[key] = part
    cells["zip"] = h.zip_code[:4]
    if "contact" in layout.cells:
        cells["contact"] = h.contact_number
    if "email" in layout.cells:
        cells["email"] = h.email
    for key, spec in layout.cells.items():  # the TIN and name strip repeated atop pages 2 onwards
        if re.fullmatch(r"tin_p\d+", key):
            cells[key] = tin + h.branch_code[:5] if len(spec.cells) > 9 else tin
        elif re.fullmatch(r"name_p\d+", key):
            cells[key] = wrap(h.name, [len(spec.cells)])[0] if h.name else ""
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


# Descriptions printed beside lines the forms leave for the filer to "specify".
_DESCRIPTIONS = {
    "S1_17D": "OTHERS - SEE ATTACHED WORKBOOK", "S4_17D": "OTHERS - SEE ATTACHED WORKBOOK",
    "S3_19": "OTHER INCOME", "41": "OTHER INCOME", "50": "OTHER INCOME",
    "S5_2": "NON-DEDUCTIBLE EXPENSES", "S5_3": "OTHER RECONCILING ITEMS", "S5_5": "NON-TAXABLE INCOME",
    "S5_7": "OTHER RECONCILING ITEMS", "P9_2": "NON-DEDUCTIBLE EXPENSES", "P9_3": "OTHER RECONCILING ITEMS",
    "P9_6": "NON-TAXABLE INCOME", "P9_8": "OTHER RECONCILING ITEMS",
}


def _annual_common(values, h, layout, amended) -> _Fill:
    fill = _Fill(checks=["amended_yes" if amended else "amended_no", "short_no"])
    for key, value in values.items():
        if key.endswith("_YEAR") and key in layout.cells:
            fill.cells[key] = str(value)
    for key, text in _DESCRIPTIONS.items():
        if f"{key}_DESC" in layout.cells and _nonzero(values, key):
            fill.cells[f"{key}_DESC"] = text
    option = values.get("OVERPAYMENT_OPTION", "")
    if option in ("refund", "tcc", "carry_over"):
        fill.checks.append(option)
    return fill


def _fill_1702rt(values, h, amended, month) -> _Fill:
    fill = _annual_common(values, h, LAYOUTS["1702RT"], amended)
    fill.cells.update({"year_month": f"{h.fiscal_year_end_month:02d}", "year_yy": f"{h.fiscal_year % 100:02d}",
                       "40": values.get("40", "")})
    fill.checks += ["calendar" if h.fiscal_year_end_month == 12 else "fiscal", "atc_IC055",
                    "osd" if h.deduction_method == "osd" else "itemized"]
    return fill


def _fill_1701(values, h, amended, month) -> _Fill:
    fill = _annual_common(values, h, LAYOUTS["1701"], amended)
    fill.cells["year"] = str(h.fiscal_year)
    eight = h.income_tax_option == "eight_percent"
    if h.has_compensation_income:  # mixed income: II013 graduated, II017 8% on business plus graduated on salary
        atc = "atc_II017" if eight else "atc_II013"
        fill.checks += ["compensation_earner"]
    else:
        atc = "atc_II015" if eight else "atc_II012"
    fill.checks += ["single_proprietor", atc, "foreign_credits_no", "exempt_no", "special_no"]
    fill.checks += ["rate_eight"] if eight else ["rate_graduated", "osd" if h.deduction_method == "osd" else "itemized"]
    return fill


def _fill_1701a(values, h, amended, month) -> _Fill:
    eight = h.income_tax_option == "eight_percent"
    fill = _annual_common(values, h, LAYOUTS["1701A"], amended)
    fill.cells.update({"year_month": f"{h.fiscal_year_end_month:02d}", "year": str(h.fiscal_year)})
    fill.checks += ["single_proprietor", "atc_II015" if eight else "atc_II012", "foreign_credits_no",
                    "rate_eight" if eight else "rate_osd"]
    return fill


_FILLERS = {"2551Q": _fill_2551q, "1701Q": _fill_1701q, "1702Q": _fill_1702q, "0619E": _fill_0619e,
            "1601EQ": _fill_1601eq, "1601C": _fill_1601c, "1702RT": _fill_1702rt, "1701": _fill_1701,
            "1701A": _fill_1701a}


def render_return(form: str, values: dict[str, str], header: ReturnHeader, *,
                  highlights: frozenset[str] = frozenset(), amended: bool = False,
                  draft_reviews: int = 0, missing: Sequence[str] = ()) -> Rendered:
    base, month = split_form(form)
    if base not in _FILLERS:
        raise ValueError(f"No PDF layout for {form}")
    layout = LAYOUTS[base]
    fill = _FILLERS[base](values, header, amended, month)
    cells = {**_identity(layout, header), **fill.cells}
    marked = set(highlights) | {key for key, source in fill.sources.items() if source in highlights}
    return render_form(layout, amounts={**values, **fill.extra}, cells=cells, checks=fill.checks,
                       highlights=frozenset(marked), draft_reviews=draft_reviews, notes=fill.notes,
                       missing=missing)
