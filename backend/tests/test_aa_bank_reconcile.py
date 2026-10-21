from datetime import date
from decimal import Decimal

from app.services.accounting.bank_report_pdf import reconciliation_pdf
from app.services.accounting.books_pdf import Header
from app.services.accounting.compute.bank_books import MatchedLine, apply_bank_lines
from app.services.accounting.compute.bank_reconcile import cleared_entry_ids, opening_gap, reconcile
from app.services.accounting.compute.books import Payment, post_all
from tests.aa_factories import expense
from tests.test_aa_bank_books import C, books, matched_lines
from tests.test_aa_bank_match import DOCS

D = Decimal
DEC = (date(2026, 12, 1), date(2026, 12, 31))


def q4_entries(extra_payments=(), lines=None):
    lines = matched_lines() if lines is None else lines
    payments, filed, postings = apply_bank_lines(list(extra_payments), (), lines)
    entries, _ = post_all(books(payments, postings, filed))
    return entries, lines


def test_q4_december_reconciles_with_zero_uncleared():
    entries, lines = q4_entries()
    rec = reconcile(C("bank"), *DEC, D("330854.85"), entries, cleared_entry_ids(lines), DEC[0], [])
    assert rec.book_balance == D("330854.85") and rec.uncleared == () and rec.difference == 0 and rec.ok


def test_bank_payment_with_no_statement_line_is_uncleared():
    permit = expense(id="permit2", account="taxes_licenses", counterparty_name="City Government of Marikina",
                     doc_number="OR-7790001", doc_date=date(2026, 12, 29), gross="3500")
    cheque = Payment("paid:permit2", "permit2", date(2026, 12, 30), None, "bank", "000820")
    lines = matched_lines()
    payments, filed, postings = apply_bank_lines([cheque], (), lines)
    entries, _ = post_all(books(payments, postings, filed, docs=DOCS + [permit]))
    rec = reconcile(C("bank"), *DEC, D("330854.85"), entries, cleared_entry_ids(lines), DEC[0], [])
    assert [u["id"] for u in rec.uncleared] == ["pay:paid:permit2"]
    assert rec.book_balance == D("327354.85") and rec.outstanding == D("-3500.00")
    assert rec.difference == 0 and rec.ok
    assert reconcile(C("bank"), *DEC, D("330854.85"), entries, cleared_entry_ids(lines), DEC[0], ["l8"]).ok is False


def test_unmatched_charge_leaves_a_difference():
    entries, lines = q4_entries(lines=matched_lines(confirm_charges=False))
    rec = reconcile(C("bank"), *DEC, D("330854.85"), entries, cleared_entry_ids(lines), DEC[0], ["l8"])
    assert rec.difference == D("150.00") and not rec.ok


def test_opening_gap_flags_a_missing_opening_balance():
    entries, _ = q4_entries()
    assert opening_gap(entries, C("bank"), DEC[0], D("412880.15")) is None
    without = [e for e in entries if e.source != "opening"]
    assert opening_gap(without, C("bank"), DEC[0], D("412880.15")) == {
        "date": "2026-12-01", "statement": "412880.15", "books": "0.00"}
    assert opening_gap(entries, C("bank"), DEC[0], None) is None


def test_reconciliation_pdf_renders():
    entries, lines = q4_entries()
    rec = reconcile(C("bank"), *DEC, D("330854.85"), entries, cleared_entry_ids(lines), DEC[0], [])
    data = reconciliation_pdf(Header("Bayanihan Hardware Trading Corp.", "123-456-789-00000", "Marikina"),
                              "1020 Cash in bank · Pinoy Commerce Bank ****7710", rec, "owner@example.com")
    assert data[:4] == b"%PDF"
    import fitz
    text = fitz.open(stream=data, filetype="pdf")[0].get_text()
    assert "330,854.85" in text and "Reconciled" in text


def test_cleared_ids_cover_every_kind():
    lines = [MatchedLine("a", date(2026, 12, 1), D("-1"), "1020", "document", "doc1", None),
             MatchedLine("b", date(2026, 12, 1), D("-1"), "1020", "posting", "", None, "6130"),
             MatchedLine("c", date(2026, 12, 1), D("-1"), "1020", "tax", "0619E:2026Q4", None),
             MatchedLine("d", date(2026, 12, 1), D("-1"), "1020", "journal", "je1", None)]
    assert cleared_entry_ids(lines) == {"pay:bank:a", "pay:rcpt:doc1", "bank:b", "tax:0619E:2026Q4:paid", "je:je1"}
