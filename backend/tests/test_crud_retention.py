from datetime import date

from app.services.accounting.compute.retention import deletion_problem


def problem(days=(), periods=(), closes=(), filed=(), fye=12, from_date=None):
    return deletion_problem(days, periods, closes, set(filed), fye, from_date=from_date)


def test_open_unfiled_records_can_be_deleted():
    assert problem([date(2026, 1, 1)]) is None


def test_close_boundaries_are_inclusive():
    closed = [(date(2026, 1, 1), date(2026, 1, 31))]
    assert 'closed' in problem([date(2026, 1, 1)], closes=closed)
    assert 'closed' in problem([date(2026, 1, 31)], closes=closed)
    assert problem([date(2026, 2, 1)], closes=closed) is None


def test_quarter_and_annual_filing_protect_dates_in_non_calendar_fiscal_year():
    assert 'filed' in problem([date(2026, 7, 1)], filed=[(2027, 1)], fye=6)
    assert 'filed' in problem([date(2027, 6, 30)], filed=[(2027, 0)], fye=6)
    assert 'filed' in problem([date(2026, 6, 30)], filed=[(2027, 1)], fye=6)
    assert problem([date(2027, 7, 1)], filed=[(2027, 1)], fye=6) is None


def test_manual_period_assignment_is_protected_even_without_document_date():
    assert 'filed' in problem(periods=[(2026, 3)], filed=[(2026, 3)])
    assert 'filed' in problem(periods=[(2026, 3)], filed=[(2026, 0)])


def test_opening_balances_and_assets_affect_later_finalized_history():
    assert 'closed' in problem(from_date=date(2026, 1, 1), closes=[(date(2026, 9, 1), date(2026, 9, 30))])
    assert 'filed' in problem(from_date=date(2026, 1, 1), filed=[(2026, 3)])
    assert problem(from_date=date(2027, 1, 1), filed=[(2026, 0)]) is None


def test_later_ytd_filing_protects_earlier_quarter_source():
    assert 'filed' in problem([date(2026, 1, 10)], filed=[(2026, 2)])
    assert problem([date(2026, 10, 1)], filed=[(2026, 2)]) is None


def test_cross_year_vat_and_inventory_carry_protect_previous_year_source():
    assert 'filed' in problem([date(2025, 12, 10)], filed=[(2026, 1)])
