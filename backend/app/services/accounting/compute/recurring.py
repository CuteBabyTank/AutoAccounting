"""Recurring journal entry schedules (pure): the next occurrence and the occurrences due by a date.

A template keeps an anchor day (1–31): a rent accrual on the 31st posts on Feb 28 and is back on Mar 31.
"""

import calendar
from datetime import date

FREQUENCIES = {"monthly": 1, "quarterly": 3}


def _on_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def add_period(d: date, frequency: str, anchor_day: int) -> date:
    """The occurrence after ``d``."""
    if frequency not in FREQUENCIES:
        raise ValueError(f"Unknown frequency {frequency!r}")
    months = d.year * 12 + d.month - 1 + FREQUENCIES[frequency]
    return _on_day(months // 12, months % 12 + 1, max(1, min(anchor_day, 31)))


def due_dates(next_date: date, frequency: str, anchor_day: int, through: date, end_date: date | None,
              limit: int = 24) -> list[date]:
    """Occurrences from ``next_date`` up to ``through`` (and ``end_date``), at most ``limit``."""
    out: list[date] = []
    d = next_date
    while d <= through and (end_date is None or d <= end_date) and len(out) < limit:
        out.append(d)
        d = add_period(d, frequency, anchor_day)
    return out
