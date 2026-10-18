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
