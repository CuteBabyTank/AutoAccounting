"""Recurring journal entry schedules (pure)."""

from datetime import date

import pytest

from app.services.accounting.compute.recurring import add_period, due_dates


def test_monthly_keeps_the_anchor_day_through_short_months():
    assert add_period(date(2026, 1, 31), "monthly", 31) == date(2026, 2, 28)
    assert add_period(date(2026, 2, 28), "monthly", 31) == date(2026, 3, 31)
    assert add_period(date(2028, 1, 31), "monthly", 31) == date(2028, 2, 29)
    assert add_period(date(2026, 12, 15), "monthly", 15) == date(2027, 1, 15)


def test_quarterly_steps_three_months():
    assert add_period(date(2026, 11, 30), "quarterly", 30) == date(2027, 2, 28)
    assert add_period(date(2027, 2, 28), "quarterly", 30) == date(2027, 5, 30)


def test_unknown_frequency():
    with pytest.raises(ValueError):
        add_period(date(2026, 1, 1), "weekly", 1)


def test_due_dates_up_to_through():
    got = due_dates(date(2026, 8, 31), "monthly", 31, date(2026, 10, 19), None)
    assert got == [date(2026, 8, 31), date(2026, 9, 30)]


def test_due_dates_stop_at_end_date_and_limit():
    assert due_dates(date(2026, 1, 5), "monthly", 5, date(2026, 12, 31), date(2026, 3, 5)) == [
        date(2026, 1, 5), date(2026, 2, 5), date(2026, 3, 5)]
    assert len(due_dates(date(2020, 1, 1), "monthly", 1, date(2026, 12, 31), None, limit=24)) == 24


def test_nothing_due_before_next_date():
    assert due_dates(date(2026, 11, 1), "monthly", 1, date(2026, 10, 19), None) == []


def _body(**kw):
    from app.routers.accounting_recurring import RecurringIn
    values = dict(name=" Rent accrual ", next_date=date(2026, 1, 31), lines=[
        {"account_code": "6020", "debit": "25000"}, {"account_code": "2010", "credit": "25000"}])
    values.update(kw)
    return RecurringIn(**values)


def test_template_body_validates_balance_and_dates():
    from pydantic import ValidationError
    assert _body().name == "Rent accrual"
    with pytest.raises(ValidationError, match="must balance"):
        _body(lines=[{"account_code": "6020", "debit": "1"}, {"account_code": "2010", "credit": "2"}])
    with pytest.raises(ValidationError, match="end date"):
        _body(end_date=date(2025, 12, 31))


def test_template_out_lists_due_dates_and_anchor():
    import uuid
    from app.models.accounting import AARecurringEntry
    from app.routers.accounting_recurring import _apply, _out
    row = AARecurringEntry(id=uuid.uuid4())
    _apply(row, _body())
    assert row.day_of_month == 31 and row.lines[0]["debit"] == "25000"
    out = _out(row, date(2026, 3, 31))
    assert out.due == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)] and out.amount == "25000.00"
    row.active = False
    assert _out(row, date(2026, 3, 31)).due == []
