"""Client health checks (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, ChartAccount, standard_chart
from app.services.accounting.compute.health import (
    months_not_closed, negative_balances, over_90, reconciled_through, review_balances, unreconciled_months,
)
from app.services.accounting.compute.subledger import OpenDoc, OpenItem

D = Decimal
CHART = Chart(standard_chart("corporation") + [ChartAccount("1990", "Suspense account", "asset")])


def test_negative_cash_on_hand_is_flagged_and_contra_is_not():
    rows = negative_balances({"1010": D("-12500.00"), "1020": D("330854.85"), "1510": D("-40000.00"),
                              "2010": D("5000.00"), "2100": D("-800.00"), "6020": D("-1.00")}, CHART)
    assert [(r["code"], r["balance"]) for r in rows] == [("1010", D("12500.00")), ("2010", D("5000.00"))]
    assert rows[0]["name"] == "Cash on hand" and rows[0]["type"] == "asset"


def test_review_accounts_with_balances():
    rows = review_balances({"1310": D("200.00"), "1990": D("-50.00"), "1300": D("999.00")}, CHART)
    assert [(r["code"], r["balance"]) for r in rows] == [("1310", D("200.00")), ("1990", D("-50.00"))]
    assert review_balances({"1310": D("0.00")}, CHART) == []


def test_months_not_closed():
    closed = {date(2026, 7, 1), date(2026, 9, 1)}
    assert months_not_closed(date(2026, 7, 15), closed, date(2026, 10, 17)) == [date(2026, 8, 1)]
    assert months_not_closed(None, set(), date(2026, 10, 17)) == []
    assert months_not_closed(date(2026, 10, 1), set(), date(2026, 10, 17)) == []   # October isn't over
    assert months_not_closed(date(2025, 12, 1), set(), date(2026, 2, 1)) == [date(2025, 12, 1), date(2026, 1, 1)]


def test_unreconciled_months_only_count_months_that_ended():
    lines = {("1020", date(2026, 8, 1)), ("1020", date(2026, 9, 1)), ("1020", date(2026, 10, 1)),
             ("1021", date(2026, 9, 1))}
    rec = {("1020", date(2026, 8, 1))}
    assert unreconciled_months(lines, rec, date(2026, 10, 17)) == [("1020", date(2026, 9, 1)), ("1021", date(2026, 9, 1))]


def test_reconciled_through_stops_at_the_first_gap():
    m = [(date(2026, 7, 1), date(2026, 7, 31)), (date(2026, 8, 1), date(2026, 8, 31)),
         (date(2026, 10, 1), date(2026, 10, 31))]
    assert reconciled_through(m) == date(2026, 8, 31)
    assert reconciled_through([]) is None
    assert reconciled_through(list(reversed(m))) == date(2026, 8, 31)


def _item(bucket, amount, kind="ar"):
    doc = OpenDoc("x", kind, "k", "n", "", "1", date(2026, 1, 1), amount)
    return OpenItem(doc, date(2026, 1, 1), D("0"), amount, 120 if bucket == "90+" else 10, bucket)


def test_over_90():
    items = [_item("90+", D("100.00")), _item("90+", D("50.50")), _item("1-30", D("999.00"))]
    assert over_90(items) == (2, D("150.50"))
