"""The books agree with the returns built from the same documents (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.books.loader import books_warnings
from app.services.accounting.compute.book_ledgers import balances, build_books
from app.services.accounting.compute.books import BooksInput, QuarterTaxes, post_all
from app.services.accounting.compute.due_dates import quarter_end
from app.services.accounting.compute.engine import build_quarter
from app.services.accounting.compute.ewt import compute_ewt
from app.services.accounting.compute.inputs import PeriodData, PeriodInputs
from app.services.accounting.compute.money import ZERO, total
from tests.aa_factories import company, expense, purchase, sale

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code
START, END = date(2026, 7, 1), date(2026, 9, 30)
KEPT = frozenset(default_books(True))


def _quarter(*extra):
    facts = company(is_withholding_agent=True)
    lines = (
        sale(vatable="100000", vat="12000", gross="112000", doc_date=date(2026, 7, 10), doc_number="SI-1"),
        sale(vatable="50000", vat="6000", gross="56000", doc_date=date(2026, 8, 10), doc_number="SI-2",
             counterparty_name="Payor Inc", counterparty_tin="999888777"),
        purchase(gross="56000", vatable="50000", vat="6000", input_vat_valid=True, doc_date=date(2026, 7, 12)),
        expense(account="rent", counterparty_name="Ayala Land Inc.", counterparty_tin="111222333", gross="11200",
                vat="1200", vatable="10000", input_vat_valid=True, doc_date=date(2026, 7, 5)),
        sale(category="2307", account="2307_received", gross="50000", withholding="1000", doc_date=date(2026, 8, 20),
             counterparty_name="Payor Inc", counterparty_tin="999888777"),
    ) + extra
    period = PeriodData(2026, 3, lines, PeriodInputs(opening_inventory=D("0"), ending_inventory=D("0")))
    result = build_quarter(facts, [period])
    ewt = {line_id: tax for line_id, (_, tax) in compute_ewt(lines, facts, 2026, 3).by_line().items()}
    inp = BooksInput(facts, CHART, KEPT, START, END, lines=lines, ewt=ewt,
                     quarters=(QuarterTaxes(2026, 3, quarter_end(2026, 3, 12), result.forms),))
    entries, _ = post_all(inp)
    tabs = build_books(entries, CHART, START, END, 12, KEPT, C("retained_earnings"))
    return lines, result, entries, tabs


def test_books_tie_to_the_returns():
    lines, result, entries, tabs = _quarter()
    assert total(r["output_vat"] for r in tabs["SJ"]) == total(l.vat for l in lines if l.category == "sales")
    assert total(r["input_vat"] for r in tabs["PJ"]) == total(r["input_tax"] for r in result.ledgers["SLP"])
    ewt_from_documents = total(r["credit"] for r in tabs["GL"]
                               if r["code"] == C("ewt_payable") and "|doc:" in r["key"])
    assert ewt_from_documents == result.forms["1601EQ"]["19"] and ewt_from_documents > 0
    assert abs(balances(entries, END).get(C("output_vat"), ZERO)) <= D("1")
    assert not any("Output VAT" in w for w in books_warnings(tabs, PeriodInputs(), False, CHART, 3))


def test_output_vat_that_the_return_does_not_carry_warns():
    # A sale whose VAT isn't 12% of the VATable amount: the 2550-Q recomputes it, the books post the document's.
    odd = sale(vatable="10000", vat="1500", gross="11500", doc_date=date(2026, 9, 1), doc_number="SI-3")
    _, _, entries, tabs = _quarter(odd)
    off = abs(balances(entries, END).get(C("output_vat"), ZERO))
    assert off > D("1")
    [w] = [w for w in books_warnings(tabs, PeriodInputs(), False, CHART, 3) if "Output VAT" in w]
    assert w == (f"Output VAT in the books differs from the 2550-Q by ₱{off:,.2f}. Check the sales documents whose VAT "
                 "isn't 12% of the VATable amount.")
