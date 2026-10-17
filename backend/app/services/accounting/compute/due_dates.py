"""Quarter bounds and BIR filing due dates (pure). A deadline on a weekend or a Philippine national holiday moves to
the next working day (Administrative Code, Book I Sec. 31). Eid'l Fitr and Eid'l Adha are proclaimed each year and
aren't modelled."""

import calendar
from datetime import date, timedelta
from functools import lru_cache

# Chinese New Year (special non-working day) follows the lunar calendar.
_CHINESE_NEW_YEAR = {
    2024: date(2024, 2, 10), 2025: date(2025, 1, 29), 2026: date(2026, 2, 17), 2027: date(2027, 2, 6),
    2028: date(2028, 1, 26), 2029: date(2029, 2, 13), 2030: date(2030, 2, 3),
}


def _easter(year: int) -> date:
    """Western Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def ph_holidays(year: int) -> frozenset[date]:
    """Regular holidays and the special non-working days declared every year (RA 9492, RA 9256, RA 10966 and the
    yearly proclamations). Days only some years' proclamations add, like November 2, are left out so a deadline is
    never shown later than it is."""
    easter = _easter(year)
    last_day_aug = date(year, 8, 31)
    heroes = last_day_aug - timedelta(days=last_day_aug.weekday())  # last Monday of August
    days = {
        date(year, 1, 1), easter - timedelta(days=3), easter - timedelta(days=2), easter - timedelta(days=1),
        date(year, 4, 9), date(year, 5, 1), date(year, 6, 12), date(year, 8, 21), heroes,
        date(year, 11, 1), date(year, 11, 30), date(year, 12, 8),
        date(year, 12, 24), date(year, 12, 25), date(year, 12, 30), date(year, 12, 31),
    }
    if year in _CHINESE_NEW_YEAR:
        days.add(_CHINESE_NEW_YEAR[year])
    return frozenset(days)


def _end_month(quarter: int, fye: int) -> int:
    return (fye + quarter * 3 - 1) % 12 + 1


def quarter_end(fiscal_year: int, quarter: int, fye: int = 12) -> date:
    month = _end_month(quarter, fye)
    year = fiscal_year if month <= fye else fiscal_year - 1
    return date(year, month, calendar.monthrange(year, month)[1])


def quarter_start(fiscal_year: int, quarter: int, fye: int = 12) -> date:
    end = quarter_end(fiscal_year, quarter, fye)
    month, year = end.month - 2, end.year
    if month < 1:
        month, year = month + 12, year - 1
    return date(year, month, 1)


def _next_business_day(day: date) -> date:
    while day.weekday() >= 5 or day in ph_holidays(day.year):
        day += timedelta(days=1)
    return day


def _add_months(first: date, n: int) -> date:
    index = first.month - 1 + n
    return date(first.year + index // 12, index % 12 + 1, 1)


def month_start(fiscal_year: int, quarter: int, fye: int, month: int) -> date:
    """First day of month 1–3 of the quarter."""
    return _add_months(quarter_start(fiscal_year, quarter, fye), month - 1)


_INDIVIDUAL_DUE = {1: (5, 15), 2: (8, 15), 3: (11, 15)}


def due_dates(forms, fiscal_year: int, quarter: int, fye: int = 12) -> dict[str, date]:
    end = quarter_end(fiscal_year, quarter, fye)
    out: dict[str, date] = {}
    for form in forms:
        if form in ("2550Q", "2551Q"):
            out[form] = _next_business_day(end + timedelta(days=25))
        elif form == "1702Q":
            out[form] = _next_business_day(end + timedelta(days=60))
        elif form == "1701Q" and quarter in _INDIVIDUAL_DUE:
            month, day = _INDIVIDUAL_DUE[quarter]
            out[form] = _next_business_day(date(end.year, month, day))
        elif form.startswith(("0619E-M", "1601C-M")):
            following = _add_months(month_start(fiscal_year, quarter, fye, int(form[-1])), 1)
            if form.startswith("1601C") and following.month == 1:
                out[form] = _next_business_day(date(following.year, 1, 15))
            else:
                out[form] = _next_business_day(date(following.year, following.month, 10))
        elif form == "1601EQ":
            following = _add_months(date(end.year, end.month, 1), 1)
            last = calendar.monthrange(following.year, following.month)[1]
            out[form] = _next_business_day(date(following.year, following.month, last))
    return out


def annual_due_date(form: str, fiscal_year: int, fye: int = 12) -> date:
    """1702-RT: the 15th day of the 4th month after year end. 1701 / 1701-A: April 15 of the next year."""
    if form == "1702RT":
        end = quarter_end(fiscal_year, 4, fye)
        due = _add_months(date(end.year, end.month, 1), 4)
        return _next_business_day(date(due.year, due.month, 15))
    return _next_business_day(date(fiscal_year + 1, 4, 15))


def alphalist_due_date(year: int) -> date:
    """1604-C (annual information return of income taxes withheld on compensation): January 31 of the next year."""
    return _next_business_day(date(year + 1, 1, 31))
