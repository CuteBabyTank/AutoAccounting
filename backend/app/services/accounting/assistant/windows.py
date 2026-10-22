"""Relative assistant windows resolved from the server's Manila date (pure)."""

import calendar
from datetime import date, timedelta
from typing import Literal

from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.reports import fy_start
from app.services.accounting.periods import period_for

ReportPeriod = Literal["this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year"]
REPORT_PERIODS = ("this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year")


def day_window(today: date, *, within_days: int | None = None,
               past_days: int | None = None) -> tuple[date, date] | None:
    """Inclusive due-date bounds; relative windows replace both model-supplied dates."""
    for name, days in (("within_days", within_days), ("past_days", past_days)):
        if days is not None and (type(days) is not int or not 1 <= days <= 366):
            raise ValueError(f"{name} must be an integer from 1 to 366")
    if within_days is not None and past_days is not None:
        raise ValueError("Use within_days or past_days, not both")
    if within_days is not None:
        return today, today + timedelta(days=within_days)
    if past_days is not None:
        return today - timedelta(days=past_days), today
    return None


def report_window(today: date, fye: int, period: ReportPeriod) -> tuple[date, date]:
    """Full calendar months / fiscal quarters; this_year is fiscal year to date."""
    if period not in REPORT_PERIODS:
        raise ValueError(f"period must be one of {', '.join(REPORT_PERIODS)}")
    if period in ("this_month", "last_month"):
        first = today.replace(day=1)
        if period == "last_month":
            first = (first - timedelta(days=1)).replace(day=1)
        return first, first.replace(day=calendar.monthrange(first.year, first.month)[1])
    if period in ("this_quarter", "last_quarter"):
        where = period_for(today, fye)
        if period == "last_quarter":
            where = period_for(quarter_start(where.fiscal_year, where.quarter, fye) - timedelta(days=1), fye)
        return quarter_start(where.fiscal_year, where.quarter, fye), quarter_end(where.fiscal_year, where.quarter, fye)
    first = fy_start(today, fye)
    if period == "this_year":
        return first, today
    last = first - timedelta(days=1)
    return fy_start(last, fye), last


FormPeriod = Literal["this_month", "last_month", "this_quarter", "last_quarter"]
FORM_PERIODS = ("this_month", "last_month", "this_quarter", "last_quarter")


def form_period(today: date, fye: int, period: FormPeriod) -> tuple[int, int, int | None]:
    """(fiscal year, fiscal quarter, month of that quarter) of a relative period; the month is None for a quarter."""
    if period not in FORM_PERIODS:
        raise ValueError(f"period must be one of {', '.join(FORM_PERIODS)}")
    where = period_for(report_window(today, fye, period)[0], fye)
    return where.fiscal_year, where.quarter, where.month_in_quarter if period.endswith("month") else None
