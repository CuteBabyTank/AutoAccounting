"""Cash projection from open A/R / A/P due dates (pure) and the books' cash balance."""

from datetime import date, timedelta
from decimal import Decimal

from app.services.accounting.compute.cashflow import projection
from app.services.accounting.compute.subledger import OpenDoc, open_items

D = Decimal
AS_OF = date(2026, 12, 31)   # a Thursday


def doc(i, kind, total, due):
    return OpenDoc(id=i, kind=kind, contact_key="k", contact_name="X", contact_tin="", doc_number=i,
                   doc_date=date(2026, 12, 1), total=D(total), due_date=due)


def run(opening, docs, weeks=4):
    return projection(opening, open_items(docs, [], AS_OF, {}), AS_OF, weeks)


def test_weekly_flows_and_running_balance():
    out = run(D("100000.00"), [doc("s1", "ar", "50000.00", AS_OF + timedelta(days=2)),
                               doc("b1", "ap", "30000.00", AS_OF + timedelta(days=16)),
                               doc("far", "ar", "9999.00", AS_OF + timedelta(days=60))])
    w = out["weeks"]
    assert len(w) == 4 and w[0]["start"] == AS_OF + timedelta(days=1) and w[0]["end"] == AS_OF + timedelta(days=7)
    assert (w[0]["inflow"], w[0]["outflow"], w[0]["closing"]) == (D("50000.00"), D("0.00"), D("150000.00"))
    assert (w[2]["outflow"], w[2]["net"], w[2]["closing"]) == (D("30000.00"), D("-30000.00"), D("120000.00"))
    assert out["closing"] == D("120000.00")
    assert out["later_in"] == D("9999.00") and out["later_out"] == D("0.00")


def test_due_today_counts_in_the_first_week():
    out = run(D("0"), [doc("s", "ar", "10.00", AS_OF)])
    assert out["weeks"][0]["inflow"] == D("10.00") and out["overdue_in"] == D("0.00")


def test_overdue_items_are_shown_apart_and_not_in_the_balance():
    out = run(D("1000.00"), [doc("old", "ar", "500.00", AS_OF - timedelta(days=40)),
                             doc("late", "ap", "200.00", AS_OF - timedelta(days=3))])
    assert (out["overdue_in"], out["overdue_out"]) == (D("500.00"), D("200.00"))
    assert out["closing"] == D("1000.00")


def test_no_books_means_flows_only():
    out = run(None, [doc("s", "ar", "10.00", AS_OF + timedelta(days=1))])
    assert out["opening"] is None and out["closing"] is None and out["weeks"][0]["closing"] is None
    assert out["weeks"][0]["net"] == D("10.00")


def test_credit_memo_reduces_inflow():
    out = run(D("0"), [doc("s", "ar", "100.00", AS_OF + timedelta(days=1)),
                       doc("cm", "ar", "-30.00", AS_OF + timedelta(days=1))])
    assert out["weeks"][0]["inflow"] == D("70.00")
