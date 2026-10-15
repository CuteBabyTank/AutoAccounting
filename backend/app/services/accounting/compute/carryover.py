"""NOLCO and excess MCIT carried across taxable years (pure).

A row is usable in the years after it arose, up to ``year + life``; whatever is still
unapplied in that last year expires. Rows are applied oldest first.
"""

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation

from app.services.accounting.compute.money import ZERO, c2

MAX_ROWS = 20


@dataclass(frozen=True)
class CarryRow:
    year: int
    amount: Decimal
    used: Decimal = ZERO
    normal_tax: Decimal | None = None
    mcit: Decimal | None = None


@dataclass(frozen=True)
class CarryResult:
    applied: Decimal
    expired: Decimal
    expired_years: tuple[int, ...]
    closing: tuple[CarryRow, ...]
    schedule: list[dict]


def nolco_life(year: int) -> int:
    """RR 25-2020: losses of taxable years 2020 and 2021 carry over for 5 years, others for 3."""
    return 5 if year in (2020, 2021) else 3


def mcit_life(year: int) -> int:
    return 3


def _row_out(row: CarryRow, life, used_now: Decimal, expired: Decimal, left: Decimal) -> dict:
    return {"key": str(row.year), "year": str(row.year), "amount": c2(row.amount),
            "normal_tax": "" if row.normal_tax is None else c2(row.normal_tax),
            "mcit": "" if row.mcit is None else c2(row.mcit), "used_before": c2(row.used),
            "used_this_year": used_now, "expired_this_year": expired, "remaining": left,
            "expiry_year": str(row.year + life(row.year))}


def apply_carry(rows, fiscal_year: int, budget, life, *, deduct: bool = True) -> CarryResult:
    left_to_apply = max(c2(budget), ZERO) if deduct else ZERO
    applied = expired = ZERO
    expired_years: list[int] = []
    closing: list[CarryRow] = []
    schedule: list[dict] = []
    for row in sorted(rows, key=lambda r: r.year):
        last = row.year + life(row.year)
        if row.year >= fiscal_year or fiscal_year > last:
            continue
        remaining = max(c2(row.amount - row.used), ZERO)
        used_now = min(remaining, left_to_apply)
        left_to_apply = c2(left_to_apply - used_now)
        gone = c2(remaining - used_now) if fiscal_year == last else ZERO
        left = c2(remaining - used_now - gone)
        schedule.append(_row_out(row, life, used_now, gone, left))
        applied, expired = c2(applied + used_now), c2(expired + gone)
        if gone > 0:
            expired_years.append(row.year)
        if left > 0:
            closing.append(replace(row, amount=c2(row.amount), used=c2(row.used + used_now)))
    return CarryResult(applied, expired, tuple(expired_years), tuple(closing), schedule)


def add_new(result: CarryResult, year: int, amount, life, normal_tax=None, mcit=None) -> CarryResult:
    amount = c2(amount)
    if amount <= 0:
        return result
    row = CarryRow(year, amount, ZERO, normal_tax, mcit)
    return replace(result, closing=result.closing + (row,),
                   schedule=result.schedule + [_row_out(row, life, ZERO, ZERO, amount)])


def _money(value) -> Decimal | None:
    try:
        return c2(value)
    except (InvalidOperation, TypeError, ValueError):
        return None


def rows_from_json(raw) -> tuple[CarryRow, ...]:
    rows: list[CarryRow] = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_ROWS]:
        if not isinstance(item, dict):
            continue
        try:
            year = int(item.get("year"))
        except (TypeError, ValueError):
            continue
        amount = _money(item.get("amount"))
        used = _money(item.get("used") or "0")
        if not 2000 <= year <= 2100 or amount is None or amount <= 0 or used is None or used < 0:
            continue
        rows.append(CarryRow(year, amount, used, _money(item["normal_tax"]) if item.get("normal_tax") else None,
                             _money(item["mcit"]) if item.get("mcit") else None))
    return tuple(rows)


def rows_to_json(rows) -> list[dict]:
    out = []
    for r in rows:
        item = {"year": r.year, "amount": str(c2(r.amount)), "used": str(c2(r.used))}
        if r.normal_tax is not None:
            item["normal_tax"] = str(c2(r.normal_tax))
        if r.mcit is not None:
            item["mcit"] = str(c2(r.mcit))
        out.append(item)
    return out
