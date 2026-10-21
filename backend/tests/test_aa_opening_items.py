"""Opening open items (A/R / A/P outstanding at books start) in the books, the subledger and the bank matcher."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.services.accounting.bank_match import open_items as bank_open_items
from app.services.accounting.books.chart import Chart, default_books, standard_chart
from app.services.accounting.compute.books import BooksInput, Payment, post_all
from app.services.accounting.compute.subledger import open_items
from app.services.accounting.opening_items import (
    control_balances, opening_doc_line, opening_open_doc, opening_payments, opening_seen_party,
)
from tests.aa_factories import company

D = Decimal
START = date(2026, 1, 1)
CHART = Chart(standard_chart("corporation"))


def item(**kw):
    values = dict(id=uuid.uuid4(), kind="ar", contact_name="Mabuhay Builders Inc.", contact_tin="123456789",
                  doc_number="0003", doc_date=date(2025, 10, 10), due_date=None, terms_days=30,
                  amount=D("150000.00"), paid_on=None, paid_via="", paid_account="", deleted_at=None)
    values.update(kw)
    return SimpleNamespace(**values)


def test_opening_doc_line_is_before_books_start():
    i = item()
    l = opening_doc_line(i, START)
    assert (l.id, l.category, l.client_role, l.gross, l.doc_date, l.ewt_atc) == (
        str(i.id), "sales", "seller", D("150000.00"), START - timedelta(days=1), "NONE")
    ap = opening_doc_line(item(kind="ap", contact_name="Pacific Steel"), START)
    assert (ap.category, ap.client_role, ap.counterparty_name) == ("purchases", "buyer", "Pacific Steel")


def test_payment_on_opening_item_posts_collection_only():
    i, bill = item(), item(kind="ap", amount=D("80000"), doc_number="PS-77")
    inp = BooksInput(company(), CHART, frozenset(default_books(True)), START, date(2026, 3, 31),
                     lines=(opening_doc_line(i, START), opening_doc_line(bill, START)),
                     payments=(Payment("bank:x", str(i.id), date(2026, 1, 20), D("150000.00"), "bank", "", "1020"),
                               Payment("bank:y", str(bill.id), date(2026, 2, 1), D("30000.00"), "bank", "", "1020")))
    entries, warnings = post_all(inp)
    assert warnings == []
    posted = sorted((l.account, l.debit, l.credit) for e in entries for l in e.lines)
    assert posted == [("1020", D("0"), D("30000.00")), ("1020", D("150000.00"), D("0")),
                      ("1100", D("0"), D("150000.00")), ("2010", D("30000.00"), D("0"))]


def test_opening_payments_from_paid_on():
    paid = item(paid_on=date(2026, 1, 5), paid_via="cash", paid_account="1010")
    assert opening_payments([item(), paid]) == [Payment(f"paid:{paid.id}", str(paid.id), date(2026, 1, 5), None,
                                                        "cash", "0003", "1010")]


def test_opening_open_doc_ages_from_its_date():
    i = item()
    o = opening_open_doc(i, {}, {})
    assert (o.id, o.kind, o.contact_key, o.doc_date, o.terms_days, o.opening) == (
        str(i.id), "ar", "123456789", date(2025, 10, 10), 30, True)
    [open_item] = open_items([o], [], date(2026, 1, 31), {})
    assert open_item.open == D("150000.00") and open_item.bucket == "61-90"
    assert opening_open_doc(i, {"123456789": "OTHER"}, {"OTHER": ("Mabuhay", "")}).contact_key == "OTHER"


def test_seen_party_for_contacts():
    p = opening_seen_party(item(kind="ap", contact_tin="", contact_name="Pacific Steel"))
    assert (p.key, p.role, p.name) == ("NAME:pacific steel", "supplier", "Pacific Steel")


def test_bank_candidate_for_opening_item():
    i = item()
    [c] = bank_open_items([opening_doc_line(i, START)], {}, {}, {})
    assert (c.ref, c.amount, c.direction, c.payee) == (str(i.id), D("150000.00"), "in", "Mabuhay Builders Inc.")


def test_control_balances_from_opening_lines():
    lines = [{"account_code": "1100", "debit": "150000.00", "credit": "0"},
             {"account_code": "2010", "debit": "0", "credit": "80000.00"},
             {"account_code": "1020", "debit": "1", "credit": "0"}]
    assert control_balances(lines, CHART) == {"ar": D("150000.00"), "ap": D("80000.00")}
