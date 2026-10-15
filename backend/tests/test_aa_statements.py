"""Year-end closing entries and financial statements from the books (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.book_ledgers import balances
from app.services.accounting.compute.books import BooksInput, Line, ManualEntry, Payment, QuarterTaxes, post_all
from app.services.accounting.compute.depreciation import Asset
from app.services.accounting.compute.statements import build_statements, closing_entries
from tests.aa_factories import company, expense, purchase, sale

D = Decimal


def _year(taxpayer_type="corporation"):
    chart = Chart(standard_chart(taxpayer_type))
    C = chart.code
    closing = C("retained_earnings") if taxpayer_type == "corporation" else C("capital")
    opening = ManualEntry("o", "opening", "GJ", date(2026, 1, 1), "OB", "Opening balances", (
        Line(C("bank"), debit=D("100000")), Line(C("inventory"), debit=D("20000")),
        Line(C("capital"), credit=D("120000"))))
    drawing = ManualEntry("w", "manual", "GJ", date(2026, 6, 1), "W1", "Owner withdrawal", (
        Line(C("drawings"), debit=D("5000")), Line(C("bank"), credit=D("5000"))))
    s = sale(gross="80000", vatable="0", vat="0", doc_date=date(2026, 3, 1))
    p = purchase(gross="40000", vatable="0", vat="0", doc_date=date(2026, 2, 1), counterparty_tin="")
    x = expense(gross="6000", vatable="0", vat="0", doc_date=date(2026, 4, 1), counterparty_tin="")
    pays = (Payment("p1", s.id, date(2026, 4, 1), None, "bank", "OR1"),
            Payment("p2", p.id, date(2026, 3, 1), None, "bank", "CV1"))
    q4 = QuarterTaxes(2026, 4, date(2026, 12, 31), {}, ending_inventory=D("25000"))
    truck = Asset("a1", "doc-truck", "Truck", "T1", D("24000"), date(2026, 7, 1), 24)
    manual = (opening,) + ((drawing,) if taxpayer_type != "corporation" else ())
    inp = BooksInput(company(vat_registered=False, taxpayer_type=taxpayer_type), chart,
                     frozenset(default_books(False)), date(2026, 1, 1), date(2026, 12, 31),
                     lines=(s, p, x), payments=pays, manual=manual, quarters=(q4,), assets=(truck,))
    entries, _ = post_all(inp)
    entries += closing_entries(entries, chart, 2026, 12, closing, taxpayer_type)
    return chart, entries, closing


def _amount(rows, key):
    return next(r["amount"] for r in rows if r["key"] == key)


def test_closing_entries_zero_the_income_and_expense_accounts():
    chart, entries, closing = _year()
    b = balances(entries, date(2026, 12, 31))
    assert all(v == 0 for code, v in b.items() if chart.get(code).type in ("income", "cost", "expense"))
    assert b[chart.code("income_summary")] == 0


def test_statements_balance_and_reconcile():
    chart, entries, closing = _year()
    tabs, warnings = build_statements(entries, chart, 2026, 12, closing, "corporation", date(2026, 1, 1))
    assert not any("doesn't" in w for w in warnings), warnings
    # sales 80,000 − cost (20,000 + 40,000 − 25,000 = 35,000) − expenses 6,000 − depreciation 6,000
    assert _amount(tabs["IS"], "net_sales") == D("80000.00")
    assert _amount(tabs["IS"], "cos") == D("35000.00")
    assert _amount(tabs["IS"], "net_income") == D("33000.00")
    assert _amount(tabs["SFP"], "assets_total") == _amount(tabs["SFP"], "le_total")
    assert _amount(tabs["SCF"], "cash_end") == balances(entries, date(2026, 12, 31))[chart.code("bank")]
    assert _amount(tabs["SCE"], "total") == _amount(tabs["SFP"], "eq_total")
    debit, credit = tabs["PCTB"][-1]["debit"], tabs["PCTB"][-1]["credit"]
    assert debit == credit


def test_individual_closes_drawings_to_capital():
    chart, entries, closing = _year("individual")
    b = balances(entries, date(2026, 12, 31))
    assert b.get(chart.code("drawings"), D("0")) == 0
    tabs, warnings = build_statements(entries, chart, 2026, 12, closing, "individual", date(2026, 1, 1))
    assert not any("doesn't" in w for w in warnings), warnings
    # capital 120,000 + net income 33,000 − drawings 5,000
    assert _amount(tabs["SCE"], f"{closing}:end") == D("148000.00")
