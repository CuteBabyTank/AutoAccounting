"""Bulk write-off of customer invoices (pure)."""

from datetime import date
from decimal import Decimal

from app.services.accounting.compute.books import Payment
from app.services.accounting.compute.subledger import OpenDoc, open_items
from app.services.accounting.compute.writeoff import candidates, entry_lines, payments

D = Decimal
AS_OF = date(2026, 12, 31)


def doc(i, total, on, kind="ar", key="400500600", name="Kalayaan Construction Co.", withheld="0"):
    return OpenDoc(id=i, kind=kind, contact_key=key, contact_name=name, contact_tin="400500600",
                   doc_number=f"SI {i}", doc_date=on, total=D(total), withheld=D(withheld))


DOCS = [doc("a", "1200.00", date(2026, 6, 1)), doc("b", "50000.00", date(2026, 7, 1)),
        doc("c", "800.00", date(2026, 12, 20)), doc("d", "500.00", date(2026, 5, 1), kind="ap"),
        doc("e", "-300.00", date(2026, 5, 1))]


def items(pays=()):
    return open_items(DOCS, list(pays), AS_OF, {})


def test_candidates_filter_by_age_balance_and_kind():
    assert [i.doc.id for i in candidates(items(), 90, None)] == ["a", "b"]
    assert [i.doc.id for i in candidates(items(), 90, D("2000"))] == ["a"]
    assert [i.doc.id for i in candidates(items(), 0, None)] == ["a", "b", "c"]   # credit memo and the bill never
    not_due = open_items(DOCS, [], date(2026, 12, 20), {})
    assert "c" in [i.doc.id for i in candidates(not_due, 0, None)]       # 0 days = everything open, due or not
    assert "c" not in [i.doc.id for i in candidates(not_due, 1, None)]


def test_entry_lines_balance_one_debit_and_a_credit_per_item():
    chosen = candidates(items(), 90, None)
    lines = entry_lines(chosen, "6140", "1100")
    assert lines[0] == {"account_code": "6140", "debit": "51200.00", "credit": "0", "party_name": "",
                        "party_tin": ""}
    assert [(l["account_code"], l["credit"], l["party_name"]) for l in lines[1:]] == [
        ("1100", "1200.00", "Kalayaan Construction Co."), ("1100", "50000.00", "Kalayaan Construction Co.")]


def test_entry_lines_use_the_open_balance_net_of_withholding_and_payments():
    d = doc("w", "11200.00", date(2026, 1, 10), withheld="200.00")
    item = open_items([d], [Payment("p", "w", date(2026, 2, 1), D("5000.00"), "bank", "")], AS_OF, {})
    assert entry_lines(item, "6140", "1100")[1]["credit"] == "6000.00"


def test_writeoff_payments_close_the_items():
    rows = [("je1", date(2026, 12, 31), [{"id": "a", "amount": "1200.00"}, {"id": "b", "amount": "50000.00"}])]
    pays = payments(rows)
    assert pays[0] == Payment("wo:je1:a", "a", date(2026, 12, 31), D("1200.00"), "writeoff", "Write-off")
    assert sorted(i.doc.id for i in items(pays)) == ["c", "d", "e"]
    # before the write-off date the items are still open
    assert {i.doc.id for i in open_items(DOCS, pays, date(2026, 12, 30), {})} >= {"a", "b"}


def test_entry_lines_fit_the_journal_line_schema():
    # contact TINs are stored formatted with a branch code; a JE line keeps 9 digits (as the JE import does)
    from app.schemas.accounting_books import JournalLineIn

    d = OpenDoc(id="t", kind="ar", contact_key="k", contact_name="N" * 300, contact_tin="400-500-600-00000",
                doc_number="SI 9", doc_date=date(2026, 1, 5), total=D("100.00"), withheld=D("0"))
    lines = entry_lines(open_items([d], [], AS_OF, {}), "6140", "1100")
    assert lines[1]["party_tin"] == "400500600"
    for line in lines:
        JournalLineIn(**line)


def test_later_payments_block_a_backdated_writeoff():
    from app.services.accounting.compute.writeoff import paid_after

    pays = [Payment("p1", "a", date(2026, 3, 1), D("100.00"), "bank", ""),
            Payment("p2", "b", date(2026, 9, 1), None, "cash", ""),
            Payment("p3", "c", date(2026, 6, 30), D("5.00"), "bank", "")]
    assert paid_after(pays, {"a", "b", "c"}, date(2026, 6, 30)) == {"b"}
    assert paid_after(pays, {"a"}, date(2026, 1, 1)) == {"a"}


