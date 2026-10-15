from datetime import date
from decimal import Decimal

from app.services.accounting.compute.depreciation import (
    Asset, depreciation_between, fiscal_year_window, monthly_amounts, register_rows,
)


def _asset(**kw):
    values = dict(id="a1", document_id="d1", description="Sewing machine", doc_number="SI-1",
                  cost=Decimal("100000.00"), in_service=date(2026, 3, 20), life_months=60)
    values.update(kw)
    return Asset(**values)


def test_in_service_month_counts_and_total_equals_cost():
    a = _asset(cost=Decimal("1000.00"), life_months=3)
    assert monthly_amounts(a) == [Decimal("333.33"), Decimal("333.33"), Decimal("333.34")]
    assert depreciation_between(a, date(2026, 3, 1), date(2026, 3, 31)) == Decimal("333.33")
    assert depreciation_between(a, date(2026, 1, 1), date(2030, 12, 31)) == Decimal("1000.00")


def test_rounding_never_goes_negative():
    a = _asset(cost=Decimal("1.00"), life_months=199)
    amounts = monthly_amounts(a)
    assert all(x >= 0 for x in amounts) and sum(amounts) == Decimal("1.00")


def test_end_date_stops_depreciation_after_its_month():
    a = _asset(cost=Decimal("6000.00"), life_months=60, end_date=date(2026, 5, 10))
    assert depreciation_between(a, date(2026, 1, 1), date(2026, 12, 31)) == Decimal("300.00")  # Mar–May


def test_fiscal_year_window():
    assert fiscal_year_window(2026, 6) == (date(2025, 7, 1), date(2026, 6, 30))
    a = _asset(cost=Decimal("12000.00"), life_months=12, in_service=date(2025, 12, 5))
    start, end = fiscal_year_window(2026, 6)
    assert depreciation_between(a, start, end) == Decimal("7000.00")  # Dec 2025 – Jun 2026


def test_register_rows_for_a_year():
    a = _asset(cost=Decimal("12000.00"), life_months=24, in_service=date(2025, 7, 1))
    rows = register_rows([a, _asset(id="later", in_service=date(2027, 1, 1))], date(2026, 1, 1), date(2026, 12, 31))
    assert len(rows) == 1
    r = rows[0]
    assert (r["accumulated_start"], r["this_year"], r["accumulated_end"], r["net_book_value"]) == (
        Decimal("3000.00"), Decimal("6000.00"), Decimal("9000.00"), Decimal("3000.00"))
    assert r["key"] == "a1" and r["in_service"] == "2025-07-01" and r["life_months"] == "24"
