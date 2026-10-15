from datetime import date
from decimal import Decimal

from app.services.accounting.books.receipts import (
    DocRef, is_invoice, is_payment_receipt, match_receipts, party_key,
)

D = Decimal


def inv(id, gross, on=date(2026, 7, 1), party="111222333", role="seller", wt="0"):
    return DocRef(id, party, role, on, D(gross), D(wt))


def rcpt(id, gross, on=date(2026, 7, 20), party="111222333", role="seller"):
    return DocRef(id, party, role, on, D(gross))


def test_receipt_and_invoice_titles():
    assert is_payment_receipt("OFFICIAL RECEIPT", "receipt")
    assert is_payment_receipt("Collection Receipt", "other")
    assert is_payment_receipt("ACKNOWLEDGMENT RECEIPT", "invoice")
    assert not is_payment_receipt("SALES INVOICE", "invoice")
    assert not is_payment_receipt("SERVICE INVOICE / OFFICIAL RECEIPT", "receipt")  # a combined pre-EOPT form
    assert is_invoice("SALES INVOICE", "receipt") and is_invoice("", "invoice")


def test_party_key_prefers_tin():
    assert party_key("123456789", "Juan") == "123456789"
    assert party_key("", "Juan's  Store Inc.") == party_key("", "JUAN'S STORE INC")


def test_one_candidate_links():
    [m] = match_receipts([rcpt("r1", "1120")], [inv("i1", "1120"), inv("i2", "999")])
    assert (m.invoice_id, m.candidates) == ("i1", ())


def test_amount_net_of_withholding_matches():
    [m] = match_receipts([rcpt("r1", "1100")], [inv("i1", "1120", wt="20")])
    assert m.invoice_id == "i1"


def test_several_candidates_are_not_linked():
    [m] = match_receipts([rcpt("r1", "500")], [inv("i1", "500"), inv("i2", "500", on=date(2026, 7, 5))])
    assert m.invoice_id is None and set(m.candidates) == {"i1", "i2"}


def test_no_match_outside_window_party_role_or_amount():
    invoices = [inv("old", "500", on=date(2025, 12, 1)), inv("later", "500", on=date(2026, 8, 1)),
                inv("other", "500", party="999888777"), inv("buy", "500", role="buyer"), inv("amt", "502")]
    [m] = match_receipts([rcpt("r1", "500")], invoices)
    assert m.invoice_id is None and m.candidates == ()


def test_an_invoice_is_claimed_once_oldest_receipt_first():
    matches = match_receipts([rcpt("r2", "500", on=date(2026, 7, 25)), rcpt("r1", "500", on=date(2026, 7, 10))],
                             [inv("i1", "500")])
    assert {m.receipt_id: m.invoice_id for m in matches} == {"r1": "i1", "r2": None}


def test_taken_invoices_are_skipped():
    [m] = match_receipts([rcpt("r1", "500")], [inv("i1", "500")], taken={"i1"})
    assert m.invoice_id is None


def test_undated_receipt_never_matches():
    [m] = match_receipts([DocRef("r1", "111222333", "seller", None, D("500"))], [inv("i1", "500")])
    assert m.invoice_id is None