def test_written_off_totals_feed_the_bank_matcher():
    from app.services.accounting.bank_match import open_items as bank_open_items
    from app.services.accounting.compute.inputs import DocLine
    from app.services.accounting.compute.writeoff import written_off

    rows = [("je1", date(2026, 12, 31), [{"id": "a", "amount": "1200.00"}]),
            ("je2", date(2026, 12, 31), [{"id": "b", "amount": "400.00"}])]
    paid = written_off(rows)
    assert paid == {"a": D("1200.00"), "b": D("400.00")}
    lines = [DocLine(id=i, category="sales", account="sales", doc_type="invoice", client_role="seller",
                     doc_date=date(2026, 6, 1), doc_number=f"SI {i}", counterparty_tin="", counterparty_name="K",
                     counterparty_address="", gross=D(g)) for i, g in (("a", "1200.00"), ("b", "1000.00"))]
    left = {c.ref: c.amount for c in bank_open_items(lines, {}, {}, paid)}
    assert left == {"b": D("600.00")}       # fully written off: never offered; partly: only the rest


def test_legacy_writeoff_lines_with_formatted_tin_still_serialise():
    """Write-offs saved before the TIN fix carry "400-500-600-000" on their A/R lines; reading them must not fail."""
    import uuid
    from datetime import datetime, timezone

    from app.schemas.accounting_books import JournalEntryOut

    out = JournalEntryOut(
        id=uuid.uuid4(), kind="manual", book="GJ", entry_date=date(2026, 12, 31), reference="", particulars="",
        lines=[{"account_code": "6140", "debit": "1200.00", "credit": "0", "party_name": "", "party_tin": ""},
               {"account_code": "1100", "debit": "0", "credit": "1200.00", "party_name": "K" * 300,
                "party_tin": "400-500-600-000"}],
        is_writeoff=True, created_at=datetime.now(timezone.utc))
    assert out.lines[1].party_tin == "400500600"
    assert len(out.lines[1].party_name) == 255
    assert out.lines[1].credit == D("1200.00")
    # missing keys in an old row default instead of failing
    bare = JournalEntryOut(id=uuid.uuid4(), kind="manual", book="GJ", entry_date=date(2026, 12, 31), reference="",
                           particulars="", lines=[{"account_code": "1010", "debit": "5", "credit": "0"}],
                           created_at=datetime.now(timezone.utc))
    assert bare.lines[0].party_tin == "" and bare.lines[0].party_name == ""


def test_payment_after_a_writeoff_shows_as_a_credit_like_the_books():
    """The books credit A/R for the full payment (the write-off is a journal entry, not a payment to them), so the
    subledger must too: the invoice shows a credit of what was written off, and the recovery is flagged."""
    from app.services.accounting.books.chart import Chart, default_books, standard_chart
    from app.services.accounting.compute.books import BooksInput, payment_entries
    from app.services.accounting.compute.subledger import payment_amounts
    from app.services.accounting.compute.writeoff import recovered
    from tests.aa_factories import company, sale

    d = doc("a", "1200.00", date(2026, 6, 1))
    wo = payments([("je1", date(2026, 9, 30), [{"id": "a", "amount": "1200.00"}])])
    later = Payment("p1", "a", date(2026, 11, 5), None, "bank", "")
    [item] = open_items([d], wo + [later], AS_OF, {})
    assert item.open == D("-1200.00") and item.paid == D("2400.00")
    assert [a for _, a in payment_amounts([d], wo + [later])] == [D("1200.00"), D("1200.00")]

    chart = Chart(standard_chart("corporation"))
    s = sale(id="a", gross="1200.00", vatable="1071.43", vat="128.57", doc_date=date(2026, 6, 1))
    inp = BooksInput(company=company(), chart=chart, books_kept=frozenset(default_books(True)),
                     start=date(2026, 1, 1), through=AS_OF, lines=(s,), payments=(later,))
    [e] = payment_entries(inp, [])
    assert sum(x.credit for x in e.lines) == D("1200.00")     # same figure the subledger now counts

    assert recovered(wo + [later]) == {"a": D("1200.00")}
    # a payment dated before the write-off is not a recovery; none at all → nothing flagged
    assert recovered(wo + [Payment("p0", "a", date(2026, 7, 1), D("100.00"), "bank", "")]) == {}
    assert recovered([later]) == {}


def test_partial_payment_then_writeoff_then_full_payment():
    d = doc("a", "1000.00", date(2026, 6, 1))
    pays = [Payment("p1", "a", date(2026, 7, 1), D("400.00"), "bank", "")]
    pays += payments([("je1", date(2026, 9, 30), [{"id": "a", "amount": "600.00"}])])
    pays.append(Payment("p2", "a", date(2026, 11, 5), None, "cash", ""))
    [item] = open_items([d], pays, AS_OF, {})
    assert item.open == D("-600.00")          # the books post the open-ended payment at 600 (1000 − 400)
