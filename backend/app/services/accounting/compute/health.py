"""Client health checks (QBO Client overview → Common issues), pure: wrong-way balances, balances parked in review
accounts, months not closed, bank months not reconciled, "reconciled through", aging over 90 days."""

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.books.chart import Chart
from app.services.accounting.compute.money import ZERO, c2

REVIEW_KEYS = frozenset({"vat_difference"})


def negative_balances(balances: dict[str, Decimal], chart: Chart) -> list[dict]:
    """Asset and liability accounts (not contra) whose balance sits on the wrong side, e.g. negative Cash on hand."""
    out = []
    for a in chart.accounts:
        if a.type not in ("asset", "liability") or a.contra:
            continue
        bal = c2(balances.get(a.code, ZERO))
        wrong = -bal if a.debit_normal else bal
        if wrong > 0:
            out.append({"code": a.code, "name": a.name, "type": a.type, "balance": wrong})
    return out


def review_balances(balances: dict[str, Decimal], chart: Chart) -> list[dict]:
    """Non-zero balances in accounts meant to be emptied: VAT difference for review, any "suspense" account."""
    out = []
    for a in chart.accounts:
        if a.system_key not in REVIEW_KEYS and "suspense" not in a.name.lower():
            continue
        bal = c2(balances.get(a.code, ZERO))
        if bal:
            out.append({"code": a.code, "name": a.name, "type": a.type, "balance": bal})
    return out


def _next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


def months_not_closed(books_start: date | None, closed: set[date], today: date) -> list[date]:
    """Month starts from the books' first month through the last month that has ended, with no close."""
    if books_start is None:
        return []
    out = []
    month = date(books_start.year, books_start.month, 1)
    while _next_month(month) <= today:
        if month not in closed:
            out.append(month)
        month = _next_month(month)
    return out


def unreconciled_months(line_months: set[tuple[str, date]], reconciled: set[tuple[str, date]],
                        today: date) -> list[tuple[str, date]]:
    """(account, month start) with statement lines, no reconciliation, and the month over."""
    return sorted(k for k in line_months if k not in reconciled and _next_month(k[1]) <= today)


def reconciled_through(months: Iterable[tuple[date, date]]) -> date | None:
    """The end of the last month in an unbroken run of reconciled months from the first one."""
    through = None
    for start, end in sorted(months):
        if through is not None and start > through + timedelta(days=1):
            break
        through = end
    return through


def over_90(items) -> tuple[int, Decimal]:
    hits = [i for i in items if i.bucket == "90+"]
    return len(hits), c2(sum((i.open for i in hits), ZERO))
