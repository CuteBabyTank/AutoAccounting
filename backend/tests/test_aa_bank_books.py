from datetime import date
from decimal import Decimal

from app.services.accounting.bank_match import match_all, open_items
from app.services.accounting.books.chart import Chart, ChartAccount, default_books, standard_chart
from app.services.accounting.compute.bank_books import MatchedLine, apply_bank_lines
from app.services.accounting.compute.books import (
    BooksInput, FiledPayment, Line, ManualEntry, Payment, QuarterTaxes, post_all,
)
from tests.aa_factories import company
from tests.test_aa_bank_match import CONTRIBUTIONS, DOCS, EWT, LINES

D = Decimal
CHART = Chart(standard_chart("corporation"))
C = CHART.code
OPENING = ManualEntry("ob", "opening", "GJ", date(2026, 12, 1), "OB-BANK", "Opening balances", (
    Line(C("bank"), debit=D("412880.15")), Line(C("capital"), credit=D("412880.15"))))


def books(payments=(), bank=(), filed=(), chart=CHART, docs=DOCS):
    return BooksInput(company(), chart, frozenset(default_books(True)), date(2026, 12, 1), date(2026, 12, 31),
                      lines=tuple(docs), ewt=EWT, payments=tuple(payments), manual=(OPENING,), bank=tuple(bank),
                      filed=tuple(filed),
                      quarters=(QuarterTaxes(2026, 4, date(2026, 12, 31), {},
                                             contributions=((date(2026, 12, 31), D("9300.00"), D("0.00")),)),))


def balance(entries, account, party=None):
    return sum((l.debit - l.credit for e in entries for l in e.lines if l.account == account
                and (party is None or e.party_name == party)), D("0"))


def matched_lines(confirm_charges=True):
    result = match_all(LINES, open_items(DOCS, EWT, CONTRIBUTIONS, {}))
    out = []
    for l in LINES:
        m = result[l.id]
        if m.status != "matched" and not (confirm_charges and m.posting.get("key") == "bank_charges"):
            continue
        key = m.posting.get("key")
        out.append(MatchedLine(l.id, l.on, l.amount, C("bank"), m.kind, m.ref, m.amount,
                               C(key) if key else "", l.narration, l.check_no))
    return out


def test_q4_december_book_bank_balance_equals_the_statement():
    payments, filed, postings = apply_bank_lines([], (), matched_lines())
    entries, _ = post_all(books(payments, postings, filed))
    assert balance(entries, C("bank")) == D("330854.85")
    assert sum(e.debits() for e in entries) == sum(e.credits() for e in entries)
    assert balance(entries, C("ar")) == D("81476.80")              # SI 0008 left after the ₱50,000 partial
    assert balance(entries, C("cash")) == D("-38450.00")           # the deposit came out of cash on hand
    assert balance(entries, C("bank_charges")) == D("150.00")
    assert balance(entries, C("salaries_payable")) == D("0.00")
    assert balance(entries, C("ap"), "Sta. Elena Realty Corp.") == D("0.00")


def test_unconfirmed_charge_suggestion_does_not_post():
    payments, filed, postings = apply_bank_lines([], (), matched_lines(confirm_charges=False))
    entries, _ = post_all(books(payments, postings, filed))
    assert balance(entries, C("bank")) == D("330854.85") + D("150.00")


def test_bank_match_replaces_paid_on_payment():
    paid_on = Payment("paid:golden", "golden", date(2026, 12, 25), None, "cash", "")
    line = MatchedLine("l7", date(2026, 12, 26), D("-22600.00"), C("bank"), "document", "golden", D("22600.00"))
    payments, _, _ = apply_bank_lines([paid_on], (), [line])
    assert [(p.id, p.account, p.on) for p in payments] == [("bank:l7", C("bank"), date(2026, 12, 26))]


def test_match_to_a_linked_receipt_moves_that_payment_to_the_bank():
    receipt = Payment("rcpt:r1", "si8", date(2026, 12, 12), D("50000.00"), "cash", "OR-1")
    line = MatchedLine("l3", date(2026, 12, 11), D("50000.00"), C("bank"), "document", "r1", D("50000.00"))
    [p], _, _ = apply_bank_lines([receipt], (), [line])
    assert (p.id, p.settles, p.via, p.account, p.on, p.amount) == (
        "rcpt:r1", "si8", "bank", C("bank"), date(2026, 12, 11), D("50000.00"))


def test_lines_without_account_do_not_post():
    line = MatchedLine("l8", date(2026, 12, 31), D("-150.00"), "", "posting", "", D("150.00"), C("bank_charges"))
    assert apply_bank_lines([], (), [line]) == ([], (), [])


def test_payment_through_a_second_bank_account_credits_it():
    chart = Chart(standard_chart("corporation") + [ChartAccount("1021", "BDO savings", "asset", parent_code="1020")])
    line = MatchedLine("l7", date(2026, 12, 25), D("-22600.00"), "1021", "document", "golden", D("22600.00"))
    payments, _, _ = apply_bank_lines([], (), [line])
    entries, _ = post_all(books(payments, chart=chart))
    assert balance(entries, "1021") == D("-22600.00")
    assert balance(entries, C("bank")) == D("412880.15")


def test_tax_match_names_the_account_and_adds_nothing():
    chart = Chart(standard_chart("corporation") + [ChartAccount("1021", "BDO savings", "asset", parent_code="1020")])
    filed = (FiledPayment("0619E", 2026, 4, date(2026, 12, 10), D("1500.00")),)
    line = MatchedLine("t", date(2026, 12, 10), D("-1500.00"), "1021", "tax", "0619E:2026Q4", D("1500.00"))
    payments, filed, postings = apply_bank_lines([], filed, [line])
    assert payments == [] and postings == [] and filed[0].account == "1021"
    entries, _ = post_all(books(filed=filed, chart=chart))
    assert balance(entries, "1021") == D("-1500.00")
