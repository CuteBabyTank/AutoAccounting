from datetime import date
from decimal import Decimal

import pytest

from app.services.accounting.books.chart import Chart, ChartAccount, default_books, standard_chart
from app.services.accounting.compute.books import (
    BooksInput, Line, Payment, document_entries, make_entry, payment_entries,
)
from tests.aa_factories import company, expense, line, purchase, sale

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code


def books(**kw):
    values = dict(company=company(), chart=CHART, books_kept=frozenset(default_books(True)),
                  start=date(2026, 1, 1), through=date(2026, 9, 30))
    values.update(kw)
    return BooksInput(**values)


def amounts(entry):
    return {(l.account, "Dr" if l.debit else "Cr"): l.debit or l.credit for l in entry.lines}


def test_unbalanced_entry_raises_and_empty_entry_is_none():
    with pytest.raises(ValueError):
        make_entry("x", date(2026, 1, 1), "GJ", "", ("", ""), "", "manual", Line("1010", debit=D("1")))
    assert make_entry("x", date(2026, 1, 1), "GJ", "", ("", ""), "", "manual", None) is None


def test_vat_sale_goes_to_the_sales_journal():
    [e] = document_entries(sale(gross="11200", vatable="10000", vat="1200", doc_number="SI-1"), books())
    assert e.book == "SJ" and e.reference == "SI-1"
    assert amounts(e) == {(C("ar"), "Dr"): D("11200.00"), (C("sales"), "Cr"): D("10000.00"),
                          (C("output_vat"), "Cr"): D("1200.00")}
    assert e.get("vatable") == D("10000")


def test_sale_goes_to_general_journal_when_no_sales_journal_is_kept():
    [e] = document_entries(sale(gross="500"), books(books_kept=frozenset(default_books(False))))
    assert e.book == "GJ"


def test_credit_memo_posts_to_sales_returns():
    [e] = document_entries(sale(gross="-1120", vatable="-1000", vat="-120"), books())
    assert amounts(e) == {(C("sales_returns"), "Dr"): D("1000.00"), (C("output_vat"), "Dr"): D("120.00"),
                          (C("ar"), "Cr"): D("1120.00")}


def test_purchase_with_input_vat_and_ewt():
    l = expense(account="rent", gross="11200", vat="1200", input_vat_valid=True)
    [e] = document_entries(l, books(ewt={l.id: D("500")}))
    assert e.book == "PJ"
    assert amounts(e) == {(C("doc:rent"), "Dr"): D("10000.00"), (C("input_vat"), "Dr"): D("1200.00"),
                          (C("ewt_payable"), "Cr"): D("500.00"), (C("ap"), "Cr"): D("10700.00")}


def test_unclaimed_input_vat_stays_in_the_cost_and_gl_override_wins():
    chart = Chart(standard_chart("corporation") + [ChartAccount("6051", "Supplies - store", "expense",
                                                                parent_code="6050")])
    l = expense(gross="1120", vat="120", input_vat_valid=False, gl_account="6051")
    [e] = document_entries(l, books(chart=chart))
    assert amounts(e) == {("6051", "Dr"): D("1120.00"), (C("ap"), "Cr"): D("1120.00")}


def test_capital_goods_post_to_property_and_equipment():
    l = purchase(account="capital_goods", gross="56000", vat="6000", input_vat_valid=True)
    [e] = document_entries(l, books())
    assert amounts(e)[(C("ppe"), "Dr")] == D("50000.00")


def test_payroll_and_received_2307():
    [p] = document_entries(line(category="payroll", account="salaries", gross="50000", withholding="2000"), books())
    assert amounts(p) == {(C("doc:salaries"), "Dr"): D("50000.00"), (C("wtc_payable"), "Cr"): D("2000.00"),
                          (C("salaries_payable"), "Cr"): D("48000.00")}
    [w] = document_entries(line(category="2307", account="2307_received", client_role="seller", gross="10000",
                                withholding="200"), books())
    assert amounts(w) == {(C("cwt"), "Dr"): D("200.00"), (C("ar"), "Cr"): D("200.00")}


def test_documents_that_never_post():
    for l in (line(category="2307", account="2307_issued", withholding="100"),
              line(category="support"), line(category="unsorted")):
        assert document_entries(l, books()) == []


def test_collection_with_paid_on_leaves_withholding_in_receivables():
    s = sale(gross="11200", vatable="10000", vat="1200", withholding="200", doc_number="SI-9")
    warnings: list[str] = []
    [e] = payment_entries(books(lines=(s,), payments=(Payment("p1", s.id, date(2026, 8, 3), None, "bank", ""),)),
                          warnings)
    assert e.book == "CRJ" and e.date == date(2026, 8, 3) and e.reference == "SI-9"
    assert amounts(e) == {(C("bank"), "Dr"): D("11000.00"), (C("ar"), "Cr"): D("11000.00")}
    assert warnings == []


def test_partial_receipts_and_overpayment_warning():
    b = purchase(gross="1000")
    pays = (Payment("r1", b.id, date(2026, 8, 1), D("400"), "cash", "OR-1"),
            Payment("r2", b.id, date(2026, 8, 5), D("700"), "cash", "OR-2"))
    warnings: list[str] = []
    out = payment_entries(books(lines=(b,), payments=pays), warnings)
    assert [e.book for e in out] == ["CDJ", "CDJ"]
    assert [amounts(e)[(C("ap"), "Dr")] for e in out] == [D("400.00"), D("700.00")]
    assert any("more than the balance" in w for w in warnings)


def test_payment_windows():
    b = purchase(gross="1000", doc_date=date(2025, 12, 1))
    pays = (Payment("early", b.id, date(2025, 12, 20), D("300"), "cash", ""),       # before books start
            Payment("now", b.id, date(2026, 2, 1), None, "cash", ""),              # the rest
            Payment("late", b.id, date(2026, 10, 2), D("50"), "cash", ""))         # after the quarter
    out = payment_entries(books(lines=(b,), payments=pays), [])
    assert [(e.id, amounts(e)[(C("ap"), "Dr")]) for e in out] == [("pay:now", D("700.00"))]


def test_payment_for_an_unknown_document_warns():
    warnings: list[str] = []
    assert payment_entries(books(payments=(Payment("p", "gone", date(2026, 2, 1), None, "cash", ""),)),
                           warnings) == []
    assert any("isn't in the books" in w for w in warnings)


def test_overpayment_followed_by_open_ended_payment_skips_second():
    b = purchase(gross="1000")
    pays = (Payment("explicit_over", b.id, date(2026, 8, 1), D("1200"), "cash", ""),
            Payment("open_ended", b.id, date(2026, 8, 5), None, "cash", ""))
    out = payment_entries(books(lines=(b,), payments=pays), [])
    assert [(e.id, amounts(e)[(C("ap"), "Dr")]) for e in out] == [("pay:explicit_over", D("1200.00"))]


def test_fully_withheld_sale_payment_warns_separately():
    s = sale(gross="100", withholding="100")
    warnings: list[str] = []
    assert payment_entries(books(lines=(s,), payments=(Payment("p", s.id, date(2026, 8, 1), None, "bank", ""),)),
                           warnings) == []
    assert any("fully withheld" in w for w in warnings)
