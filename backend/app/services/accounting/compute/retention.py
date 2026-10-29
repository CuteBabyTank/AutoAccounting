"""Deletion protection for retained accounting history (pure; archiving never deletes that history)."""
from datetime import date
from collections.abc import Iterable

from app.services.accounting.periods import period_for
from app.services.accounting.compute.due_dates import quarter_end


def deletion_problem(dates: Iterable[date], periods: Iterable[tuple[int, int]],
                     closes: Iterable[tuple[date, date]], filed: set[tuple[int, int]], fye: int,
                     *, from_date: date | None = None) -> str | None:
    days = set(dates)
    for start, end in closes:
        if any(start <= d <= end for d in days) or (from_date is not None and end >= from_date):
            return f"{start:%B %Y} is closed. Reopen the month before deleting; retained books cannot be removed."
    affected = set(periods)
    for d in days:
        p = period_for(d, fye)
        affected.add((p.fiscal_year, p.quarter))
    affected |= {(y, 0) for y, _ in affected}
    # YTD income tax, excess VAT and inventory carry forward, including across fiscal years.
    later_filing = any(q != 0 and (fy, fq or 5) >= (y, q) for y, q in affected for fy, fq in filed)
    if affected & filed or later_filing or (from_date is not None and any(
        quarter_end(y, q or 4, fye) >= from_date for y, q in filed
    )):
        return "This record affects a filed return. Correct it through an amendment or journal entry instead of deleting it."
    return None
