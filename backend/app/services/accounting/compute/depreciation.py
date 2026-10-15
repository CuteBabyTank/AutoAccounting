"""Straight-line depreciation from the asset register (pure).

The month an asset goes into service counts as a full month. Each month is cost ÷ life
rounded to centavos; the last month takes the remainder so the total equals cost.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.accounting.compute.due_dates import quarter_end, quarter_start
from app.services.accounting.compute.money import ZERO, c2, total

DEFAULT_LIFE_MONTHS = 60


@dataclass(frozen=True)
class Asset:
    id: str
    document_id: str
    description: str
    doc_number: str
    cost: Decimal
    in_service: date
    life_months: int = DEFAULT_LIFE_MONTHS
    end_date: date | None = None


def _month(d: date) -> int:
    return d.year * 12 + d.month - 1


def monthly_amounts(asset: Asset) -> list[Decimal]:
    months = max(int(asset.life_months), 1)
    cost = c2(asset.cost)
    if cost <= 0:
        return [ZERO] * months
    monthly = c2(cost / months)
    amounts: list[Decimal] = []
    booked = ZERO
    for index in range(months):
        left = c2(cost - booked)
        amount = left if index == months - 1 else min(monthly, left)
        amounts.append(amount)
        booked = c2(booked + amount)
    return amounts


def _booked(asset: Asset, first: int, last: int) -> Decimal:
    start = _month(asset.in_service)
    stop = _month(asset.end_date) if asset.end_date else None
    return total(amount for offset, amount in enumerate(monthly_amounts(asset))
                 if first <= start + offset <= last and (stop is None or start + offset <= stop))


def depreciation_between(asset: Asset, start: date, end: date) -> Decimal:
    return _booked(asset, _month(start), _month(end))


def fiscal_year_window(fiscal_year: int, fye: int = 12) -> tuple[date, date]:
    return quarter_start(fiscal_year, 1, fye), quarter_end(fiscal_year, 4, fye)


def register_rows(assets, start: date, end: date) -> list[dict]:
    rows = []
    for a in sorted(assets, key=lambda x: (x.in_service, x.description, x.id)):
        if a.in_service > end:
            continue
        before = _booked(a, 0, _month(start) - 1)
        this_year = depreciation_between(a, start, end)
        accumulated = c2(before + this_year)
        rows.append({
            "key": a.id, "description": a.description, "doc_number": a.doc_number,
            "in_service": a.in_service.isoformat(), "cost": c2(a.cost), "life_months": str(a.life_months),
            "end_date": a.end_date.isoformat() if a.end_date else "", "accumulated_start": before,
            "this_year": this_year, "accumulated_end": accumulated, "net_book_value": c2(c2(a.cost) - accumulated),
        })
    return rows
