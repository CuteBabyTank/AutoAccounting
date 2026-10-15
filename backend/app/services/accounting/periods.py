"""Fiscal period arithmetic for AutoAccounting (pure)."""

from dataclasses import dataclass
from datetime import date

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Period:
    fiscal_year: int       # the calendar year the fiscal year ends in
    quarter: int           # 1..4
    month_in_quarter: int  # 1..3


def _check_fye(fiscal_year_end_month: int) -> None:
    if not 1 <= fiscal_year_end_month <= 12:
        raise ValueError("fiscal_year_end_month must be between 1 and 12")


def period_for(d: date, fiscal_year_end_month: int = 12) -> Period:
    """The fiscal period a document dated ``d`` belongs to."""
    _check_fye(fiscal_year_end_month)
    start_month = fiscal_year_end_month % 12 + 1
    offset = (d.month - start_month) % 12
    fiscal_year = d.year if d.month <= fiscal_year_end_month else d.year + 1
    return Period(fiscal_year, offset // 3 + 1, offset % 3 + 1)


def quarter_label(quarter: int, fiscal_year_end_month: int = 12) -> str:
    """Human label with the quarter's calendar months, e.g. ``Q3 (Jul–Sep)``."""
    _check_fye(fiscal_year_end_month)
    if not 1 <= quarter <= 4:
        raise ValueError("quarter must be between 1 and 4")
    first = (fiscal_year_end_month + (quarter - 1) * 3) % 12
    last = (first + 2) % 12
    return f"Q{quarter} ({_MONTHS[first]}–{_MONTHS[last]})"


def period_fields(d: date | None, fiscal_year_end_month: int = 12) -> tuple[int | None, int | None, int | None]:
    """(fiscal_year, quarter, month_in_quarter) for a document date, all None when undated."""
    if d is None:
        return None, None, None
    p = period_for(d, fiscal_year_end_month)
    return p.fiscal_year, p.quarter, p.month_in_quarter
